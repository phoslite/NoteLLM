"""L0 联动沉淀优化回归：post-classify 移出边循环、簇索引复用、commit 隔离（docs/联动沉淀优化方案.md L0）。"""
import json

from app.core.database import SessionLocal
from app.models.book import Book


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _task_result(client, wait_task, task_id: str) -> dict:
    st = wait_task(client, task_id)
    assert st["status"] == "success", st.get("error")
    return st["result"] or {}


def _add_relation(db, a: int, b: int, strength: float = 80.0):
    from app.models.graph import BookRelation

    rel = BookRelation(
        book_a_id=min(a, b),
        book_b_id=max(a, b),
        strength=strength,
        direction="无",
        relation_type="概念共现",
        reasons_json=json.dumps(["变分法", "泛函"], ensure_ascii=False),
    )
    db.add(rel)
    db.commit()
    return rel.id


def _fake_client_reply() -> str:
    return json.dumps(
        {
            "summary": "跨书关联总结：变分法与泛函分析存在共同概念。",
            "key_points": ["变分法研究泛函极值", "跨书关联：泛函空间"],
            "skills": [{"name": "对比法", "applicable": "跨书", "usage": "步骤", "sources": ["跨书关联"]}],
        },
        ensure_ascii=False,
    )


def test_sync_post_classify_once_per_affected_book(client, monkeypatch, wait_task):
    """L0：LLM 更新后 post-classify 每受影响书一次且复用簇索引；merge 最后统一一次。"""
    from app.services import graph_sync

    class _FakeClient:
        def chat(self, messages):
            return _fake_client_reply()

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _FakeClient())
    orig_post = graph_sync.post_classify_book
    orig_merge = graph_sync.merge_and_rename_clusters
    post_calls: list[tuple[int, bool]] = []
    merge_calls: list[int] = []

    def counting_post(db, book, index=None):
        post_calls.append((book.id, index is not None))
        return orig_post(db, book, index=index)

    def counting_merge(db):
        merge_calls.append(1)
        return orig_merge(db)

    monkeypatch.setattr(graph_sync, "post_classify_book", counting_post)
    monkeypatch.setattr(graph_sync, "merge_and_rename_clusters", counting_merge)

    a = _import_md(client, "L0A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "L0B.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 80.0)
    finally:
        db.close()

    data = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert data["llm_updated"] == 2
    assert len(post_calls) == 2, f"应每受影响书恰好一次，实际 {len(post_calls)}"
    assert {book_id for book_id, _ in post_calls} == {a, b}
    assert all(indexed for _, indexed in post_calls), "应复用簇代表特征索引"
    assert len(merge_calls) == 1, "merge 应在循环后统一执行一次"


def test_post_classify_index_equiv_no_index(client):
    """L0：post_classify_book 带 index 与不带 index 结果一致（索引复用等价性）。"""
    from app.repositories.assets import upsert_asset
    from app.services.graph.clustering import build_posterior_index, post_classify_book

    a = _import_md(client, "L0C.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "L0D.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    db = SessionLocal()
    try:
        upsert_asset(db, a, "rag", {"title": "L0C", "summary": "变分法研究泛函极值", "key_points": ["变分法", "泛函", "极值"]})
        upsert_asset(db, b, "rag", {"title": "L0D", "summary": "泛函空间与极值问题", "key_points": ["泛函", "极值", "变分"]})
        name_a = post_classify_book(db, db.get(Book, a))
        name_b = post_classify_book(db, db.get(Book, b))
        assert name_a and name_b
        index = build_posterior_index(db)
        assert post_classify_book(db, db.get(Book, a), index=index) == name_a
        assert post_classify_book(db, db.get(Book, b), index=index) == name_b
    finally:
        db.close()


def test_sync_post_classify_failure_keeps_assets(client, monkeypatch, wait_task):
    """L0：post-classify 失败只回滚分类，不丢已成功落库的 LLM 资产（commit 隔离）。"""
    from app.services import graph_sync

    class _FakeClient:
        def chat(self, messages):
            return json.dumps(
                {
                    "summary": "隔离总结：跨书关联已沉淀。",
                    "key_points": ["变分法"],
                    "skills": [{"name": "隔离法", "applicable": "x", "usage": "y", "sources": []}],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _FakeClient())

    def boom_post(db, book, index=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_sync, "post_classify_book", boom_post)
    monkeypatch.setattr(graph_sync, "merge_and_rename_clusters", lambda db: {"merged": 0, "renamed": 0})

    a = _import_md(client, "L0E.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "L0F.md", "# 第一章 泛函分析\n\n泛函空间。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 80.0)
    finally:
        db.close()

    data = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert data["llm_updated"] == 2
    db = SessionLocal()
    try:
        from app.repositories.assets import get_asset, read_asset_content

        rag_a = read_asset_content(db, a, "rag")
        assert "隔离总结" in rag_a.get("summary", ""), "post-classify 失败不应回滚已落库资产"
        assert get_asset(db, a, "rag").version >= 2
    finally:
        db.close()
def test_post_classify_shared_index_excludes_self(client):
    """L0 修复：共享簇索引按书粒度保留，排除被归类书自身关键词（自匹配会压制簇迁移）。

    构造：C 当前在「数学分析」簇但关键词与「变分法」簇高度重叠、与簇内其它书无重叠
    ——无索引路径（排除自身）应迁移到「变分法」；共享索引路径必须与之一致。
    """
    from app.models.book import Book
    from app.repositories.assets import get_asset, upsert_asset
    from app.services.graph.clustering import build_posterior_index, post_classify_book

    def _seed(name: str, cluster: str, kps: list[str]) -> int:
        bid = _import_md(client, name, f"# 第一章 {kps[0]}\n\n{kps[0]}研究。\n")
        db = SessionLocal()
        try:
            upsert_asset(db, bid, "rag", {"title": name, "summary": " ".join(kps), "key_points": kps})
            b = db.get(Book, bid)
            b.cluster_name = cluster
            b.classify_source = "post"
            b.classify_version = get_asset(db, bid, "rag").version
            db.commit()
        finally:
            db.close()
        return bid

    _seed("L0G.md", "数学分析", ["微积分", "极限", "级数"])
    _seed("L0H.md", "变分法", ["变分法", "泛函", "极值", "欧拉方程"])
    c = _seed("L0I.md", "数学分析", ["变分法", "泛函", "极值"])
    db = SessionLocal()
    try:
        from app.repositories.assets import get_asset
        from app.services.graph.clustering import build_posterior_index

        expected = post_classify_book(db, db.get(Book, c))
        assert expected == "变分法", f"无索引路径应迁移到「变分法」，实际 {expected}"
        cc = db.get(Book, c)
        cc.cluster_name = "数学分析"
        cc.classify_source = "post"
        cc.classify_version = get_asset(db, c, "rag").version
        db.commit()
        index = build_posterior_index(db)
        got = post_classify_book(db, db.get(Book, c), index=index)
        assert got == expected, f"共享索引路径应与无索引路径一致，实际 {got}"
    finally:
        db.close()
