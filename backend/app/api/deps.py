"""API 公共依赖。"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db  # noqa: F401
from app.repositories import books as book_repo


def require_book(db: Session, book_id: int):
    """按 ID 取书；不存在抛 404。供各路由复用，避免重复实现。"""
    book = book_repo.get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return book