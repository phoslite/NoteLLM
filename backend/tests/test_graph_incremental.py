"""M8 增量闭环：新书导入自动增量更新跨书关联 + 知识点跨书检索（该知识点还出现在哪些书）。"""
from app.core.database import SessionLocal
from app.models.book import Book


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _global_graph(client, wait_task) -> dict:
    """拉取全局图谱；懒构建中时等待后台任务完成再拉取（决策 35 后台化适配）。"""
    data = client.get("/api/graph/books").json()["data"]
    if data.get("building"):
        st = wait_task(client, data["task_id"])
        assert st["status"] == "success", st.get("error")
        data = client.get("/api/graph/books").json()["data"]
    return data


def _intra_graph(client, wait_task, book_id: int) -> dict:
    data = client.get(f"/api/graph/books/{book_id}").json()["data"]
    if data.get("building"):
        st = wait_task(client, data["task_id"])
        assert st["status"] == "success", st.get("error")
        data = client.get(f"/api/graph/books/{book_id}").json()["data"]
    return data


def _get_book(book_id: int) -> Book:
    db = SessionLocal()
    try:
        return db.get(Book, book_id)
    finally:
        db.close()


def test_import_triggers_incremental_graph_update(client, wait_task):
    """新书导入自动补跨书关联：导入第 3 本同主题书后边数增加，无需手动重建。"""
    a = _import_md(client, "增量A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n\n# 第二章 泛函分析\n\n泛函空间与范数。\n")
    b = _import_md(client, "增量B.md", "# 第一章 泛函分析入门\n\n泛函与极值问题在变分法中常见。\n")
    data = _global_graph(client, wait_task)
    edges_before = len(data["edges"])
    assert edges_before >= 1
    assert any(a in (e["book_a"], e["book_b"]) and b in (e["book_a"], e["book_b"]) for e in data["edges"])

    c = _import_md(client, "增量C.md", "# 第一章 变分法进阶\n\n变分法与泛函极值的深入讨论。\n")
    data2 = _global_graph(client, wait_task)
    assert len(data2["edges"]) > edges_before, "导入新书后应增量补边"
    assert any(c in (e["book_a"], e["book_b"]) for e in data2["edges"]), "新书应参与至少一条边"
    # 既有 A-B 边不被破坏
    assert any(a in (e["book_a"], e["book_b"]) and b in (e["book_a"], e["book_b"]) for e in data2["edges"])


def test_incremental_update_is_idempotent(client):
    """增量更新幂等：既有边存在时重复调用不重复建边。"""
    from app.models.graph import BookRelation
    from app.services.graph.cross_book import incremental_cross_book_graph

    a = _import_md(client, "幂等A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    _import_md(client, "幂等B.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    db = SessionLocal()
    try:
        # 导入已自动建边；手动删除后增量重建恰好补回一条，再次调用为 0（幂等）
        db.query(BookRelation).delete()
        db.commit()
        first = incremental_cross_book_graph(db, a)
        assert first["relations_added"] >= 1
        second = incremental_cross_book_graph(db, a)
        assert second["relations_added"] == 0
    finally:
        db.close()


def test_knowledge_appears_in_cross_book(client, wait_task):
    """跨书检索：知识点还出现在哪些书（先构建两本书内图谱，重要段落知识点关键词命中）。"""
    text = "# 第一章 定义与定理\n\n定理 1：完备空间是巴拿赫空间。\n\n# 第二章 证明方法\n\n证明：先证明必要性。\n"
    a = _import_md(client, "跨书A.md", text)
    b = _import_md(client, "跨书B.md", text)
    # 先构建两本书内图谱（懒构建）
    intra_a = _intra_graph(client, wait_task, a)
    _intra_graph(client, wait_task, b)

    kp = next((n for n in intra_a["nodes"] if n["level"] == "重要段落"), None)
    assert kp is not None, "书内图谱应有重要段落级知识点"

    resp = client.get(f"/api/graph/knowledge/{kp['id']}/appears-in")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["source"]["kp_id"] == kp["id"]
    assert data["total"] >= 1
    hit = next((x for x in data["books"] if x["book_id"] == b), None)
    assert hit is not None, "同知识点应命中另一本书"
    assert hit["matched_kps"], "另一本书应有命中知识点"

    # 不存在的知识点 404
    assert client.get("/api/graph/knowledge/999999/appears-in").status_code == 404


def test_knowledge_appears_in_rag_key_points(client, wait_task):
    """跨书检索补充来源：其他书 RAG key_points 命中（用户标记级知识点）。"""
    from app.repositories.assets import upsert_asset

    a = _import_md(client, "跨书RAG-A.md", "# 第一章\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "跨书RAG-B.md", "# 第一章\n\n泛函分析入门。\n")
    db = SessionLocal()
    try:
        upsert_asset(db, b, "rag", {"title": "跨书RAG-B", "summary": "泛函", "key_points": ["变分法研究泛函极值问题"]})
    finally:
        db.close()

    detail = client.get(f"/api/books/{a}").json()["data"]
    ch1 = next(c for c in detail["chapters"] if c["index"] == 1)
    client.post(
        f"/api/books/{a}/notes",
        json={"chapter_id": ch1["id"], "quote_text": "变分法研究泛函极值", "note_text": "关注极值问题", "note_type": "高亮"},
    )
    st = wait_task(client, client.post(f"/api/graph/books/{a}/rebuild").json()["data"]["task_id"])
    assert st["status"] == "success", st.get("error")
    intra = _intra_graph(client, wait_task, a)
    kp = next(n for n in intra["nodes"] if n["level"] == "用户标记")
    data = client.get(f"/api/graph/knowledge/{kp['id']}/appears-in").json()["data"]
    hit = next((x for x in data["books"] if x["book_id"] == b), None)
    assert hit is not None and hit["rag_hits"], "其他书 RAG key_points 应命中"