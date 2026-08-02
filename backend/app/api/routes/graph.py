"""知识图谱 API（M8）：跨书谱系图 + 书内知识图谱 + 重建 + 关联人工反馈 + 联动沉淀。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_book
from app.core.database import get_db
from app.models.graph import BookRelation
from app.schemas.common import ok
from app.services.graph.cross_book import (
    compute_cross_book_graph,
    global_graph_payload,
    rebuild_all_graph,
)
from app.services.graph.intra_book import build_intra_book_graph, intra_graph_payload

router = APIRouter(prefix="/api/graph", tags=["graph"])


class FeedbackIn(BaseModel):
    action: str  # 确认 / 忽略 / 修改
    strength: float | None = None  # 修改时传入 0~100


@router.get("/books")
def get_global_graph(db: Session = Depends(get_db)):
    """书籍级谱系图：聚类 + 节点 + 关联边（懒构建：尚无关联时自动计算并触发本地联动存根）。"""
    from app.models.book import Book

    if db.query(BookRelation).count() == 0 and db.query(Book).count() > 0:
        compute_cross_book_graph(db)
        from app.services.graph_sync import link_graph_assets

        link_graph_assets(db)
    return ok(global_graph_payload(db))


@router.get("/books/{book_id}")
def get_intra_book_graph(book_id: int, db: Session = Depends(get_db)):
    """书内知识图谱：章节级/重要段落级/用户标记级知识点与关系（懒构建）。"""
    book = require_book(db, book_id)
    if not book.graph_built:
        build_intra_book_graph(db, book)
    return ok(intra_graph_payload(db, book))


@router.post("/rebuild")
def rebuild_graph(db: Session = Depends(get_db)):
    """重建全部图谱（跨书关联 + 全部书内知识图谱），并补本地联动存根。"""
    return ok(rebuild_all_graph(db), "图谱已重建")


@router.get("/knowledge/{kp_id}/appears-in")
def knowledge_appears_in(kp_id: int, db: Session = Depends(get_db)):
    """跨书检索（需求 3.4.7）：该知识点还出现在哪些书（其他书知识点命中 + RAG key_points 命中）。"""
    from app.services.graph.cross_book import knowledge_appears_in as _service

    data = _service(db, kp_id)
    if not data:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return ok(data)


@router.post("/sync")
def sync_graph_assets(db: Session = Depends(get_db)):
    """图谱联动沉淀（需求 3.4.7/3.4.9）：受影响书籍 RAG/Skill 增量增改。

    - 始终补本地 RAG 存根（linked_books / domain_terms，无 AI 也可执行）；
    - 已配置文本 AI 时，对强度 ≥ 50 且未忽略的关联执行 LLM 增量增改
      （RAG 补跨书条目、Skill 融合新方法，version+1，失败回滚不阻塞）。
    """
    from app.services.graph_sync import link_domain_terms, sync_assets_for_relations

    merged = sync_assets_for_relations(db)
    terms = link_domain_terms(db)
    return ok(
        {**merged, "domain_terms": terms},
        "图谱资产联动完成（本地存根 + LLM 增量增改）",
    )


@router.post("/books/{book_id}/rebuild")
def rebuild_book_graph(book_id: int, db: Session = Depends(get_db)):
    """重建单书内部知识图谱。"""
    book = require_book(db, book_id)
    return ok(build_intra_book_graph(db, book), "本书知识图谱已重建")


@router.post("/relations/{relation_id}/feedback")
def relation_feedback(relation_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    """人工反馈：确认/忽略/修改强度，结果回写作为后续计算的修正层；确认/修改联动补 RAG 存根。"""
    rel = db.get(BookRelation, relation_id)
    if not rel:
        raise HTTPException(status_code=404, detail="关联不存在")
    if body.action == "确认":
        rel.user_feedback = "确认"
    elif body.action == "忽略":
        rel.user_feedback = "忽略"
    elif body.action == "修改":
        if body.strength is None:
            raise HTTPException(status_code=400, detail="修改强度需传入 strength")
        rel.user_feedback = "修改"
        rel.strength = max(0.0, min(100.0, float(body.strength)))
    else:
        raise HTTPException(status_code=400, detail="action 仅支持 确认/忽略/修改")
    db.commit()
    if body.action in ("确认", "修改"):
        from app.services.graph_sync import link_relation_stubs

        try:
            link_relation_stubs(db, rel)
        except Exception:
            db.rollback()
    return ok({"id": rel.id, "user_feedback": rel.user_feedback, "strength": rel.strength})