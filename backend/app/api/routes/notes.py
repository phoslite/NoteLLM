"""笔记 API：高亮/批注/思考/不理解 + Markdown/PDF 导出。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.repositories import books as book_repo
from app.repositories import notes as note_repo
from app.schemas.common import ok
from app.schemas.serializers import note_to_dict
from app.services.note_export import build_notes_markdown, build_notes_pdf

router = APIRouter(prefix="/api", tags=["notes"])


class NoteIn(BaseModel):
    chapter_id: int | None = None
    quote_text: str = ""
    note_text: str = ""
    note_type: str = Field(default="高亮", pattern="^(高亮|批注|思考|不理解)$")


class NoteUpdate(BaseModel):
    note_text: str | None = None
    note_type: str | None = None



@router.get("/books/{book_id}/notes")
def list_notes(book_id: int, db: Session = Depends(get_db)):
    require_book(db, book_id)
    return ok([note_to_dict(n) for n in note_repo.list_notes(db, book_id)])


@router.post("/books/{book_id}/notes")
def create_note(book_id: int, body: NoteIn, db: Session = Depends(get_db)):
    require_book(db, book_id)
    if body.chapter_id is not None and not any(
        c.id == body.chapter_id for c in book_repo.list_chapters(db, book_id)
    ):
        raise HTTPException(status_code=404, detail="章节不存在")
    note = note_repo.create_note(
        db, book_id, body.chapter_id, body.note_type, body.note_text.strip(), body.quote_text.strip()
    )
    # 热画像回写：笔记/划线/「不理解」点（失败不影响笔记保存）
    try:
        from app.services.profile_service import update_hot_profile

        book = require_book(db, book_id)
        update_hot_profile(
            db,
            book,
            highlight={
                "chapter_id": body.chapter_id,
                "type": body.note_type,
                "text": (body.quote_text or body.note_text or "")[:200],
            },
        )
    except Exception:
        db.rollback()
    return ok(note_to_dict(note), "已保存")


@router.patch("/notes/{note_id}")
def update_note(note_id: int, body: NoteUpdate, db: Session = Depends(get_db)):
    note = note_repo.update_note(db, note_id, body.note_text, body.note_type)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ok(note_to_dict(note))


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    if not note_repo.delete_note(db, note_id):
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ok(None, "已删除")


@router.get("/books/{book_id}/notes/export")
def export_notes(
    book_id: int,
    fmt: str = Query("md", pattern="^(md|markdown|pdf)$", description="导出格式：md/markdown 或 pdf"),
    db: Session = Depends(get_db),
):
    """导出全书笔记（M10）：Markdown 或 PDF，结构与公式（LaTeX 源码）保留。"""
    book = require_book(db, book_id)
    notes = note_repo.list_notes(db, book_id)
    chapters = {c.id: c for c in book_repo.list_chapters(db, book_id)}
    if fmt == "pdf":
        return Response(
            content=build_notes_pdf(book, notes, chapters),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="notes.pdf"'},
        )
    return Response(
        content=build_notes_markdown(book, notes, chapters),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="notes.md"'},
    )