"""性能优化第一梯队（docs/性能优化路径.md §4）+ 前端并行收尾（需求-决策 §9.3.2 #10/#11）验证。

覆盖：SQLite PRAGMA 调优、外键/热点索引补齐、关键词内容寻址缓存、
聚类结果落盘缓存（群体签名失效）、上传分块流式写盘（无残留暂存文件）。
"""
import hashlib

from sqlalchemy import text

from app.core.database import engine, init_db


def _sqlite_master(client_engine):
    with client_engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }


def test_sqlite_pragmas_applied():
    """PRAGMA 调优：WAL + 外键 + synchronous=NORMAL + 页缓存/mmap 生效。"""
    init_db()
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL=1
        assert conn.execute(text("PRAGMA cache_size")).scalar() == -20000
        assert conn.execute(text("PRAGMA mmap_size")).scalar() == 268435456


def test_foreign_key_indexes_created():
    """索引补齐：外键/热点查询列存在幂等索引（存量库 _ensure_indexes / 新库 create_all）。"""
    init_db()
    indexes = _sqlite_master(engine)
    expected = {
        "ix_chapters_book_id",
        "ix_book_relations_book_a_id",
        "ix_book_relations_book_b_id",
        "ix_book_relations_from_book_id",
        "ix_knowledge_points_book_id",
        "ix_knowledge_points_chapter_id",
        "ix_kp_relations_from_kp_id",
        "ix_kp_relations_to_kp_id",
        "ix_book_assets_book_id",
        "ix_book_assets_book_kind",
        "ix_notes_book_id",
        "ix_bookmarks_book_id",
        "ix_bookmarks_book_created",
        "ix_chat_messages_ref_book_id",
        "ix_reading_logs_book_id",
        "ix_books_folder_id",
        "ix_folders_parent_id",
        "ix_tasks_related_id",
    }
    assert expected <= indexes, f"缺失索引: {expected - indexes}"


def test_keyword_cache_content_addressed():
    """关键词缓存：内容寻址命中、清空接口可用、不同文本互不影响。"""
    from app.services.graph.keywords import clear_keyword_cache, extract_keywords

    clear_keyword_cache()
    text_a = "变分法研究泛函极值问题，泛函分析是基础。" * 10
    text_b = "概率论与数理统计教程内容。" * 10
    first = extract_keywords(text_a, 40)
    assert extract_keywords(text_a, 40) == first  # 重复抽取结果一致（缓存命中）
    assert extract_keywords(text_b, 40) != first
    assert extract_keywords(text_a, 80) == first  # top_n 只是切片，不影响内容
    clear_keyword_cache()
    assert extract_keywords(text_a, 40) == first  # 清空后重算仍与历史结果一致


