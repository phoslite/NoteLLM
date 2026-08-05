"""M7 多模态视觉提取与页缓存：按页提取落盘、缓存命中、滑动窗口增量、隐私开关、随书清理、路由。"""
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from app.core.database import SessionLocal
from app.repositories import books as book_repo
from app.services import vision_extract
from app.services.ai_context import build_page_context_block
from app.services.chat_service import build_messages
from app.services.citations import extract_citations


def _make_pdf(path: Path, pages: int = 4) -> None:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        page.draw_rect(pymupdf.Rect(50, 50, 250, 350), color=(0.2, 0.4, 0.8), fill=(0.9, 0.9, 0.95))
    doc.save(str(path))
    doc.close()


def _import(client, path: Path, name: str):
    r = client.post("/api/books", files={"file": (name, path.read_bytes(), "application/pdf")})
    assert r.status_code == 200
    return r.json()["data"]


def _book(db, book_id):
    return book_repo.get_book(db, book_id)


class FakeVision:
    """记录被提取页号，返回对应页内容。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def chat(self, messages):
        text = next((p.get("text", "") for p in messages[1]["content"] if p.get("type") == "text"), "")
        page = next((int(seg) for seg in text.split() if seg.isdigit()), 0)
        return f"# 第 {page} 页内容\n\n正文示例。\n"


def test_extract_page_writes_cache_and_reuses(monkeypatch, client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=3)
    data = _import(client, pdf, "scan.pdf")
    calls: list[int] = []

    class CountingVision(FakeVision):
        def chat(self, messages):
            calls.append(0)
            return super().chat(messages)

    monkeypatch.setattr(vision_extract, "LLMClient", CountingVision)
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        text = vision_extract.ensure_page_cache(db, book, 2)
        assert "第 2 页内容" in text
        assert len(calls) == 1
        path = vision_extract.page_text_path(book, 2)
        assert path.exists() and path.read_text(encoding="utf-8").strip() == text
        # 命中缓存不重复调用多模态
        again = vision_extract.ensure_page_cache(db, book, 2)
        assert again == text and len(calls) == 1
        # force 强制重提取
        vision_extract.ensure_page_cache(db, book, 2, force=True)
        assert len(calls) == 2
    finally:
        db.close()


def test_window_incremental_cache(monkeypatch, client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=7)
    data = _import(client, pdf, "scan.pdf")
    extracted: list[int] = []

    class Recorder(FakeVision):
        def chat(self, messages):
            text = next((p.get("text", "") for p in messages[1]["content"] if p.get("type") == "text"), "")
            page = next((int(seg) for seg in text.split() if seg.isdigit()), 0)
            extracted.append(page)
            return f"内容 {page}"

    monkeypatch.setattr(vision_extract, "LLMClient", Recorder)
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        w1 = vision_extract.ensure_window_caches(db, book, 1)  # 第 1 页 → [1,2]
        assert list(w1) == [1, 2]
        assert extracted == [1, 2]
        w6 = vision_extract.ensure_window_caches(db, book, 6)  # [5,6,7]
        assert list(w6) == [5, 6, 7]
        assert extracted == [1, 2, 5, 6, 7]
        w7 = vision_extract.ensure_window_caches(db, book, 7)  # [6,7] 全部命中
        assert list(w7) == [6, 7]
        assert extracted == [1, 2, 5, 6, 7]
        # 末页裁剪：不越界
        assert 8 not in w7
    finally:
        db.close()


def test_vision_client_kwargs_force_chat_mode(client):
    """多模态客户端强制 chat 模式并携带 max_tokens（SiliconFlow 仅支持 /chat/completions）。"""
    from app.repositories.settings import vision_client_kwargs

    db = SessionLocal()
    try:
        kwargs = vision_client_kwargs(db)
        assert kwargs["mode"] == "chat"
        assert isinstance(kwargs["max_tokens"], int) and kwargs["max_tokens"] > 0
    finally:
        db.close()


def test_privacy_off_blocks_extraction(client, tmp_path):
    from app.repositories.settings import set_setting

    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan.pdf")
    db = SessionLocal()
    try:
        set_setting(db, "ai_enable_body_send", "0")
        book = _book(db, data["id"])
        try:
            vision_extract.ensure_page_cache(db, book, 1)
            pytest.fail("隐私开关关闭时应抛出 ValueError")
        except ValueError:
            pass
        assert not vision_extract.page_text_path(book, 1).exists()
    finally:
        db.close()


def test_page_cache_removed_with_book(client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan.pdf")
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        p = vision_extract.page_text_path(book, 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    finally:
        db.close()
    r = client.delete(f"/api/books/{data['id']}")
    assert r.status_code == 200
    assert not p.exists()
    assert not p.parent.exists()


def test_reextract_page_route(monkeypatch, client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan.pdf")

    monkeypatch.setattr(vision_extract, "LLMClient", FakeVision)
    # 配置多模态（独立一套）
    r = client.patch(
        "/api/settings/ai",
        json={"vision_base_url": "https://example.com/v1", "vision_api_key": "sk-test", "vision_model": "gpt-4o-mini"},
    )
    assert r.status_code == 200
    view = r.json()["data"]
    assert view["vision_api_key_set"] is True
    assert "sk-test" not in view["vision_api_key"]

    # 未配置时拒绝（先清空配置验证 400 分支在下一处）
    rr = client.post(f"/api/books/{data['id']}/page-text/1")
    assert rr.status_code == 200 and rr.json()["data"]["text"]
    assert "第 1 页" in rr.json()["data"]["text"]

    st = client.get(f"/api/books/{data['id']}/page-text/status").json()["data"]
    assert st["total"] == 2 and st["cached"] == 1

    pg = client.get(f"/api/books/{data['id']}/page-text/1").json()["data"]
    assert pg["cached"] is True and "第 1 页" in pg["text"]
    assert client.get(f"/api/books/{data['id']}/page-text/9").status_code == 404


def test_reextract_requires_vision_config(client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=1)
    data = _import(client, pdf, "scan.pdf")
    r = client.post(f"/api/books/{data['id']}/page-text/1")
    assert r.status_code == 400


def test_build_messages_page_context():
    book = SimpleNamespace(title="页书")
    chapter = SimpleNamespace(index=1, title="第 1 页", content_text="")
    msgs = build_messages(
        book,
        chapter,
        "这页讲了什么",
        "",
        [],
        [],
        True,
        page_context="【第 1 页】\n正文",
        page_mode=True,
    )
    assert "【第X页】" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "页缓存" in user and "【第 1 页】" in user


def test_extract_image_attachment_unconfigured_returns_none(client):
    """决策 36：未配置视觉模型时附件提取返回 None（调用方降级纯文本，不报错）。"""
    from app.core.database import SessionLocal
    from app.services.vision_extract import extract_image_attachment
    db = SessionLocal()
    try:
        assert extract_image_attachment(db, "data:image/png;base64,AAAA") is None
    finally:
        db.close()


def test_extract_image_attachment_caches_result(client, monkeypatch, tmp_path):
    """决策 36：附件视觉提取按内容 hash 缓存，二次命中不重复调用多模态 API。"""
    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.services import vision_extract
    db = SessionLocal()
    try:
        uri = "data:image/png;base64,QUJD"
        calls = {"n": 0}

        class FakeVision:
            def __init__(self, **kw):
                pass
            def chat(self, messages):
                calls["n"] += 1
                return "图片内容：Krein–Milman 定理 $\\overline{\\operatorname{conv}}(\\operatorname{ext}(K))$"

        monkeypatch.setattr(settings, "data_dir", tmp_path)
        monkeypatch.setattr(vision_extract, "vision_configured", lambda db: True)
        monkeypatch.setattr(vision_extract, "LLMClient", FakeVision)
        text = vision_extract.extract_image_attachment(db, uri, hint="正文插图")
        assert "Krein" in text and calls["n"] == 1
        # 命中缓存：不再调用视觉 API
        text2 = vision_extract.extract_image_attachment(db, uri)
        assert text2 == text and calls["n"] == 1
        # 不同图片内容 hash 不同 → 重新提取
        vision_extract.extract_image_attachment(db, "data:image/png;base64,QUJDQQ==")
        assert calls["n"] == 2
    finally:
        db.close()


def test_extract_page_citations():
    out = extract_citations("见【第 5 页】与【第2章 第3段】。")
    assert out == [{"chapter": 5, "para": "页"}, {"chapter": 2, "para": "3"}]


def test_build_page_context_block_privacy():
    assert "【第 1 页】" in build_page_context_block({1: "第一页", 2: "第二页"}, True)
    assert build_page_context_block({1: "x"}, False) == ""
