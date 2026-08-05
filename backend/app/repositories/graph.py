"""graph 域仓储（审查 P0-8 第一步：只读查询下沉）。

收敛 cross_book / clustering / graph_sync / intra_book / graph 路由等共享查询，
服务层不再直接拼 SQLAlchemy 查询；写入路径（delete/add/update）在测试全绿后第二步搬移。
"""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.activity import Note
from app.models.asset import BookAsset
from app.models.book import Book, Folder
from app.models.graph import BookRelation, KnowledgePoint, KpRelation


def list_books(db: Session) -> list[Book]:
    """全部书籍（id 升序，图谱域默认遍历顺序）。"""
    return db.query(Book).order_by(Book.id).all()


def list_books_except(db: Session, book_id: int) -> list[Book]:
    """排除指定书后的其余书籍（id 升序）。"""
    return db.query(Book).filter(Book.id != book_id).order_by(Book.id).all()


def list_books_by_ids(db: Session, book_ids: list[int]) -> list[Book]:
    """按 id 集合取书（命中书籍回填用）。"""
    return db.query(Book).filter(Book.id.in_(list(book_ids))).all()


def list_post_classified_books(db: Session, exclude_book_id: int | None = None) -> list[Book]:
    """已 post-classify 且有簇名的书（簇合并/重命名与 post 归类共用；可排除指定书）。"""
    query = db.query(Book).filter(Book.classify_source == "post", Book.cluster_name.isnot(None))
    if exclude_book_id is not None:
        query = query.filter(Book.id != exclude_book_id)
    return query.all()


def count_books(db: Session) -> int:
    """书籍总数（懒构建判定用）。"""
    return db.query(Book).count()


def list_relations(db: Session) -> list[BookRelation]:
    """全部书籍关联（id 升序）。"""
    return db.query(BookRelation).order_by(BookRelation.id).all()


def list_active_relations(
    db: Session,
    relation_ids: list[int] | None = None,
    *,
    book_id: int | None = None,
    limit: int | None = None,
) -> list[BookRelation]:
    """未忽略的书籍关联（联动存根 / LLM 联动共用）；relation_ids 为空时返回全部。

    book_id 非空时仅返回与该书相关的关联（按 strength 降序，谱系关联降级挑选用）；
    limit 非空时截断数量。
    """
    query = db.query(BookRelation).filter(
        or_(BookRelation.user_feedback.is_(None), BookRelation.user_feedback != "忽略")
    )
    if relation_ids is not None:
        query = query.filter(BookRelation.id.in_(relation_ids))
    if book_id is not None:
        query = query.filter(
            or_(BookRelation.book_a_id == book_id, BookRelation.book_b_id == book_id)
        ).order_by(BookRelation.strength.desc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_relations(db: Session) -> int:
    """书籍关联总数（懒构建 / 重建统计用）。"""
    return db.query(BookRelation).count()


def count_knowledge_points(db: Session) -> int:
    """书内知识点总数（重建统计用）。"""
    return db.query(KnowledgePoint).count()


def list_notes(db: Session, book_id: int | None = None) -> list[Note]:
    """笔记：全量或按书（id 升序）。"""
    query = db.query(Note)
    if book_id is not None:
        query = query.filter(Note.book_id == book_id)
    return query.order_by(Note.id).all()


def list_folders_by_ids(db: Session, folder_ids: set[int]) -> list[Folder]:
    """按 id 集合取文件夹（聚类签名 / 文件夹名映射用）。"""
    return db.query(Folder).filter(Folder.id.in_(folder_ids)).all()


def asset_classify_versions(db: Session, book_ids: list[int]) -> dict[int, int]:
    """每书当前资产最大版本（post-classify 失效懒校验用）。"""
    if not book_ids:
        return {}
    rows = (
        db.query(BookAsset.book_id, func.max(BookAsset.version))
        .filter(BookAsset.book_id.in_(book_ids))
        .group_by(BookAsset.book_id)
        .all()
    )
    return dict(rows)


def list_kp_ids_by_book(db: Session, book_id: int) -> list[int]:
    """单书知识点 id 列表（重建前清理用）。"""
    return [k.id for k in db.query(KnowledgePoint.id).filter(KnowledgePoint.book_id == book_id).all()]


def list_knowledge_points(
    db: Session,
    book_id: int | None = None,
    *,
    level: str | None = None,
    exclude_book_id: int | None = None,
) -> list[KnowledgePoint]:
    """知识点：按书 / 层级过滤，可排除来源书（跨书检索用；id 升序）。"""
    query = db.query(KnowledgePoint)
    if book_id is not None:
        query = query.filter(KnowledgePoint.book_id == book_id)
    if exclude_book_id is not None:
        query = query.filter(KnowledgePoint.book_id != exclude_book_id)
    if level is not None:
        query = query.filter(KnowledgePoint.level == level)
    return query.order_by(KnowledgePoint.id).all()


def list_kp_relations(db: Session, from_kp_ids: list[int]) -> list[KpRelation]:
    """知识点关系：源节点 id 集合内的全部关系（id 升序）。"""
    if not from_kp_ids:
        return []
    return db.query(KpRelation).filter(KpRelation.from_kp_id.in_(from_kp_ids)).order_by(KpRelation.id).all()


def clear_relations(db: Session) -> None:
    """清空全部书籍关联（全量重建前调用）。"""
    db.query(BookRelation).delete()


def clear_book_knowledge_graph(db: Session, book_id: int, old_kp_ids: list[int]) -> None:
    """清空单书既有知识点与关系（书内图谱重建前调用；由调用方负责 flush/commit）。"""
    if old_kp_ids:
        db.query(KpRelation).filter(
            KpRelation.from_kp_id.in_(old_kp_ids) | KpRelation.to_kp_id.in_(old_kp_ids)
        ).delete(synchronize_session=False)
    db.query(KnowledgePoint).filter(KnowledgePoint.book_id == book_id).delete(synchronize_session=False)
