"""L1 联动沉淀优化回归：按书聚合 multi-link、幂等指纹、force（docs/联动沉淀优化方案.md L1）。"""
import json

from app.core.database import SessionLocal
from app.repositories.assets import get_asset, read_asset_content


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


def _fake_client(calls: list) -> object:
    class _FakeClient:
        def chat(self, messages):
            calls.append(messages)
            return json.dumps(
                {
                    "summary": "跨书关联总结：变分法与泛函分析存在共同概念。",
                    "key_points": ["变分法研究泛函极值", "跨书关联：泛函空间"],
                    "skills": [{"name": "对比法", "applicable": "跨书", "usage": "步骤", "sources": ["跨书关联"]}],
                },
                ensure_ascii=False,
            )

    return _FakeClient()


def test_multi_link_aggregates_edges_per_book(client, monkeypatch, wait_task):
    """L1：同一本书的多条关联合并为一次 LLM 调用（按书聚合），消息含全部关联书。"""
    from app.services import graph_sync

    calls: list = []
    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _fake_client(calls))

    a = _import_md(client, "L1A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "L1B.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    c = _import_md(client, "L1C.md", "# 第一章 测度论\n\n测度空间与泛函极值。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 90.0)
        _add_relation(db, a, c, 60.0)
    finally:
        db.close()

    data = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    # 3 本书受影响（A 聚合两条边，B/C 各一条）→ 3 次调用（原实现为 4 次）
    assert data["llm_updated"] == 3
    assert data["llm_skipped"] == 0
    assert len(calls) == 3
    # A 的调用消息应同时包含《第一章 泛函分析》与《第一章 测度论》（书名取自 md 首个标题）
    a_msg = next(m for m in calls if "书籍：《第一章 变分法》" in m[-1]["content"])
    assert "《第一章 泛函分析》" in a_msg[-1]["content"]
    assert "《第一章 测度论》" in a_msg[-1]["content"]
    assert "本轮跨书关联（共 2 条）" in a_msg[-1]["content"]
    # B/C 的调用各一条关联
    b_msg = next(m for m in calls if "书籍：《第一章 泛函分析》" in m[-1]["content"])
    assert "本轮跨书关联（共 1 条）" in b_msg[-1]["content"]
    c_msg = next(m for m in calls if "书籍：《第一章 测度论》" in m[-1]["content"])
    assert "本轮跨书关联（共 1 条）" in c_msg[-1]["content"]


def test_sync_idempotent_fingerprint_skips(client, monkeypatch, wait_task):
    """L1：边集合未变时重跑 /sync 零 LLM 调用（指纹命中），版本不 bump。"""
    from app.services import graph_sync

    calls: list = []
    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _fake_client(calls))

    a = _import_md(client, "L1D.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "L1E.md", "# 第一章 泛函分析\n\n泛函空间。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 80.0)
    finally:
        db.close()

    first = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert first["llm_updated"] == 2
    assert len(calls) == 2

    db = SessionLocal()
    try:
        version_after_first = get_asset(db, a, "rag").version
        fp = read_asset_content(db, a, "rag").get("linked_sync_fingerprint")
    finally:
        db.close()
    assert fp, "应写入 linked_sync_fingerprint"

    second = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert second["llm_updated"] == 0
    assert second["llm_skipped"] == 2
    assert len(calls) == 2, "指纹命中不应再调用 LLM"
    db = SessionLocal()
    try:
        assert get_asset(db, a, "rag").version == version_after_first, "指纹命中不应 bump 版本"
    finally:
        db.close()


def test_sync_force_reruns_llm(client, monkeypatch, wait_task):
    """L1：force=True 忽略指纹强制重新联动。"""
    from app.services import graph_sync

    calls: list = []
    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _fake_client(calls))

    a = _import_md(client, "L1F.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "L1G.md", "# 第一章 泛函分析\n\n泛函空间。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 80.0)
    finally:
        db.close()

    _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert len(calls) == 2

    # 服务层直接调用 force=True（任务层暂不暴露，验证参数语义）
    from app.services.graph_sync import sync_assets_for_relations

    db = SessionLocal()
    try:
        result = sync_assets_for_relations(db, force=True)
    finally:
        db.close()
    assert result["llm_updated"] == 2
    assert result["llm_skipped"] == 0
    assert len(calls) == 4


def test_fingerprint_invalidates_on_strength_change(client, monkeypatch, wait_task):
    """L1：关联强度变化 → 指纹变化 → 重新联动。"""
    from app.services import graph_sync

    calls: list = []
    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _fake_client(calls))

    a = _import_md(client, "L1H.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "L1I.md", "# 第一章 泛函分析\n\n泛函空间。\n")
    db = SessionLocal()
    try:
        rel_id = _add_relation(db, a, b, 80.0)
    finally:
        db.close()

    _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert len(calls) == 2

    db = SessionLocal()
    try:
        from app.models.graph import BookRelation

        rel = db.get(BookRelation, rel_id)
        rel.strength = 95.0
        db.commit()
    finally:
        db.close()

    third = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert third["llm_updated"] == 2
    assert third["llm_skipped"] == 0
    assert len(calls) == 4


def test_single_edge_matches_previous_behavior(client, monkeypatch, wait_task):
    """L1 兼容：单边两本书 llm_updated=2，返回结构含 llm_skipped。"""
    from app.services import graph_sync

    calls: list = []
    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _fake_client(calls))

    a = _import_md(client, "L1J.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n")
    b = _import_md(client, "L1K.md", "# 第一章 泛函分析\n\n泛函空间。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 85.0)
    finally:
        db.close()

    data = _task_result(client, wait_task, client.post("/api/graph/sync").json()["data"]["task_id"])
    assert data["llm_updated"] == 2
    assert data["llm_skipped"] == 0
    assert "llm_skipped" in data
