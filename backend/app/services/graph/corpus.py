"""书籍语料组装：章节正文优先，PDF 扫描件回退 local_text 页文本。"""
from pathlib import Path

from app.models.book import Book, Chapter
from app.services.html_util import html_to_text


def book_corpus(book: Book) -> str:
    """书籍文本语料：标题/作者 + 章节标题与正文；PDF 统一按页，补充 local_text 页文本。"""
    parts = [book.title or "", book.author or ""]
    for ch in book.chapters:
        parts.append(ch.title or "")
        if ch.content_text:
            parts.append(html_to_text(ch.content_text) if getattr(book, "format", None) == "epub" else ch.content_text)
    if book.format == "pdf" or not any(p.strip() for p in parts[2:]):
        local_dir = Path(book.file_path).parent / "local_text"
        if local_dir.is_dir():
            for f in sorted(local_dir.glob("page_*.txt")):
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
    return "\n".join(parts)

def _chapter_text(book: Book, chapter: Chapter) -> str:
    """章节正文：优先 content_text；PDF 按页章节回退读取 local_text 对应页。"""
    if chapter.content_text:
        return html_to_text(chapter.content_text) if getattr(book, "format", None) == "epub" else chapter.content_text
    if chapter.page_index:
        p = Path(book.file_path).parent / "local_text" / f"page_{chapter.page_index:03d}.txt"
        if p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return ""
