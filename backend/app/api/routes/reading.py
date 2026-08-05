"""阅读闭环 API：章节正文、进度记录与恢复。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.models.book import Chapter
from app.repositories import books as book_repo
from app.repositories.reading import (
    book_reading_summary,
    get_latest_log,
    set_all_chapters_read_flag,
    set_chapter_read_flag,
)
from app.schemas.common import ok
from app.schemas.serializers import (
    book_to_dict,
    chapter_content_to_dict,
    chapter_to_dict,
    progress_to_dict,
)
from app.services.reading_service import save_book_progress

router = APIRouter(prefix="/api/books", tags=["reading"])


class ChapterReadIn(BaseModel):
    read: bool


class ProgressIn(BaseModel):
    chapter_id: int
    position: float = 0.0
    progress: float | None = None
    mark_read: bool = False  # 前端确认读完该章（阅读时长≥10s 且滚动到底）时置 True


class ReadAllIn(BaseModel):
    read: bool


@router.patch("/{book_id}/read-all")
def set_all_chapters_read(book_id: int, body: ReadAllIn, db: Session = Depends(get_db)):
    """整本标记：全部章节已读（读完）或全部未读（标记为在读）。"""
    book = require_book(db, book_id)
    book = set_all_chapters_read_flag(db, book, body.read)
    read_chapters, latest_chapter = book_reading_summary(db, book)
    return ok(book_to_dict(book, read_chapters=read_chapters, latest_chapter=latest_chapter))


@router.patch("/{book_id}/chapters/{chapter_id}/read")
def set_chapter_read(book_id: int, chapter_id: int, body: ChapterReadIn, db: Session = Depends(get_db)):
    """手动设置章节已读/未读（支持取消已读）。"""
    book = require_book(db, book_id)
    chapter = db.get(Chapter, chapter_id)
    if not chapter or chapter.book_id != book.id:
        raise HTTPException(status_code=404, detail="章节不存在")
    book = set_chapter_read_flag(db, book, chapter, body.read)
    return ok(chapter_to_dict(chapter))


@router.get("/{book_id}/chapters/{chapter_id}")
def get_chapter_content(book_id: int, chapter_id: int, db: Session = Depends(get_db)):
    """章节正文（含 Markdown 原文，供前端渲染）。"""
    require_book(db, book_id)
    chapter = next((c for c in book_repo.list_chapters(db, book_id) if c.id == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ok(chapter_content_to_dict(chapter, book_id))


@router.get("/{book_id}/progress")
def get_progress(book_id: int, db: Session = Depends(get_db)):
    """读取最近阅读位置（重新打开回到上次位置）。"""
    book = require_book(db, book_id)
    return ok(progress_to_dict(book, get_latest_log(db, book_id)))


@router.post("/{book_id}/progress")
def save_progress(book_id: int, body: ProgressIn, db: Session = Depends(get_db)):
    """保存阅读位置：ReadingLog + 书籍整体进度；mark_read=True 时标记章节已读。"""
    book = require_book(db, book_id)
    try:
        book, log = save_book_progress(
            db, book, body.chapter_id, body.position, body.progress, body.mark_read
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="章节不存在") from exc
    return ok(progress_to_dict(book, log))