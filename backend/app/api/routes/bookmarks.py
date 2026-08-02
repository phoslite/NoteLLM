"""书签 API：位置书签（全格式）CRUD + 分组归类。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.repositories import bookmarks as bookmark_repo
from app.repositories import books as book_repo
from app.schemas.common import ok
from app.schemas.serializers import bookmark_to_dict

router = APIRouter(prefix="/api", tags=["bookmarks"])


class BookmarkIn(BaseModel):
    chapter_id: int | None = None
    page_index: int | None = None
    para_pos: str | None = None
    title: str = Field(default="", max_length=200)
    note: str = ""
    group_name: str = Field(default="", max_length=100)


class BookmarkUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    note: str | None = None
    group_name: str | None = Field(default=None, max_length=100)


@router.get("/books/{book_id}/bookmarks")
def list_bookmarks(book_id: int, db: Session = Depends(get_db)):
    """书签列表（默认按时间倒序）。"""
    require_book(db, book_id)
    return ok([bookmark_to_dict(b) for b in bookmark_repo.list_bookmarks(db, book_id)])


@router.post("/books/{book_id}/bookmarks")
def create_bookmark(book_id: int, body: BookmarkIn, db: Session = Depends(get_db)):
    require_book(db, book_id)
    title = body.title.strip() or "未命名书签"
    if body.chapter_id is not None and not any(
        c.id == body.chapter_id for c in book_repo.list_chapters(db, book_id)
    ):
        raise HTTPException(status_code=404, detail="章节不存在")
    bm = bookmark_repo.create_bookmark(
        db,
        book_id,
        body.chapter_id,
        body.page_index,
        body.para_pos,
        title,
        body.note,
        body.group_name,
    )
    return ok(bookmark_to_dict(bm), "书签已保存")


@router.patch("/bookmarks/{bookmark_id}")
def update_bookmark(bookmark_id: int, body: BookmarkUpdate, db: Session = Depends(get_db)):
    bm = bookmark_repo.update_bookmark(db, bookmark_id, body.title, body.note, body.group_name)
    if not bm:
        raise HTTPException(status_code=404, detail="书签不存在")
    return ok(bookmark_to_dict(bm))


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: int, db: Session = Depends(get_db)):
    if not bookmark_repo.delete_bookmark(db, bookmark_id):
        raise HTTPException(status_code=404, detail="书签不存在")
    return ok(None, "已删除")
