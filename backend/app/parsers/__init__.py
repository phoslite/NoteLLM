"""书籍解析器：按扩展名分发。"""
from pathlib import Path

from app.parsers.base import ParsedBook
from app.parsers.epub import parse_epub
from app.parsers.pdf import parse_pdf
from app.parsers.text import parse_markdown, parse_txt

SUPPORTED_EXT = {".pdf", ".md", ".markdown", ".txt", ".epub"}


def parse_book(path: str | Path, title_hint: str | None = None, images_dir: str | Path | None = None) -> ParsedBook:
    """解析书籍文件为 ParsedBook；不支持的格式抛 ValueError。

    images_dir：EPUB 图片资源输出目录（方案 A，默认 <书目录>/images）。
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, title_hint)
    if suffix == ".epub":
        return parse_epub(path, title_hint, images_dir=images_dir)
    if suffix in (".md", ".markdown"):
        return parse_markdown(path, title_hint)
    if suffix == ".txt":
        return parse_txt(path, title_hint)
    raise ValueError(f"不支持的格式: {suffix}（支持 {'、'.join(sorted(SUPPORTED_EXT))}）")
