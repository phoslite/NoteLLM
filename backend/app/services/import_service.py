"""书籍导入服务：保存文件 → 解析 → 入库。"""
import hashlib
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.book import Book
from app.parsers import SUPPORTED_EXT, parse_book
from app.parsers.epub import extract_epub_cover
from app.parsers.pdf import extract_pdf_cover, render_pdf_pages
from app.repositories.books import add_chapters, create_book
from app.repositories.settings import vision_configured

_FORMAT_MAP = {".md": "md", ".markdown": "md", ".txt": "txt", ".pdf": "pdf", ".epub": "epub"}


def import_book(
    db: Session,
    file_bytes: bytes,
    filename: str,
    title: str | None = None,
    author: str | None = None,
) -> Book:
    """导入书籍文件，返回 Book 记录；不支持的格式抛 ValueError。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXT:
        raise ValueError(f"不支持的格式 {suffix or '(无扩展名)'}，支持：{'、'.join(sorted(SUPPORTED_EXT))}")

    book_root = settings.data_dir / "books"
    book_root.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:12]
    # 每本书独立子目录（书文件 + cover.jpg + pages/），避免封面/页图跨书共享覆盖。
    book_dir = book_root / file_id
    book_dir.mkdir(parents=True, exist_ok=True)
    dest = book_dir / f"{file_id}{suffix}"
    dest.write_bytes(file_bytes)

    parsed = parse_book(dest, title_hint=Path(filename).stem)
    book_title = (title or parsed.title or Path(filename).stem).strip() or Path(filename).stem

    # 封面：PDF 渲染第 1 页；EPUB 提取 OPF cover；Markdown/TXT 无封面（前端显示占位）。
    cover_rel: str | None = None
    if suffix == ".pdf":
        cover = extract_pdf_cover(dest, dest.parent / "cover.jpg")
        if cover:
            cover_rel = cover.name
    elif suffix == ".epub":
        cover = extract_epub_cover(dest, dest.parent)
        if cover:
            cover_rel = cover.name

    # PDF（含文本型）：按原始页渲染页面图片（page_001.jpg ...），阅读时按页读图。
    if suffix == ".pdf":
        render_pdf_pages(dest, dest.parent / "pages")
        # 本地抽取文本仅作全文检索索引（非空才落盘，不用于正文展示与 AI 上下文）。
        local_text_dir = dest.parent / "local_text"
        for i, page_text in enumerate(parsed.page_texts, 1):
            if page_text.strip():
                local_text_dir.mkdir(parents=True, exist_ok=True)
                (local_text_dir / f"page_{i:03d}.txt").write_text(page_text, encoding="utf-8")

    book = create_book(
        db,
        title=book_title,
        content_hash=hashlib.sha256(file_bytes).hexdigest(),
        author=author or parsed.author or None,
        format=_FORMAT_MAP[suffix],
        file_path=str(dest),
        cover=cover_rel,
        is_scanned=parsed.is_scanned,
        page_count=parsed.page_count,
        total_chapters=len(parsed.chapters),
    )
    add_chapters(db, book.id, [(c.index, c.title, c.content, c.page_index) for c in parsed.chapters])
    # M7 批量预提取：导入 PDF（含文本型）作为知识库时后台补齐全书页缓存；
    # 受「发送书籍内容至模型」隐私开关与多模态配置约束。
    if suffix == ".pdf" and settings.ai_enable_body_send and vision_configured(db):
        from app.services.vision_extract import extract_book_pages_task
        from app.tasks import submit

        submit("vision-pre-extract", lambda: extract_book_pages_task(book.id))
    return book