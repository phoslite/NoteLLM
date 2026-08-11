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
    assert r.status_code == 400, r.text  # 错误契约（审查）：HTTP 400 + detail，与同模块其余端点一致
    body = r.json()
    assert body["detail"]
    books_dir = settings.data_dir / "books"
    if books_dir.exists():
        orphan = [p for p in books_dir.iterdir() if p.is_dir() and (p / "测试.xyz").exists()]
        assert orphan == [], "不支持格式导入不应残留书籍目录"

def test_corrupt_epub_rejected_without_orphan(client):
    """审查 C-问题14/2：损坏 EPUB 包装为 ValueError → 业务码 400，且不残留孤儿目录。"""
    from app.core.config import settings

    r = client.post("/api/books", files={"file": ("损坏.epub", b"not a real epub zip", "application/epub+zip")})
    assert r.status_code == 400, r.text  # 错误契约（审查）：HTTP 400 + detail
    body = r.json()
    assert "EPUB" in body["detail"]
    books_dir = settings.data_dir / "books"
    if books_dir.exists():
        orphan = [p for p in books_dir.iterdir() if p.is_dir() and (p / "损坏.epub").exists()]
        assert orphan == [], "损坏 EPUB 不应残留孤儿目录"


def test_oversize_upload_rejected(client, monkeypatch):
    """审查 C-问题13：超过大小上限的文件被 413 拦截，不残留书籍目录。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    r = client.post("/api/books", files={"file": ("超大.md", ("x" * 2048).encode(), "text/markdown")})
    assert r.status_code == 413, r.text
    books_dir = settings.data_dir / "books"
    if books_dir.exists():
        orphan = [p for p in books_dir.iterdir() if p.is_dir() and (p / "超大.md").exists()]
        assert orphan == [], "超大文件不应残留书籍目录"

def test_markdown_inline_images_copy_and_media_endpoint(client):
    """决策 31：Markdown 内嵌图片→ images/ 复制、引用改写、媒体端点白名单与占位。"""
    import base64

    from app.services import import_service

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    upload_dir = import_service._upload_dir()
    (upload_dir / "logo.png").write_bytes(png)
    md = "# 图文书\n\n![示意图](logo.png)\n\n![远程](https://example.com/a.png)\n\n![缺失](../nope.png)\n"
    try:
        book_id = _import_md(client, "图文.md", md)
        detail = client.get(f"/api/books/{book_id}").json()["data"]
        ch = client.get(f"/api/books/{book_id}/chapters/{detail['chapters'][0]['id']}").json()["data"]
        # DB 层保留相对引用 images/logo.png，API 层重写为 URL
        from app.core.database import SessionLocal
        from app.models.book import Chapter
        dbs = SessionLocal()
        try:
            db_content = dbs.query(Chapter).filter_by(book_id=book_id).first().content_text
            assert "images/logo.png" in db_content
        finally:
            dbs.close()
        assert f"/api/books/{book_id}/media/logo.png" in ch["content_text"]  # 读取时重写为 URL
        assert "https://example.com/a.png" in ch["content_text"]  # 远程不改写
        r_img = client.get(f"/api/books/{book_id}/media/logo.png")
        assert r_img.status_code == 200 and r_img.content == png
        # 缺失图片→ 占位 SVG；非白名单扩展名→ 占位
        missing = client.get(f"/api/books/{book_id}/media/nope.png")
        assert missing.status_code == 200 and missing.content.startswith(b"<svg")
        bad = client.get(f"/api/books/{book_id}/media/evil.py")
        assert bad.status_code == 200 and bad.content.startswith(b"<svg")
    finally:
        (upload_dir / "logo.png").unlink(missing_ok=True)


def test_import_corrupt_pdf_returns_400(client, tmp_path):
    """I-6：损坏 PDF 上传应返回业务码 400（解析异常统一包装为 ValueError），且不残留孤儿目录。"""
    from app.core.config import settings

    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"not a real pdf at all")
    with open(bad, "rb") as f:
        r = client.post("/api/books", files={"file": ("corrupt.pdf", f, "application/pdf")})
    assert r.status_code == 400, r.text  # 错误契约（审查）：HTTP 400 + detail
    body = r.json()
    assert "PDF" in body["detail"]
    books_dir = settings.data_dir / "books"
    if books_dir.exists():
        orphan = [p for p in books_dir.iterdir() if p.is_dir() and (p / "corrupt.pdf").exists()]
        assert orphan == [], "损坏 PDF 导入不应残留书籍目录"
