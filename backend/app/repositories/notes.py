"""笔记数据访问层：高亮/批注/思考/不理解。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Note


def list_notes(db: Session, book_id: int) -> list[Note]:
    return list(db.scalars(select(Note).where(Note.book_id == book_id).order_by(Note.chapter_id, Note.id)))


def create_note(
    db: Session,
    book_id: int,
    chapter_id: int | None,
    note_type: str,
    note_text: str = "",
    quote_text: str = "",
) -> Note:
    note = Note(book_id=book_id, chapter_id=chapter_id, note_type=note_type, note_text=note_text, quote_text=quote_text)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def update_note(db: Session, note_id: int, note_text: str | None = None, note_type: str | None = None) -> Note | None:
    note = db.get(Note, note_id)
    if not note:
        return None
    if note_text is not None:
        note.note_text = note_text
    if note_type is not None:
        note.note_type = note_type
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note_id: int) -> bool:
    note = db.get(Note, note_id)
    if not note:
        return False
    db.delete(note)
    db.commit()
    return True