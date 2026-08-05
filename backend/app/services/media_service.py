"""书籍媒体资源管理：封面提取/回填、旧版扁平目录迁移、共享残留清理。"""
import base64
import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.book import Book
from app.parsers.epub import extract_epub_cover
from app.parsers.pdf import extract_pdf_cover

PAGE_IMAGE_PATTERN = "page_{page_index:03d}.jpg"

# 决策 31：Markdown 内嵌本地图片（白名单扩展名 + 防越越）
MEDIA_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_MD_MEDIA_REF_RE = re.compile(r"(images/[^\s\"')[\]]+)")
_MEDIA_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}
PLACEHOLDER_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120">'
                  '<rect width="100%" height="100%" fill="#f2f3f5"/>'
                  '<text x="50%" y="50%" font-size="14" fill="#909399" '
                  'text-anchor="middle" dominant-baseline="middle">图片缺失</text></svg>')


def book_images_dir(book) -> Path:
    """Markdown 内嵌本地图片目录（决策 31）：<book_dir>/images/ 。"""
    return Path(book.file_path).parent / "images"


def copy_markdown_images(content: str, bases: list[Path]) -> str:
    """把 Markdown 内嵌本地图片（相对/绝对/file://）复制到 bases[0]/images/ 并改写引用。

    bases 按优先级排列：书籍目录、上传原目录。http(s)/data 引用不改写；
    文件不存在或扩展名不在白名单时保留原引用（渲染时占位提示）。
    """
    images_dir = bases[0] / "images"
    used: set[str] = set()

    def repl(m: re.Match) -> str:
        alt, raw = m.group(1), m.group(2).strip()
        if raw.startswith(("http://", "https://", "data:")):
            return m.group(0)
        candidate = raw
        if candidate.startswith("file://"):
            candidate = candidate[len("file://"):].lstrip("/")
        p = Path(candidate)
        found: Path | None = None
        if p.is_absolute():
            if p.is_file():
                found = p
        else:
            for base in bases:
                cand = base / p
                if cand.is_file():
                    found = cand
                    break
        if found is None or found.suffix.lower() not in MEDIA_ALLOWED_EXT:
            return m.group(0)
        name = found.name
        if name in used:
            stem, ext = found.stem, found.suffix
            i = 2
            while f"{stem}_{i}{ext}" in used:
                i += 1
            name = f"{stem}_{i}{ext}"
        used.add(name)
        images_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found, images_dir / name)
        return f"![{alt}](images/{name})"

    return _MD_IMAGE_RE.sub(repl, content)


def rewrite_chapter_media_urls(content: str, book_id: int) -> str:
    """章节返回时把 images/<name> 引用重写为可访问 URL（决策 31）。"""
    if not content or "images/" not in content:
        return content
    return _MD_MEDIA_REF_RE.sub(lambda m: f"/api/books/{book_id}/media/{Path(m.group(1)).name}", content)


def resolve_book_media(book, filename: str) -> Path | None:
    """白名单 + 防越越解析 Markdown 内嵋图片（决策 31）。"""
    name = Path(filename).name
    if name != filename or Path(filename).suffix.lower() not in MEDIA_ALLOWED_EXT:
        return None
    images_dir = book_images_dir(book)
    path = images_dir / name
    try:
        resolved = path.resolve()
        if resolved.parent != images_dir.resolve() or not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved


def markdown_image_data_uris(book, content: str, limit: int = 3) -> list[str]:
    """Markdown 内嵌图片附件（决策 31）：扫描 images/<name> 引用读为 data URI，最多 limit 张。"""
    images_dir = book_images_dir(book)
    if not images_dir.exists():
        return []
    uris: list[str] = []
    for ref in _MD_MEDIA_REF_RE.findall(content or ""):
        path = images_dir / Path(ref).name
        if not path.exists() or path.suffix.lower() not in MEDIA_ALLOWED_EXT:
            continue
        mime = _MEDIA_MIME.get(path.suffix.lower(), "application/octet-stream")
        uris.append(f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}")
        if len(uris) >= limit:
            break
    return uris




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
