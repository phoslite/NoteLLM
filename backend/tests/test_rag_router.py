"""决策 34 验收测试：LLM 自主挑选 RAG/Skill（跨书注入 + 会话缓存 + 降级 + 页模式 + 隐私）。

覆盖：候选目录分组、LLM 挑选预算裁剪与当前书兜底、挑选失败降级规则方案、
session_id 会话缓存（同章复用/跨章重挑）、跨书 chunks 出处格式、
页模式仍注入 RAG、隐私关闭仅注入 Skill、跨书引用解析。
"""
import json
from types import SimpleNamespace

from app.ai.client import LLMClient, LLMError
from app.core.database import SessionLocal
from app.models.book import Book, Chapter
from app.repositories.assets import save_asset_content
from app.services.chat_service import build_messages, prepare_chat_job
from app.services.citations import extract_citations
from app.services.rag_router import (
    _SESSION_CACHE,
    _cache_get,
    _cache_put,
    build_catalog,
    clear_session_cache,
    select_knowledge,
)


def _upload(client, title, text=None):
    # 书名取自正文首个标题（导入服务约定），这里用书名作标题保证断言稳定
    body = text or f"# {title}\n\n正文第一段\n\n# 第二章\n\n正文二\n"
    r = client.post(
        "/api/books", files={"file": (f"{title}.md", body.encode("utf-8"), "text/markdown")}
    )
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _configure(client):
    r = client.patch(
        "/api/settings/ai",
        json={"base_url": "http://127.0.0.1:18999/v1", "api_key": "sk-test", "model": "mock", "mode": "responses"},
    )
    assert r.status_code == 200


def _add_rag_skill(db, book_id, rag_summary="摘要", skill_name="技巧", chunks=None, skills=None):
    save_asset_content(
        db,
        book_id,
        "rag",
        {
            "summary": rag_summary,
            "key_points": ["要点A", "要点B"],
            "chunks": chunks
            or [
                {"chapter_index": 1, "chapter_title": "第一章", "para_pos": "1", "text": "正文第一段"},
                {"chapter_index": 2, "chapter_title": "第二章", "para_pos": "2", "text": "正文二"},
            ],
        },
    )
    save_asset_content(
        db,
        book_id,
        "skill",
        {
            "skills": skills
            or [{"name": skill_name, "applicable": "适用场景", "usage": "使用步骤", "sources": ["第一章"]}]
        },
    )


def _set_tags(db, book_id, tags):
    book = db.get(Book, book_id)
    book.tags_json = json.dumps(tags)
    db.commit()


def test_catalog_groups_by_domain_and_marks_current(client):
    db = SessionLocal()
    try:
        a = _upload(client, "线性代数")
        b = _upload(client, "复分析")
        _set_tags(db, a, ["数学"])
        _set_tags(db, b, ["数学"])
        _add_rag_skill(db, a, rag_summary="矩阵与行列式")
        _add_rag_skill(db, b, rag_summary="全纯函数")
        text, index = build_catalog(db, current_book_id=a)
        assert "【数学】" in text
        assert f"id={a}" in text and "《线性代数》" in text
        assert "【当前阅读】" in text  # 当前书标记
        assert "矩阵与行列式" in text  # 摘要截断注入
        assert "技巧" in text  # 技能名注入
        assert index[a]["domain"] == "数学"
        assert len(index) == 2
    finally:
        db.close()


