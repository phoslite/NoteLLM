"""EPUB 解析：解包正文与目录（保留原排版能力由前端承担，此处提取文本）。"""
from html.parser import HTMLParser
from pathlib import Path

from ebooklib import ITEM_COVER, ITEM_DOCUMENT, epub

from app.parsers.base import ParsedBook, ParsedChapter


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        return "\n".join(p for p in (x.strip() for x in self.parts) if p)


def _html_to_text(raw: bytes) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw.decode("utf-8", errors="replace"))
    except Exception:
        return ""
    return parser.text()


def extract_epub_cover(path: str | Path, out_dir: str | Path) -> Path | None:
    """提取 EPUB 封面图片（OPF cover-image 或 cover 元数据）；无封面返回 None。"""
    book = epub.read_epub(str(path))
    item = None
    covers = list(book.get_items_of_type(ITEM_COVER))
    if covers:
        item = covers[0]
    else:
        metas = book.get_metadata("OPF", "cover")
        if metas:
            item = book.get_item_with_id(metas[0][0])
    if item is None:
        return None
    out = Path(out_dir) / f"cover{Path(item.get_name()).suffix.lower() or '.jpg'}"
    out.write_bytes(item.get_content())
    return out


def parse_epub(path: str | Path, title_hint: str | None = None) -> ParsedBook:
    book = epub.read_epub(str(path))
    metadata_title = book.get_metadata("DC", "title")
    title = str(metadata_title[0][0]) if metadata_title else (title_hint or Path(path).stem)
    chapters: list[ParsedChapter] = []
    idx = 0
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        text = _html_to_text(item.get_body_content())
        if not text:
            continue
        idx += 1
        first_line = text.splitlines()[0].strip()
        heading = first_line[:80] if first_line else f"章节 {idx}"
        chapters.append(ParsedChapter(idx, heading, text))
    return ParsedBook(title=title, chapters=chapters)