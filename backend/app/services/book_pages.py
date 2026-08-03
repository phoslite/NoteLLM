"""扫描版 PDF 页图服务：按页渲染/重渲染，供阅读与视觉提问共用。"""
from pathlib import Path

from app.models.book import Book
from app.parsers.pdf import jpeg_width, pdf_page_target_width, render_pdf_page
from app.services.media_service import page_image_path


def get_or_render_page(book: Book, page_index: int) -> Path | None:
    """返回扫描版 PDF 第 page_index 页的图片文件路径；缺失或分辨率低于内嵌原图时按需重渲染。

    低清判定：PDF 内嵌图片目标宽度 > 0 且当前 jpg 宽度 < 目标的 85%。
    返回 None 表示该书不是扫描版、文件不可用或渲染失败（调用方据此回 404）。
    """
    if not (book.is_scanned and Path(book.file_path).exists()):
        return None
    path = page_image_path(book, page_index)
    if path.exists():
        try:
            target = pdf_page_target_width(Path(book.file_path), page_index)
            if target > 0 and jpeg_width(path) < target * 0.85:
                path.unlink(missing_ok=True)  # 低清：删除后走重渲染
            else:
                return path
        except Exception:
            return path  # 判定失败：保留现有文件
    if not path.exists():
        try:
            render_pdf_page(Path(book.file_path), page_index, path)
            return path
        except Exception:
            return None
    return path
