"""性能优化第二/三梯队（docs/性能优化路径.md §5/§6）验证。

覆盖：
- 会话历史裁剪（默认只留最近 200 条，0=不限）；
- LLM 结果缓存（内容寻址命中 / TTL 过期 / 容量淘汰最旧 / 按书与全量清理）；
- FTS5 全书搜索（中文子串命中 / 短词 LIKE 回退 / 删除章节联动清理）；
- 预设模式缓存键（确定性、输入变化产生新键、非可缓存模式与关闭缓存返回 None）。
"""
import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine, init_db
from app.core.time import utcnow
from app.models.activity import ChatMessage
from app.models.book import Book, Chapter
from app.models.llm_cache import LlmCache
from app.repositories.chat import persist_chat
from app.services.llm_cache import clear_llm_cache, get_llm_cache, set_llm_cache


@pytest.fixture(autouse=True)
def _ensure_tables():
    init_db()  # 本模块直接使用 SessionLocal（不经 TestClient）：先建表（含 FTS 虚表，幂等）
    yield
    # teardown：与 client 夹具一致的完整隔离——drop 全部业务表 + FTS 虚表（残留 rowid/回填会污染后续测试）
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fts_chapters"))


def _seed_book(db, title="性能测试书", chapter_text="变分法研究泛函极值问题，泛函分析是基础。"):
    book = Book(title=title, format="md", file_path="/tmp/perf_tier2.md", content_hash="perf-t2")
    db.add(book)
    db.commit()
    ch = Chapter(book_id=book.id, index=1, title="第一章 变分法", content_text=chapter_text)
    db.add(ch)
    db.commit()
    return book, ch


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_chat_history_trimmed_and_unlimited(monkeypatch):
    """性能决策 1：persist_chat 后自动裁剪到最近 200 条；limit=0 不限制。"""
    monkeypatch.setattr(settings, "chat_history_limit", 200)
    db = SessionLocal()
    try:
        book, ch = _seed_book(db)
        for i in range(103):  # 103 轮 = 206 条 → 裁剪到 200
            persist_chat(db, book.id, ch.id, "", f"q{i}", f"a{i}")
        assert _count(db, ChatMessage) == 200
        newest = db.scalars(select(ChatMessage.content).order_by(ChatMessage.id.desc()).limit(2)).all()
        assert "q102" in newest or "a102" in newest  # 最新保留
        assert db.scalar(select(ChatMessage).where(ChatMessage.content == "q0")) is None  # 最旧被裁

        monkeypatch.setattr(settings, "chat_history_limit", 0)  # 0=不限制
        persist_chat(db, book.id, ch.id, "", "q200", "a200")
        assert _count(db, ChatMessage) == 202
    finally:
        db.close()


def test_llm_cache_hit_ttl_and_clear(monkeypatch):
    """性能决策 5：缓存命中返回内容；过期自动失效并清理；按书/全量清空。"""
    monkeypatch.setattr(settings, "llm_cache_max_entries", 300)
    monkeypatch.setattr(settings, "llm_cache_ttl_days", 30)
    db = SessionLocal()
    try:
        book_a, _ = _seed_book(db, title="缓存书A")
        book_b, _ = _seed_book(db, title="缓存书B")
        set_llm_cache(db, book_a.id, "mindmap", "key-a", {"tree": {"name": "T"}})
        set_llm_cache(db, book_b.id, "解读", "key-b", {"answer": "回答B"})
        assert get_llm_cache(db, book_a.id, "mindmap", "key-a") == {"tree": {"name": "T"}}
        assert get_llm_cache(db, book_a.id, "mindmap", "miss") is None

        # TTL 过期 → 未命中且行被清理
        row = db.scalar(select(LlmCache).where(LlmCache.book_id == book_a.id))
        row.expires_at = utcnow() - timedelta(days=1)
        db.commit()
        assert get_llm_cache(db, book_a.id, "mindmap", "key-a") is None
        assert _count(db, LlmCache) == 1  # 过期行已删除，只剩 B

        assert clear_llm_cache(db, book_b.id) == 1
        assert _count(db, LlmCache) == 0
        set_llm_cache(db, book_a.id, "mindmap", "key-a", {"tree": {"name": "T"}})
        assert clear_llm_cache(db) == 1
        assert _count(db, LlmCache) == 0
    finally:
        db.close()


def test_llm_cache_capacity_evicts_oldest(monkeypatch):
    """性能决策 5：写入超容量上限时删除最旧条目（含全部 kind 的全局容量）。"""
    monkeypatch.setattr(settings, "llm_cache_max_entries", 2)
    db = SessionLocal()
    try:
        clear_llm_cache(db)  # 清掉前序测试残留，保证全局容量断言确定性
        book, _ = _seed_book(db, title="容量书")
        set_llm_cache(db, book.id, "mindmap", "k1", {"v": 1})
        set_llm_cache(db, book.id, "解读", "k2", {"v": 2})
        set_llm_cache(db, book.id, "概论", "k3", {"v": 3})
        assert get_llm_cache(db, book.id, "mindmap", "k1") is None  # 最旧被淘汰
        assert get_llm_cache(db, book.id, "解读", "k2") == {"v": 2}
        assert get_llm_cache(db, book.id, "概论", "k3") == {"v": 3}
        assert _count(db, LlmCache) == 2
    finally:
        db.close()


