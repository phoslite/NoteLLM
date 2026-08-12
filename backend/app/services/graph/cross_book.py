"""跨书谱系：关键词共现余弦分 + 笔记加权 + 同聚类低分边；全局谱系序列化与重建。"""
import json
import threading
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.activity import Note
from app.models.asset import BookAsset
from app.models.book import Book
from app.models.graph import BookRelation, KnowledgePoint
from app.repositories.assets import list_assets_by_books
from app.repositories.graph import (
    clear_relations,
    count_knowledge_points,
    count_relations,
    list_books,
    list_books_by_ids,
    list_books_except,
    list_feedback_relations,
    list_knowledge_points,
    list_notes,
    list_relations,
)
from app.services.graph.clustering import assign_clusters
from app.services.graph.edges import pair_key
from app.services.graph.intra_book import build_intra_book_graph
from app.services.graph.keywords import book_keywords, extract_keywords
from app.services.graph.llm_score import apply_llm_result, enrich_pairs_with_llm
from app.services.graph.similarity import idf_weights, pair_similarity_weighted, weighted_vectors
from app.services.graph.terms import canonical_terms
from app.services.graph_sync import link_graph_assets


def _note_keywords(note: Note, top_n: int = 30) -> set[str]:
    return set(extract_keywords(f"{note.quote_text or ''} {note.note_text or ''}", top_n))

def _load_notes_by_book(db: Session) -> dict[int, list[Note]]:
    """一次性加载全部笔记并按 book_id 分组（审查 A-8：消除每对书籍组合的重复查询）。"""
    notes_by_book: dict[int, list[Note]] = {}
    for note in list_notes(db):
        notes_by_book.setdefault(note.book_id, []).append(note)
    return notes_by_book


# ---- H3：跨书检索进程内倒排索引（词 → KP / 词 → RAG key_points）----
# 惰性构建 + 指纹失效：(kp_count, max_kp_id, book_count, asset_count, asset_version_sum)。
# KnowledgePoint 无 updated_at，且全库不存在就地更新路径（仅 intra_book 新建/重建删除），
# 指纹可覆盖全部 KP 变更；资产 upsert 必 bump version（repositories/assets.upsert_asset），
# 故 RAG 内容变更同样可检测。并发安全：双检锁 + 不可变快照（构建完成后不再修改）。
_KP_INDEX_LOCK = threading.Lock()
_KP_INDEX: dict | None = None


def _kp_index_fingerprint(db: Session) -> tuple:
    """索引数据源指纹：两三条轻量聚合查询，与构建内容一一对应。"""
    kp_count, kp_max = db.query(func.count(KnowledgePoint.id), func.max(KnowledgePoint.id)).one()
    asset_count, asset_ver_sum = db.query(
        func.count(BookAsset.id), func.coalesce(func.sum(BookAsset.version), 0)
    ).one()
    book_count = db.query(func.count(Book.id)).scalar()
    return (kp_count, kp_max, book_count, asset_count, asset_ver_sum)


def _build_kp_index(db: Session, fingerprint: tuple) -> dict:
    """全量构建：KP title+summary（top30）与每书 RAG key_points（top20）词倒排。"""
    kp_rows: list[dict] = []
    kp_posting: dict[str, list[int]] = defaultdict(list)
    for kp in list_knowledge_points(db):  # id 升序，输出顺序与全量扫描一致
        toks = frozenset(extract_keywords(f"{kp.title or ''} {kp.summary or ''}", 30))
        idx = len(kp_rows)
        kp_rows.append(
            {
                "id": kp.id,
                "book_id": kp.book_id,
                "title": kp.title,
                "summary": kp.summary,
                "level": kp.level,
                "chapter_id": kp.chapter_id,
                "para_pos": kp.para_pos,
                "tokens": toks,
            }
        )
        for t in toks:
            kp_posting[t].append(idx)
    rag_books: list[tuple[int, list[tuple[str, frozenset]]]] = []
    rag_posting: dict[str, list[tuple[int, int]]] = defaultdict(list)
    assets = list_assets_by_books(db)
    for book_id in sorted(assets):  # 书 id 升序，与 list_books_except 遍历序一致
        rag = assets[book_id].get("rag") or {}
        entries: list[tuple[str, frozenset]] = []
        for kp_text in rag.get("key_points") or []:
            if not isinstance(kp_text, str):
                kp_text = str(kp_text.get("title") or kp_text.get("point") or "")
            toks = frozenset(extract_keywords(kp_text, 20))
            entries.append((kp_text, toks))
        if not entries:
            continue
        book_idx = len(rag_books)
        rag_books.append((book_id, entries))
        for e_idx, (_text, toks) in enumerate(entries):
            for t in toks:
                rag_posting[t].append((book_idx, e_idx))
    return {
        "fingerprint": fingerprint,
        "kps": kp_rows,
        "kp_posting": dict(kp_posting),
        "rag_books": rag_books,
        "rag_posting": dict(rag_posting),
    }


