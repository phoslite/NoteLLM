"""SQLAlchemy 引擎与会话（SQLite WAL + 外键）。"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.db_url, connect_args={"check_same_thread": False, "timeout": 30}  # 决策 4：busy timeout 缓解并发写锁
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    # 性能优化第一梯队（docs/性能优化路径.md §4）：写盘频率降为 NORMAL（WAL 下安全），
    # 页缓存 20MB（cache_size 负数为 KB 单位）、mmap 256MB 减少堆复制。
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA cache_size=-20000")
    cur.execute("PRAGMA mmap_size=268435456")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ensure_columns() -> None:
    """轻量迁移：create_all 不会为已存在的表补新列，这里用 ALTER TABLE 补齐。"""
    with engine.begin() as conn:
        for table, col, ddl in (
            ("books", "is_scanned", "ALTER TABLE books ADD COLUMN is_scanned BOOLEAN NOT NULL DEFAULT 0"),
            ("books", "page_count", "ALTER TABLE books ADD COLUMN page_count INTEGER NOT NULL DEFAULT 0"),
            ("chapters", "page_index", "ALTER TABLE chapters ADD COLUMN page_index INTEGER"),
            ("books", "cluster_name", "ALTER TABLE books ADD COLUMN cluster_name VARCHAR(100)"),
            ("books", "classify_source", "ALTER TABLE books ADD COLUMN classify_source VARCHAR(20)"),
            ("books", "classified_at", "ALTER TABLE books ADD COLUMN classified_at DATETIME"),
            ("books", "classify_version", "ALTER TABLE books ADD COLUMN classify_version INTEGER"),
            ("books", "position", "ALTER TABLE books ADD COLUMN position INTEGER NOT NULL DEFAULT 0"),
            ("books", "content_hash", "ALTER TABLE books ADD COLUMN content_hash VARCHAR(64)"),
            ("book_relations", "from_book_id", "ALTER TABLE book_relations ADD COLUMN from_book_id INTEGER"),
            ("chat_messages", "stream_key", "ALTER TABLE chat_messages ADD COLUMN stream_key VARCHAR(64)"),
        ):
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
            if col not in cols:
                conn.execute(text(ddl))


# 外键/热点查询索引（性能优化第一梯队）：名称与 SQLAlchemy 模型 `index=True` / `__table_args__`
# 约定一致（ix_<table>_<column>），对存量库幂等补齐；新库由 create_all 直接创建。
_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_folders_parent_id ON folders(parent_id)",
    "CREATE INDEX IF NOT EXISTS ix_books_folder_id ON books(folder_id)",
    "CREATE INDEX IF NOT EXISTS ix_chapters_book_id ON chapters(book_id)",
    "CREATE INDEX IF NOT EXISTS ix_reading_logs_book_id ON reading_logs(book_id)",
    "CREATE INDEX IF NOT EXISTS ix_reading_logs_chapter_id ON reading_logs(chapter_id)",
    "CREATE INDEX IF NOT EXISTS ix_reading_logs_book_updated ON reading_logs(book_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_user_profiles_layer_dim ON user_profiles(layer, dimension)",
    "CREATE INDEX IF NOT EXISTS ix_notes_book_id ON notes(book_id)",
    "CREATE INDEX IF NOT EXISTS ix_notes_chapter_id ON notes(chapter_id)",
    "CREATE INDEX IF NOT EXISTS ix_bookmarks_book_id ON bookmarks(book_id)",
    "CREATE INDEX IF NOT EXISTS ix_bookmarks_chapter_id ON bookmarks(chapter_id)",
    "CREATE INDEX IF NOT EXISTS ix_bookmarks_book_created ON bookmarks(book_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_ref_book_id ON chat_messages(ref_book_id)",
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_ref_chapter_id ON chat_messages(ref_chapter_id)",
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_stream_key ON chat_messages(stream_key)",
    "CREATE INDEX IF NOT EXISTS ix_book_relations_book_a_id ON book_relations(book_a_id)",
    "CREATE INDEX IF NOT EXISTS ix_book_relations_book_b_id ON book_relations(book_b_id)",
    "CREATE INDEX IF NOT EXISTS ix_book_relations_from_book_id ON book_relations(from_book_id)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_points_book_id ON knowledge_points(book_id)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_points_chapter_id ON knowledge_points(chapter_id)",
    "CREATE INDEX IF NOT EXISTS ix_kp_relations_from_kp_id ON kp_relations(from_kp_id)",
    "CREATE INDEX IF NOT EXISTS ix_kp_relations_to_kp_id ON kp_relations(to_kp_id)",
    "CREATE INDEX IF NOT EXISTS ix_book_assets_book_id ON book_assets(book_id)",
    "CREATE INDEX IF NOT EXISTS ix_book_assets_book_kind ON book_assets(book_id, kind)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_related_id ON tasks(related_id)",
    "CREATE INDEX IF NOT EXISTS ix_term_aliases_canonical ON term_aliases(canonical)",
)


def _ensure_indexes() -> None:
    """轻量迁移：为存量库补齐外键/热点查询索引（幂等，启动时执行）。"""
    with engine.begin() as conn:
        for ddl in _INDEX_DDL:
            conn.execute(text(ddl))
        # 审查 P1-3：存量重复边去重后建唯一索引（新库由模型 UniqueConstraint 直接创建）
        conn.execute(
            text(
                "DELETE FROM book_relations WHERE id NOT IN "
                "(SELECT MIN(id) FROM book_relations GROUP BY book_a_id, book_b_id)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_book_relations_pair "
                "ON book_relations(book_a_id, book_b_id)"
            )
        )


def _ensure_fts() -> None:
    """FTS5 全书搜索（性能优化 §7 决策 3）：chapters 虚表 + 同步触发器（幂等，可重复执行）。

    - 索引范围：DB 内文本（chapter.title + chapter.content_text）；扫描版 PDF 按页阅读，
      local_text 为文件页缓存，不做行级索引（标题/页标题可命中章节标题列）。
    - 分词器：trigram（SQLite ≥3.34）——中文任意 3 字符及以上子串可命中（如「极值问题」命中
      「泛函极值问题」）；1-2 字符短词由 search_service 回退 LIKE 扫描。
    - 触发器：AFTER INSERT/UPDATE/DELETE ON chapters 保持 fts_chapters 与章节表同步；
      删除书籍经章节级联删除自动清理对应行。
    - 存量回填：仅当虚表为空时全量重建一次（新启用），之后靠触发器增量维护。
    """
    if not settings.fts_search_enabled:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts_chapters USING fts5("
            "book_id UNINDEXED, chapter_id UNINDEXED, title, content, tokenize='trigram')"
        ))
        conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS trg_fts_chapters_ai AFTER INSERT ON chapters BEGIN "
            "INSERT INTO fts_chapters(rowid, book_id, chapter_id, title, content) "
            "VALUES (new.id, new.book_id, new.id, new.title, new.content_text); END"
        ))
        conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS trg_fts_chapters_ad AFTER DELETE ON chapters BEGIN "
            "DELETE FROM fts_chapters WHERE rowid = old.id; END"
        ))
        conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS trg_fts_chapters_au AFTER UPDATE ON chapters BEGIN "
            "DELETE FROM fts_chapters WHERE rowid = old.id; "
            "INSERT INTO fts_chapters(rowid, book_id, chapter_id, title, content) "
            "VALUES (new.id, new.book_id, new.id, new.title, new.content_text); END"
        ))
        count = conn.execute(text("SELECT count(*) FROM fts_chapters")).scalar_one()
        if not count:
            conn.execute(text(
                "INSERT INTO fts_chapters(rowid, book_id, chapter_id, title, content) "
                "SELECT id, book_id, id, title, content_text FROM chapters"
            ))


def init_db() -> None:
    """首次启动建表（M2 用 create_all；后续模型变更走 Alembic，增量列走 _ensure_columns，索引走 _ensure_indexes）。"""
    from app import models  # noqa: F401  注册所有模型

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _ensure_indexes()
    _ensure_fts()


def get_db():
    """FastAPI 依赖：请求级会话（I-7 修复：请求成功统一 commit，异常回滚）。

    持久化不再依赖「仓储内部 commit」隐式契约——路由/服务层直接 db.add 的对象
    在请求正常结束后也会提交；仓储内部已有的 commit 保持不变（重复 commit 无害）。
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()