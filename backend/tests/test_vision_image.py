"""v1.86 视觉提取压缩页图（pages_vlm/）：裁边/缩放/空白预判/meta 重建/批量预生成 + OCR 预留扩展。"""
import base64
import shutil
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories import books as book_repo
from app.services import vision_extract, vision_image
from app.services.blank_page import BLANK_PAGE_MARK


def _make_pdf(path: Path, pages: int = 3, blank: bool = False) -> None:
    """生成扫描样张：内容块在页面中部（四边留白）；blank=True 生成纯白页。"""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        if not blank:
            # 内容块覆盖页面约 55% 面积（触发裁边但不触发 <50% 回退）；深色 fill 灰度 <200 计入墨迹
            page.draw_rect(pymupdf.Rect(40, 50, 260, 350),
                           color=(0.1, 0.2, 0.5), fill=(0.2, 0.4, 0.8))
    doc.save(str(path))
    doc.close()


def _import(client, path: Path, name: str):
    r = client.post("/api/books", files={"file": (name, path.read_bytes(), "application/pdf")})
    assert r.status_code == 200
    return r.json()["data"]


def _book(db, book_id):
    return book_repo.get_book(db, book_id)


def _purge_vlm(book) -> None:
    """清空压缩图目录（含 meta），保证测试从全新状态开始（导入后台可能已预生成）。"""
    root = Path(book.file_path).parent / "pages_vlm"
    if root.exists():
        shutil.rmtree(root)


def test_prep_page_image_crops_and_caches(client, tmp_path):
    """单页压缩图：裁边重渲染生成、二次调用命中缓存、宽度不超过阈值、meta 落盘。"""
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan.pdf")
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        _purge_vlm(book)
        res = vision_image.prep_page_image(book, 1)
        assert res["source"] == "new"
        assert res["blank"] is False and res["trimmed"] is True
        vlm = vision_image.vlm_page_path(book, 1)
        assert vlm.exists()
        assert pymupdf.Pixmap(str(vlm)).width <= settings.vision_image_max_width
        # 二次调用命中缓存（不重新分析/渲染）
        res2 = vision_image.prep_page_image(book, 1)
        assert res2["source"] == "cached"
        assert vision_image._meta_valid(book)
    finally:
        db.close()


def test_prep_blank_page_detected(client, tmp_path):
    """纯白页：空白预判 True，不生成压缩图（调用方直接落盘空白标记）。"""
    pdf = tmp_path / "blank.pdf"
    _make_pdf(pdf, pages=1, blank=True)
    data = _import(client, pdf, "blank.pdf")
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        _purge_vlm(book)
        res = vision_image.prep_page_image(book, 1)
        assert res["blank"] is True
        assert not vision_image.vlm_page_path(book, 1).exists()
    finally:
        db.close()


def test_ensure_page_cache_blank_shortcircuit(monkeypatch, client, tmp_path):
    """空白预判短路：不调用多模态 API，直接落盘统一空白标记。"""
    pdf = tmp_path / "blank2.pdf"
    _make_pdf(pdf, pages=1, blank=True)
    data = _import(client, pdf, "blank2.pdf")
    calls = {"n": 0}

    class BoomVision:
        def __init__(self, **kw):
            pass

        def chat(self, messages):
            calls["n"] += 1
            raise AssertionError("空白页不应调用多模态")

    monkeypatch.setattr(vision_extract, "LLMClient", BoomVision)
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        _purge_vlm(book)
        text = vision_extract.ensure_page_cache(db, book, 1)
        assert text == BLANK_PAGE_MARK and calls["n"] == 0
        path = vision_extract.page_text_path(book, 1)
        assert path.read_text(encoding="utf-8").strip() == BLANK_PAGE_MARK
    finally:
        db.close()


def test_extract_uses_vlm_image(monkeypatch, client, tmp_path):
    """多模态输入优先压缩页图：视觉模型收到的图片 == pages_vlm/page_XXX.jpg。"""
    pdf = tmp_path / "scan2.pdf"
    _make_pdf(pdf, pages=1)
    data = _import(client, pdf, "scan2.pdf")
    seen = {}

    class RecordVision:
        def __init__(self, **kw):
            pass

        def chat(self, messages):
            seen["uri"] = next(p["image_url"]["url"]
                               for p in messages[1]["content"] if p.get("type") == "image_url")
            return "第 1 页内容"

    monkeypatch.setattr(vision_extract, "LLMClient", RecordVision)
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        vision_image.prepare_book_vlm_images(book)  # 测试环境未配置 vision：导入后台不预提取，显式生成
        vlm = vision_image.vlm_page_path(book, 1)
        assert vlm.exists(), "批量预生成应产出压缩图"
        vision_extract.ensure_page_cache(db, book, 1)
        expected = "data:image/jpeg;base64," + base64.b64encode(vlm.read_bytes()).decode("ascii")
        assert seen["uri"] == expected
    finally:
        db.close()


