"""书籍语料组装：章节正文优先，PDF 扫描件回退 local_text 页文本。

L3（RAG 文本层，K1 定稿）：`weighted_book_texts` 输出带来源权重的文本片段
（章节标题 2.0 / 正文 1.0 / RAG 后验 3.0），供关键词加权抽取；扫描书回退书名。
"""
from pathlib import Path

from app.models.book import Book, Chapter
from app.repositories.assets import read_asset_content
from app.services.html_util import html_to_text


def book_corpus(book: Book) -> str:
    """书籍文本语料：标题/作者 + 章节标题与正文；PDF 统一按页，补充 local_text 页文本。

    【legacy，仅测试使用】（m-1）：book_keywords 已重构为 weighted_book_texts
    （L3 RAG 文本层，章节标题 2.0/正文 1.0/RAG 后验 3.0），生产侧不再调用本函数，
    保留供测试对照（perf 基线）；新代码请使用 weighted_book_texts。
    """
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


def _rag_texts(content: dict) -> list[str]:
    """RAG 资产关键文本：summary + key_points + chunks 前 300 字（demo _rag_texts 移植）。"""
    texts: list[str] = []
    if content.get("summary"):
        texts.append(str(content["summary"]))
    for kp in content.get("key_points") or []:
        if isinstance(kp, str):
            texts.append(kp)
        elif isinstance(kp, dict):
            texts.append(str(kp.get("title") or kp.get("point") or ""))
    for ch in content.get("chunks") or []:
        if isinstance(ch, dict) and ch.get("text"):
            texts.append(str(ch["text"])[:300])
    return [t for t in texts if t]


def weighted_book_texts(book: Book, rag_content: dict | None = None) -> list[tuple[str, float]]:
    """带来源权重的书级文本片段（L3 RAG 文本层，K1 定稿）：

    - 标题/作者：权重 1.0；
    - 章节标题：权重 2.0；章节正文：权重 1.0；
    - RAG 资产（summary/key_points/chunks）：权重 3.0（后验信息最强）；
    - PDF 扫描件（无正文）：回退 local_text 页文本，权重 1.0。
    片段间权重可加：下游按片段加权合并词频即可获得整书加权关键词。
    """
    pieces: list[tuple[str, float]] = [(book.title or "", 1.0)]
    if book.author:
        pieces.append((book.author, 1.0))
    has_body = False
    for ch in book.chapters:
        if ch.title:
            pieces.append((ch.title or "", 2.0))
        if ch.content_text:
            pieces.append((html_to_text(ch.content_text) if getattr(book, "format", None) == "epub" else ch.content_text, 1.0))
            has_body = True
        elif ch.page_index:
            p = Path(book.file_path).parent / "local_text" / f"page_{ch.page_index:03d}.txt"
            if p.exists():
                try:
                    pieces.append((p.read_text(encoding="utf-8", errors="replace"), 1.0))
                except OSError:
                    pass
    for rag_text in _rag_texts(rag_content or {}):
        pieces.append((rag_text, 3.0))
    if not has_body and book.format == "pdf":
        local_dir = Path(book.file_path).parent / "local_text"
        if local_dir.is_dir():
            for f in sorted(local_dir.glob("page_*.txt")):
                try:
                    pieces.append((f.read_text(encoding="utf-8", errors="replace"), 1.0))
                except OSError:
                    continue
    return pieces


def book_weighted_rag(db, book: Book) -> dict | None:
    """按需读取 RAG 资产（db 可空）；封装 read_asset_content，避免 keywords 层直接依赖仓储。"""
    if db is None:
        return None
    return read_asset_content(db, book.id, "rag") or None
