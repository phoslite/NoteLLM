"""相关度判定函数（需求 3.4.1 / 9.1 决策 20 落地，M9 第五轮）。

「相关领域」判定落地为可解释、可学习、可手动覆盖的相关度函数：
- 谱系信号（主信号，0~100）：与任一非「忽略」关联边的最大 strength，直接可比（历史阈值语义）；
- 暖画像信号（辅助，0~100）：该书术语对暖画像 themes + recent_books 关键内容的覆盖率；
- 冷画像信号（辅助，0~100）：该书术语对冷画像 domain_preferences + long_term_interests 的覆盖率；
- 同 post 簇：直接判定相关（保留既有行为），分数至少抬升到当前阈值。

相关度分数 score = max(谱系强度, 0.5*暖画像覆盖率*100 + 0.5*冷画像覆盖率*100)（0~100 裁剪）；
related = 同簇 或 score >= related_strength 阈值（画像阈值自动学习产出，设置页可手动覆盖）。
"""
import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.book import Book, Chapter
from app.models.graph import BookRelation
from app.models.profile import UserProfile
from app.repositories.assets import read_asset_content
from app.services.graph.keywords import extract_keywords
from app.services.profile_learning import get_thresholds

# 画像辅助信号权重（合计 1.0；谱系为主信号直接取原始强度）
W_PROFILE_WARM = 0.5
W_PROFILE_COLD = 0.5

TERM_TOP_N = 30
MAX_CHAPTERS_SCAN = 50


def _terms_of_text(text: str, top_n: int = TERM_TOP_N) -> set[str]:
    """短文本 → 术语集合（复用关键词抽取：中文二元组 + 英文词）。"""
    return set(extract_keywords(text or "", top_n))


def _book_terms(db: Session, book: Book) -> set[str]:
    """书相关术语：RAG 资产 key_points/summary 优先，回退书名 + 章节标题。"""
    rag = read_asset_content(db, book.id, "rag")
    texts: list[str] = []
    if rag:
        texts.append(str(rag.get("summary") or ""))
        for kp in rag.get("key_points") or []:
            if isinstance(kp, str):
                texts.append(kp)
            elif isinstance(kp, dict):
                texts.append(str(kp.get("title") or kp.get("point") or ""))
    texts.append(book.title or "")
    titles = [
        ch.title or ""
        for ch in db.query(Chapter.title)
        .filter(Chapter.book_id == book.id)
        .limit(MAX_CHAPTERS_SCAN)
        .all()
    ]
    texts.extend(titles)
    return _terms_of_text(" ".join(texts))


def _profile_terms(db: Session, layer: str) -> set[str]:
    """画像术语集合：暖 = themes + recent_books 关键内容；冷 = domain_preferences + 长期兴趣。"""
    row = db.query(UserProfile).filter_by(layer=layer, dimension="default").first()
    if not row:
        return set()
    try:
        value = json.loads(row.value_json or "{}")
    except ValueError:
        return set()
    if not isinstance(value, dict):
        return set()
    terms: set[str] = set()
    if layer == "warm":
        terms.update((value.get("themes") or {}).keys())
        for r in value.get("recent_books") or []:
            if not isinstance(r, dict):
                continue
            kps = r.get("key_points") or []
            if isinstance(kps, list):
                kps_text = " ".join(str(k) for k in kps)
            else:
                kps_text = str(kps)
            terms.update(_terms_of_text(f"{r.get('summary', '')} {kps_text}"))
    else:  # cold
        terms.update((value.get("domain_preferences") or {}).keys())
        terms.update(str(t) for t in (value.get("long_term_interests") or []))
    return terms


def _overlap_rate(book_terms: set[str], profile_terms: set[str]) -> float:
    """画像术语覆盖率：书命中画像术语数 / 画像术语总数（空画像返回 0）。"""
    if not profile_terms or not book_terms:
        return 0.0
    hit = sum(1 for t in profile_terms if t in book_terms)
    return hit / len(profile_terms)


def _max_edge_strength(db: Session, book: Book) -> float:
    """该书与任一非「忽略」关联边的最大强度（无则 0）。"""
    rel = (
        db.query(BookRelation)
        .filter(
            or_(BookRelation.user_feedback.is_(None), BookRelation.user_feedback != "忽略"),
            (BookRelation.book_a_id == book.id) | (BookRelation.book_b_id == book.id),
        )
        .order_by(BookRelation.strength.desc())
        .first()
    )
    return float(rel.strength) if rel else 0.0


def _same_post_cluster(db: Session, book: Book) -> bool:
    """该书是否与其它书同 post 簇（用户/后验聚类结论，直接视为相关）。"""
    if book.classify_source != "post" or not book.cluster_name:
        return False
    return (
        db.query(Book.id)
        .filter(
            Book.id != book.id,
            Book.classify_source == "post",
            Book.cluster_name == book.cluster_name,
        )
        .first()
        is not None
    )


def compute_relatedness(db: Session, book: Book) -> dict:
    """计算相关度：{score, threshold, related, same_cluster, signals}。

    - score：0~100 综合分数 = max(谱系强度, 0.5*暖覆盖率*100 + 0.5*冷覆盖率*100)，同簇抬升到阈值；
    - related：同簇 或 score >= related_strength 阈值（自动学习/手动覆盖）；
    - signals：各信号分值，供前端展示与用户解释。
    """
    threshold = float(get_thresholds(db)["related_strength"])
    graph_strength = _max_edge_strength(db, book)
    book_terms = _book_terms(db, book)
    warm_rate = _overlap_rate(book_terms, _profile_terms(db, "warm"))
    cold_rate = _overlap_rate(book_terms, _profile_terms(db, "cold"))
    same_cluster = _same_post_cluster(db, book)

    profile_score = round(
        W_PROFILE_WARM * warm_rate * 100 + W_PROFILE_COLD * cold_rate * 100
    )
    score = max(round(graph_strength), profile_score)
    score = max(0, min(100, score))
    if same_cluster:
        score = max(score, int(threshold))

    signals = [
        {"signal": "跨书关联", "value": round(graph_strength, 1), "primary": True},
        {"signal": "暖画像主题", "value": round(warm_rate * 100, 1), "primary": False},
        {"signal": "冷画像领域", "value": round(cold_rate * 100, 1), "primary": False},
    ]
    if same_cluster:
        signals.append({"signal": "同簇", "value": 100.0, "primary": False})
    return {
        "score": score,
        "threshold": threshold,
        "related": bool(same_cluster or score >= threshold),
        "same_cluster": same_cluster,
        "signals": signals,
    }


def is_related_book(db: Session, book: Book) -> bool:
    """快捷判定（保留原 profile_service._is_related_book 语义）。"""
    return bool(compute_relatedness(db, book)["related"])
