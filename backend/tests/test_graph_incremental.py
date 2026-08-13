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


def test_kp_index_fingerprint_changes_on_rowid_reuse(client):
    """审查 P1-1：删最大 id KP 后重建同数量 KP（rowid 复用）→ (count, max_id) 不变，updated_at 指纹必变。"""
    from datetime import timedelta

    from sqlalchemy import func, text

    from app.core.database import _ensure_columns, engine
    from app.core.time import utcnow
    from app.models.graph import KnowledgePoint
    from app.services.graph.cross_book import _get_kp_index, _kp_index_fingerprint

    db = SessionLocal()
    try:
        b = Book(title="指纹书", file_path="/tmp/fp.md", format="md")
        db.add(b)
        db.commit()
        kps = [
            KnowledgePoint(book_id=b.id, title=f"KP{i}", summary="变分法研究泛函极值问题", level="章节级")
            for i in range(3)
        ]
        db.add_all(kps)
        db.commit()
        max_id = max(k.id for k in kps)

        # 存量库迁移：模拟旧库无 updated_at 列 → _ensure_columns 补列并回填 created_at
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE knowledge_points DROP COLUMN updated_at"))
        _ensure_columns()
        with engine.begin() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(knowledge_points)")).fetchall()]
            assert "updated_at" in cols, "迁移后应补回 updated_at 列"
            backfilled = conn.execute(
                text("SELECT count(*) FROM knowledge_points WHERE updated_at = created_at")
            ).scalar_one()
            assert backfilled == 3, "存量行 updated_at 应回填为 created_at"

        fp1 = _kp_index_fingerprint(db)
        # 重建语义：先删最大 id 知识点，再插入同数量新 KP（SQLite 复用被删的 rowid）
        db.query(KnowledgePoint).filter(KnowledgePoint.id == max_id).delete()
        db.commit()
        db.add(
            KnowledgePoint(
                book_id=b.id,
                title="新知识点",
                summary="变分法研究泛函极值问题",
                level="章节级",
                updated_at=utcnow() + timedelta(seconds=1),
            )
        )
        db.commit()
        new_max = db.query(func.max(KnowledgePoint.id)).scalar()
        assert new_max == max_id, "删最大 id 后新插应复用该 rowid（缺口前提）"
        fp2 = _kp_index_fingerprint(db)
        assert fp1[0] == fp2[0] and fp1[1] == fp2[1], "count/max_id 不变（rowid 复用场景前提）"
        assert fp1[2] != fp2[2], "max(updated_at) 必须变化 → 倒排索引重建"
        index = _get_kp_index(db)
        assert index["fingerprint"] == fp2, "指纹变化后应重建索引"
        assert any(k["title"] == "新知识点" for k in index["kps"]), "重建后的索引应包含新 KP"
    finally:
        db.close()


def test_incremental_graph_retries_on_concurrent_duplicate_edge(client, monkeypatch):
    """审查 P2-1：并发导入时另一会话先插入同 pair 边 → IntegrityError 回滚重试，任务不失败、无重复边。"""
    from app.models.graph import BookRelation
    from app.services.graph.cross_book import incremental_cross_book_graph

    a = _import_md(client, "并发A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "并发B.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    lo, hi = min(a, b), max(a, b)
    db1 = SessionLocal()
    db2 = SessionLocal()
    try:
        db1.query(BookRelation).delete()
        db1.commit()
        db2.query(BookRelation).delete()
        db2.commit()
        injected = {"done": False}
        orig_commit = db1.commit

        def racing_commit():
            if not injected["done"]:
                injected["done"] = True
                db2.add(
                    BookRelation(
                        book_a_id=lo, book_b_id=hi, strength=50.0, direction="无",
                        relation_type="概念共现", reasons_json="[]",
                    )
                )
                db2.commit()
            orig_commit()

        monkeypatch.setattr(db1, "commit", racing_commit)
        incremental_cross_book_graph(db1, a)  # 并发冲突下不得抛 IntegrityError
        assert injected["done"], "竞态注入应已触发（首轮提交被另一会话抢先）"
        rows = db1.query(BookRelation).all()
        pairs = [tuple(sorted((r.book_a_id, r.book_b_id))) for r in rows]
        assert len(pairs) == len(set(pairs)), "唯一约束下不得出现重复边"
        assert (lo, hi) in pairs, "并发会话先落地的边应保留"
    finally:
        db1.close()
        db2.close()
