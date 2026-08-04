"""LLM 结果缓存服务（性能优化 §7 决策 5）：内容寻址 + TTL + 容量上限。

- 命中：TTL 内（expires_at > now）返回缓存内容；过期行顺带清理；
- 写入：超容量上限（llm_cache_max_entries > 0）时删除最旧条目；0=关闭缓存；
- 清理：clear_llm_cache(db, book_id=None) 删除指定书/全部缓存（删除书籍时级联）。
"""
import hashlib
import json
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utcnow
from app.models.llm_cache import LlmCache


def cache_key(payload: dict) -> str:
    """输入指纹：规范化 JSON（排序键、紧凑序列化）后的 sha256 前 16 位。"""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def chapter_fingerprint(chapter) -> str:
    """章节内容指纹：content_text 的 sha256 前 16 位（长文本不进 key，仅存摘要）。"""
    return hashlib.sha256((chapter.content_text or "").encode("utf-8")).hexdigest()[:16]


def get_llm_cache(db: Session, book_id: int, kind: str, key: str) -> dict | None:
    """命中返回缓存内容 dict；未命中/过期返回 None（过期顺带删除该行）。"""
    if not settings.llm_cache_max_entries:
        return None
    row = db.scalar(
        select(LlmCache).where(
            LlmCache.book_id == book_id,
            LlmCache.kind == kind,
            LlmCache.input_hash == key,
        )
    )
    if row is None:
        return None
    if row.expires_at and row.expires_at <= utcnow():
        db.delete(row)
        db.commit()
        return None
    try:
        content = json.loads(row.content_json or "{}")
    except (ValueError, TypeError):
        return None
    return content if isinstance(content, dict) else None


def set_llm_cache(db: Session, book_id: int, kind: str, key: str, content: dict) -> None:
    """写入/刷新缓存条目；超容量上限时删除最旧条目（容量统计含全部 kind）。"""
    if not settings.llm_cache_max_entries:
        return
    row = db.scalar(
        select(LlmCache).where(
            LlmCache.book_id == book_id,
            LlmCache.kind == kind,
            LlmCache.input_hash == key,
        )
    )
    if row is None:
        row = LlmCache(book_id=book_id, kind=kind, input_hash=key)
        db.add(row)
    row.content_json = json.dumps(content, ensure_ascii=False)
    row.created_at = utcnow()
    row.expires_at = utcnow() + timedelta(days=settings.llm_cache_ttl_days)
    db.commit()
    _evict_oldest(db)


def _evict_oldest(db: Session) -> None:
    limit = settings.llm_cache_max_entries
    if not limit or limit <= 0:
        return
    ids = list(
        db.scalars(
            select(LlmCache.id).order_by(LlmCache.created_at.desc(), LlmCache.id.desc()).offset(limit).limit(1000)
        )
    )
    if ids:
        db.execute(delete(LlmCache).where(LlmCache.id.in_(ids)))
        db.commit()


def clear_llm_cache(db: Session, book_id: int | None = None) -> int:
    """清空指定书（None=全部）的 LLM 缓存，返回删除条数。"""
    stmt = delete(LlmCache)
    if book_id is not None:
        stmt = stmt.where(LlmCache.book_id == book_id)
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0