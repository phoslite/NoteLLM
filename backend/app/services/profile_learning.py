"""画像阈值自动学习（需求 3.4.1）：按归档节奏/确认关联分布自动调整迁移阈值。

- 持久化键（Setting 表）：profile.warm_threshold / profile.related_strength /
  profile.review_days / profile.learning_state（JSON 样本与学习记录）；
- 学习触发：归档时记录节奏样本，样本达到下限后自动调整；设置页可手动覆盖；
- 样本不足时返回默认常量（与 profile_service 旧常量一致，保证既有行为不回退）。
"""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.graph import BookRelation
from app.repositories.settings import get_setting, set_setting

# Setting 键
KEY_WARM_THRESHOLD = "profile.warm_threshold"
KEY_RELATED_STRENGTH = "profile.related_strength"
KEY_REVIEW_DAYS = "profile.review_days"
KEY_LEARNING_STATE = "profile.learning_state"

# 默认值（与 profile_service / recommendation_service 常量一致）
DEFAULT_WARM_THRESHOLD = 3
DEFAULT_RELATED_STRENGTH = 60.0
DEFAULT_REVIEW_DAYS = 1

# 学习样本下限：低于该值不自动调整（归档数 ≤5 的历史测试不受影响）
MIN_LEARN_SAMPLES = 6
# 确认关联边样本下限（低于不改 related_strength）
MIN_CONFIRMED_EDGES = 3
# 相关度行为样本下限（归档书相关度分数 ≥ 该值后参与 related_strength 学习）
MIN_RELATED_SAMPLES = 6

# 可学习/可调范围
WARM_THRESHOLD_MIN, WARM_THRESHOLD_MAX = 2, 5
RELATED_STRENGTH_MIN, RELATED_STRENGTH_MAX = 45.0, 60.0
REVIEW_DAYS_MIN, REVIEW_DAYS_MAX = 1, 7


