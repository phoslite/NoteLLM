"""PDF 统一按页读图（含文本型，M7）+ 封面：导入检测、封面/页面端点、LLM 图片附件。"""
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from app.services.chat_service import build_messages


def _make_scanned_pdf(path: Path, pages: int = 3) -> None:
    """无文本层的 PDF：只有图形，用于模拟扫描版。"""
    doc = pymupdf.open()
    for _i in range(pages):
        page = doc.new_page(width=300, height=400)
        page.draw_rect(pymupdf.Rect(50, 50, 250, 350), color=(0.2, 0.4, 0.8), fill=(0.9, 0.9, 0.95))
    doc.save(str(path))
    doc.close()


def _make_text_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1 Introduction\n\nBody paragraph one here.", fontsize=12)
    doc.save(str(path))
    doc.close()


def _render_all(path: Path, out_dir: Path, workers: int | None = None) -> int:
    """渲染全部页（供并发/串行对比）。"""
    from app.parsers.pdf import render_pdf_pages

    return render_pdf_pages(path, out_dir, workers=workers)


def test_render_pdf_pages_concurrent_matches_serial(tmp_path):
    """并发渲染（worker 级 doc 复用）与串行结果一致：页数/文件齐全（决策 35）。"""
    import pymupdf

    pdf = tmp_path / "multi.pdf"
    _make_scanned_pdf(pdf, pages=5)

    serial_dir = tmp_path / "serial"
    n_serial = _render_all(pdf, serial_dir, workers=None)
    assert n_serial == 5

    conc_dir = tmp_path / "conc"
    n_conc = _render_all(pdf, conc_dir, workers=3)
    assert n_conc == 5
    files_serial = sorted(f.name for f in serial_dir.glob("page_*.jpg"))
    files_conc = sorted(f.name for f in conc_dir.glob("page_*.jpg"))
    assert files_serial == files_conc == [f"page_{i:03d}.jpg" for i in range(1, 6)]
    # 并发产物非空且可打开
    for name in files_conc:
        doc = pymupdf.open(str(conc_dir / name))
        doc.close()
        assert (conc_dir / name).stat().st_size > 0


def _import(client, path: Path, name: str):
    r = client.post("/api/books", files={"file": (name, path.read_bytes(), "application/pdf")})
    assert r.status_code == 200
    return r.json()["data"]


def test_import_scanned_pdf_pages_and_cover(client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    _make_scanned_pdf(pdf, pages=3)
    data = _import(client, pdf, "scan.pdf")

    assert data["is_scanned"] is True
    assert data["page_count"] == 3
    assert data["total_chapters"] == 3
    assert data["cover_url"] == f"/api/books/{data['id']}/cover"

    chs = client.get(f"/api/books/{data['id']}").json()["data"]["chapters"]
    assert [c["page_index"] for c in chs] == [1, 2, 3]
    assert [c["title"] for c in chs] == ["第 1 页", "第 2 页", "第 3 页"]

    cov = client.get(f"/api/books/{data['id']}/cover")
    assert cov.status_code == 200 and cov.headers["content-type"].startswith("image/")

    pg = client.get(f"/api/books/{data['id']}/pages/2")
    assert pg.status_code == 200 and pg.headers["content-type"].startswith("image/")
    assert client.get(f"/api/books/{data['id']}/pages/99").status_code == 404
    assert client.get(f"/api/books/{data['id']}/pages/0").status_code == 404


def test_import_text_pdf_unified_page_mode_with_cover(client, tmp_path):
    """文本型 PDF 同样按页处理（M7）：is_scanned=True、按页切章、渲染页图、保留封面。"""
    from app.core.database import SessionLocal
    from app.repositories import books as book_repo

    pdf = tmp_path / "text.pdf"
    _make_text_pdf(pdf)
    data = _import(client, pdf, "text.pdf")

    assert data["is_scanned"] is True
    assert data["page_count"] == 1
    assert data["total_chapters"] == 1
    assert data["cover_url"] is not None
    assert client.get(f"/api/books/{data['id']}/cover").status_code == 200
    # 文本型 PDF 也渲染原图页
    assert client.get(f"/api/books/{data['id']}/pages/1").status_code == 200
    chs = client.get(f"/api/books/{data['id']}").json()["data"]["chapters"]
    assert [c["page_index"] for c in chs] == [1]
    # 正文不再抽取（页面模式 content 为空）
    content = client.get(f"/api/books/{data['id']}/chapters/{chs[0]['id']}").json()["data"]
    assert content["content_text"] == ""
    # 本地抽取文本仅作全文检索索引
    db = SessionLocal()
    try:
        fp = book_repo.get_book(db, data["id"]).file_path
    finally:
        db.close()
    txt = Path(fp).parent / "local_text" / "page_001.txt"
    assert txt.exists() and "Introduction" in txt.read_text(encoding="utf-8")


def test_build_messages_injects_attachment_texts():
    """决策 36：主模型只收文本——划线裁剪图 / 插图由视觉模型提取为文本后注入，不再直发 image_url。"""
    book = SimpleNamespace(title="扫描书")
    chapter = SimpleNamespace(index=1, title="第 1 页", content_text="")

    msgs = build_messages(
        book, chapter, "这页讲了什么", "", [], [], True,
        crop_text="划线区域含公式 $\\Lambda^n V$",
        crop_label="第 2 段",
        media_texts=["插图：Cauchy–Binet 公式推导"],
    )
    user = msgs[1]["content"]
    assert isinstance(user, str)
    assert "image_url" not in user
    assert "划线区域" in user and "$\\Lambda^n V$" in user
    assert "第 2 段" in user
    assert "正文插图 1" in user and "Cauchy" in user

    # 隐私开关关闭时不注入附件文本
    msgs2 = build_messages(
        book, chapter, "这页讲了什么", "", [], [], False,
        crop_text="划线内容", media_texts=["插图内容"],
    )
    assert isinstance(msgs2[1]["content"], str)
    assert "划线内容" not in msgs2[1]["content"]
    assert "插图内容" not in msgs2[1]["content"]
