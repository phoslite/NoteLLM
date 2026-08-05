"""RAG/Skill 资产 API：触发总结（后台任务）、任务状态、资产读取与删除。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.repositories.assets import (
    delete_asset,
    delete_asset_item,
    list_assets,
    merge_duplicate_assets,
)
from app.schemas.common import ok
from app.schemas.serializers import asset_to_dict
from app.services.graph.tasks import run_summarize_task
from app.services.rag_service import archive_book_task
from app.tasks import find_active, submit

router = APIRouter(prefix="/api", tags=["assets"])


@router.post("/books/{book_id}/summarize")
def summarize_book(book_id: int, db: Session = Depends(get_db)):
    """把书籍总结为 RAG + Skill 资产；后台任务执行，返回 task_id 供轮询。"""
    require_book(db, book_id)
    existing = find_active("text", related_id=book_id, name_prefix="rag-skill-summarize")
    if existing:  # 审查 C-问题4：幂等防护，防双击重复提交互相覆盖资产
        return ok({"task_id": existing}, "已有进行中的总结任务，直接复用")
    task_id = submit(
        "text", "rag-skill-summarize", lambda: run_summarize_task(book_id=book_id)
    )
    return ok({"task_id": task_id}, "已提交总结任务")


@router.post("/books/{book_id}/archive")
def archive_book(book_id: int, db: Session = Depends(get_db)):
    """M9 读完归档：PDF 先视觉通读全书并缓存 → 文本模型总结 RAG/Skill → 标记读完。

    后台任务执行（archive_book_task），返回 task_id 供轮询；结果含
    {book_id, version, rag, skill} 及 PDF 场景的 page_cache 提取统计。
    """
    require_book(db, book_id)
    existing = find_active("text", related_id=book_id, name_prefix="book-archive")
    if existing:  # 审查 C-问题4：幂等防护，防重复提交归档任务
        return ok({"task_id": existing}, "已有进行中的归档任务，直接复用")
    task_id = submit("text", "book-archive", lambda: archive_book_task(book_id), related_id=book_id)
    return ok({"task_id": task_id}, "已提交归档任务")


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




@router.post("/assets/dedupe")
def dedupe_assets(db: Session = Depends(get_db)):
    """跨书资产去重合并：kind + 内容 hash 相同的整条资产合并为一条主资产。

    返回 {rag, skill} 合并条数；被合并书仍可透明读取共享资产（见资料页「共享 N 本书」）。
    """
    return ok(merge_duplicate_assets(db), "去重合并完成")


@router.delete("/books/{book_id}/asset")
def delete_book_asset(book_id: int, kind: str, db: Session = Depends(get_db)):
    """删除指定 kind（rag / skill）的整条资产；kind 非法时拒绝。"""
    require_book(db, book_id)
    if kind not in {"rag", "skill"}:
        return ok(None, f"未知资产类型：{kind}")
    removed = delete_asset(db, book_id, kind)
    return ok({"deleted": removed}, "已删除" if removed else "资产不存在")


@router.delete("/books/{book_id}/asset/{kind}/{section}/{index}")
def delete_book_asset_item(
    book_id: int, kind: str, section: str, index: int, db: Session = Depends(get_db)
):
    """删除资产内第 index 项（0 基）：rag.key_points / rag.chunks / skill.skills。

    删除后 version + 1（保持「变更即版本递增」约定）；返回删除后的资产内容。
    """
    require_book(db, book_id)
    if kind not in {"rag", "skill"} or section not in {"key_points", "chunks", "skills"}:
        return ok(None, "不支持的删除目标")
    try:
        content = delete_asset_item(db, book_id, kind, section, index)
    except ValueError as exc:
        return ok(None, str(exc))
    return ok({"content": content}, "已删除")