def _read_num(db: Session, key: str, default: float) -> float:
    raw = get_setting(db, key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_thresholds(db: Session) -> dict:
    """读取当前阈值（已持久化优先，未设置回默认常量）。"""
    return {
        "warm_threshold": int(_read_num(db, KEY_WARM_THRESHOLD, DEFAULT_WARM_THRESHOLD)),
        "related_strength": _read_num(db, KEY_RELATED_STRENGTH, DEFAULT_RELATED_STRENGTH),
        "review_days": int(_read_num(db, KEY_REVIEW_DAYS, DEFAULT_REVIEW_DAYS)),
    }


def save_thresholds(
    db: Session,
    *,
    warm_threshold: int | None = None,
    related_strength: float | None = None,
    review_days: int | None = None,
) -> dict:
    """手动覆盖阈值（设置页可调）；越界裁剪到学习范围。"""
    if warm_threshold is not None:
        value = int(min(WARM_THRESHOLD_MAX, max(WARM_THRESHOLD_MIN, int(warm_threshold))))
        set_setting(db, KEY_WARM_THRESHOLD, str(value))
    if related_strength is not None:
        value = round(min(RELATED_STRENGTH_MAX, max(RELATED_STRENGTH_MIN, float(related_strength))), 1)
        set_setting(db, KEY_RELATED_STRENGTH, str(value))
    if review_days is not None:
        value = int(min(REVIEW_DAYS_MAX, max(REVIEW_DAYS_MIN, int(review_days))))
        set_setting(db, KEY_REVIEW_DAYS, str(value))
    return get_thresholds(db)


def _load_state(db: Session) -> dict:
    raw = get_setting(db, KEY_LEARNING_STATE)
    if not raw:
        return {"samples": [], "last_learned_at": None, "learned": None}
    try:
        state = json.loads(raw)
    except ValueError:
        return {"samples": [], "last_learned_at": None, "learned": None}
    if not isinstance(state, dict):
        return {"samples": [], "last_learned_at": None, "learned": None}
    state.setdefault("samples", [])
    return state


def _save_state(db: Session, state: dict) -> None:
    set_setting(db, KEY_LEARNING_STATE, json.dumps(state, ensure_ascii=False))


def record_archive(db: Session, archived_at: str) -> None:
    """归档时记录节奏样本：相邻两本归档间隔（天），保留最近 24 条。"""
    state = _load_state(db)
    samples = state["samples"]
    if samples:
        try:
            last = datetime.fromisoformat(str(samples[-1].get("archived_at", "")))
            cur = datetime.fromisoformat(archived_at)
            interval = max(0.0, (cur - last).total_seconds() / 86400.0)
        except ValueError:
            interval = None
        if interval is not None:
            samples.append({"archived_at": archived_at, "interval_days": round(interval, 2)})
    else:
        samples.append({"archived_at": archived_at, "interval_days": None})
    state["samples"] = samples[-24:]
    _save_state(db, state)


def record_relatedness_sample(
    db: Session, book_id: int, score: float, same_cluster: bool, archived_at: str
) -> None:
    """归档时记录相关度行为样本（related_samples，保留最近 48 条）。

    样本 = 每次归档书的相关度分数与是否同簇；learn_thresholds 依据非簇样本的
    分数分布低分位学习 related_strength（用户实际阅读归档书的相关度下界）。
    """
    state = _load_state(db)
    samples = state.setdefault("related_samples", [])
    samples.append(
        {
            "book_id": book_id,
            "score": round(float(score), 1),
            "same_cluster": bool(same_cluster),
            "archived_at": archived_at,
        }
    )
    state["related_samples"] = samples[-48:]
    _save_state(db, state)


def learn_thresholds(db: Session) -> dict:
    """按样本自动学习并持久化阈值；样本不足仅记录时间戳、不修改阈值。

    - review_days：归档间隔中位数（裁剪 1~7 天）；
    - warm_threshold：按阅读节奏（中位间隔 → 快 2 / 慢 5）平滑调整；
    - related_strength：确认关联边强度分布低分位（25%），裁剪 45~60。
    """
    state = _load_state(db)
    samples = state.get("samples", [])
    intervals = sorted(
        float(s["interval_days"]) for s in samples if s.get("interval_days") is not None
    )
    confirmed = [
        r.strength
        for r in db.query(BookRelation).filter(BookRelation.user_feedback == "确认").all()
    ]
    related_samples = [
        float(s["score"])
        for s in state.get("related_samples", [])
        if not s.get("same_cluster") and s.get("score") is not None
    ]
    learned: dict = {}
    if len(samples) >= MIN_LEARN_SAMPLES and intervals:
        median = intervals[len(intervals) // 2]
        review_days = int(round(max(REVIEW_DAYS_MIN, min(REVIEW_DAYS_MAX, median))))
        pace = max(0.0, min(1.0, median / 7.0))
        warm_threshold = int(
            round(WARM_THRESHOLD_MIN + pace * (WARM_THRESHOLD_MAX - WARM_THRESHOLD_MIN))
        )
        save_thresholds(db, review_days=review_days, warm_threshold=warm_threshold)
        learned.update(
            {
                "samples": len(samples),
                "median_interval_days": round(median, 2),
                "warm_threshold": warm_threshold,
                "review_days": review_days,
            }
        )
    # related_strength：行为样本低分位与确认关联低分位取保守 min（均裁剪 45~60）
    candidate: float | None = None
    if len(related_samples) >= MIN_RELATED_SAMPLES:
        ordered = sorted(related_samples)
        low_q = ordered[min(len(ordered) - 1, int(len(ordered) * 0.25))]
        candidate = round(max(RELATED_STRENGTH_MIN, min(RELATED_STRENGTH_MAX, low_q)), 1)
    if len(confirmed) >= MIN_CONFIRMED_EDGES:
        ordered = sorted(confirmed)
        low_q = ordered[min(len(ordered) - 1, int(len(ordered) * 0.25))]
        confirmed_low = round(max(RELATED_STRENGTH_MIN, min(RELATED_STRENGTH_MAX, low_q)), 1)
        candidate = confirmed_low if candidate is None else min(candidate, confirmed_low)
    if candidate is not None:
        save_thresholds(db, related_strength=candidate)
        learned["related_strength"] = candidate
    if learned:
        state["learned"] = {**dict(state.get("learned") or {}), **learned, "at": datetime.now().isoformat()}
    state["last_learned_at"] = datetime.now().isoformat()
    _save_state(db, state)
    return get_thresholds(db)


def learning_state(db: Session) -> dict:
    """学习状态视图（样本数、上次学习时间、已学阈值；供 API 返回，不开放手动改）。"""
    state = _load_state(db)
    samples = state.get("samples", [])
    return {
        "sample_count": len(samples),
        "related_sample_count": len(state.get("related_samples", [])),
        "last_learned_at": state.get("last_learned_at"),
        "learned": state.get("learned"),
        "min_samples": MIN_LEARN_SAMPLES,
        "confirmed_edges_min": MIN_CONFIRMED_EDGES,
        "related_samples_min": MIN_RELATED_SAMPLES,
    }