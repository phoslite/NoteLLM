"""知识图谱 API（M8）：跨书谱系图 + 书内知识图谱 + 重建 + 关联人工反馈 + 联动沉淀。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.models.graph import BookRelation
from app.repositories.graph import count_books, count_relations
from app.schemas.common import ok
from app.services.graph.cross_book import global_graph_payload
from app.services.graph.cross_book import knowledge_appears_in as cross_book_knowledge_appears_in
from app.services.graph.intra_book import intra_graph_payload
from app.services.graph.tasks import (
    build_intra_task,
    lazy_global_build,
    rebuild_graph_task,
    sync_assets_task,
)
from app.services.graph_sync import apply_relation_feedback
from app.tasks import find_active, submit

router = APIRouter(prefix="/api/graph", tags=["graph"])


class FeedbackIn(BaseModel):
    action: str  # 确认 / 忽略 / 修改
    strength: float | None = None  # 修改时传入 0~100


def _submit_graph_task(task_type: str, name: str, fn, related_id: int | None = None) -> str:
    """提交图谱类后台任务；同类型同目标进行中时复用已有任务（幂等，避免重复计算）。"""
    existing = find_active(task_type, related_id=related_id, name_prefix=name)
    if existing:
        return existing
    return submit(task_type, name, fn, related_id=related_id)


@router.get("/books")
def get_global_graph(db: Session = Depends(get_db)):
    """书籍级谱系图：聚类 + 节点 + 关联边。

    懒构建（决策 35 后台化）：尚无关联且书架非空时提交构建任务，返回
    {building: true, task_id}，前端轮询任务完成后重新拉取。
    """

    if count_relations(db) == 0 and count_books(db) > 0:
        task_id = _submit_graph_task("text", "graph-global-build", lazy_global_build)
        return ok({"building": True, "task_id": task_id}, "图谱构建中，稍后自动刷新")
    return ok(global_graph_payload(db))


@router.get("/books/{book_id}")
def get_intra_book_graph(book_id: int, db: Session = Depends(get_db)):
    """书内知识图谱：章节级/重要段落级/用户标记级知识点与关系（懒构建，后台化）。"""
    book = require_book(db, book_id)
    if not book.graph_built:
        task_id = _submit_graph_task("text", "graph-intra-build", lambda: build_intra_task(book_id), related_id=book_id)
        return ok({"building": True, "task_id": task_id}, "书内图谱构建中，稍后自动刷新")
    return ok(intra_graph_payload(db, book))


@router.post("/rebuild")
def rebuild_graph(db: Session = Depends(get_db)):
    """重建全部图谱（跨书关联 + 全部书内知识图谱），并补本地联动存根（后台任务）。"""
    task_id = _submit_graph_task("text", "graph-rebuild", rebuild_graph_task)
    return ok({"task_id": task_id}, "已提交图谱重建任务")


@router.get("/knowledge/{kp_id}/appears-in")
def knowledge_appears_in(kp_id: int, db: Session = Depends(get_db)):
    """跨书检索（需求 3.4.7）：该知识点还出现在哪些书（其他书知识点命中 + RAG key_points 命中）。"""

    data = cross_book_knowledge_appears_in(db, kp_id)
    if not data:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return ok(data)


@router.post("/sync")
def sync_graph_assets(db: Session = Depends(get_db)):
    """图谱联动沉淀（需求 3.4.7/3.4.9）：受影响书籍 RAG/Skill 增量增改（后台任务）。

    - 始终补本地 RAG 存根（linked_books / domain_terms，无 AI 也可执行）；
    - 已配置文本 AI 时，对强度 ≥ 50 且未忽略的关联执行 LLM 增量增改
      （RAG 补跨书条目、Skill 融合新方法，version+1，失败回滚不阻塞）。
    """

    task_id = _submit_graph_task(
        "text",
        "graph-sync",
        lambda: sync_assets_task(),
    )
    return ok({"task_id": task_id}, "已提交图谱资产联动任务")


@router.post("/books/{book_id}/rebuild")
def rebuild_book_graph(book_id: int, db: Session = Depends(get_db)):
    """重建单书内部知识图谱（后台任务）。"""
    require_book(db, book_id)
    task_id = _submit_graph_task("text", "graph-book-rebuild", lambda: build_intra_task(book_id), related_id=book_id)
    return ok({"task_id": task_id}, "已提交本书知识图谱重建任务")


@router.post("/relations/{relation_id}/feedback")
def relation_feedback(relation_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    """人工反馈：确认/忽略/修改强度，结果回写作为后续计算的修正层；确认/修改联动补 RAG 存根。"""
    rel = db.get(BookRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=404, detail="关联不存在")
    try:
        apply_relation_feedback(db, rel, body.action, body.strength)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"id": rel.id, "user_feedback": rel.user_feedback, "strength": rel.strength})