def test_meta_signature_purge_rebuild(monkeypatch, client, tmp_path):
    """参数签名变更：批量入口整目录重建（purge 旧图、重写 meta）。"""
    pdf = tmp_path / "scan3.pdf"
    _make_pdf(pdf, pages=2)
    data = _import(client, pdf, "scan3.pdf")
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        vision_image.prepare_book_vlm_images(book)
        vlm1 = vision_image.vlm_page_path(book, 1)
        assert vlm1.exists()
        old_bytes = vlm1.read_bytes()
        monkeypatch.setattr(settings, "vision_image_max_width", 400, raising=False)
        assert not vision_image._meta_valid(book)
        stats = vision_image.prepare_book_vlm_images(book)
        assert stats["purged"] == 1
        assert vlm1.exists() and vlm1.read_bytes() != old_bytes
        assert vision_image._meta_valid(book)
    finally:
        db.close()


def test_trim_bbox_conservative_and_aggressive():
    """裁边 bbox 纯函数：conservative 只裁完全空白边带；aggressive 保护带外扩 + padding。"""
    w = h = 100
    gray = bytearray([255] * (w * h))
    for y in range(30, 71):
        for x in range(30, 71):
            gray[y * w + x] = 0
    row_ink, col_ink = vision_image._ink_stats(gray, w, h)
    # scale=2（原图 200px）：smooth(7) 使内容 span 外扩到 27..74（demo 实测行为）
    bb = vision_image._trim_bbox(row_ink, col_ink, w, h, 2.0, "conservative")
    assert bb == (27, 27, 74, 74)
    # aggressive：保护带(16px→8 分析像素)内无墨迹 → 外扩 padding 至 (22,22,79,79)
    bb2 = vision_image._trim_bbox(row_ink, col_ink, w, h, 2.0, "aggressive")
    assert bb2 == (22, 22, 79, 79)
    # none 不裁
    bb3 = vision_image._trim_bbox(row_ink, col_ink, w, h, 2.0, "none")
    assert bb3 == (0, 0, w, h)
    # 全白页 → 无内容 → None
    blank = bytearray([255] * (w * h))
    r_, c_ = vision_image._ink_stats(blank, w, h)
    assert vision_image._trim_bbox(r_, c_, w, h, 1.0, "conservative") is None


def test_ocr_unconfigured_returns_none(monkeypatch, client, tmp_path):
    """OCR 预留扩展：未配置引擎时 ocr_configured=False、ocr_page_text 返回 None（不抛）。"""
    monkeypatch.setattr(settings, "vision_ocr_engine", "", raising=False)
    assert vision_image.ocr_configured() is False
    pdf = tmp_path / "ocr.pdf"
    _make_pdf(pdf, pages=1)
    data = _import(client, pdf, "ocr.pdf")
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        vision_image.prepare_book_vlm_images(book)
        vlm = vision_image.vlm_page_path(book, 1)
        assert vlm.exists()
        assert vision_image.ocr_page_text(vlm) is None
        assert vision_image.read_ocr_cache(book, 1) is None
    finally:
        db.close()


def test_ocr_tesseract_missing_bin_returns_none(monkeypatch):
    """tesseract 引擎：可执行文件不存在/调用失败 → 返回 None（回退视觉模型，不抛）。"""
    monkeypatch.setattr(settings, "vision_ocr_engine", "tesseract", raising=False)
    monkeypatch.setattr(settings, "vision_ocr_bin", "definitely-not-tesseract-bin", raising=False)
    monkeypatch.setattr(settings, "vision_ocr_lang", "eng", raising=False)
    assert vision_image.ocr_configured() is True
    assert vision_image.ocr_page_text(Path("not-exists.png")) is None


def test_ensure_page_cache_ocr_priority(monkeypatch, client, tmp_path):
    """OCR 文本缓存优先：已配置引擎且有 OCR 文本时，不调用多模态 API。"""
    pdf = tmp_path / "ocr2.pdf"
    _make_pdf(pdf, pages=1)
    data = _import(client, pdf, "ocr2.pdf")
    calls = {"n": 0}

    class BoomVision:
        def __init__(self, **kw):
            pass

        def chat(self, messages):
            calls["n"] += 1
            raise AssertionError("有 OCR 文本时不应调用多模态")

    monkeypatch.setattr(vision_extract, "LLMClient", BoomVision)
    monkeypatch.setattr(settings, "vision_ocr_engine", "tesseract", raising=False)
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        vision_image.write_ocr_cache(book, 1, "OCR 提取的页面文本 $E=mc^2$")
        text = vision_extract.ensure_page_cache(db, book, 1)
        assert "OCR" in text and calls["n"] == 0
    finally:
        db.close()


def test_prepare_book_vlm_images_stats(client, tmp_path):
    """批量预生成统计：全书生成、二次执行全部命中缓存、无错误。"""
    pdf = tmp_path / "stats.pdf"
    _make_pdf(pdf, pages=3)
    data = _import(client, pdf, "stats.pdf")
    db = SessionLocal()
    try:
        book = _book(db, data["id"])
        _purge_vlm(book)
        stats = vision_image.prepare_book_vlm_images(book)
        assert stats["total"] == 3
        assert stats["ok"] + stats["blank"] == 3
        assert stats["errors"] == []
        assert (Path(book.file_path).parent / "pages_vlm" / "page_001.jpg").exists()
        stats2 = vision_image.prepare_book_vlm_images(book)
        assert stats2["ok"] == 0 and stats2["skipped"] == 3
    finally:
        db.close()