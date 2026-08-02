"""BookAsset 仓储：RAG / Skill 资产读写、内容解析与检索（按书存储，版本递增）。"""
import json
import re

from sqlalchemy.orm import Session

from app.models.asset import BookAsset

RAG_TOP_K = 4


def get_asset(db: Session, book_id: int, kind: str) -> BookAsset | None:
    return db.query(BookAsset).filter(BookAsset.book_id == book_id, BookAsset.kind == kind).first()


def read_asset_content(db: Session, book_id: int, kind: str) -> dict:
    """读取资产内容 dict；不存在或非法 JSON 返回 {}。"""
    asset = get_asset(db, book_id, kind)
    if not asset:
        return {}
    try:
        content = json.loads(asset.content_json or "{}")
    except (ValueError, TypeError):
        return {}
    return content if isinstance(content, dict) else {}


def upsert_asset(db: Session, book_id: int, kind: str, content: dict) -> BookAsset:
    """写入/更新资产；已存在则 version + 1（保留历史约定，见技术栈规范 AI 接入规范）。"""
    asset = get_asset(db, book_id, kind)
    if asset:
        asset.version += 1
    else:
        asset = BookAsset(book_id=book_id, kind=kind, version=1)
        db.add(asset)
    asset.content_json = json.dumps(content, ensure_ascii=False)
    db.commit()
    db.refresh(asset)
    return asset


def list_assets(db: Session, book_id: int) -> list[BookAsset]:
    return db.query(BookAsset).filter(BookAsset.book_id == book_id).order_by(BookAsset.kind).all()


def delete_assets(db: Session, book_id: int) -> None:
    db.query(BookAsset).filter(BookAsset.book_id == book_id).delete()
    db.commit()


def retrieve_rag_chunks(db: Session, book_id: int, question: str, top_k: int = RAG_TOP_K) -> list[dict]:
    """从书籍 RAG 资产中按关键词重叠检索相关片段；无资产/无命中时返回空。"""
    content = read_asset_content(db, book_id, "rag")
    chunks = content.get("chunks") or []
    if not chunks:
        return []
    tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]*", question or ""))
    if not tokens:
        return chunks[:top_k]

    def _score(c: dict) -> int:
        text = str(c.get("text", ""))
        return sum(1 for t in tokens if t in text)

    scored = sorted(chunks, key=_score, reverse=True)
    hits = [c for c in scored if _score(c) > 0][:top_k]
    return hits or chunks[:top_k]


def load_skills(db: Session, book_id: int) -> list[dict]:
    """读取书籍 Skill 资产中的技能列表。"""
    content = read_asset_content(db, book_id, "skill")
    return content.get("skills") or []
