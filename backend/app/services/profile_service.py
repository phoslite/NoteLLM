"""三层画像服务（M9）：冷/暖/热画像读写、阅读行为回写、归档迁移与暖记忆联动。

- 热画像（hot）：当前这本书的大部分细节——章节脉络、划线/笔记/「不理解」点、进行中的问题（随阅读实时更新）；
- 暖画像（warm）：近期 1~2 本书的重要内容 + 相关领域书籍的关键内容（recent_books / related_books）；
- 冷画像（cold）：重要但不常调用的长期特征——领域偏好、知识水平、语言风格、长期兴趣。
- 归档迁移（需求 3.4.1）：归档跨越 1 本 → 热画像归档至暖画像；跨 3 本 → 暖画像归档至冷画像；
  > 3 本 → 全部沉淀为冷画像（暖画像只保留最近 1 本）。阈值初值见常量，后续按用户习惯学习调整。
- 暖记忆联动（需求 3.4.1/3.4.9，决策 20 已落地）：归档时按相关度判定函数
  （services/relatedness.py：跨书谱系边强度 + 暖/冷画像术语覆盖率 + 同 post 簇）判定是否相关，
  相关书关键内容追加进暖画像 related_books；阈值由画像阈值自动学习产出、设置页可手动覆盖。
"""
import json
import re

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.book import Book
from app.models.profile import UserProfile
from app.services.graph.keywords import extract_keywords
from app.services.profile_learning import (
    get_thresholds,
    learn_thresholds,
    record_archive,
    record_relatedness_sample,
)
from app.services.relatedness import compute_relatedness

HOT = "hot"
WARM = "warm"
COLD = "cold"

# 暖转冷跨书数阈值（需求 3.4.1 初值：3 本）
WARM_TO_COLD_THRESHOLD = 3
# 暖画像保留最近书目数（近 1~2 本）
KEEP_RECENT = 2


def _load(db: Session, layer: str, dimension: str, default: dict) -> dict:
    row = db.query(UserProfile).filter_by(layer=layer, dimension=dimension).first()
    if not row:
        return default
    try:
        return json.loads(row.value_json or "{}")
    except ValueError:
        return default


def _save(db: Session, layer: str, dimension: str, value: dict) -> None:
    row = db.query(UserProfile).filter_by(layer=layer, dimension=dimension).first()
    if row:
        row.value_json = json.dumps(value, ensure_ascii=False)
        row.updated_at = utcnow()
    else:
        db.add(
            UserProfile(
                layer=layer,
                dimension=dimension,
                value_json=json.dumps(value, ensure_ascii=False),
            )
        )
    db.commit()


def get_hot(db: Session) -> dict:
    return _load(db, HOT, "current", {})


def get_warm(db: Session) -> dict:
    return _load(db, WARM, "default", {})


def get_cold(db: Session) -> dict:
    return _load(db, COLD, "default", {})


_COLD_NAME_CLEAN_RE = re.compile(r"[^\w\u4e00-\u9fff ]+", re.UNICODE)


def _clean_cold_name(name: str) -> str:
    """冷画像手动编辑名称清洗：只保留汉字/英文数字/下划线/空格（与聚类标签规则一致）。"""
    s = _COLD_NAME_CLEAN_RE.sub(" ", name or "").strip()
    return re.sub(r"\s+", " ", s)


def update_cold_profile(
    db: Session,
    domain_preferences: dict[str, int] | None = None,
    long_term_interests: list[str] | None = None,
) -> dict:
    """手动编辑冷画像（方案 A：仅冷画像可编辑——领域偏好 / 专业领域长期兴趣）。

    只更新传入字段；分数裁剪 1~10，名称清洗特殊标点，空值删除条目。
    """
    cold = get_cold(db)
    if domain_preferences is not None:
        cleaned: dict[str, int] = {}
        for name, score in domain_preferences.items():
            n = _clean_cold_name(str(name))
            if not n:
                continue
            try:
                s = max(1, min(10, int(score)))
            except (TypeError, ValueError):
                s = 1
            cleaned[n] = s
        cold["domain_preferences"] = cleaned
    if long_term_interests is not None:
        seen: set[str] = set()
        uniq: list[str] = []
        for item in long_term_interests:
            n = _clean_cold_name(str(item))
            if n and n not in seen:
                seen.add(n)
                uniq.append(n)
        cold["long_term_interests"] = uniq
    _save(db, COLD, "default", cold)
    return cold




def get_all_profiles(db: Session) -> dict:
    return {"cold": get_cold(db), "warm": get_warm(db), "hot": get_hot(db)}


def reset_profiles(db: Session) -> None:
    db.query(UserProfile).filter(UserProfile.layer.in_([HOT, WARM, COLD])).delete()
    db.commit()


