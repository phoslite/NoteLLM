"""EPUB 解析：解包正文（保留原排版 HTML，方案 A）与封面。

- 正文：按 EPUB 文档提取原始 XHTML，服务端消毒（scrub_html）+ 图片资源提取到
  <book_dir>/images/ 并重写引用（复用决策 31 媒体端点 /api/books/{id}/media/…）；
- content_text 存消毒后 HTML，前端 DOMPurify 白名单渲染（epub_render 分支，见使用手册-前端）；
- LLM/RAG/图谱/搜索等文本消费点统一经 html_util.html_to_text 转纯文本（不污染语料）。
"""
import hashlib
import posixpath
from html.parser import HTMLParser
from pathlib import Path

from ebooklib import ITEM_COVER, ITEM_DOCUMENT, ITEM_IMAGE, epub

from app.parsers.base import ParsedBook, ParsedChapter
from app.services.html_util import html_to_text, scrub_html

# 与媒体端点白名单一致（media_service.MEDIA_ALLOWED_EXT），仅复制可服务的图片
_MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def extract_epub_cover(path: str | Path, out_dir: str | Path) -> Path | None:
    """提取 EPUB 封面图片（OPF cover-image 或 cover 元数据）；无封面返回 None。"""
    try:
        book = epub.read_epub(str(path))
    except Exception:  # noqa: BLE001 审查 C-问题14：封面提取失败不阻塞导入
        return None
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


def _extract_images(book, images_dir: Path) -> dict[str, str]:
    """把 EPUB 内图片写入 <images_dir>/，返回 {zip 内归一化路径: 文件名}。

    同名文件冲突时加短 hash 前缀；扩展名不在媒体白名单（不可经媒体端点提供）不复制。
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for item in book.get_items_of_type(ITEM_IMAGE):
        zip_name = posixpath.normpath(item.get_name())
        ext = Path(zip_name).suffix.lower()
        if ext not in _MEDIA_EXT:
            continue
        name = Path(zip_name).name
        if name in used:  # 不同目录同名图片：短 hash 前缀去重
            digest = hashlib.sha1(zip_name.encode("utf-8")).hexdigest()[:8]  # noqa: S324 仅命名去重，非安全用途
            name = f"{digest}_{name}"
        used.add(name)
        (images_dir / name).write_bytes(item.get_content())
        mapping[zip_name] = name
    return mapping


class _HeadingFinder(HTMLParser):
    """取正文首个 h1-h3 文本作为章节标题。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self.heading = ""

    def handle_starttag(self, tag, attrs):
        self._stack.append(tag.lower())

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self.heading:
            return
        if any(t in ("h1", "h2", "h3") for t in self._stack):
            text = " ".join(data.split())
            if text:
                self.heading = text


def _first_heading(html: str) -> str:
    parser = _HeadingFinder()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return parser.heading[:80]


def _rewrite_and_scrub(html: str, doc_dir: str, image_map: dict[str, str]) -> str:
    """重写图片引用（zip 路径 → images/<name>）并做服务端消毒（一次遍历）。"""
    return scrub_html(html, image_map=image_map, doc_dir=doc_dir)


def parse_epub(path: str | Path, title_hint: str | None = None, images_dir: str | Path | None = None) -> ParsedBook:
    try:
        book = epub.read_epub(str(path))
    except Exception as exc:  # noqa: BLE001 审查 C-问题14：损坏 EPUB 统一包装为 ValueError（路由映射 400，避免 500+孤儿文件）
        raise ValueError(f"EPUB 解析失败（文件损坏或非 EPUB）：{exc}") from exc
    images_dir = Path(images_dir) if images_dir else Path(path).parent / "images"
    image_map = _extract_images(book, images_dir)

    # ????????spine?????EPUB3 nav ????????????
    # ???? nav ?? spine???? nav ?? id ?????
    spine_ids = {ref[0] for ref in (book.spine or []) if isinstance(ref, (tuple, list)) and ref}
    try:
        nav_item = book.get_item_with_id("nav")
    except Exception:  # noqa: BLE001 ????? nav????????
        nav_item = None
    nav_id = nav_item.get_id() if nav_item else None
    metadata_title = book.get_metadata("DC", "title")
    title = str(metadata_title[0][0]) if metadata_title else (title_hint or Path(path).stem)
    chapters: list[ParsedChapter] = []
    idx = 0
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        if item.get_id() == nav_id or (spine_ids and item.get_id() not in spine_ids):
            continue
        raw = item.get_body_content()
        if not raw:
            continue
        html = raw.decode("utf-8", errors="replace")
        doc_dir = posixpath.dirname(posixpath.normpath(item.get_name()))
        cleaned = _rewrite_and_scrub(html, doc_dir, image_map)
        text = html_to_text(cleaned)
        if not text.strip() and "images/" not in cleaned:
            continue  # 空文档（目录/封面页等）跳过
        idx += 1
        heading = _first_heading(cleaned) or text.splitlines()[0].strip()[:80] or f"章节 {idx}"
        chapters.append(ParsedChapter(idx, heading, cleaned))
    return ParsedBook(title=title, chapters=chapters)
