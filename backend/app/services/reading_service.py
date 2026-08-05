"""阅读进度编排服务（审查 P0-5）：进度计算与画像回写从路由下沉。

路由只做参数校验与序列化；进度公式、热画像回写、异常隔离统一在本层。
"""
from sqlalchemy.orm import Session

from app.models.book import Book
from app.repositories import books as book_repo
from app.repositories.reading import update_book_reading, upsert_log
from app.services.profile_service import update_hot_profile


def save_book_progress(
    db: Session,
    book: Book,
    chapter_id: int,
    position: float,
    progress: float | None = None,
    mark_read: bool = False,
):
    """保存阅读位置：ReadingLog + 书籍整体进度 + 热画像回写。

    未显式传 progress 时按「章节序号 + 页内位置」线性估算；
    热画像回写失败不影响阅读（单独 rollback 隔离）。
    """
    chapters = book_repo.list_chapters(db, book.id)
    if not any(c.id == chapter_id for c in chapters):
        raise LookupError("章节不存在")
    log = upsert_log(db, book.id, chapter_id, position)
    if progress is None:
        total = len(chapters) or 1
        idx = next((i for i, c in enumerate(chapters) if c.id == chapter_id), 0)
        progress = (idx + max(0.0, min(1.0, position))) / total
    book = update_book_reading(db, book, progress, chapter_id, mark_read=mark_read)
    try:
        chapter = next((c for c in chapters if c.id == chapter_id), None)
        update_hot_profile(
            db,
            book,
            progress=progress,
            chapter_title=chapter.title if chapter else None,
        )
    except Exception:
        db.rollback()
    return book, log