def test_book_keywords_weighted_by_source(client):
    """book_keywords 按来源加权（L3）：章节标题×2.0/正文×1.0，不再与纯语料抽取等价。"""
    from app.core.database import SessionLocal
    from app.models.book import Book
    from app.services.graph.corpus import book_corpus
    from app.services.graph.keywords import book_keywords, extract_keywords

    r = client.post(
        "/api/books",
        files={"file": ("缓存书.md", "# 第一章 拓扑\n\n拓扑空间与连续映射。\n".encode(), "text/markdown")},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        book = db.query(Book).first()
        weighted = book_keywords(book, 40)
        plain = extract_keywords(book_corpus(book), 40)
        # 拓扑：书名 1 次×1.0 + 章节标题 1 次×2.0 + 正文 1 次×1.0 = 4.0（纯语料抽取为 3.0）
        assert weighted["拓扑"] == 4.0
        assert weighted["拓扑"] > plain["拓扑"]
    finally:
        db.close()


def test_cluster_cache_hit_and_invalidate(client):
    """聚类落盘缓存：首算写缓存、二开命中（不再全量重算）、tag 变更自动失效。"""
    import json

    from app.core.database import SessionLocal
    from app.services.graph import assign_clusters
    from app.services.graph.clustering import _cluster_cache_path

    a = client.post(
        "/api/books",
        files={"file": ("谱A.md", "# 第一章 变分法基础\n\n变分法研究泛函极值问题。\n".encode(), "text/markdown")},
    ).json()["data"]["id"]
    b = client.post(
        "/api/books",
        files={"file": ("谱B.md", "# 第一章 泛函分析入门\n\n泛函与极值问题在变分法中常见。\n".encode(), "text/markdown")},
    ).json()["data"]["id"]

    db = SessionLocal()
    try:
        first = assign_clusters(db)
        assert first[a] == first[b]  # 无 tag/folder：领域自动聚类成簇
        cache_path = _cluster_cache_path()
        assert cache_path.exists(), "首次计算应写缓存文件"
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert "population" in data and str(a) in data["books"]

        second = assign_clusters(db)
        assert second == first  # 二次调用直接命中缓存，结果一致

        # 变更 tag → 群体签名变化 → 缓存失效重算（谱B 无 tag，命名受全局术语词库影响，不细究）
        client.patch(f"/api/books/{a}", json={"tags": ["数学"]})
        third = assign_clusters(db)
        assert third[a] == "数学"
        assert third != first
    finally:
        db.close()


def test_cluster_cache_invalidates_on_algo_params(client):
    """聚类缓存：参数签名变化（如调 τ/bloat）→ 旧缓存自动失效重算，免手动清缓存。"""
    import json

    from app.core.database import SessionLocal
    from app.services.graph import assign_clusters
    from app.services.graph.clustering import _algo_params_signature, _cluster_cache_path

    a = client.post(
        "/api/books",
        files={"file": ("谱C.md", "# 第一章 变分法基础\n\n变分法研究泛函极值问题。\n".encode(), "text/markdown")},
    ).json()["data"]["id"]

    db = SessionLocal()
    try:
        assign_clusters(db)
        cache_path = _cluster_cache_path()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["algo_params"] == _algo_params_signature(), "写缓存应带当前参数签名"
        assert "population" in data, "population 字段保留"

        # 篡改参数签名模拟「改过 τ/bloat」→ 缓存失效 → 重算回写新签名
        data["algo_params"] = "stale-params"
        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = assign_clusters(db)
        assert result[a]
        refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
        assert refreshed["algo_params"] == _algo_params_signature()
    finally:
        db.close()


def test_upload_streaming_chunks_no_leftover(client):
    """上传分块流式写盘：大文件多次读块、sha256 正确、暂存目录无残留。"""
    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.book import Book

    payload = ("# 第一章\n\n" + "流式写盘测试内容。" * 60000 + "\n").encode()
    assert len(payload) > 1024 * 1024  # 确保触发多块读取
    r = client.post(
        "/api/books",
        files={"file": ("大文件.md", payload, "text/markdown")},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] > 0

    upload_dir = settings.data_dir / "uploads"
    if upload_dir.exists():
        assert list(upload_dir.iterdir()) == [], "暂存文件应已移入书籍目录，无残留"

    db = SessionLocal()
    try:
        book = db.get(Book, data["id"])
        assert book is not None
        assert book.content_hash == hashlib.sha256(payload).hexdigest()
    finally:
        db.close()

def test_cluster_cache_actually_hits_after_persist(client):
    """A-C1 回归：persist=True 写库后，随后 GET（persist=False）必须命中落盘缓存。

    旧缺陷：缓存键用「写库前签名」，persist 回写 classify_* 字段后签名变化，
    下次 GET 从 DB 算出的签名永不相等 → 每次打开谱系图全量重算（性能承诺失效）。
    """
    from unittest import mock

    from app.core.database import SessionLocal
    from app.services.graph import assign_clusters
    from app.services.graph import clustering as clustering_mod

    client.post(
        "/api/books",
        files={"file": ("命中A.md", "# 第一章 变分法基础\n\n变分法研究泛函极值问题。\n".encode(), "text/markdown")},
    )
    client.post(
        "/api/books",
        files={"file": ("命中B.md", "# 第一章 泛函分析入门\n\n泛函与极值问题在变分法中常见。\n".encode(), "text/markdown")},
    )

    db = SessionLocal()
    try:
        # 同进程其它测试可能已写入同人口签名缓存（conftest 共享临时数据目录），
        # 先清空缓存文件保证本测试从「冷缓存」开始
        clustering_mod._cluster_cache_path().unlink(missing_ok=True)
        with mock.patch.object(clustering_mod, "_build_sim_graph", wraps=clustering_mod._build_sim_graph) as spy:
            first = assign_clusters(db)  # 首算：重算并落盘
            assert spy.call_count > 0
        with mock.patch.object(clustering_mod, "_build_sim_graph", wraps=clustering_mod._build_sim_graph) as spy2:
            second = assign_clusters(db, persist=False)  # GET 链路：应直接命中缓存
            assert spy2.call_count == 0, "persist 后 GET 必须命中落盘缓存（A-C1 回归）"
        assert second == first
    finally:
        db.close()
