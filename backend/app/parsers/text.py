"""Markdown / TXT 解析：按标题层级切分章节（共用 split_by_headings）。"""
import re
from pathlib import Path

from app.parsers._split import split_by_headings
from app.parsers.base import ParsedBook

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_CHAPTER_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百千零]+\s*[章节卷部篇]|"
    r"Chapter\s+\d+|CHAPTER\s+\d+)\s*[:：]?\s*(.*)$",
    re.IGNORECASE,
)


def _md_heading(line: str) -> str | None:
    m = _HEADING_RE.match(line)
    if m and m.group(1) in ("#", "##", "###"):
        return m.group(2).strip()
    return None


def _read_text(path: str | Path) -> str:
    """按编码尝试读取（审查 C-问题12）：utf-8 → gbk → latin-1 兜底，避免 GBK 中文 txt 乱码入库。"""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_markdown(path: str | Path, title_hint: str | None = None) -> ParsedBook:
    raw = _read_text(path)
    h1 = next(
        (m.group(1).strip() for m in (re.match(r"^#\s+(.+?)\s*$", ln) for ln in raw.splitlines()) if m),
        None,
    )
    title = h1 or title_hint or Path(path).stem
    return split_by_headings(raw, title, _md_heading)


def _txt_heading(line: str) -> str | None:
    m = _CHAPTER_RE.match(line)
    if not m:
        return None
    return m.group(2).strip() or m.group(1).strip()


def parse_txt(path: str | Path, title_hint: str | None = None) -> ParsedBook:
    raw = _read_text(path)
    return split_by_headings(raw, title_hint or Path(path).stem, _txt_heading)