def test_llm_selection_caps_and_injects_cross_book_chunks(client, monkeypatch):
    """LLM 返回超预算选择 → 裁剪；当前书自动选入；跨书 chunks 带书名。"""
    _configure(client)
    db = SessionLocal()
    try:
        a = _upload(client, "当前书")
        b = _upload(client, "相关书")
        _add_rag_skill(db, a, rag_summary="当前书摘要", skill_name="当前技巧")
        _add_rag_skill(
            db,
            b,
            rag_summary="相关书摘要",
            skill_name="相关技巧",
            skills=[
                {"name": "相关技巧", "applicable": "适用", "usage": "步骤", "sources": []},
                {"name": "进阶技巧", "applicable": "适用", "usage": "步骤", "sources": []},
            ],
        )
        calls = []

        def fake_chat(self, messages):
            calls.append(messages)
            # 返回 3 个 skill（超预算 2）并故意漏掉当前书 → 当前书兜底 + 裁剪
            return json.dumps({
                "selected_books": [{"book_id": b, "reasons": "相关"}],
                "selected_skills": [
                    {"book_id": b, "name": "相关技巧"},
                    {"book_id": b, "name": "进阶技巧"},
                    {"book_id": b, "name": "不存在技能"},
                ],
                "reasons": "测试挑选",
            })

        monkeypatch.setattr(LLMClient, "chat", fake_chat)
        chapter = db.query(Chapter).filter_by(book_id=a).first()
        out = select_knowledge(db, db.get(Book, a), chapter, "什么是矩阵")
        assert out["source"] == "llm"
        assert len(calls) == 1
        # 当前书兜底 + 相关书
        assert out["selection"]["book_ids"] == [a, b]
        titles = {c["book_title"] for c in out["chunks"]}
        assert titles == {"当前书", "相关书"}
        assert all("book_id" in c and "book_title" in c for c in out["chunks"])
        # skill 预算裁剪（2 上限；不存在的技能被过滤）
        assert out["selection"]["skill_refs"] == [
            {"book_id": b, "name": "相关技巧"},
            {"book_id": b, "name": "进阶技巧"},
        ]
        assert len(out["skills"]) == 2
        # 系统提示词包含预算说明
        assert "最多 3 本书" in calls[0][0]["content"] or "最多 3 本" in calls[0][0]["content"]
    finally:
        db.close()
        clear_session_cache()


def test_selector_failure_falls_back_to_rules(client, monkeypatch):
    """LLM 挑选失败（抛错/坏 JSON）→ 规则降级：当前书 chunks 仍注入。"""
    _configure(client)
    db = SessionLocal()
    try:
        a = _upload(client, "当前书")
        _add_rag_skill(db, a, rag_summary="摘要", skill_name="技巧")

        def fail_chat(self, messages):
            raise LLMError("模拟挑选失败")

        monkeypatch.setattr(LLMClient, "chat", fail_chat)
        chapter = db.query(Chapter).filter_by(book_id=a).first()
        out = select_knowledge(db, db.get(Book, a), chapter, "问题")
        assert out["source"] == "fallback"
        assert out["selection"]["book_ids"] == [a]
        assert len(out["chunks"]) >= 1
    finally:
        db.close()
        clear_session_cache()


def test_fallback_keeps_null_feedback_relations(client, monkeypatch):
    """回归（审查 P0）：_select_fallback 的 user_feedback != "忽略" 漏 NULL 处理——
    user_feedback IS NULL 的边（默认绝大多数）应视为未忽略并纳入谱系关联候选。"""
    from app.models.graph import BookRelation

    _configure(client)
    db = SessionLocal()
    try:
        a = _upload(client, "当前书")
        b = _upload(client, "关联书B")
        c = _upload(client, "忽略书C")
        for bid in (a, b, c):
            _add_rag_skill(db, bid, rag_summary="摘要", skill_name="技巧")
        # 默认 NULL 反馈（多数边）与显式「忽略」各一条
        db.add_all([
            BookRelation(book_a_id=min(a, b), book_b_id=max(a, b), strength=90.0,
                         direction="无", relation_type="概念共现", reasons_json="[]", user_feedback=None),
            BookRelation(book_a_id=min(a, c), book_b_id=max(a, c), strength=95.0,
                         direction="无", relation_type="概念共现", reasons_json="[]", user_feedback="忽略"),
        ])
        db.commit()

        def fail_chat(self, messages):
            raise LLMError("模拟挑选失败")

        monkeypatch.setattr(LLMClient, "chat", fail_chat)
        chapter = db.query(Chapter).filter_by(book_id=a).first()
        out = select_knowledge(db, db.get(Book, a), chapter, "问题")
        assert out["source"] == "fallback"
        # NULL 反馈边未被过滤：B 入选；「忽略」边被排除：C 不入选
        assert b in out["selection"]["book_ids"]
        assert c not in out["selection"]["book_ids"]
    finally:
        db.close()
        clear_session_cache()


def test_session_cache_cap_sweeps_oldest(client, monkeypatch):
    """审查问题 10：会话缓存超限时写时清扫最旧。"""
    monkeypatch.setattr("app.services.rag_router._SESSION_CACHE_MAX", 2)
    _SESSION_CACHE.clear()
    try:
        _cache_put("s:1", {"v": 1})
        _cache_put("s:2", {"v": 2})
        _cache_put("s:3", {"v": 3})
        assert len(_SESSION_CACHE) == 2
        assert _cache_get("s:1") is None  # 最旧被淘汰
        assert _cache_get("s:3") == {"v": 3}
    finally:
        _SESSION_CACHE.clear()
        monkeypatch.undo()


