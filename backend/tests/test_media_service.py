"""封面回填、书籍独立目录布局、删除清理与旧版扁平目录迁移。"""
from pathlib import Path

import pymupdf

from app.core.database import SessionLocal
from app.repositories import books as book_repo
from app.services.media_service import ensure_book_cover, migrate_book_layout


def _make_scanned_pdf(path: Path, pages: int = 2) -> None:
    """无文本层 PDF：只有图形，用于模拟扫描版。"""
    doc = pymupdf.open()
    for _i in range(pages):
        page = doc.new_page(width=200, height=300)
        page.draw_rect(pymupdf.Rect(30, 30, 170, 270), color=(0.1, 0.3, 0.6), fill=(0.8, 0.9, 1.0))
    doc.save(str(path))
    doc.close()


def _import(client, path: Path, name: str):
    r = client.post("/api/books", files={"file": (name, path.read_bytes(), "application/pdf")})
    assert r.status_code == 200
    return r.json()["data"]


def test_import_uses_per_book_directory(client, tmp_path):
    """新导入的书籍使用独立子目录：书文件 + 专属 cover.jpg + pages/。"""
    pdf = tmp_path / "scan.pdf"
    _make_scanned_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan.pdf")

    db = SessionLocal()
    try:
        book = book_repo.get_book(db, data["id"])
        fp = Path(book.file_path)
        assert fp.parent.name == fp.stem
        assert (fp.parent / "cover.jpg").exists()
        assert (fp.parent / "pages" / "page_001.jpg").exists()
        assert (fp.parent / "pages" / "page_002.jpg").exists()
    finally:
        db.close()


def test_ensure_book_cover_backfills(client, tmp_path):
    """旧书（cover 为空）启动后按需回填封面。"""
    pdf = tmp_path / "text.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello cover backfill", fontsize=12)
    doc.save(str(pdf))
    doc.close()
    data = _import(client, pdf, "text.pdf")

    db = SessionLocal()
    try:
        book = book_repo.get_book(db, data["id"])
        book.cover = None  # 模拟功能上线前导入的旧书
        db.commit()
        cover = ensure_book_cover(db, book)
        assert cover == "cover.jpg"
        assert (Path(book.file_path).parent / cover).exists()
    finally:
        db.close()
    assert client.get(f"/api/books/{data['id']}/cover").status_code == 200


def test_delete_book_removes_files_and_chat(client, tmp_path):
    """删除书籍：DB 记录、聊天记录与整个书籍子目录都被清理。"""
    from sqlalchemy import select

    from app.models.activity import ChatMessage, Note, ReadingLog

    pdf = tmp_path / "scan.pdf"
    _make_scanned_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan.pdf")
    book_id = data["id"]

    db = SessionLocal()
    try:
        book = book_repo.get_book(db, book_id)
        fp = Path(book.file_path)
        assert fp.exists()
        chapter = book_repo.list_chapters(db, book_id)[0]
        db.add(ChatMessage(session_id=f"book:{book_id}", role="user", content="hi", ref_book_id=book_id, ref_chapter_id=chapter.id))
        db.add(ReadingLog(book_id=book_id, chapter_id=chapter.id, position=0.5))
        db.add(Note(book_id=book_id, chapter_id=chapter.id, note_text="n"))
        db.commit()
    finally:
        db.close()

    r = client.delete(f"/api/books/{book_id}")
    assert r.status_code == 200
    assert not fp.parent.exists()

    db = SessionLocal()
    try:
        assert book_repo.get_book(db, book_id) is None
        rows = db.scalars(select(ChatMessage).where(ChatMessage.ref_book_id == book_id)).all()
        assert rows == []
        assert db.scalars(select(ReadingLog).where(ReadingLog.book_id == book_id)).all() == []
        assert db.scalars(select(Note).where(Note.book_id == book_id)).all() == []
    finally:
        db.close()


def test_migrate_flat_layout(client, tmp_path):
    """旧版扁平布局迁移为独立子目录，并重新提取专属封面。"""
    from app.core.config import settings
    from app.models.book import Book

    root = settings.data_dir / "books"
    flat = root / "flat123.pdf"
    _make_scanned_pdf(flat, pages=1)

    db = SessionLocal()
    try:
        book = Book(
            title="旧书",
            format="pdf",
            file_path=str(flat),
            cover="cover.jpg",  # 旧共享封面名
            is_scanned=True,
            page_count=1,
            total_chapters=1,
        )
        db.add(book)
        db.commit()
        db.refresh(book)

        assert migrate_book_layout(db, book) is True
        new_fp = Path(book.file_path)
        assert new_fp.parent.name == "flat123"
        assert new_fp.exists()
        assert (new_fp.parent / "cover.jpg").exists()
        db.refresh(book)
        assert book.cover == "cover.jpg"
    finally:
        db.close()