def _get_kp_index(db: Session) -> dict:
    """双检锁取索引：指纹未变直接复用（命中查询零全库扫描）；变更时重建。"""
    global _KP_INDEX
    fp = _kp_index_fingerprint(db)
    idx = _KP_INDEX
    if idx is not None and idx["fingerprint"] == fp:
        return idx
    with _KP_INDEX_LOCK:
        idx = _KP_INDEX
        if idx is not None and idx["fingerprint"] == fp:
            return idx
        idx = _build_kp_index(db, fp)
        _KP_INDEX = idx
        return idx


def _note_weight(
    notes_by_book: dict[int, list[Note]], book_a_id: int, book_b_id: int, common: set[str]
) -> float:
    """笔记加权：任一书笔记命中共同关键词 +2；两书笔记共享任意术语 +3/对（上限 15 分）。"""
    if not common:
        return 0.0
    kw_a = [_note_keywords(n) for n in notes_by_book.get(book_a_id, [])]
    kw_b = [_note_keywords(n) for n in notes_by_book.get(book_b_id, [])]
    a_hit = any(s & common for s in kw_a)
    b_hit = any(s & common for s in kw_b)
    cross = sum(1 for s1 in kw_a for s2 in kw_b if s1 & s2)
    return min(15.0, 2.0 * a_hit + 2.0 * b_hit + 3.0 * min(2, cross))

def _pair_score(
    db: Session, a: Book, b: Book, ka: dict[str, float], kb: dict[str, float],
    notes_by_book: dict[int, list[Note]], idf: dict[str, float], wv: dict,
) -> tuple[float, list[str]] | None:
    """两书关联评分（L2）：IDF 加权余弦 ×100 + 笔记加权；低于 τ_edge 返回 None（不建边）。

    H2：wv 为入口预计算的加权向量/范数表（weighted_vectors(keywords, idf)），
    逐对不再重复构建 IDF 加权向量（实测 4.4x 冗余）。
    """
    wa, norm_a = wv.get(a.id, ({}, 0.0))
    wb, norm_b = wv.get(b.id, ({}, 0.0))
    result = pair_similarity_weighted(ka, kb, wa, norm_a, wb, norm_b)
    if result is None:
        return None
    sim, reasons = result
    score = round(100.0 * sim, 1)
    score = min(100.0, round(score + _note_weight(notes_by_book, a.id, b.id, set(reasons)), 1))
    return score, reasons


def _overlapping_pairs(books: list, keywords: dict[int, dict[str, float]]) -> set[tuple[int, int]]:
    """倒排索引生成「有共同关键词」的书对集合（去重、规范序）。

    与原全量两两枚举等价：无共同关键词的对在 _pair_score 中必然返回 None（不建边），
    此处直接跳过；有共同词的对全部保留，评分逻辑不变（2026-08-06 性能优化）。
    """
    inverted: dict[str, list[int]] = {}
    for b in books:
        for term in keywords.get(b.id, {}):
            inverted.setdefault(term, []).append(b.id)
    pairs: set[tuple[int, int]] = set()
    for ids in inverted.values():
        if len(ids) < 2:
            continue
        uniq = sorted(set(ids))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a_id, b_id = uniq[i], uniq[j]
                pairs.add((a_id, b_id) if a_id < b_id else (b_id, a_id))
    return pairs


