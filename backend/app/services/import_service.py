"""书籍导入服务：保存文件 → 解析 → 入库（决策 35 两段式：同步快速入架 + 后台耗时处理）。

- 同步阶段：写文件、解析元数据/章节、建 Book 记录、封面提取（秒级返回，前端立即上架）；
- 后台任务（import-background，render 配额）：PDF 页图渲染、本地全文索引、跨书图谱增量、
  视觉预提取——全部进入任务系统，任务中心展示进度（导入 40/40/20 权重）。
"""
import hashlib
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.book import Book
from app.parsers import SUPPORTED_EXT, parse_book
from app.parsers.epub import extract_epub_cover
from app.parsers.pdf import extract_pdf_cover, render_pdf_pages
from app.repositories import books as book_repo
from app.repositories.books import add_chapters, create_book
from app.repositories.settings import vision_configured
from app.services.graph.cross_book import incremental_cross_book_graph
from app.services.vision_extract import extract_book_pages_task
from app.tasks import submit, update_progress

_FORMAT_MAP = {".md": "md", ".markdown": "md", ".txt": "txt", ".pdf": "pdf", ".epub": "epub"}


def import_book(
    db: Session,
    file_bytes: bytes,
    filename: str,
    title: str | None = None,
    author: str | None = None,
) -> tuple[Book, str]:
    """导入书籍：同步完成快速阶段（写文件/解析/建记录），返回 (Book, task_id)。

    耗时阶段（PDF 页渲染、全文索引、跨书图谱、视觉预提取）进入后台任务；
    不支持的格式抛 ValueError。
    """
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
    task_id = submit(
        "render",
        "import-background",
        lambda: _import_background(book.id),
        related_id=book.id,
    )
    return book, task_id


def _import_background(book_id: int) -> dict:
    """导入后台阶段（决策 35）：PDF 页渲染 + 本地全文索引 → 跨书图谱增量 → 视觉预提取。

    权重：渲染 40 / 图谱 40 / 视觉 20；任一步失败由任务系统透出 error 不阻塞书架。
    """
    db = SessionLocal()
    try:
        book = book_repo.get_book(db, book_id)
        if not book:
            return {"error": "书籍不存在"}
        path = Path(book.file_path)
        if path.suffix.lower() == ".pdf":
            update_progress(10, "渲染 PDF 页图")
            render_pdf_pages(path, path.parent / "pages")
            update_progress(35, "生成本地全文索引")
            parsed = parse_book(path, title_hint=path.stem)
            local_dir = path.parent / "local_text"
            for i, page_text in enumerate(parsed.page_texts, 1):
                if page_text.strip():
                    local_dir.mkdir(parents=True, exist_ok=True)
                    (local_dir / f"page_{i:03d}.txt").write_text(page_text, encoding="utf-8")
        update_progress(50, "更新跨书关联")
        incremental_cross_book_graph(db, book.id)
        # M7 批量预提取：导入 PDF 作为知识库时补齐全书页缓存；
        # 受「发送书籍内容至模型」隐私开关与多模态配置约束。
        if path.suffix.lower() == ".pdf" and settings.ai_enable_body_send and vision_configured(db):
            update_progress(80, "视觉预提取页缓存")
            extract_book_pages_task(book.id)
        update_progress(100, "导入完成")
        return {"book_id": book.id, "rendered": True}
    finally:
        db.close()
