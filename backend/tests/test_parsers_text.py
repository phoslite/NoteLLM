"""Markdown/TXT 解析测试。"""
from pathlib import Path

from app.parsers._split import split_by_headings
from app.parsers.text import parse_markdown, parse_txt


def test_parse_markdown_chapters(tmp_path: Path):
    f = tmp_path / "book.md"
    f.write_text(
        "# 第一章 开始\n\n正文一\n\n## 第一节\n\n内容\n\n# 第二章 进阶\n\n正文二\n",
        encoding="utf-8",
    )
    book = parse_markdown(f)
    assert book.title == "第一章 开始"
    assert len(book.chapters) >= 2
    assert "正文二" in book.chapters[-1].content


def test_parse_txt_chapters(tmp_path: Path):
    f = tmp_path / "book.txt"
    f.write_text("第1章 引言\n\n你好\n\n第2章 主体\n\n世界\n", encoding="utf-8")
    book = parse_txt(f)
    assert len(book.chapters) == 2
    assert book.chapters[1].title == "主体"


def test_split_by_headings_shared_helper():
    raw = "第1章 引言\n\n正文A\n\n第2章 主体\n\n正文B\n"
    book = split_by_headings(raw, "书名", lambda ln: ln.strip() if ln.startswith("第") else None)
    assert book.title == "书名"
    assert len(book.chapters) == 2
    assert book.chapters[0].title == "第1章 引言"
    assert "正文B" in book.chapters[1].content


def test_split_by_headings_skips_empty_chapters():
    raw = "第1章\n\n正文\n\n第2章\n\n\n第3章\n\n结束\n"
    book = split_by_headings(raw, "t", lambda ln: ln.strip() if ln.startswith("第") else None)
    assert [c.title for c in book.chapters] == ["第1章", "第3章"]