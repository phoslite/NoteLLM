"""跨书谱系：关键词共现余弦分 + 笔记加权 + 同聚类低分边；全局谱系序列化与重建。"""
import json
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models.activity import Note
from app.models.book import Book
from app.models.graph import BookRelation, KnowledgePoint
from app.services.graph.clustering import assign_clusters
from app.services.graph.corpus import book_corpus
from app.services.graph.intra_book import build_intra_book_graph
from app.services.graph.keywords import extract_keywords


def _note_keywords(note: Note, top_n: int = 30) -> set[str]:
    return set(extract_keywords(f"{note.quote_text or ''} {note.note_text or ''}", top_n))

def _note_weight(db: Session, book_a_id: int, book_b_id: int, common: set[str]) -> float:
    """笔记加权：任一书笔记命中共同关键词 +2；两书笔记共享任意术语 +3/对（上限 15 分）。"""
    if not common:
        return 0.0
    notes_a = db.query(Note).filter(Note.book_id == book_a_id).all()
    notes_b = db.query(Note).filter(Note.book_id == book_b_id).all()
    kw_a = [_note_keywords(n) for n in notes_a]
    kw_b = [_note_keywords(n) for n in notes_b]
    a_hit = any(s & common for s in kw_a)
    b_hit = any(s & common for s in kw_b)
    cross = sum(1 for s1 in kw_a for s2 in kw_b if s1 & s2)
    return min(15.0, 2.0 * a_hit + 2.0 * b_hit + 3.0 * min(2, cross))

def _pair_score(
    db: Session, a: Book, b: Book, ka: dict[str, float], kb: dict[str, float]
) -> tuple[float, list[str]] | None:
    """两书关联评分：关键词共现余弦分 + 笔记加权；低于阈值返回 None（不建边）。"""
    if not ka or not kb:
        return None
    common = set(ka) & set(kb)
    if not common:
        return None
    dot = sum(min(ka[t], kb[t]) for t in common)
    denom = (sum(ka.values()) ** 0.5) * (sum(kb.values()) ** 0.5)
    score = round(100.0 * (dot / denom if denom else 0.0), 1)
    if score < 1.0:
        return None
    score = min(100.0, round(score + _note_weight(db, a.id, b.id, common), 1))
    reasons = sorted(common, key=lambda t: min(ka[t], kb[t]), reverse=True)[:5]
    return score, reasons


def pair_key(x: int, y: int) -> tuple[int, int]:
    return (x, y) if x < y else (y, x)


def compute_cross_book_graph(db: Session) -> dict:
    """重建全部书籍关联（先清空再计算）：关键词共现余弦分 + 笔记加权；同聚类低分「主题相似」边。"""
    books = db.query(Book).order_by(Book.id).all()
    keywords = {b.id: extract_keywords(book_corpus(b)) for b in books}
    db.query(BookRelation).delete()
    pairs: set[tuple[int, int]] = set()
    created: dict[tuple[int, int], BookRelation] = {}
    candidates: list[tuple[int, int, float]] = []

    for i, a in enumerate(books):
        for b in books[i + 1 :]:
            result = _pair_score(db, a, b, keywords.get(a.id, {}), keywords.get(b.id, {}))
            if not result:
                continue
            score, reasons = result
            key = pair_key(a.id, b.id)
            rel = BookRelation(
                book_a_id=key[0],
                book_b_id=key[1],
                strength=score,
                direction="无",
                relation_type="概念共现",
                reasons_json=json.dumps(reasons, ensure_ascii=False),
            )
            db.add(rel)
            created[key] = rel
            pairs.add(key)
            candidates.append((a.id, b.id, score))

    # 同聚类但关键词重叠不足的书：补「主题相似」低分边（同领域基础关联）
    clusters = assign_clusters(db, books)
    for i, a in enumerate(books):
        for b in books[i + 1 :]:
            key = pair_key(a.id, b.id)
            ca, cb = clusters.get(a.id, "其他"), clusters.get(b.id, "其他")
            if key in pairs or ca != cb or ca in ("", "其他"):
                continue
            db.add(
                BookRelation(
                    book_a_id=key[0],
                    book_b_id=key[1],
                    strength=8.0,
                    direction="无",
                    relation_type="主题相似",
                    reasons_json=json.dumps([f"同属「{ca}」领域"], ensure_ascii=False),
                )
            )
    db.flush()
    # LLM 打分与方向/原因增强（有界调用，失败回退关键词分）
    from app.services.graph.llm_score import apply_llm_result, enrich_pairs_with_llm

    books_by_id = {b.id: b for b in books}
    llm_results = enrich_pairs_with_llm(db, books_by_id, keywords, candidates)
    for key, result in llm_results.items():
        rel = created.get(key)
        if rel is not None:
            apply_llm_result(rel, key[0], key[1], result)
    db.commit()
    return global_graph_payload(db, books)


