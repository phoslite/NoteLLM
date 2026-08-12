"""L2 联动沉淀优化回归：并发 chat（GRAPH_SYNC_CONCURRENCY，默认 1=串行）、进度回调、失败隔离。

docs/联动沉淀优化方案.md §3.6：三段式执行（主线程准备 → 并发 chat → 主线程落盘），
非视觉 e2e（API 级断言，不依赖浏览器）。
"""
import json
import threading
import time

from app.core.database import SessionLocal


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _add_relation(db, a: int, b: int, strength: float = 80.0):
    from sqlalchemy import delete

    from app.models.graph import BookRelation

    # 唯一约束（审查 P1-3）：同 pair 先删后插（upsert 语义），覆盖导入后台自动边
    db.execute(
        delete(BookRelation).where(
            BookRelation.book_a_id == min(a, b), BookRelation.book_b_id == max(a, b)
        )
    )
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


def _fake_reply() -> str:
    return json.dumps(
        {
            "summary": "跨书关联总结：变分法与泛函分析存在共同概念。",
            "key_points": ["变分法研究泛函极值", "跨书关联：泛函空间"],
            "skills": [{"name": "对比法", "applicable": "跨书", "usage": "步骤", "sources": ["跨书关联"]}],
        },
        ensure_ascii=False,
    )


def _setup_three_books(client) -> tuple[int, int, int]:
    a = _import_md(client, "L2A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "L2B.md", "# 第一章 泛函分析\n\n泛函空间与极值问题。\n")
    c = _import_md(client, "L2C.md", "# 第一章 测度论\n\n测度空间与泛函极值。\n")
    db = SessionLocal()
    try:
        _add_relation(db, a, b, 90.0)
        _add_relation(db, a, c, 60.0)
    finally:
        db.close()
    return a, b, c


def test_sync_concurrent_parallel_and_progress(client, monkeypatch):
    """L2：GRAPH_SYNC_CONCURRENCY=2 时并发调用（峰值 ≥2）、调用次数与串行一致、进度按书回调。"""
    from app.core.config import settings
    from app.services import graph_sync

    monkeypatch.setattr(settings, "graph_sync_concurrency", 2)
    state = {"in_flight": 0, "peak": 0}
    lock = threading.Lock()
    calls: list = []
    progress: list[tuple[int, int]] = []

    class _FakeClient:
        def chat(self, messages):
            calls.append(messages)
            with lock:
                state["in_flight"] += 1
                state["peak"] = max(state["peak"], state["in_flight"])
            try:
                time.sleep(0.05)
                return _fake_reply()
            finally:
                with lock:
                    state["in_flight"] -= 1

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _FakeClient())

    a, b, c = _setup_three_books(client)
    db = SessionLocal()
    try:
        from app.services.graph_sync import sync_assets_for_relations

        result = sync_assets_for_relations(db, on_progress=lambda d, t: progress.append((d, t)))
    finally:
        db.close()
    assert result["llm_updated"] == 3, result
    assert result["llm_skipped"] == 0
    assert len(calls) == 3, "并发不应改变调用次数（每书一次）"
    assert state["peak"] >= 2, f"应观察到并发，实际峰值 {state['peak']}"
    assert progress == [(1, 3), (2, 3), (3, 3)], progress

    # 幂等：并发模式下重跑指纹命中 → 零调用、零更新
    db = SessionLocal()
    try:
        second = sync_assets_for_relations(db)
    finally:
        db.close()
    assert second["llm_updated"] == 0
    assert second["llm_skipped"] == 3
    assert len(calls) == 3


def test_sync_concurrent_failure_isolated(client, monkeypatch):
    """L2：并发下单书 chat 失败只回滚该书，其余书照常落盘；进度仍按书走完。"""
    from app.core.config import settings
    from app.services import graph_sync

    monkeypatch.setattr(settings, "graph_sync_concurrency", 2)
    progress: list[tuple[int, int]] = []

    class _FlakyClient:
        def chat(self, messages):
            content = messages[-1]["content"]
            if "书籍：《第一章 变分法》" in content:
                raise RuntimeError("boom")
            time.sleep(0.02)
            return _fake_reply()

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _FlakyClient())

    a, b, c = _setup_three_books(client)
    db = SessionLocal()
    try:
        from app.repositories.assets import get_asset, read_asset_content
        from app.services.graph_sync import sync_assets_for_relations

        result = sync_assets_for_relations(db, on_progress=lambda d, t: progress.append((d, t)))
        assert result["llm_updated"] == 2, result
        assert result["llm_skipped"] == 0
        assert progress == [(1, 3), (2, 3), (3, 3)], progress
        assert "跨书关联总结" in read_asset_content(db, b, "rag").get("summary", "")
        assert "跨书关联总结" in read_asset_content(db, c, "rag").get("summary", "")
        assert get_asset(db, a, "rag").version == 1, "失败书不 bump 版本"
        assert get_asset(db, b, "rag").version >= 2
    finally:
        db.close()


def test_sync_concurrency_one_is_serial(client, monkeypatch):
    """L2：GRAPH_SYNC_CONCURRENCY=1（默认）时串行执行（峰值 == 1），语义与 L1 一致。"""
    from app.core.config import settings
    from app.services import graph_sync

    monkeypatch.setattr(settings, "graph_sync_concurrency", 1)
    state = {"in_flight": 0, "peak": 0}
    lock = threading.Lock()

    class _FakeClient:
        def chat(self, messages):
            with lock:
                state["in_flight"] += 1
                state["peak"] = max(state["peak"], state["in_flight"])
            try:
                time.sleep(0.02)
                return _fake_reply()
            finally:
                with lock:
                    state["in_flight"] -= 1

    monkeypatch.setattr(graph_sync, "is_configured", lambda db: True)
    monkeypatch.setattr(graph_sync, "build_client", lambda db: _FakeClient())

    _setup_three_books(client)
    db = SessionLocal()
    try:
        from app.services.graph_sync import sync_assets_for_relations

        result = sync_assets_for_relations(db)
    finally:
        db.close()
    assert result["llm_updated"] == 3
    assert state["peak"] == 1, f"串行模式峰值应为 1，实际 {state['peak']}"


def test_graph_sync_concurrency_settings_override(client):
    """设置页覆盖 graph_sync_concurrency：视图回显 + _sync_llm_workers 消费 DB 覆盖（0=不限制）。"""
    from app.core.database import SessionLocal
    from app.services.graph_sync import _sync_llm_workers

    r = client.patch("/api/settings/ai", json={"graph_sync_concurrency": 4})
    assert r.status_code == 200
    assert r.json()["data"]["graph_sync_concurrency"] == 4
    db = SessionLocal()
    try:
        assert _sync_llm_workers(db, 3) == 4, "DB 覆盖应优先于 .env"
        client.patch("/api/settings/ai", json={"graph_sync_concurrency": 0})
        assert _sync_llm_workers(db, 3) == 3, "0=不限制：worker 数取 min(书数,8)"
        assert _sync_llm_workers(db, 20) == 8, "0=不限制：上限 8"
        client.patch("/api/settings/ai", json={"graph_sync_concurrency": 1})
        assert _sync_llm_workers(db, 3) == 1, "1=串行"
    finally:
        db.close()
