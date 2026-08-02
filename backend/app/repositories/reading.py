"""阅读进度数据访问层：ReadingLog + 书籍进度/章节已读标记。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.activity import ReadingLog
from app.models.book import Book, Chapter


def get_latest_log(db: Session, book_id: int) -> ReadingLog | None:
    return db.scalars(
        select(ReadingLog).where(ReadingLog.book_id == book_id).order_by(ReadingLog.updated_at.desc()).limit(1)
    ).first()


def upsert_log(db: Session, book_id: int, chapter_id: int, position: float) -> ReadingLog:
    """记录阅读位置；同一章节内重复记录更新 position。"""
    log = db.scalars(
        select(ReadingLog).where(ReadingLog.book_id == book_id, ReadingLog.chapter_id == chapter_id).limit(1)
    ).first()
    if log:
        log.position = position
        log.updated_at = utcnow()
    else:
        log = ReadingLog(book_id=book_id, chapter_id=chapter_id, position=position)
        db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _refresh_status(db: Session, book: Book) -> list[Chapter]:
    """按章节已读情况同步书籍状态：全部读完→读完；部分已读→在读；全部未读→未读。"""
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id)))
    read_count = sum(1 for c in chapters if c.read_flag)
    if chapters and read_count == len(chapters):
        book.status = "读完"
    elif read_count == 0:
        book.status = "未读"
    else:
        book.status = "在读"
    return chapters


def update_book_reading(
    db: Session, book: Book, progress: float, chapter_id: int | None = None, mark_read: bool = False
) -> Book:
    """更新书籍整体进度与最近打开时间；仅当 mark_read=True 时标记对应章节已读，并同步书籍状态。"""
    book.progress = max(0.0, min(1.0, progress))
    book.last_opened_at = utcnow()
    if chapter_id is not None and mark_read:
        chapter = db.get(Chapter, chapter_id)
        if chapter and chapter.book_id == book.id:
            chapter.read_flag = True
    db.flush()
    # 仅章节已读状态变化时同步书籍状态，位置保存不改变 status（保留手动标记）
    if mark_read:
        _refresh_status(db, book)
    db.commit()
    db.refresh(book)
    return book


def set_chapter_read_flag(db: Session, book: Book, chapter: Chapter, read: bool) -> Book:
    """手动设置章节已读/未读，并同步书籍状态（取消一章会使读完状态回退）。"""
    chapter.read_flag = read
    db.flush()
    _refresh_status(db, book)
    db.commit()
    db.refresh(book)
    return book


def set_all_chapters_read_flag(db: Session, book: Book, read: bool) -> Book:
    """整本标记：全部章节已读/未读，并同步书籍状态与整体进度（读完→读完/100%，取消→在读/0%）。"""
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id)))
    for ch in chapters:
        ch.read_flag = read
    db.flush()
    if read:
        book.status = "读完"
        book.progress = 1.0
    else:
        book.status = "在读"
        book.progress = 0.0
    db.commit()
    db.refresh(book)
    return book


def book_reading_summary(db: Session, book: Book) -> tuple[int, Chapter | None]:
    """书籍阅读概况：已读章节数 + 最新章节（最近阅读日志章节，兜底已读最高章节）。"""
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index)))
    read_count = sum(1 for c in chapters if c.read_flag)
    latest: Chapter | None = None
    log = get_latest_log(db, book.id)
    if log and log.chapter_id is not None:
        latest = next((c for c in chapters if c.id == log.chapter_id), None)
    if latest is None:
        latest = next((c for c in reversed(chapters) if c.read_flag), None)
    return read_count, latest


def books_reading_summary(db: Session, books: list[Book]) -> dict[int, tuple[int, Chapter | None]]:
    """批量书籍阅读概况：一次查询全部最新阅读日志后内存统计，避免 list_books 的 N+1。

    章节列表复用传入 books 上已加载的 chapters（list_books 使用 selectinload 预载）。
    """
    if not books:
        return {}
    book_ids = [b.id for b in books]
    logs = list(
        db.scalars(
            select(ReadingLog)
            .where(ReadingLog.book_id.in_(book_ids))
            .order_by(ReadingLog.updated_at.desc())
        )
    )
    latest_log_by_book: dict[int, ReadingLog] = {}
    for log in logs:
        latest_log_by_book.setdefault(log.book_id, log)
    result: dict[int, tuple[int, Chapter | None]] = {}
    for book in books:
        chapters = list(book.chapters)
        read_count = sum(1 for c in chapters if c.read_flag)
        latest: Chapter | None = None
        log = latest_log_by_book.get(book.id)
        if log and log.chapter_id is not None:
            latest = next((c for c in chapters if c.id == log.chapter_id), None)
        if latest is None:
            latest = next((c for c in reversed(chapters) if c.read_flag), None)
        result[book.id] = (read_count, latest)
    return result