def test_mode_cache_key_deterministic(monkeypatch):
    """预设模式缓存键：确定性；提问/选区/模式变化产生新键；非可缓存模式与关闭缓存返回 None。"""
    from types import SimpleNamespace

    from app.services.chat_service import build_mode_cache_key

    monkeypatch.setattr(settings, "llm_cache_max_entries", 100)
    db = SessionLocal()
    try:
        chapter = SimpleNamespace(id=7, content_text="线性空间与度量空间", page_index=None)
        k1 = build_mode_cache_key(db, None, chapter, "请解读本章", "", "解读")
        assert k1
        assert build_mode_cache_key(db, None, chapter, "请解读本章", "", "解读") == k1
        assert build_mode_cache_key(db, None, chapter, "请解读本章", "选中一段", "解读") != k1
        assert build_mode_cache_key(db, None, chapter, "请解读本章", "", "概论") != k1
        assert build_mode_cache_key(db, None, chapter, "请解读本章", "", "") is None
        assert build_mode_cache_key(db, None, chapter, "请解读本章", "", "思考逻辑") is not None
        monkeypatch.setattr(settings, "llm_cache_max_entries", 0)
        assert build_mode_cache_key(db, None, chapter, "请解读本章", "", "解读") is None
    finally:
        db.close()


def test_fts_search_chinese_substring_and_delete_sync():
    """性能决策 3：trigram 中文子串命中、短词 LIKE 回退、删除章节联动清理 FTS 行。"""
    if not settings.fts_search_enabled:
        return
    from app.services.search_service import search_books

    init_db()  # 建表 + FTS 虚表/触发器（幂等）
    db = SessionLocal()
    try:
        book, ch = _seed_book(db, title="搜索书", chapter_text="变分法研究泛函极值问题，泛函分析是基础。")
        assert any(h["chapter_id"] == ch.id for h in search_books(db, "极值问题"))  # trigram 子串
        assert any(h["chapter_id"] == ch.id for h in search_books(db, "泛函分析"))
        assert any(h["chapter_id"] == ch.id for h in search_books(db, "极值"))  # 短词 LIKE 回退
        assert any(h["chapter_id"] == ch.id for h in search_books(db, "变分法"))  # 标题命中
        db.delete(ch)
        db.commit()
        assert not any(h["chapter_id"] == ch.id for h in search_books(db, "极值问题"))
        assert not any(h["chapter_id"] == ch.id for h in search_books(db, "极值"))
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM fts_chapters"))  # 测试隔离：清掉跨测试残留
        db.close()


def test_search_disabled_returns_empty(monkeypatch):
    """fts_search_enabled=False：接口/服务直接返回空，不建索引。"""
    monkeypatch.setattr(settings, "fts_search_enabled", False)
    db = SessionLocal()
    try:
        book, ch = _seed_book(db, title="禁用搜索书")
        from app.services.search_service import search_books

        assert search_books(db, "极值") == []
        assert search_books(db, "极值问题") == []
        assert search_books(db, "   ") == []
        db.delete(ch)
        db.delete(book)
        db.commit()
    finally:
        db.close()

# ---------- 集成层：搜索路由 + 预设模式问答缓存回放 ----------

def _upload_md(client, text="# 第一章 变分法\n\n变分法研究泛函极值问题，泛函分析是基础。"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]


def test_search_route_returns_chapter_hits(client):
    """GET /api/books/search?q=：章节级命中（trigram 子串），空关键词返回空列表。"""
    data = _upload_md(client)
    hits = client.get("/api/books/search", params={"q": "极值问题"}).json()["data"]
    assert hits and hits[0]["book_id"] == data["id"]
    assert hits[0]["chapter_index"] == 1
    assert "极值问题" in (hits[0]["snippet"] or "") or hits[0]["snippet"]
    assert client.get("/api/books/search", params={"q": "   "}).json()["data"] == []


def test_mode_chat_second_call_served_from_cache(client, monkeypatch):
    """预设模式问答：首次流式并写入 LLM 缓存，同键二次请求直接回放（end.cached=true，不再调用 LLM）。"""
    from app.ai.client import LLMClient

    # 与 test_chat 相同的配置方式：落 settings 表
    client.patch(
        "/api/settings/ai",
        json={"base_url": "http://127.0.0.1:18999/v1", "api_key": "sk-test", "model": "mock", "mode": "responses"},
    )
    data = _upload_md(client)
    ch = client.get(f"/api/books/{data['id']}").json()["data"]["chapters"][0]["id"]

    calls = {"n": 0}

    def fake_stream_events(self, messages):
        calls["n"] += 1
        yield {"kind": "delta", "text": "缓存回答：变分法研究泛函极值【第1章 第1段】。"}

    monkeypatch.setattr(LLMClient, "stream_events", fake_stream_events)

    def read_events(resp):
        return [json.loads(line[5:]) for line in resp.iter_lines() if (line or "").startswith("data:")]

    body = {"question": "请对本章进行解读", "chapter_id": ch, "mode": "解读"}
    with client.stream("POST", f"/api/books/{data['id']}/chat", json=body) as resp:
        assert resp.status_code == 200
        evs1 = read_events(resp)
        assert evs1[-1]["type"] == "end" and evs1[-1]["cached"] is False
    with client.stream("POST", f"/api/books/{data['id']}/chat", json=body) as resp:
        evs2 = read_events(resp)
        assert evs2[-1]["type"] == "end"
        assert evs2[-1]["cached"] is True
        assert evs2[-1]["text"] == "缓存回答：变分法研究泛函极值【第1章 第1段】。"
    assert calls["n"] == 1  # 第二次请求未调用 LLM

    # 历史落库：两次提问产生两条 user 记录（回放也会写历史）
    msgs = client.get(f"/api/books/{data['id']}/chat/messages", params={"mode": "解读"}).json()["data"]
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 2
