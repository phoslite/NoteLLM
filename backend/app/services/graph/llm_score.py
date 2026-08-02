"""跨书关联 LLM 打分与方向/原因增强（M8 待办落地）。

在关键词共现 + 笔记加权的基础上，对候选书对做**有界** LLM 打分：
- 每次重建/增量最多 MAX_LLM_PAIRS 对（按关键词分降序截断），控制数百本书时的成本；
- 未配置 AI / 调用失败 / 解析失败一律回退（返回 None，调用方保留关键词分）；
- LLM 结果为 {strength, from_book, direction, relation_type, reasons}，由 cross_book
  合并进 BookRelation（强度取 max，方向/类型/原因/源头以 LLM 为准）。
"""
import json

from sqlalchemy.orm import Session

from app.ai.factory import build_client, is_configured
from app.ai.parsing import parse_llm_json
from app.ai.prompts.graph_edge import SYSTEM_PROMPT, build_edge_user_prompt
from app.models.book import Book

# 每次重建/增量 LLM 打分对数的上限（数百本书时控制成本与耗时）
MAX_LLM_PAIRS = 40
DIRECTIONS = {"承接", "发展", "批判", "无"}
RELATION_TYPES = {"理论传承", "概念共现", "主题相似", "应用扩展"}
MAX_REASONS = 6


def _keywords_preview(ka: dict[str, float], kb: dict[str, float], top_n: int = 12) -> list[str]:
    """两书关键词合并预览（权重求和降序取 top_n），供 LLM 判断。"""
    merged: dict[str, float] = {}
    for source in (ka, kb):
        for k, v in source.items():
            merged[k] = merged.get(k, 0) + v
    return [k for k, _ in sorted(merged.items(), key=lambda kv: -kv[1])[:top_n]]


def score_pair_llm(
    db: Session, a: Book, b: Book, ka: dict[str, float], kb: dict[str, float]
) -> dict | None:
    """对一对书调用 LLM 打分；未配置/失败/非法输出返回 None（调用方回退关键词分）。"""
    if not is_configured(db):
        return None
    try:
        client = build_client(db)
        reply = client.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_edge_user_prompt(a.title or "", b.title or "", _keywords_preview(ka, kb)),
                },
            ]
        )
        data = parse_llm_json(reply)
    except Exception:
        return None

    try:
        strength = max(0.0, min(100.0, float(data.get("strength"))))
    except (TypeError, ValueError):
        strength = None
    from_book = data.get("from_book")
    if from_book not in ("A", "B", None):
        from_book = None
    direction = data.get("direction") or "无"
    if from_book is None:
        direction = "无"
    elif direction not in DIRECTIONS:
        direction = "承接"
    relation_type = data.get("relation_type") or "概念共现"
    if relation_type not in RELATION_TYPES:
        relation_type = "概念共现"
    reasons = data.get("reasons")
    reasons = [str(r).strip() for r in reasons if str(r).strip()][:MAX_REASONS] if isinstance(reasons, list) else []
    return {
        "strength": strength,
        "from_book": from_book,
        "direction": direction,
        "relation_type": relation_type,
        "reasons": reasons,
    }


def enrich_pairs_with_llm(
    db: Session,
    books_by_id: dict[int, Book],
    keywords: dict[int, dict[str, float]],
    candidates: list[tuple[int, int, float]],
) -> dict[tuple[int, int], dict]:
    """对候选书对做有界 LLM 打分，返回 {pair_key: llm_result}（失败对不返回）。

    candidates: [(a_id, b_id, 关键词分)]，按关键词分降序截断到 MAX_LLM_PAIRS。
    """
    if not is_configured(db) or not candidates:
        return {}
    from app.services.graph.cross_book import pair_key

    results: dict[tuple[int, int], dict] = {}
    for a_id, b_id, _kw in sorted(candidates, key=lambda x: -x[2])[:MAX_LLM_PAIRS]:
        a = books_by_id.get(a_id)
        b = books_by_id.get(b_id)
        if not a or not b:
            continue
        res = score_pair_llm(db, a, b, keywords.get(a_id, {}), keywords.get(b_id, {}))
        if res:
            results[pair_key(a_id, b_id)] = res
    return results


def apply_llm_result(rel, a_id: int, b_id: int, result: dict) -> None:
    """把 LLM 结果合并进 BookRelation：强度取 max，方向/类型/原因/源头以 LLM 为准。"""
    if result.get("strength") is not None:
        rel.strength = round(max(float(rel.strength or 0.0), float(result["strength"])), 1)
    rel.direction = result.get("direction") or "无"
    rel.relation_type = result.get("relation_type") or rel.relation_type
    if result.get("reasons"):
        rel.reasons_json = json.dumps(result["reasons"], ensure_ascii=False)
    from_book = result.get("from_book")
    if from_book == "A":
        rel.from_book_id = a_id
    elif from_book == "B":
        rel.from_book_id = b_id
    else:
        rel.from_book_id = None