def compute_cross_book_graph(db: Session) -> dict:
    """重建全部书籍关联（先清空再计算）：关键词共现余弦分 + 笔记加权；同聚类低分「主题相似」边。"""
    books = list_books(db)
    books_by_id = {b.id: b for b in books}
    keywords = {b.id: canonical_terms(book_keywords(b, db=db)) for b in books}
    idf = idf_weights(keywords)
    wv = weighted_vectors(keywords, idf)  # H2：加权向量/范数入口一次预计算
    notes_by_book = _load_notes_by_book(db)  # 审查 A-8：入口预加载，_pair_score 直接查内存
    # 终审 §6.9：重建保留人工反馈（确认/忽略/修改），避免用户反复处理同一关联
    feedback: dict[tuple[int, int], dict] = {
        pair_key(r.book_a_id, r.book_b_id): {"feedback": r.user_feedback, "strength": r.strength}
        for r in list_feedback_relations(db)
    }
    clear_relations(db)
    pairs: set[tuple[int, int]] = set()
    created: dict[tuple[int, int], BookRelation] = {}
    candidates: list[tuple[int, int, float]] = []

    # 倒排索引（2026-08-06）：只枚举有共同关键词的书对，稀疏场景 O(N²K) → O(Σ df(k)²)
    pair_ids = _overlapping_pairs(books, keywords)
    for a_id, b_id in pair_ids:
        a = books_by_id[a_id]
        b = books_by_id[b_id]
        result = _pair_score(db, a, b, keywords.get(a_id, {}), keywords.get(b_id, {}), notes_by_book, idf, wv)
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
    # 回填人工反馈：忽略/确认保持原状；「修改」保留用户指定强度
    for key, rel in created.items():
        saved = feedback.get(key)
        if not saved:
            continue
        rel.user_feedback = saved["feedback"]
        if saved["feedback"] == "修改" and saved["strength"] is not None:
            rel.strength = saved["strength"]
    db.flush()
    db.commit()  # 审查 B-1（问题5）：清理与本地边先落库，避免 LLM 打分期间持有 SQLite 写锁（分钟级）
    llm_results = enrich_pairs_with_llm(db, books_by_id, keywords, candidates)
    for key, result in llm_results.items():
        rel = created.get(key)
        if rel is not None:
            apply_llm_result(rel, key[0], key[1], result)
    if llm_results:
        db.commit()
    return global_graph_payload(db, books)


def incremental_cross_book_graph(db: Session, book_id: int) -> dict:
    """新书导入后增量更新跨书关联（需求 3.6.2）：只补新书与其他书的边，不动既有关联；随后补本地联动存根。"""
    book = db.get(Book, book_id)
    if not book:
        return {"relations_added": 0, "linked": 0}
    others = list_books_except(db, book.id)
    if not others:
        return {"relations_added": 0, "linked": 0}
    keywords = {b.id: canonical_terms(book_keywords(b, db=db)) for b in [book, *others]}
    idf = idf_weights(keywords)
    wv = weighted_vectors(keywords, idf)  # H2：加权向量/范数入口一次预计算
    notes_by_book = _load_notes_by_book(db)  # 审查 A-8：入口预加载
    existing: set[tuple[int, int]] = {pair_key(r.book_a_id, r.book_b_id) for r in list_relations(db)}
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
        result = _pair_score(db, book, other, keywords.get(book.id, {}), keywords.get(other.id, {}), notes_by_book, idf, wv)
        if result:
            score, reasons = result
            add_pair(book, other, score, reasons, "概念共现")

    # 同聚类低分边（新书归属簇与其它书一致时补「主题相似」）
    # A-I3：增量补边必须用全量人口聚类（子集 IDF/簇与全局矛盾，且子集 persist 会写坏全量缓存）
    clusters = assign_clusters(db, list_books(db))
    ca = clusters.get(book.id, "其他")
    if ca not in ("", "其他"):
        for other in others:
            if clusters.get(other.id, "其他") == ca:
                add_pair(book, other, 8.0, [f"同属「{ca}」领域"], "主题相似")
    db.commit()
    books_by_id = {b.id: b for b in [book, *others]}
    llm_results = enrich_pairs_with_llm(db, books_by_id, keywords, candidates)
    for key, result in llm_results.items():
        rel = created.get(key)
        if rel is not None:
            apply_llm_result(rel, key[0], key[1], result)
    if llm_results:
        db.commit()

    linked = link_graph_assets(db)
    return {"relations_added": added, "linked": linked["stubs"]}


