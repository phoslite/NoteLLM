"""页图涂鸦 API：按「书 → 页」读写画板标注（annotations/page_XXX.json）。

涂鸦元素 JSON 约定（需求 3.5 / 技术栈规范 §4.7）：
- stroke：{type:'stroke', tool:'pen'|'highlight', color, line_width, points:[[x,y],...], note?, note_meta?}
- text：{type:'text', text, color, font_size, x, y}
撤销栈仅前端会话内维护，本接口只保存最终元素列表，不保存历史版本。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.schemas.common import ok
from app.services.annotation_service import read_page_annotations
from app.services.annotation_service import save_page_annotations as persist_page_annotations

router = APIRouter(prefix="/api/books", tags=["annotations"])


class AnnotationIn(BaseModel):
    page_index: int = Field(ge=1)
    elements: list[dict] = []


@router.get("/{book_id}/annotations")
def get_page_annotations(book_id: int, page_index: int, db: Session = Depends(get_db)):
    """读取指定页涂鸦元素（无标注返回空数组）。"""
    book = require_book(db, book_id)
    return ok(read_page_annotations(book, page_index))


@router.put("/{book_id}/annotations")
def save_page_annotations(book_id: int, body: AnnotationIn, db: Session = Depends(get_db)):
    """整页保存涂鸦元素（覆盖式写文件）；随书删除时目录一并清理。"""
    book = require_book(db, book_id)
    if (book.page_count or 0) > 0 and body.page_index > book.page_count:
        raise HTTPException(status_code=400, detail=f"页号越界：{body.page_index} > {book.page_count}")
    try:
        count = persist_page_annotations(book, body.page_index, body.elements)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(count, "已保存")
