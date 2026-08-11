"""阅读建议与复习提醒基础版（M9，需求 3.4.6 增强项）。

本地规则/统计驱动（可复现、零成本）：阅读节奏建议、薄弱概念补强（「不理解」标记聚合）、
复习提醒（最近归档书按间隔）、习惯统计；后续可叠加 LLM 生成个性化建议与间隔重复参数。
"""
from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.activity import ChatMessage, Note
from app.models.book import Book, Chapter
from app.services.graph.keywords import extract_keywords
from app.services.profile_learning import get_thresholds
from app.services.profile_service import get_all_profiles

# 归档后 ≥1 天建议复习（初值，后续按用户复习频率学习调整）
REVIEW_AFTER_DAYS = 1
WEAK_TOP_N = 3


def generate_recommendations(db: Session) -> dict:
    """生成阅读建议：{stats, weak_concepts, review, rhythm}。"""
    profiles = get_all_profiles(db)
    warm = profiles["warm"] or {}
    cold = profiles["cold"] or {}

    stats = {
        "archived_books": int(warm.get("archived_count", 0)),
        "notes": db.query(Note).count(),
        "questions": db.query(Note).filter(Note.note_type == "不理解").count(),
        "chat_messages": db.query(ChatMessage).count(),
        "read_chapters": db.query(Chapter).filter(Chapter.read_flag.is_(True)).count(),
        "books_total": db.query(Book).count(),
    }

    review_days = int(get_thresholds(db)["review_days"])
    return {
        "stats": stats,
        "weak_concepts": _weak_concepts(db),
        "review": _review_reminders(warm, review_days),
        "rhythm": _rhythm_advice(stats, cold),
    }


def _weak_concepts(db: Session) -> list[dict]:
    """薄弱概念：用户标记「不理解」的内容聚合关键词，取出现次数最多前 N 个。"""
    counter: Counter = Counter()
    for n in db.query(Note).filter(Note.note_type == "不理解").all():
        for w in extract_keywords(f"{n.quote_text or ''} {n.note_text or ''}", 10):
            counter[w] += 1
    return [{"concept": w, "count": c} for w, c in counter.most_common(WEAK_TOP_N)]


def _review_reminders(warm: dict, review_days: int = REVIEW_AFTER_DAYS) -> list[dict]:
    """复习提醒：最近归档书按间隔，超过 review_days 天标为到期（默认 1 天，按用户习惯学习）。"""
    now = utcnow()
    out: list[dict] = []
    for r in warm.get("recent_books") or []:
        try:
            at = datetime.fromisoformat(str(r.get("archived_at", "")))
        except ValueError:
            continue
        days = (now - at).days
        out.append(
            {
                "book_id": r.get("book_id"),
                "title": r.get("title"),
                "days_ago": max(days, 0),
                "due": days >= review_days,
            }
        )
    return out


def _rhythm_advice(stats: dict, cold: dict) -> dict:
    """阅读节奏建议（本地规则初值）。"""
    archived = int(stats["archived_books"])
    if archived == 0:
        tip = "完成第一本书的归档，将建立暖画像并开始个性化建议"
        level = "start"
    elif archived < 3:
        tip = "保持阅读节奏，归档 3 本后进入暖→冷沉淀阶段"
        level = "building"
    else:
        prefs = cold.get("domain_preferences") or {}
        top = sorted(prefs, key=lambda k: -prefs[k])[:3]
        tip = f"已稳定沉淀 {archived} 本书，可尝试向「{'、'.join(top) or '相关'}」领域扩展" if top else f"已稳定沉淀 {archived} 本书"
        level = "stable"
    return {"level": level, "archived_books": archived, "tip": tip}
