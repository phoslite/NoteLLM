"""笔记导出服务：Markdown 与 PDF 两种格式（M10 打磨）。

- Markdown：与 M3 一致的结构化导出（标题 / [类型] 章节定位 / 引文 / 笔记正文）。
- PDF：使用 PyMuPDF 内嵌 CJK 字体（Droid Sans Fallback）生成 A4 PDF；
  笔记正文中的 Markdown 记号转为纯文本，LaTeX 公式以源码形式保留（PDF 端不做公式排版）。
"""
import io
import re
from datetime import date

import pymupdf

from app.models.book import Book

_PAGE_W, _PAGE_H = 595.0, 842.0  # A4 点
_MARGIN = 56.0
_FONT_SIZE = 11.0
_HEADING_SIZE = 13.0
_TITLE_SIZE = 18.0
_SUB_SIZE = 10.0
_LINE_STEP = 15.0
_NOTE_GAP = 12.0

_MD_BLOCK = re.compile(r"(?m)^(#{1,6}\s*|>\s*|[-*+]\s+|\d+\.\s+)")


def build_notes_markdown(book: Book, notes, chapters: dict) -> str:
    """生成全书笔记的 Markdown 文本（标题 / [类型] 章节定位 / 引文 / 正文）。"""
    lines = [f"# {book.title} 笔记导出", ""]
    for n in notes:
        ch = chapters.get(n.chapter_id)
        loc = f"（第{ch.index}章 {ch.title}）" if ch else "（未定位章节）"
        lines.append(f"## [{n.note_type}] {loc}")
        if n.quote_text:
            lines.append(f"> {n.quote_text}")
            lines.append("")
        lines.append(n.note_text or "")
        lines.append("")
    return "\n".join(lines)


def _plain_text(text: str) -> str:
    """把笔记正文中的 Markdown 记号转为适合 PDF 的纯文本；LaTeX 公式源码保留。"""
    t = text
    t = _MD_BLOCK.sub(lambda m: "• " if m.group(0).strip() in ("-", "*", "+") else "", t)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"\$\$|\$", "", t)
    return t.strip()


def _wrap(font: pymupdf.Font, text: str, fontsize: float, max_width: float) -> list[str]:
    """按宽度逐字换行（兼容中文与长公式）。"""
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            cand = cur + ch
            if cur and font.text_length(cand, fontsize) > max_width:
                lines.append(cur)
                cur = ch
            else:
                cur = cand
        lines.append(cur)
    return lines


def build_notes_pdf(book: Book, notes, chapters: dict) -> bytes:
    """生成全书笔记的 A4 PDF（内嵌 CJK 字体）。"""
    doc = pymupdf.open()
    font = pymupdf.Font("cjk")
    max_width = _PAGE_W - _MARGIN * 2
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    tw = pymupdf.TextWriter(page.rect)
    y = _MARGIN

    def flush() -> None:
        tw.write_text(page)

    def ensure(space: float) -> None:
        nonlocal page, tw, y
        if y + space > _PAGE_H - _MARGIN:
            flush()
            page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
            tw = pymupdf.TextWriter(page.rect)
            y = _MARGIN

    def draw(text: str, fontsize: float, indent: float = 0.0, step: float = _LINE_STEP) -> None:
        """绘制一段文本：逐行前进 fontsize+4，块结束后追加 step 间距。"""
        nonlocal y
        lines = _wrap(font, text, fontsize, max_width - indent)
        block_h = len(lines) * (fontsize + 4)
        ensure(block_h + step)
        for line in lines:
            tw.append((_MARGIN + indent, y + fontsize), line, font=font, fontsize=fontsize)
            y += fontsize + 4
        y += step

    draw(f"{book.title} 笔记导出", _TITLE_SIZE, step=8)
    y += 8
    draw(f"导出日期：{date.today().isoformat()}　共 {len(notes)} 条笔记", _SUB_SIZE, step=12)
    y += 6

    for n in notes:
        ch = chapters.get(n.chapter_id)
        loc = f"（第{ch.index}章 {ch.title}）" if ch else "（未定位章节）"
        draw(f"[{n.note_type}] {loc}", _HEADING_SIZE, step=3)
        if n.quote_text:
            draw(f"引文：{_plain_text(n.quote_text)}", _FONT_SIZE, indent=24, step=3)
        if n.note_text:
            draw(_plain_text(n.note_text), _FONT_SIZE, indent=24, step=3)
        y += _NOTE_GAP

    flush()
    doc.set_metadata({"title": f"{book.title} 笔记导出", "author": "LLMnotebook"})
    buf = io.BytesIO()
    doc.save(buf, garbage=3, deflate=True)
    return buf.getvalue()
