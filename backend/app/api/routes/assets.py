"""RAG/Skill 资产 API：触发总结（后台任务）、任务状态、资产读取。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import SessionLocal, get_db
from app.repositories.assets import list_assets
from app.schemas.common import ok
from app.schemas.serializers import asset_to_dict
from app.services.rag_service import archive_book_task, generate_rag_skill
from app.tasks import get_status, submit

router = APIRouter(prefix="/api", tags=["assets"])


@router.post("/books/{book_id}/summarize")
def summarize_book(book_id: int, db: Session = Depends(get_db)):
    """把书籍总结为 RAG + Skill 资产；后台任务执行，返回 task_id 供轮询。"""
    require_book(db, book_id)
    task_id = submit(
        "rag-skill-summarize", lambda: generate_rag_skill(SessionLocal(), book_id=book_id)
    )
    return ok({"task_id": task_id}, "已提交总结任务")


@router.post("/books/{book_id}/archive")
def archive_book(book_id: int, db: Session = Depends(get_db)):
    """M9 读完归档：PDF 先视觉通读全书并缓存 → 文本模型总结 RAG/Skill → 标记读完。

    后台任务执行（archive_book_task），返回 task_id 供轮询；结果含
    {book_id, version, rag, skill} 及 PDF 场景的 page_cache 提取统计。
    """
    require_book(db, book_id)
    task_id = submit("book-archive", lambda: archive_book_task(book_id))
    return ok({"task_id": task_id}, "已提交归档任务")


@router.get("/tasks/{task_id}")
def task_status(task_id: str):
    """查询后台任务状态：{status, result, error}。"""
    return ok(get_status(task_id))


@router.get("/books/{book_id}/asset")
def book_asset(book_id: int, db: Session = Depends(get_db)):
    """读取书籍的 RAG / Skill 资产。"""
    require_book(db, book_id)
    assets = list_assets(db, book_id)
    data: dict = {"rag": None, "skill": None}
    for asset in assets:
        data[asset.kind] = asset_to_dict(asset)
    data["version"] = max((a.version for a in assets), default=0)
    return ok(data)