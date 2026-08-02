"""通用章节切分：按标题行切分全文（md / txt / pdf 共用，消除三处重复逻辑）。"""
from collections.abc import Callable

from app.parsers.base import ParsedBook, ParsedChapter


def split_by_headings(
    raw: str,
    title_fallback: str,
    is_heading: Callable[[str], str | None],
) -> ParsedBook:
    """按标题行把全文切分为章节。

    - is_heading(line) 命中时返回该行解析出的章节标题，否则返回 None。
    - 空内容章节不占序号；没有任何标题时整本作为一章（标题用 title_fallback）。
    """
    chapters: list[ParsedChapter] = []
    current_title = ""
    buf: list[str] = []
    idx = 0

    def flush() -> None:
        nonlocal idx
        content = "\n".join(buf).strip()
        if content:
            idx += 1
            chapters.append(ParsedChapter(idx, current_title, content))
        buf.clear()

    for line in raw.splitlines():
        heading = is_heading(line)
        if heading is not None:
            flush()
            current_title = heading
        else:
            buf.append(line)
    flush()
    if not chapters:
        chapters = [ParsedChapter(1, title_fallback, raw.strip())]
    return ParsedBook(title=title_fallback, chapters=chapters)