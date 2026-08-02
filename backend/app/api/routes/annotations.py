"""页图涂鸦 API：按「书 → 页」读写画板标注（annotations/page_XXX.json）。

涂鸦元素 JSON 约定（需求 3.5 / 技术栈规范 §4.7）：
- stroke：{type:'stroke', tool:'pen'|'highlight', color, line_width, points:[[x,y],...], note?, note_meta?}
- text：{type:'text', text, color, font_size, x, y}
撤销栈仅前端会话内维护，本接口只保存最终元素列表，不保存历史版本。
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.schemas.common import ok

router = APIRouter(prefix="/api/books", tags=["annotations"])

MAX_ELEMENTS = 2000


def _annotations_dir(book) -> Path:
    return Path(book.file_path).parent / "annotations"


def _annotations_path(book, page_index: int) -> Path:
    return _annotations_dir(book) / f"page_{page_index:03d}.json"


def _read_elements(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        return []
    return []


class AnnotationIn(BaseModel):
    page_index: int = Field(ge=1)
    elements: list[dict] = []


@router.get("/{book_id}/annotations")
def get_page_annotations(book_id: int, page_index: int, db: Session = Depends(get_db)):
    """读取指定页涂鸦元素（无标注返回空数组）。"""
    book = require_book(db, book_id)
    path = _annotations_path(book, page_index)
    return ok(_read_elements(path))


@router.put("/{book_id}/annotations")
def save_page_annotations(book_id: int, body: AnnotationIn, db: Session = Depends(get_db)):
    """整页保存涂鸦元素（覆盖式写文件）；随书删除时目录一并清理。"""
    book = require_book(db, book_id)
    if len(body.elements) > MAX_ELEMENTS:
        raise HTTPException(status_code=400, detail=f"单页涂鸦元素过多（上限 {MAX_ELEMENTS}）")
    path = _annotations_path(book, body.page_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body.elements, ensure_ascii=False), encoding="utf-8")
    return ok(len(body.elements), "已保存")