def incremental_cross_book_graph(db: Session, book_id: int) -> dict:
    """新书导入后增量更新跨书关联（需求 3.6.2）：只补新书与其他书的边，不动既有关联；随后补本地联动存根。"""
    book = db.get(Book, book_id)
    if not book:
        return {"relations_added": 0, "linked": 0}
    others = [b for b in db.query(Book).filter(Book.id != book.id).order_by(Book.id).all()]
    if not others:
        return {"relations_added": 0, "linked": 0}
    keywords = {b.id: extract_keywords(book_corpus(b)) for b in [book, *others]}
    existing: set[tuple[int, int]] = {pair_key(r.book_a_id, r.book_b_id) for r in db.query(BookRelation).all()}
    added = 0
    created: dict[tuple[int, int], BookRelation] = {}
    candidates: list[tuple[int, int, float]] = []

    def add_pair(a: Book, b: Book, score: float, reasons: list[str], rel_type: str) -> None:
        nonlocal added
        key = pair_key(a.id, b.id)
        if key in existing:
            return
        existing.add(key)
        rel = BookRelation(
            book_a_id=key[0],
            book_b_id=key[1],
            strength=score,
            direction="无",
            relation_type=rel_type,
            reasons_json=json.dumps(reasons, ensure_ascii=False),
        )
        db.add(rel)
        created[key] = rel
        added += 1
        candidates.append((a.id, b.id, score))

    for other in others:
        result = _pair_score(db, book, other, keywords.get(book.id, {}), keywords.get(other.id, {}))
        if result:
            score, reasons = result
            add_pair(book, other, score, reasons, "概念共现")

    # 同聚类低分边（新书归属簇与其它书一致时补「主题相似」）
    clusters = assign_clusters(db, [book, *others])
    ca = clusters.get(book.id, "其他")
    if ca not in ("", "其他"):
        for other in others:
            if clusters.get(other.id, "其他") == ca:
                add_pair(book, other, 8.0, [f"同属「{ca}」领域"], "主题相似")
    db.commit()
    # LLM 打分与方向/原因增强（有界调用，失败回退关键词分）
    from app.services.graph.llm_score import apply_llm_result, enrich_pairs_with_llm

    books_by_id = {b.id: b for b in [book, *others]}
    llm_results = enrich_pairs_with_llm(db, books_by_id, keywords, candidates)
    for key, result in llm_results.items():
        rel = created.get(key)
        if rel is not None:
            apply_llm_result(rel, key[0], key[1], result)
    if llm_results:
        db.commit()
    from app.services.graph_sync import link_graph_assets

    linked = link_graph_assets(db)
    return {"relations_added": added, "linked": linked["stubs"]}


