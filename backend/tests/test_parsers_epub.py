"""EPUB 方案 A：保留原排版 HTML + 服务端消毒 + 图片提取重写 + 文本消费点纯文本。"""
import base64
from pathlib import Path

from ebooklib import epub

from app.parsers.epub import parse_epub
from app.services.html_util import chapter_plain_text, html_to_text, scrub_html
from app.services.media_service import rewrite_chapter_media_urls
from app.services.rag_input import chunk_chapter

# 1x1 透明 PNG（最小合法文件）
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _make_epub(path: Path) -> None:
    """构造测试 EPUB：两章正文（含图片/脚本/事件属性）+ 一张图片资源。"""
    book = epub.EpubBook()
    book.set_identifier("test-epub-001")
    book.set_title("测试 EPUB")
    book.set_language("zh")
    book.add_author("测试作者")
    img = epub.EpubItem(
        uid="img1", file_name="OEBPS/Images/fig.png", media_type="image/png", content=_PNG
    )
    book.add_item(img)
    c1 = epub.EpubHtml(title="第一章", file_name="OEBPS/text/ch1.xhtml", lang="zh")
    c1.content = (
        "<html><head><title>第一章</title></head><body>"
        '<h1>第一章 引言</h1>'
        '<p style="text-indent:2em">第一段正文 <img src="../Images/fig.png" alt="图1" '
        'onclick="alert(1)"/></p>'
        "<script>alert('xss')</script>"
        '<p>第二段正文 <a href="javascript:evil()">链接</a></p>'
        "</body></html>"
    )
    book.add_item(c1)
    c2 = epub.EpubHtml(title="第二章", file_name="OEBPS/text/ch2.xhtml", lang="zh")
    c2.content = "<html><body><h2>第二章 结论</h2><p>只有文字的章节。</p></body></html>"
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_parse_epub_preserves_layout_and_sanitizes(tmp_path):
    """正文保留原排版 HTML；script/事件属性/危险 URL 被服务端消毒；图片引用重写；nav 不当作章节。"""
    src = tmp_path / "book.epub"
    _make_epub(src)
    parsed = parse_epub(src, images_dir=tmp_path / "out")

    assert parsed.title == "测试 EPUB"
    assert len(parsed.chapters) == 2
    ch1 = parsed.chapters[0]
    assert ch1.title == "第一章 引言"
    assert "<h1>第一章 引言</h1>" in ch1.content
    assert 'style="text-indent:2em"' in ch1.content
    assert 'src="images/fig.png"' in ch1.content
    assert "<script" not in ch1.content
    assert "onclick" not in ch1.content
    assert "javascript:" not in ch1.content
    assert "xss" not in ch1.content  # 脚本内容被剔除
    assert (tmp_path / "out" / "fig.png").read_bytes() == _PNG


def test_parse_epub_rewrites_images_relative_to_doc_dir(tmp_path):
    """图片引用按文档所在目录解析（OEBPS/text/ch1.xhtml → ../Images/fig.png = OEBPS/Images/fig.png）。"""
    src = tmp_path / "book.epub"
    _make_epub(src)
    parsed = parse_epub(src, images_dir=tmp_path / "out")
    assert 'src="images/fig.png"' in parsed.chapters[0].content


def test_parse_epub_skips_documents_without_content(tmp_path):
    """??????????????????????????"""
    src = tmp_path / "book.epub"
    book = epub.EpubBook()
    book.set_identifier("empty-001")
    book.set_title("??")
    script_only = epub.EpubHtml(title="???", file_name="OEBPS/script.xhtml", lang="zh")
    script_only.content = "<html><body><script>bad()</script></body></html>"
    book.add_item(script_only)
    book.toc = (script_only,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(src), book)
    parsed = parse_epub(src, images_dir=tmp_path / "out")
    assert parsed.chapters == []


def test_html_util_text_and_scrub():
    """html_to_text 块级换行；scrub_html 剔除危险标签与事件属性。"""
    html = "<h1>标题</h1><p>第一段</p><p>第二段</p><br/>尾部"
    text = html_to_text(html)
    assert "标题" in text and "第一段" in text and "第二段" in text and "尾部" in text
    assert text.index("标题") < text.index("第一段") < text.index("第二段")

    dangerous = '<p onclick="x()">a</p><script>bad()</script><a href="javascript:evil()">b</a>'
    cleaned = scrub_html(dangerous)
    assert "onclick" not in cleaned and "<script" not in cleaned and "javascript:" not in cleaned
    assert "<p>a</p>" in cleaned and "<a href=\"javascript:evil()\">b</a>" not in cleaned


def test_chapter_plain_text_by_format():
    """epub 格式转纯文本；md/txt 原样返回。"""
    assert chapter_plain_text("epub", "<p>甲</p><p>乙</p>") == "甲\n乙"
    assert chapter_plain_text("md", "**加粗**") == "**加粗**"
    assert chapter_plain_text("txt", "一行") == "一行"
    assert chapter_plain_text(None, "<p>x</p>") == "<p>x</p>"


def test_rewrite_chapter_media_urls_html_src():
    """决策 31 媒体重写支持 HTML 属性内引用（含引号边界，审查回归）。"""
    out = rewrite_chapter_media_urls('<p><img src="images/fig.png" alt="x"></p>', 7)
    assert out == '<p><img src="/api/books/7/media/fig.png" alt="x"></p>'


def test_import_epub_media_endpoint(client, tmp_path):
    """?? EPUB????????????? URL??????????? 31 ????"""
    src = tmp_path / "book.epub"
    _make_epub(src)
    r = client.post(
        "/api/books",
        files={"file": ("book.epub", src.read_bytes(), "application/epub+zip")},
    )
    assert r.status_code == 200
    book_id = r.json()["data"]["id"]
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch = detail["chapters"][0]
    content = client.get(f"/api/books/{book_id}/chapters/{ch['id']}").json()["data"]["content_text"]
    assert f"/api/books/{book_id}/media/fig.png" in content
    # EPUB 字数按纯文本统计（正文为消毒后 HTML，标签不计入）
    assert 0 < ch["word_count"] < 500
    assert ch["word_count"] == len(html_to_text(content))
    img = client.get(f"/api/books/{book_id}/media/fig.png")
    assert img.status_code == 200
    assert img.content == _PNG


def test_rag_chunk_epub_html_to_text():
    """RAG 切块对 EPUB HTML 正文先转纯文本（不把标签切进片段）。"""
    from types import SimpleNamespace

    chapter = SimpleNamespace(index=1, title="第一章", content_text="<p>第一段</p><p>第二段</p>")
    chunks = chunk_chapter(chapter, is_html=True)
    assert chunks
    assert all("<" not in c["text"] for c in chunks)
    assert "第一段" in chunks[0]["text"]

def test_book_corpus_epub_plain_text():
    """聚类/关键词语料：EPUB HTML 正文先转纯文本（book_corpus 不携带标签）。"""
    from types import SimpleNamespace

    from app.services.graph.corpus import book_corpus

    book = SimpleNamespace(
        title="测试",
        author="",
        format="epub",
        chapters=[SimpleNamespace(title="第一章", content_text="<p>第一段</p><p>第二段</p>")],
    )
    text = book_corpus(book)
    assert "<p>" not in text
    assert "第一段" in text and "第二段" in text
