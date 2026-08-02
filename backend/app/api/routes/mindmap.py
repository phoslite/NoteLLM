"""脑图 API：对章节/选中段落生成层级化脑图（ECharts 树数据 + Markdown 大纲）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.client import LLMError
from app.ai.factory import is_configured
from app.api.deps import require_book
from app.core.database import get_db
from app.repositories import books as book_repo
from app.schemas.common import ok
from app.services import mindmap_service

router = APIRouter(prefix="/api/books", tags=["mindmap"])


class MindmapIn(BaseModel):
    chapter_id: int | None = None
    selection: str | None = None
    focus: str | None = None


@router.post("/{book_id}/mindmap")
def generate_mindmap(book_id: int, body: MindmapIn, db: Session = Depends(get_db)):
    """生成脑图：以当前章节（可叠加选中段落/关注重点）为输入，返回 ECharts 树数据与 Markdown 大纲。"""
    book = require_book(db, book_id)
    if not is_configured(db):
        raise HTTPException(status_code=400, detail="未配置 AI API Key，请先在设置页填写")
    chapters = book_repo.list_chapters(db, book_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="本书没有可解析的章节")
    chapter = next((c for c in chapters if c.id == body.chapter_id), None)
    if body.chapter_id is not None and chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter is None:
        chapter = chapters[0]
    try:
        data = mindmap_service.generate_mindmap(
            db, book, chapter, body.selection or "", body.focus or ""
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ok(data)
