"""M10 验收测试：笔记 Markdown/PDF 导出（含结构与 LaTeX 源码保留）。"""
import pymupdf


def _upload(client, text="# 第一章\n\n正文一\n\n# 第二章\n\n正文二\n"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode(), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _add_notes(client, book_id):
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]
    r = client.post(
        f"/api/books/{book_id}/notes",
        json={
            "chapter_id": ch,
            "quote_text": "正文一：Krein–Milman 定理",
            "note_text": "**紧凸集**由其端点决定，公式 $\\operatorname{ext}(K)$。",
            "note_type": "批注",
        },
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/books/{book_id}/notes",
        json={"chapter_id": None, "quote_text": "", "note_text": "没看懂：\\int f(x) dx", "note_type": "不理解"},
    )
    assert r.status_code == 200


def test_notes_export_markdown_default(client):
    book_id = _upload(client)
    _add_notes(client, book_id)
    exp = client.get(f"/api/books/{book_id}/notes/export")
    assert exp.status_code == 200
    assert exp.headers["content-type"].startswith("text/markdown")
    assert "笔记导出" in exp.text
    assert "[批注]" in exp.text and "[不理解]" in exp.text
    assert "正文一：Krein–Milman 定理" in exp.text
    assert "\\operatorname{ext}(K)" in exp.text  # LaTeX 源码保留


def test_notes_export_pdf(client):
    book_id = _upload(client)
    _add_notes(client, book_id)
    r = client.get(f"/api/books/{book_id}/notes/export?fmt=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"

    doc = pymupdf.open(stream=r.content, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    assert doc.page_count >= 1
    assert "笔记导出" in text
    assert "批注" in text and "不理解" in text
    assert "紧凸集" in text
    assert "\\operatorname{ext}(K)" in text  # LaTeX 源码保留


def test_notes_export_format_validation(client):
    book_id = _upload(client)
    assert client.get(f"/api/books/{book_id}/notes/export?fmt=xlsx").status_code == 422
    assert client.get(f"/api/books/{book_id}/notes/export?fmt=markdown").status_code == 200