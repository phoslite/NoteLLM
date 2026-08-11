"""PDF 页缓存 API（M7）：缓存状态/读取、重新提取本页、重建全书页缓存（后台任务）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.repositories.settings import vision_configured
from app.schemas.common import ok
from app.services.vision_extract import (
    ensure_page_cache,
    extract_book_pages_task,
    read_page_cache,
)
from app.tasks import VISION_TASK_PREFIX, get_status, submit_dedupe

router = APIRouter(prefix="/api/books", tags=["vision"])


class RebuildIn(BaseModel):
    force: bool = False


@router.get("/{book_id}/page-text/status")
def get_page_text_status(book_id: int, db: Session = Depends(get_db)):
    """查看本书页缓存覆盖情况（供前端展示「已缓存 x/共 y 页」）。"""
    book = require_book(db, book_id)
    total = book.page_count or 0
    cached = sum(1 for i in range(1, total + 1) if read_page_cache(book, i))
    return ok({"total": total, "cached": cached})


@router.post("/{book_id}/page-text/rebuild")
def rebuild_page_text(book_id: int, body: RebuildIn | None = None, db: Session = Depends(get_db)):
    """重建本书页缓存：后台任务补缺失页（force=False）或全部重提取（force=True），返回 task_id。"""

    require_book(db, book_id)
    if not vision_configured(db):
        raise HTTPException(status_code=400, detail="未配置多模态视觉 API，请先在设置页填写")
    force = bool(body.force) if body else False
    # 终审 §6.9：force 纳入防重名——进行中的普通重建不吞并显式全量重提取；
    # B-I2：非 force 重建与导入预提取共用 VISION_TASK_PREFIX（同书同时只跑一路全书提取）
    task_name = "vision-rebuild-force" if force else "vision-rebuild"
    task_id, created = submit_dedupe(
        "vision", task_name,
        lambda: extract_book_pages_task(book_id, force=force),
        related_id=book_id,
        name_prefix=VISION_TASK_PREFIX if not force else task_name,
    )
    msg = ("已提交强制重建任务" if force else "已提交页图提取任务") if created else ("已有强制重建任务进行中，直接复用" if force else "已有页图提取任务进行中（含导入预提取），直接复用")
    return ok({"task_id": task_id, "msg": msg})

@router.get("/{book_id}/page-text/{page_index}")
def get_page_text(book_id: int, page_index: int, db: Session = Depends(get_db)):
    """读取指定页缓存文本（未缓存返回 text=None）。"""
    book = require_book(db, book_id)
    if not 1 <= page_index <= (book.page_count or 0):
        raise HTTPException(status_code=404, detail="页号越界")
    text = read_page_cache(book, page_index)
    return ok({"page_index": page_index, "cached": bool(text), "text": text})


@router.post("/{book_id}/page-text/{page_index}")
def reextract_page(book_id: int, page_index: int, db: Session = Depends(get_db)):
    """重新提取本页（强制覆盖缓存）；需已配置多模态且隐私开关开启。"""

    book = require_book(db, book_id)
    if not 1 <= page_index <= (book.page_count or 0):
        raise HTTPException(status_code=404, detail="页号越界")
    if not vision_configured(db):
        raise HTTPException(status_code=400, detail="未配置多模态视觉 API，请先在设置页填写")
    try:
        text = ensure_page_cache(db, book, page_index, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 提取失败透出原因
        raise HTTPException(status_code=502, detail=f"提取失败: {exc}") from exc
    return ok({"page_index": page_index, "cached": True, "text": text})


@router.get("/{book_id}/page-text/tasks/{task_id}")
def get_page_text_task(task_id: str, db: Session = Depends(get_db)):
    """查询页缓存任务状态。"""

    return ok(get_status(task_id))
