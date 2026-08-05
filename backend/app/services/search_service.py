"""FTS5 全书搜索服务（性能优化 §7 决策 3）：标题 + 正文全文检索，返回章节级命中。

SQL 已下沉 `repositories/search.py`（审查 P0-1），本层只做关键词拆词与结果组装。
"""
import re

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.search import fts_search, like_search

# trigram 分词器查询保留字/特殊字符：分词时剔除，避免查询语法错误
_FTS_SPECIALS = re.compile(r'["*():^~+-<>{}[\]]')


def _fts_query(keyword: str) -> str | None:
    """关键词 → FTS5 MATCH 查询：按空白拆词、去特殊字符，逐词（≥3 字符）OR 连接。

    trigram 分词器对中文/英文均支持 3 字符及以上子串匹配（如「极值问题」命中
    「泛函极值问题」）；过短词会被过滤，由调用方回退 LIKE 扫描。
    """
    words = [w for w in _FTS_SPECIALS.sub(" ", (keyword or "").strip()).split() if len(w) >= 3]
    if not words:
        return None
    return " OR ".join(f'"{w}"' for w in words[:8])


def _like_snippet(content: str, keyword: str, radius: int = 30) -> str:
    """LIKE 命中的简单摘要：取首次命中位置前后各 radius 字符。"""
    pos = content.find(keyword)
    if pos < 0:
        return (content or "")[: radius * 2]
    start = max(0, pos - radius)
    end = min(len(content), pos + len(keyword) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"


def _like_search(db: Session, keyword: str, limit: int) -> list[dict]:
    """1-2 字符短词回退：LIKE 扫描章节标题/正文（本地单用户库量级小，延迟可接受）。"""
    return [
        {
            "book_id": r["book_id"],
            "title": r["title"],
            "chapter_id": r["chapter_id"],
            "chapter_index": r["chapter_index"],
            "chapter_title": r["chapter_title"],
            "snippet": _like_snippet(r["content_text"] or "", keyword),
        }
        for r in like_search(db, keyword, limit)
    ]


def search_books(db: Session, keyword: str, limit: int = 30) -> list[dict]:
    """全书搜索：trigram FTS 命中（title/content，bm25 相关度排序）；短词回退 LIKE。

    返回字段：book_id / title / chapter_id / chapter_index / chapter_title / snippet。
    索引未启用（fts_search_enabled=False）或关键词为空时返回空列表。
    """
    if not settings.fts_search_enabled:
        return []
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    if len(keyword) < 3:
        return _like_search(db, keyword, limit)
    query = _fts_query(keyword)
    if not query:
        return _like_search(db, keyword, limit)
    return fts_search(db, query, limit)