def test_session_cache_reuses_within_chapter(client, monkeypatch):
    """会话内缓存：同 session+章节复用挑选结果（不再调 LLM）；跨章节重新挑选。"""
    _configure(client)
    db = SessionLocal()
    try:
        a = _upload(client, "当前书", text="# 第一章\n\n一\n\n# 第二章\n\n二\n")
        _add_rag_skill(db, a, rag_summary="摘要", skill_name="技巧")
        calls = []

        def fake_chat(self, messages):
            calls.append(messages)
            return json.dumps({"selected_books": [], "selected_skills": [], "reasons": ""})

        monkeypatch.setattr(LLMClient, "chat", fake_chat)
        book = db.get(Book, a)
        ch1 = db.query(Chapter).filter_by(book_id=a, index=1).first()
        ch2 = db.query(Chapter).filter_by(book_id=a, index=2).first()
        r1 = select_knowledge(db, book, ch1, "q1", session_id="sess-1")
        assert r1["source"] == "llm"
        r2 = select_knowledge(db, book, ch1, "q2-不同问题", session_id="sess-1")
        assert r2["source"] == "cache"  # 同章复用
        r3 = select_knowledge(db, book, ch2, "q3", session_id="sess-1")
        assert r3["source"] == "llm"  # 跨章重挑
        r4 = select_knowledge(db, book, ch2, "q4", session_id="sess-2")
        assert r4["source"] == "llm"  # 不同会话不共享
        assert len(calls) == 3
        # 无 session_id 不缓存
        r5 = select_knowledge(db, book, ch1, "q5")
        assert r5["source"] == "llm"
        assert len(calls) == 4
    finally:
        db.close()
        clear_session_cache()


def test_build_messages_page_mode_includes_rag_block():
    """页模式（决策 34 定稿）：页缓存与跨书 RAG 片段同时注入。"""
    chapter = SimpleNamespace(index=3, title="第三章", content_text="正文", page_index=7, id=99)
    rag_block = "【《相关书》第2章 第1段】片段内容"
    messages = build_messages(
        SimpleNamespace(title="当前书"),
        chapter,
        "问题",
        "选中",
        rag_block,
        [{"name": "技巧", "applicable": "适用", "usage": "步骤"}],
        True,
        page_context="【第 7 页】\n页内容",
        page_mode=True,
    )
    user = messages[-1]["content"]
    assert "【当前页及相邻页内容（页缓存）】" in user
    assert "【检索到的相关片段（含出处）】" in user
    assert "《相关书》" in user
    system = messages[0]["content"]
    assert "【《书名》第X章 第Y段】" in system  # 跨书引用规则已注入系统提示


def test_privacy_off_injects_skills_only(client):
    """隐私关闭：只注入 Skill，不注入跨书 chunks（决策 34 敲定）。"""
    _configure(client)
    db = SessionLocal()
    try:
        a = _upload(client, "当前书")
        b = _upload(client, "相关书")
        _add_rag_skill(db, a, rag_summary="摘要A", skill_name="技巧A")
        _add_rag_skill(db, b, rag_summary="摘要B", skill_name="技巧B")
        # 关闭正文发送
        assert client.patch("/api/settings/ai", json={"enable_body_send": False}).status_code == 200
        book = db.get(Book, a)
        chapter = db.query(Chapter).filter_by(book_id=a).first()
        job = prepare_chat_job(db, book, chapter, "问题", "", mode=None, session_id="priv-sess")
        system = job["messages"][0]["content"]
        assert "技巧" in system  # Skill 照常注入
        user = job["messages"][-1]["content"]
        assert "【检索到的相关片段（含出处）】" not in user  # chunks 不注入
        assert "（正文未发送，遵循隐私设置）" in user
    finally:
        db.close()
        clear_session_cache()


def test_cross_book_citation_parsing():
    """跨书出处【《书名》第X章 第Y段】仍可被引用解析（citations 扩展）。"""
    assert extract_citations("见【《数学分析》第3章 第5段】结论。") == [{"chapter": 3, "para": "5"}]
    assert extract_citations("当前章【第2章 第1段】与页模式【第7页】混合") == [
        {"chapter": 2, "para": "1"},
        {"chapter": 7, "para": "页"},
    ]
