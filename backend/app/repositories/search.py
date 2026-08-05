"""全书搜索仓储：FTS5 MATCH 与 LIKE 回退查询（原生 SQL 收敛于此，服务层只做拆词与组装）。

对应审查 P0-1（services 直拼 SQL 下沉）：`search_service.py` 不再出现原生 SQL 文本。
"""
from sqlalchemy import text
from sqlalchemy.orm import Session


def like_search(db: Session, keyword: str, limit: int) -> list[dict]:
    """1-2 字符短词回退：LIKE 扫描章节标题/正文，返回含 content_text 的原始行。"""
    pattern = f"%{keyword}%"
    rows = db.execute(
        text(
            "SELECT c.book_id, b.title, c.id AS chapter_id, c.\"index\" AS chapter_index, "
            "c.title AS chapter_title, c.content_text "
            "FROM chapters c JOIN books b ON b.id = c.book_id "
            "WHERE c.title LIKE :p OR c.content_text LIKE :p LIMIT :limit"
        ),
        {"p": pattern, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def fts_search(db: Session, query: str, limit: int) -> list[dict]:
    """trigram FTS5 MATCH 查询，按 bm25 相关度排序，返回带 snippet 的章节级命中。"""
    rows = db.execute(
        text(
            "SELECT f.book_id, b.title, f.chapter_id, c.\"index\" AS chapter_index, "
            "c.title AS chapter_title, snippet(fts_chapters, 3, '‹', '›', '…', 30) AS snippet "
            "FROM fts_chapters f "
            "JOIN books b ON b.id = f.book_id "
            "JOIN chapters c ON c.id = f.chapter_id "
            "WHERE fts_chapters MATCH :q "
            "ORDER BY bm25(fts_chapters) "
            "LIMIT :limit"
        ),
        {"q": query, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]