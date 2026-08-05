"""决策 37 测试：主页全局 AI 对话——无书级路由、全局知识挑选（降级/缓存）、global 会话历史。"""
from app.ai.client import LLMClient
from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories.assets import upsert_asset
from app.repositories.chat import global_session_id, recent_history_texts
from app.services.chat_service import prepare_global_job
from app.services.rag_router import select_global_knowledge


def _upload(client, text="# 第一章\n\n内容甲\n"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _configure(client, **kw):
    body = {"base_url": "http://127.0.0.1:18999/v1", "api_key": "sk-test", "model": "mock", "mode": "responses"}
    body.update(kw)
    r = client.patch("/api/settings/ai", json=body)
    assert r.status_code == 200


def _seed_assets(book_id):
    db = SessionLocal()
    try:
        upsert_asset(
            db,
            book_id,
            "rag",
            {
                "summary": "线性代数：矩阵与向量空间",
                "key_points": ["矩阵乘法"],
                "chunks": [{"chapter_index": 1, "para_pos": "1", "text": "矩阵乘法满足结合律"}],
            },
        )
        upsert_asset(
            db,
            book_id,
            "skill",
            {"skills": [{"name": "证明梳理", "applicable": "数学证明", "usage": "三步", "sources": ["第1章"]}]},
        )
    finally:
        db.close()


def test_global_chat_requires_config(client):
    r = client.post("/api/ai/chat", json={"question": "你好"})
    assert r.status_code == 400
    assert "API Key" in r.json()["detail"]


def test_global_chat_stream_and_history(client, monkeypatch):
    _configure(client)

    def fake_stream_events(self, messages):
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        yield {"kind": "delta", "text": "全局回复，引用【《书》第1章 第1段】。"}

    monkeypatch.setattr(LLMClient, "stream_events", fake_stream_events)
    sid = "panel-001"
    with client.stream("POST", "/api/ai/chat", json={"question": "讲讲矩阵", "session_id": sid}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
        assert "全局回复" in body

    rows = client.get(f"/api/ai/chat/messages?session_id={sid}").json()["data"]
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[-1]["book_id"] is None  # 全局对话不绑定书籍

    db = SessionLocal()
    try:
        hist = recent_history_texts(db, None, session_id=global_session_id(sid))
        assert len(hist) == 2
        assert hist[0]["role"] == "user"
    finally:
        db.close()

    r = client.delete(f"/api/ai/chat/messages?session_id={sid}")
    assert r.status_code == 200
    assert client.get(f"/api/ai/chat/messages?session_id={sid}").json()["data"] == []


def test_global_prepare_job_injects_assets(client, monkeypatch):
    _configure(client)
    book_id = _upload(client)
    _seed_assets(book_id)
    monkeypatch.setattr(settings, "ai_rag_select_enabled", False)

    db = SessionLocal()
    try:
        job = prepare_global_job(db, "矩阵乘法怎么证明", "panel-002")
        user = job["messages"][-1]["content"]
        system = job["messages"][0]["content"]
        assert "矩阵乘法满足结合律" in user  # chunks 注入
        assert "证明梳理" in system  # Skill 注入
        assert job["persist"]["session_id"] == "global:panel-002"
        assert job["persist"]["book_id"] is None

        # 会话内缓存：同 session_id 第二次命中（决策 37）
        k2 = select_global_knowledge(db, "矩阵乘法怎么证明", "panel-002")
        assert k2["source"] == "cache"
    finally:
        db.close()


def test_global_prepare_job_privacy_off(client, monkeypatch):
    _configure(client)
    book_id = _upload(client)
    _seed_assets(book_id)
    monkeypatch.setattr(settings, "ai_rag_select_enabled", False)
    monkeypatch.setattr(settings, "ai_enable_body_send", False)

    db = SessionLocal()
    try:
        job = prepare_global_job(db, "矩阵乘法", "panel-003")
        user = job["messages"][-1]["content"]
        system = job["messages"][0]["content"]
        assert "矩阵乘法满足结合律" not in user  # 隐私关闭不注入 chunks
        assert "证明梳理" in system  # Skill 仍注入
        assert job["persist"]["session_id"] == "global:panel-003"
    finally:
        db.close()
