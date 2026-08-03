"""书籍媒体资源管理：封面提取/回填、旧版扁平目录迁移、共享残留清理。"""
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.book import Book
from app.parsers.epub import extract_epub_cover
from app.parsers.pdf import extract_pdf_cover

PAGE_IMAGE_PATTERN = "page_{page_index:03d}.jpg"


def page_image_path(book: Book, page_index: int) -> Path:
    """扫描版 PDF 页图文件路径（导入/渲染/阅读/提问共用同一约定）。"""
    return Path(book.file_path).parent / "pages" / PAGE_IMAGE_PATTERN.format(page_index=page_index)


def ensure_book_cover(db: Session, book: Book) -> str | None:
    """确保书籍有封面：缺封面或封面文件丢失时按需重新提取（PDF 渲染第 1 页 / EPUB OPF 封面）。"""
    fp = Path(book.file_path)
    if book.cover and (fp.parent / book.cover).exists():
        return book.cover
    if book.format not in ("pdf", "epub") or not fp.exists():
        return book.cover
    try:
        if book.format == "pdf":
            cover = extract_pdf_cover(fp, fp.parent / "cover.jpg")
        else:
            cover = extract_epub_cover(fp, fp.parent)
    except Exception:
        return book.cover
    if cover:
        book.cover = cover.name
        db.commit()
        db.refresh(book)
    return book.cover




def book_cover_file(db: Session, book: Book) -> Path | None:
    """确保封面存在并返回封面文件路径；无封面/文件缺失且提取失败返回 None。

    封装 ensure_book_cover 的文件存在性检查，供 API 层直接返回 FileResponse。
    """
    cover = ensure_book_cover(db, book)
    if not cover:
        return None
    path = Path(book.file_path).parent / cover
    return path if path.exists() else None

def migrate_book_layout(db: Session, book: Book) -> bool:
    """把旧版扁平布局（<root>/<file_id>.ext + 共享 cover.jpg/pages/）迁移为
    每本书独立子目录（<root>/<file_id>/）。返回是否发生迁移。"""
    src = Path(book.file_path)
    if src.parent.name == src.stem or not src.exists():
        return False
    new_dir = src.parent / src.stem
    new_dir.mkdir(parents=True, exist_ok=True)
    new_file = new_dir / src.name
    if not new_file.exists():
        shutil.move(str(src), str(new_file))
    book.file_path = str(new_file)
    # 封面：重新提取，避免沿用共享 cover.jpg 串书。
    if book.format in ("pdf", "epub"):
        try:
            if book.format == "pdf":
                cover = extract_pdf_cover(new_file, new_dir / "cover.jpg")
            else:
                cover = extract_epub_cover(new_file, new_dir)
            book.cover = cover.name if cover else None
        except Exception:
            book.cover = None
    # 扫描版页图：共享 pages/ 页数与本书一致时整目录搬入专属目录（避免逐页重渲染）。
    if book.is_scanned:
        shared = src.parent / "pages"
        if shared.is_dir() and len(list(shared.glob("page_*.jpg"))) == book.page_count:
            shutil.move(str(shared), str(new_dir / "pages"))
    db.commit()
    return True


def migrate_all_books(db: Session) -> dict:
    """迁移全部旧布局书籍并回填封面；清理已无归属的共享 cover.jpg/pages/。幂等可重复执行。"""
    stats = {"migrated": 0, "covers": 0, "errors": 0}
    for book in db.scalars(select(Book)).all():
        try:
            if migrate_book_layout(db, book):
                stats["migrated"] += 1
            if book.format in ("pdf", "epub") and ensure_book_cover(db, book):
                stats["covers"] += 1
        except Exception:
            stats["errors"] += 1
    _cleanup_shared(settings.data_dir / "books", db)
    return stats


def _cleanup_shared(root: Path, db: Session) -> None:
    """共享 cover.jpg / pages/ 仍被扁平布局书籍引用时保留，否则删除。"""
    referenced_cover = referenced_pages = False
    for book in db.scalars(select(Book)).all():
        parent = Path(book.file_path).parent
        if book.cover and (parent / book.cover).resolve() == (root / "cover.jpg").resolve():
            referenced_cover = True
        if book.is_scanned and (parent / "pages").resolve() == (root / "pages").resolve():
            referenced_pages = True
    if not referenced_cover:
        (root / "cover.jpg").unlink(missing_ok=True)
    if not referenced_pages:
        shutil.rmtree(root / "pages", ignore_errors=True)
