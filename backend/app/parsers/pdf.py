"""PDF 解析与媒体渲染。

- PDF（含文本型）统一按原始页切章（每页一章，page_index=页号，content 为空），
  阅读页直接展示原图（按内嵌原图分辨率渲染），避免文本抽取导致数学符号乱码。
- 本地抽取的按页文本（page_texts）仅作全文检索索引，不用于正文展示与 AI 上下文。
- 封面/页面渲染基于 PyMuPDF（pymupdf），无需外部 poppler。
"""
from functools import lru_cache
from pathlib import Path

import pymupdf

from app.parsers.base import ParsedBook, ParsedChapter

# 页图渲染：自动按内嵌原图分辨率放大（默认 72 DPI 太糊），下限 2.5x（≈180 DPI），上限 6x 防超大内存
PAGE_AUTO_ZOOM_MIN = 2.5
PAGE_AUTO_ZOOM_MAX = 6.0


def parse_pdf(path: str | Path, title_hint: str | None = None) -> ParsedBook:
    """解析 PDF：统一按原始页切章（page_index 从 1 开始，content 为空），阅读页按页读图。"""
    path = str(path)
    doc = pymupdf.open(path)
    try:
        page_count = doc.page_count
        pages_text = [(page.get_text() or "") for page in doc]
    finally:
        doc.close()

    title = title_hint or Path(path).stem
    chapters = [
        ParsedChapter(index=i, title=f"第 {i} 页", content="", page_index=i) for i in range(1, page_count + 1)
    ]
    return ParsedBook(title=title, chapters=chapters, is_scanned=True, page_count=page_count, page_texts=pages_text)

def _auto_page_zoom(page) -> float:
    """按页内嵌图片原生宽度确定渲染倍率（即「原图」）；无内嵌图片时按页面宽度 2.5x 兜底。"""
    native = max((info["width"] for info in page.get_image_info()), default=0)
    if native and page.rect.width:
        return min(max(native / page.rect.width, 1.0), PAGE_AUTO_ZOOM_MAX)
    return PAGE_AUTO_ZOOM_MIN


def pdf_page_target_width(path: str | Path, page_index: int) -> int:
    """该页应渲染到的目标像素宽度（内嵌原图宽度，至少 2.5x 页面宽）；页号越界返回 0。

    M10 性能优化：目标宽度按 (文件, 页号) 进程内缓存（书籍导入后 PDF 不变，
    页图仅在分辨率不足时按需升级），避免每次页图请求都重新打开 PDF。
    """
    return _target_width_cached(str(path), page_index)


@lru_cache(maxsize=4096)
def _target_width_cached(path: str, page_index: int) -> int:
    doc = pymupdf.open(path)
    try:
        if not 1 <= page_index <= doc.page_count:
            return 0
        page = doc[page_index - 1]
        return int(round(_auto_page_zoom(page) * page.rect.width))
    finally:
        doc.close()


def jpeg_width(path: str | Path) -> int:
    """读取已渲染页图的像素宽度（用于低清页图升级判断）；读取失败返回 0。

    不能用 pymupdf.open 按点宽读取：JPEG 自带 DPI 元数据会换算成点导致比例失真。
    """
    try:
        return pymupdf.Pixmap(str(path)).width
    except Exception:
        return 0


def _render_page_from_doc(
    doc,
    page_index: int,
    out_path: str | Path,
    max_width: int = 0,
    quality: int = 90,
    zoom: float | None = None,
) -> Path:
    """用已打开的 doc 渲染指定页（page_index 从 1 开始）；供串行/并发渲染复用同一文档句柄。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not 1 <= page_index <= doc.page_count:
        raise IndexError(f"页号越界: {page_index}（共 {doc.page_count} 页）")
    page = doc[page_index - 1]
    if zoom is None:
        if max_width and page.rect.width > max_width:
            zoom = max_width / page.rect.width
        else:
            zoom = _auto_page_zoom(page)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    pix.save(str(out_path), jpg_quality=quality)
    return out_path


def render_pdf_page(
    path: str | Path,
    page_index: int,
    out_path: str | Path,
    max_width: int = 0,
    quality: int = 90,
    zoom: float | None = None,
) -> Path:
    """把 PDF 指定页渲染为图片（按扩展名输出 png/jpg），返回输出路径。page_index 从 1 开始。

    - zoom 显式给出时按其渲染；
    - 否则 max_width > 0 时保持旧行为（超过 max_width 才缩到该宽度，封面用）；
    - 否则按内嵌原图分辨率自动放大（PDF 页图阅读用），避免 72 DPI 低清。
    """
    doc = pymupdf.open(str(path))
    try:
        return _render_page_from_doc(doc, page_index, out_path, max_width=max_width, quality=quality, zoom=zoom)
    finally:
        doc.close()


def extract_pdf_cover(path: str | Path, out_path: str | Path, max_width: int = 600, quality: int = 88) -> Path | None:
    """提取 PDF 封面：渲染第 1 页；页数不足时返回 None。"""
    doc = pymupdf.open(str(path))
    try:
        if doc.page_count < 1:
            return None
    finally:
        doc.close()
    return render_pdf_page(path, 1, out_path, max_width=max_width, quality=quality)


def _render_worker(
    path: str,
    out_dir: Path,
    max_width: int,
    quality: int,
    page_indices: list[int],
) -> None:
    """并发渲染 worker：每个 worker 打开一次 doc，循环渲染分配到的页（复用文档句柄）。"""
    doc = pymupdf.open(path)
    try:
        for i in page_indices:
            _render_page_from_doc(doc, i, out_dir / f"page_{i:03d}.jpg", max_width=max_width, quality=quality)
    finally:
        doc.close()


def render_pdf_pages(
    path: str | Path,
    out_dir: str | Path,
    max_width: int = 0,
    quality: int = 90,
    workers: int | None = None,
) -> int:
    """把 PDF 全部页渲染为 page_XXX.jpg 存入 out_dir，返回渲染页数（M7 起文本型 PDF 同样渲染）。

    - workers 为 None 或 <=1 时串行（单文档句柄）；>1 时按 page_render_concurrency 并发，
      每个 worker 复用各自的文档句柄（决策 35 并发化）。
    - max_width > 0 时全部页统一缩到该宽度；否则逐页按内嵌原图分辨率自动放大。
    """
    from concurrent.futures import ThreadPoolExecutor

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(path))
    try:
        count = doc.page_count
    finally:
        doc.close()
    if count <= 1 or workers is None or workers <= 1:
        doc = pymupdf.open(str(path))
        try:
            for i in range(1, count + 1):
                _render_page_from_doc(doc, i, out_dir / f"page_{i:03d}.jpg", max_width=max_width, quality=quality)
        finally:
            doc.close()
        return count
    chunks: list[list[int]] = [[] for _ in range(workers)]
    for i in range(1, count + 1):
        chunks[i % workers].append(i)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-render") as pool:
        futures = [
            pool.submit(_render_worker, str(path), out_dir, max_width, quality, pages)
            for pages in chunks
            if pages
        ]
        for f in futures:
            f.result()  # 任一页失败整体透出（导入任务级失败）
    return count
