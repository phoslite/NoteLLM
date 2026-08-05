"""书签数据访问层：位置书签（全格式）CRUD。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Bookmark


def list_bookmarks(db: Session, book_id: int) -> list[Bookmark]:
    """按时间倒序返回本书书签。"""
    return list(
        db.scalars(select(Bookmark).where(Bookmark.book_id == book_id).order_by(Bookmark.created_at.desc(), Bookmark.id.desc()))
    )


def create_bookmark(
    db: Session,
    book_id: int,
    chapter_id: int | None,
    page_index: int | None,
    para_pos: str | None,
    title: str,
    note: str = "",
    group_name: str = "",
) -> Bookmark:
    bm = Bookmark(
        book_id=book_id,
        chapter_id=chapter_id,
        page_index=page_index,
        para_pos=para_pos,
        title=title,
        note=note,
        group_name=group_name,
    )
    db.add(bm)
    db.commit()
    db.refresh(bm)
    return bm


def update_bookmark(
    db: Session,
    bookmark_id: int,
    title: str | None = None,
    note: str | None = None,
    group_name: str | None = None,
) -> Bookmark | None:
    bm = db.get(Bookmark, bookmark_id)
    if not bm:
        return None
    if title is not None:
        bm.title = title
    if note is not None:
        bm.note = note
    if group_name is not None:
        bm.group_name = group_name
    db.commit()
    db.refresh(bm)
    return bm


def delete_bookmark(db: Session, bookmark_id: int) -> bool:
    bm = db.get(Bookmark, bookmark_id)
    if not bm:
        return False
    db.delete(bm)
    db.commit()
    return True
