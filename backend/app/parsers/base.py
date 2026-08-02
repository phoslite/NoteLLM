"""解析结果数据结构。"""
from dataclasses import dataclass, field


@dataclass
class ParsedChapter:
    index: int
    title: str
    content: str
    page_index: int | None = None  # 扫描版 PDF：对应原始 PDF 页号（从 1 开始）


@dataclass
class ParsedBook:
    title: str
    author: str = ""
    chapters: list[ParsedChapter] = field(default_factory=list)
    is_scanned: bool = False  # PDF 统一按页模式：True 表示按原始页读图（含文本型 PDF）
    page_count: int = 0  # 原始 PDF 页数（按页阅读使用）
    page_texts: list[str] = field(default_factory=list)  # PDF 本地抽取文本（按页，仅作全文检索索引）