def update_hot_profile(
    db: Session,
    book: Book,
    *,
    progress: float | None = None,
    chapter_title: str | None = None,
    highlight: dict | None = None,
    question: str | None = None,
) -> dict:
    """热画像实时回写：当前书章节脉络、笔记/划线/「不理解」、进行中的问题。"""
    hot = get_hot(db)
    if hot.get("current_book_id") != book.id:
        hot = {
            "current_book_id": book.id,
            "current_title": book.title,
            "progress": 0.0,
            "chapter_titles": [],
            "highlights": [],
            "questions": [],
        }
    if progress is not None:
        hot["progress"] = round(float(progress), 4)
    if chapter_title:
        titles = hot.setdefault("chapter_titles", [])
        if not titles or titles[-1] != chapter_title:
            titles.append(chapter_title)
    if highlight:
        hot.setdefault("highlights", []).append(highlight)
    if question:
        hot.setdefault("questions", []).append(question)
    _save(db, HOT, "current", hot)
    return hot


def _asset_summary(rag: dict | None) -> dict:
    """RAG 资产 → 概要字段（summary + key_points 文本列表）。"""
    if not rag:
        return {"summary": "", "key_points": []}
    kps = rag.get("key_points") or []
    points = []
    for kp in kps:
        if isinstance(kp, str):
            points.append(kp)
        elif isinstance(kp, dict):
            points.append(str(kp.get("title") or kp.get("point") or ""))
    return {"summary": rag.get("summary", ""), "key_points": points[:20]}


def _terms(text: str, top_n: int = 10) -> list[str]:
    """从短文本抽取术语（复用关键词抽取，中文二元组+英文词）。"""

    return list(extract_keywords(text or "", top_n))


def migrate_profiles_on_archive(db: Session, book: Book, rag: dict | None = None) -> dict:
    """读完归档时的画像迁移（需求 3.4.1）：热→暖 → 阈值暖→冷 → >3 全部沉淀；相关领域书入暖记忆。"""
    hot = get_hot(db)
    warm = get_warm(db)
    cold = get_cold(db)

    summary = _asset_summary(rag)
    now = utcnow().isoformat()
    entry = {
        "book_id": book.id,
        "title": book.title,
        "archived_at": now,
        "summary": summary.get("summary", ""),
        "key_points": summary.get("key_points", []),
        "highlights": hot.get("highlights", []),
        "questions": hot.get("questions", []),
    }
    recent = [r for r in warm.get("recent_books", []) if r.get("book_id") != book.id] + [entry]
    warm["recent_books"] = recent[-KEEP_RECENT:]
    warm["archived_count"] = int(warm.get("archived_count", 0)) + 1

    # 主题聚合（后验术语词频）
    themes = warm.setdefault("themes", {})
    for kp in summary.get("key_points", []):
        for w in _terms(kp):
            themes[w] = int(themes.get(w, 0)) + 1

    # 相关领域书入暖记忆（决策 20 相关度函数：谱系边强度 + 暖/冷画像术语 + 同簇）
    rel = compute_relatedness(db, book)
    if rel["related"]:
        related = [r for r in warm.get("related_books", []) if r.get("book_id") != book.id]
        related.append(
            {
                "book_id": book.id,
                "title": book.title,
                "archived_at": now,
                "summary": summary.get("summary", ""),
                "score": rel["score"],
            }
        )
        warm["related_books"] = related

    # 阈值迁移：跨 N 本 → 暖转冷；> N 本 → 全部沉淀冷（N 默认 3，按用户习惯学习）
    count = int(warm["archived_count"])
    warm_threshold = int(get_thresholds(db)["warm_threshold"])
    if count >= warm_threshold:
        prefs = cold.setdefault("domain_preferences", {})
        for t, c in themes.items():
            prefs[t] = int(prefs.get(t, 0)) + c
        cold.setdefault("knowledge_level", "intermediate")
        cold.setdefault("language_style", "default")
        long_terms = cold.setdefault("long_term_interests", [])
        for t in sorted(themes, key=lambda x: -themes[x])[:10]:
            if t not in long_terms:
                long_terms.append(t)
    if count > warm_threshold:
        warm["recent_books"] = warm["recent_books"][-1:]

    _save(db, WARM, "default", warm)
    _save(db, COLD, "default", cold)
    # 热画像清空（当前书已归档）
    _save(
        db,
        HOT,
        "current",
        {
            "current_book_id": None,
            "current_title": "",
            "progress": 0.0,
            "chapter_titles": [],
            "highlights": [],
            "questions": [],
        },
    )
    # 归档节奏样本 + 相关度行为样本 + 阈值自动学习（样本不足不调整，保持默认行为）
    try:
        record_archive(db, now)
        record_relatedness_sample(db, book.id, rel["score"], rel["same_cluster"], now)
        learn_thresholds(db)
    except Exception:
        db.rollback()
    return get_all_profiles(db)
