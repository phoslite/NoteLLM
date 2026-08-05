"""审查 B-2 回归测试：导入两段式单次页渲染。

- Markdown 导入：同步上架成功，不触发 PDF 页渲染；
- PDF 导入：render_pdf_pages 恰好调用一次（同步段不重复渲染，修复双倍渲染）；
- 不支持格式：400 拒绝且不产生孤儿书籍目录。
"""
from pathlib import Path

import pymupdf


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _make_scanned_pdf(path: Path, pages: int = 2) -> None:
    """无文本层 PDF：模拟扫描件（导入后台渲染路径）。"""
    doc = pymupdf.open()
    for _i in range(pages):
        page = doc.new_page(width=300, height=400)
        page.draw_rect(pymupdf.Rect(50, 50, 250, 350), color=(0.2, 0.4, 0.8), fill=(0.9, 0.9, 0.95))
    doc.save(str(path))
    doc.close()


def _count_render_calls(monkeypatch):
    """替换 import_service.render_pdf_pages 为计数器，返回计数 dict。"""
    from app.services import import_service

    calls = {"n": 0}

    def _fake_render(path, out_dir, workers=None):
        calls["n"] += 1
        return 2

    monkeypatch.setattr(import_service, "render_pdf_pages", _fake_render)
    return calls


def test_md_import_success_and_no_page_render(client, monkeypatch):
    """Markdown 导入：秒回上架、后台任务成功、不触发 PDF 页渲染（B-2）。"""
    from app.core.database import SessionLocal
    from app.models.book import Book

    calls = _count_render_calls(monkeypatch)
    book_id = _import_md(client, "导入A.md", "# 第一章 变分法\n\n变分法研究泛函极值问题。\n")

    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        assert book is not None
        assert book.format == "md"
    finally:
        db.close()
    assert calls["n"] == 0, "Markdown 导入不应触发 PDF 页渲染"


def test_pdf_import_renders_pages_exactly_once(client, monkeypatch, tmp_path):
    """PDF 导入：render_pdf_pages 恰好调用一次（B-2 双倍渲染回归）。"""
    from app.core.database import SessionLocal
    from app.models.book import Book

    calls = _count_render_calls(monkeypatch)
    pdf = tmp_path / "扫描件.pdf"
    _make_scanned_pdf(pdf, pages=2)
    with open(pdf, "rb") as f:
        r = client.post("/api/books", files={"file": ("扫描件.pdf", f, "application/pdf")})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["format"] == "pdf"
    assert data["page_count"] == 2

    db = SessionLocal()
    try:
        book = db.get(Book, data["id"])
        assert book is not None
        assert book.is_scanned is True
    finally:
        db.close()
    assert calls["n"] == 1, "PDF 导入页渲染应恰好一次（B-2 双倍渲染回归）"

def test_import_unsupported_format_rejects_without_orphan(client):
    """不支持格式：业务码 400 拒绝，且不产生孤儿书籍目录（B-2 失败路径）。"""
    from app.core.config import settings

    r = client.post(
        "/api/books", files={"file": ("测试.xyz", b"not a book", "application/octet-stream")}
    )
    body = r.json()
    assert body["code"] == 400, body
    assert body["data"] is None
    books_dir = settings.data_dir / "books"
    if books_dir.exists():
        orphan = [p for p in books_dir.iterdir() if p.is_dir() and (p / "测试.xyz").exists()]
        assert orphan == [], "不支持格式导入不应残留书籍目录"