def knowledge_appears_in(db: Session, kp_id: int) -> dict:
    """跨书检索（需求 3.4.7/M8 待办）：该知识点还出现在哪些书。

    命中来源：其他书 KnowledgePoint（章节级/重要段落/用户标记，title+summary 关键词重叠）
    + 其他书 RAG key_points 文本命中；按命中数倒序，空结果 books=[]。
    """
    from app.repositories.assets import read_asset_content

    kp = db.get(KnowledgePoint, kp_id)
    if not kp:
        return {}
    tokens = set(extract_keywords(f"{kp.title or ''} {kp.summary or ''}", 12))
    source = {
        "kp_id": kp.id,
        "book_id": kp.book_id,
        "title": kp.title,
        "summary": kp.summary,
        "level": kp.level,
        "para_pos": kp.para_pos,
        "chapter_id": kp.chapter_id,
    }
    if not tokens:
        return {"source": source, "books": [], "total": 0}

    hits: dict[int, dict] = {}
    for other_kp in db.query(KnowledgePoint).filter(KnowledgePoint.book_id != kp.book_id).all():
        common = tokens & set(extract_keywords(f"{other_kp.title or ''} {other_kp.summary or ''}", 30))
        if not common:
            continue
        entry = hits.setdefault(other_kp.book_id, {"matched_kps": [], "rag_hits": []})
        entry["matched_kps"].append(
            {
                "id": other_kp.id,
                "title": other_kp.title,
                "level": other_kp.level,
                "chapter_id": other_kp.chapter_id,
                "para_pos": other_kp.para_pos,
                "common": sorted(common)[:6],
            }
        )
    for book in db.query(Book).filter(Book.id != kp.book_id).all():
        rag = read_asset_content(db, book.id, "rag")
        for kp_text in rag.get("key_points") or []:
            if not isinstance(kp_text, str):
                kp_text = str(kp_text.get("title") or kp_text.get("point") or "")
            if tokens & set(extract_keywords(kp_text, 20)):
                entry = hits.setdefault(book.id, {"matched_kps": [], "rag_hits": []})
                entry["rag_hits"].append(kp_text[:120])
                break  # 每书 RAG 至多记一条提示

    books: list[dict] = []
    for b in db.query(Book).filter(Book.id.in_(list(hits))).all():
        info = hits[b.id]
        books.append(
            {
                "book_id": b.id,
                "title": b.title,
                "matched_kps": info["matched_kps"][:10],
                "rag_hits": info["rag_hits"][:5],
                "matched_count": len(info["matched_kps"]) + len(info["rag_hits"]),
            }
        )
    books.sort(key=lambda x: -x["matched_count"])
    return {"source": source, "books": books, "total": len(books)}

def global_graph_payload(db: Session, books: list[Book] | None = None) -> dict:
    """全局谱系数据：聚类 + 书籍节点 + 关联边。"""
    books = books or db.query(Book).order_by(Book.id).all()
    clusters = assign_clusters(db, books)
    cluster_map: dict[str, list[int]] = defaultdict(list)
    for b in books:
        cluster_map[clusters.get(b.id) or "其他"].append(b.id)
    nodes = [
        {
            "id": b.id,
            "title": b.title,
            "cluster": clusters.get(b.id) or "其他",
            "tags": json.loads(b.tags_json or "[]"),
            "format": b.format,
            "chapter_count": len(b.chapters),
            "graph_built": b.graph_built,
            "status": b.status,
        }
        for b in books
    ]
    relations = db.query(BookRelation).order_by(BookRelation.id).all()
    edges = [
        {
            "id": r.id,
            "book_a": r.book_a_id,
            "book_b": r.book_b_id,
            "strength": r.strength,
            "direction": r.direction,
            "from_book": r.from_book_id,
            "relation_type": r.relation_type,
            "reasons": json.loads(r.reasons_json or "[]"),
            "user_feedback": r.user_feedback,
        }
        for r in relations
    ]
    return {
        "clusters": [
            {"name": name, "book_ids": ids, "book_count": len(ids)} for name, ids in cluster_map.items()
        ],
        "nodes": nodes,
        "edges": edges,
    }

def rebuild_all_graph(db: Session) -> dict:
    """重建全部图谱：先逐书重建内部图，再重算跨书关联并触发本地联动沉淀。"""
    books = db.query(Book).order_by(Book.id).all()
    for b in books:
        build_intra_book_graph(db, b)
    compute_cross_book_graph(db)
    # 本地 RAG 联动存根（强度 ≥ 50 的关联补 linked_books / domain_terms，内容未变化不写）
    from app.services.graph_sync import link_graph_assets

    linked = link_graph_assets(db)
    return {
        "books": len(books),
        "relations": db.query(BookRelation).count(),
        "knowledge_points": db.query(KnowledgePoint).count(),
        "linked": linked["stubs"],
    }
