"""图谱联动 RAG/Skill 增量增改：本地存根、术语补水、LLM 联动与路由（需求 3.4.7/3.4.9）。"""
import json

from app.core.database import SessionLocal
from app.models.book import Book
from app.repositories.assets import get_asset, read_asset_content, upsert_asset


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _task_result(client, wait_task, task_id: str) -> dict:
    """等待后台任务完成并返回 result（决策 35 后台化适配）。"""
    st = wait_task(client, task_id)
    assert st["status"] == "success", st.get("error")
    return st["result"] or {}


def _get_book(book_id: int) -> Book:
    db = SessionLocal()
    try:
        return db.get(Book, book_id)
    finally:
        db.close()


def _add_relation(db, a: int, b: int, strength: float = 85.0, feedback: str | None = None):
    from app.models.graph import BookRelation

    rel = BookRelation(
        book_a_id=min(a, b),
        book_b_id=max(a, b),
        strength=strength,
        direction="无",
        relation_type="概念共现",
        reasons_json=json.dumps(["变分法", "泛函"], ensure_ascii=False),
        user_feedback=feedback,
    )
    db.add(rel)
    db.commit()
    return rel.id


def test_link_graph_assets_attaches_stubs_and_idempotent(client):
    """本地联动存根：强度达标关联为两本书补 linked_books；幂等不 bump 版本。"""
    from app.services.graph_sync import link_graph_assets

    a = _import_md(client, "联动A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "联动B.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 85.0)
        result = link_graph_assets(db)
        assert result["stubs"] == 2
        rag_a = read_asset_content(db, a, "rag")
        assert any(x["book_id"] == b and x["strength"] == 85.0 for x in rag_a.get("linked_books", []))
        rag_b = read_asset_content(db, b, "rag")
        assert any(x["book_id"] == a for x in rag_b.get("linked_books", []))

        # 幂等：重复调用不写库、不 bump 版本
        version_a = get_asset(db, a, "rag").version
        assert link_graph_assets(db)["stubs"] == 0
        assert get_asset(db, a, "rag").version == version_a
    finally:
        db.close()


def test_rebuild_returns_linked_and_lazy_get_attaches(client, wait_task):
    """重建/懒构建触发本地联动：返回 linked 计数；弱关联不生成存根。"""
    a = _import_md(client, "联动C.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n\n# 第二章 泛函分析\n\n泛函空间。\n")
    b = _import_md(client, "联动D.md", "# 第一章 泛函分析入门\n\n泛函与极值问题在变分法中常见。\n\n# 第二章 变分方法\n\n变分法应用。\n")
    stats = _task_result(client, wait_task, client.post("/api/graph/rebuild").json()["data"]["task_id"])
    assert stats["books"] == 2
    assert "linked" in stats
    db = SessionLocal()
    try:
        rag_a = read_asset_content(db, a, "rag")
        rag_b = read_asset_content(db, b, "rag")
        assert any(x["book_id"] == b for x in rag_a.get("linked_books", [])) or any(
            x["book_id"] == a for x in rag_b.get("linked_books", [])
        ), "强关联书应生成本地联动存根"
    finally:
        db.close()

    # 弱关联（strength 20）不生成存根
    c = _import_md(client, "联动E.md", "# 第一章\n\n完全无关的烹饪技巧内容。\n")
    db = SessionLocal()
    try:
        _add_relation(db, c, a, 20.0)
        from app.services.graph_sync import link_graph_assets

        assert link_graph_assets(db)["stubs"] == 0
        assert "linked_books" not in read_asset_content(db, c, "rag")
    finally:
        db.close()


def test_link_domain_terms_hydrates_and_idempotent(client):
    """RAG 术语补水：书名 + key_points 抽取术语、跳过泛化词、幂等。"""
    from app.services.graph_sync import link_domain_terms

    book_id = _import_md(client, "术语书.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    db = SessionLocal()
    try:
        upsert_asset(
            db,
            book_id,
            "rag",
            {"title": "术语书", "summary": "变分法与泛函分析概述", "key_points": ["变分法研究泛函极值问题"]},
        )
        assert link_domain_terms(db) == 1
        rag = read_asset_content(db, book_id, "rag")
        assert "泛函" in rag["domain_terms"]
        assert "变分" in rag["domain_terms"]
        assert not any(t in ("定理", "方法", "概述") for t in rag["domain_terms"])
        assert link_domain_terms(db) == 0  # 幂等
    finally:
        db.close()


def test_sync_route_llm_linkage(client, monkeypatch, wait_task):
    """POST /api/graph/sync：LLM 联动对受影响书增量增改 RAG/Skill，version+1。"""
    from app.services import graph_sync

    calls: list = []

    class _FakeClient:
        def chat(self, messages):
            calls.append(messages)
            return json.dumps(
                {
                    "summary": "本书介绍变分法与泛函分析，并与《联动G》存在跨书关联。",
                    "key_points": ["变分法研究泛函极值", "跨书关联：《联动G》共同概念 泛函/极值"],
                    "skills": [
                        {"name": "跨书对比法", "applicable": "跨书串联", "usage": "步骤", "sources": ["跨书关联"]}
                    ],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _FakeClient())

    a = _import_md(client, "联动F.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "联动G.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 80.0)
    finally:
        db.close()

    resp = client.post("/api/graph/sync")
    assert resp.status_code == 200
    data = _task_result(client, wait_task, resp.json()["data"]["task_id"])
    assert data["llm_updated"] == 2
    assert data["domain_terms"] >= 0

    db = SessionLocal()
    try:
        rag_a = read_asset_content(db, a, "rag")
        assert "跨书关联" in json.dumps(rag_a, ensure_ascii=False)
        skill_a = read_asset_content(db, a, "skill")
        assert skill_a["skills"][0]["name"] == "跨书对比法"
        assert get_asset(db, a, "rag").version >= 2
        # 关联仍保留在 linked_books（LLM 覆盖不丢存根）
        assert any(x["book_id"] == b for x in rag_a.get("linked_books", []))
    finally:
        db.close()
    assert calls, "应调用 LLM 联动"


def test_sync_without_llm_keeps_local_stub(client, monkeypatch, wait_task):
    """未配置 AI 时 /api/graph/sync 仅补本地存根，不报错。"""
    from app.services import graph_sync

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: False)
    a = _import_md(client, "联动H.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "联动I.md", "# 第一章 泛函分析\n\n泛函空间。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 75.0)
    finally:
        db.close()
    data = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert data["llm_updated"] == 0
    db = SessionLocal()
    try:
        assert read_asset_content(db, a, "rag").get("linked_books"), "无 AI 也应补本地存根"
    finally:
        db.close()