def knowledge_appears_in(db: Session, kp_id: int) -> dict:
    """跨书检索（需求 3.4.7/M8 待办）：该知识点还出现在哪些书。

    命中来源：其他书 KnowledgePoint（章节级/重要段落/用户标记，title+summary 关键词重叠）
    + 其他书 RAG key_points 文本命中；按命中数倒序，空结果 books=[]。

    H3（复杂度审查）：进程内惰性倒排索引（词→KP/词→RAG key_points）+ 指纹失效，
    消除每请求全库扫描（2 万 KP 实测 1.4s → 命中查询只碰倒排桶；RAG 资产批量读取一次）。
    """

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

    index = _get_kp_index(db)
    hits: dict[int, dict] = {}
    # KP 命中：倒排取候选、逐词累积交集；输出按 KP id 升序（与全量扫描顺序一致）
    kp_common: dict[int, set[str]] = {}
    for t in tokens:
        for kp_idx in index["kp_posting"].get(t, ()):
            kp_common.setdefault(kp_idx, set()).add(t)
    for kp_idx in sorted(kp_common):
        row = index["kps"][kp_idx]
        if row["book_id"] == kp.book_id:
            continue  # 与原实现 exclude_book_id 一致
        entry = hits.setdefault(row["book_id"], {"matched_kps": [], "rag_hits": []})
        entry["matched_kps"].append(
            {
                "id": row["id"],
                "title": row["title"],
                "level": row["level"],
                "chapter_id": row["chapter_id"],
                "para_pos": row["para_pos"],
                "common": sorted(kp_common[kp_idx])[:6],
            }
        )
    # RAG key_points 命中：倒排先筛候选书，候选书内按资产顺序取第一条命中文本
    rag_candidates: set[int] = set()
    for t in tokens:
        for book_idx, _e_idx in index["rag_posting"].get(t, ()):
            rag_candidates.add(index["rag_books"][book_idx][0])
    for _book_idx, (book_id, entries) in enumerate(index["rag_books"]):
        if book_id == kp.book_id or book_id not in rag_candidates:
            continue
        for kp_text, toks in entries:
            if toks & tokens:
                entry = hits.setdefault(book_id, {"matched_kps": [], "rag_hits": []})
                entry["rag_hits"].append(kp_text[:120])
                break  # 每书 RAG 至多记一条提示

    books: list[dict] = []
    for b in list_books_by_ids(db, list(hits)):
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
    books = books or list_books(db)
    clusters = assign_clusters(db, books, persist=False)
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
    relations = list_relations(db)
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

def rebuild_all_graph(db: Session, on_progress=None) -> dict:
    """重建全部图谱：先逐书重建内部图，再重算跨书关联并触发本地联动沉淀。

    on_progress(progress, stage)：可选进度回调（决策 35 权重 20/50/30：
    书内图 0→20、跨书 20→70、联动 70→100）。
    """
    books = list_books(db)
    total = max(1, len(books))
    for idx, b in enumerate(books):
        if on_progress:
            on_progress(5 + 15 * idx // total, f"重建《{b.title}》书内图谱")
        build_intra_book_graph(db, b)
    if on_progress:
        on_progress(20, "重算跨书关联")
    compute_cross_book_graph(db)
    # 本地 RAG 联动存根（强度 ≥ 50 的关联补 linked_books / domain_terms，内容未变化不写）
    if on_progress:
        on_progress(70, "补本地联动存根")

    linked = link_graph_assets(db)
    if on_progress:
        on_progress(100, "图谱重建完成")
    return {
        "books": len(books),
        "relations": count_relations(db),
        "knowledge_points": count_knowledge_points(db),
        "linked": linked["stubs"],
    }

