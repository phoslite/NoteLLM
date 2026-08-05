"""图谱域后台任务包装（审查 A2 收敛）：独立会话 + 进度包装统一在此层。

覆盖 5 处此前散落在路由层的「独立会话 + 进度」重复模式：
- graph 路由：全局懒构建 / 单书构建 / 全量重建 / 图谱资产联动；
- assets 路由：RAG/Skill 后台总结。
任务内必须用独立 SessionLocal（决策 35 + 审查 A-1：勿复用请求级 db）；
进度统一经 app.tasks.update_progress 上报。路由层只负责提交任务与幂等。
"""
from app.core.database import SessionLocal
from app.models.book import Book
from app.services.graph.cross_book import compute_cross_book_graph, rebuild_all_graph
from app.services.graph.intra_book import build_intra_book_graph
from app.services.graph_sync import link_domain_terms, link_graph_assets, sync_assets_for_relations
from app.services.rag_service import generate_rag_skill
from app.tasks import update_progress


def lazy_global_build() -> dict:
    """懒构建后台任务：跨书关联计算（含 LLM 打分）+ 本地联动存根，独立会话执行。"""
    with SessionLocal() as session:
        update_progress(20, "计算跨书关联")
        compute_cross_book_graph(session)
        update_progress(80, "补本地联动存根")
        link_graph_assets(session)
        update_progress(100, "图谱构建完成")
    return {"built": True}


def build_intra_task(book_id: int) -> dict:
    """单书知识图谱构建后台任务：独立会话；书不存在返回错误而非 HTTP 异常。"""
    with SessionLocal() as session:
        book = session.get(Book, book_id)
        if not book:
            return {"error": "书籍不存在"}
        update_progress(10, "构建书内知识图谱")
        result = build_intra_book_graph(session, book)
        update_progress(100, "构建完成")
        return result


def rebuild_graph_task() -> dict:
    """全量重建后台任务：书内图 20% / 跨书 50% / 联动 30% 进度权重（决策 35）。"""
    with SessionLocal() as session:
        return rebuild_all_graph(session, on_progress=lambda p, s: update_progress(p, s))


def sync_assets_task() -> dict:
    """图谱资产联动后台任务：本地存根 + LLM 增量增改，独立会话执行。"""
    with SessionLocal() as session:
        update_progress(20, "补本地联动存根")
        merged = sync_assets_for_relations(session)
        update_progress(70, "RAG 术语补水")
        terms = link_domain_terms(session)
        update_progress(100, "联动完成")
        return {**merged, "domain_terms": terms}


def run_summarize_task(book_id: int) -> dict:
    """后台总结任务：独立会话 + finally 关闭（审查 A-1：会话泄漏修复）。"""
    db = SessionLocal()
    try:
        return generate_rag_skill(db, book_id=book_id)
    finally:
        db.close()
