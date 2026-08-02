"""SQLAlchemy 引擎与会话（SQLite WAL + 外键）。"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.db_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
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
            ("book_relations", "from_book_id", "ALTER TABLE book_relations ADD COLUMN from_book_id INTEGER"),
        ):
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
            if col not in cols:
                conn.execute(text(ddl))


def init_db() -> None:
    """首次启动建表（M2 用 create_all；后续模型变更走 Alembic，增量列走 _ensure_columns）。"""
    from app import models  # noqa: F401  注册所有模型

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _migrate_book_media()


def _migrate_book_media() -> None:
    """启动时迁移旧版扁平书籍目录并回填封面；失败不阻塞启动。"""
    try:
        from app.services.media_service import migrate_all_books

        with SessionLocal() as db:
            migrate_all_books(db)
    except Exception:
        pass


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()