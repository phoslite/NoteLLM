"""两阶段聚类：post-classify 落盘、簇合并/重命名、pre-classify 领域聚类。

聚类结果落盘缓存（性能优化第一梯队，docs/性能优化路径.md §4）：
- 缓存文件 `data/cache/graph_clusters.json`，每书记录「判定签名 + 簇名」；
- 签名覆盖内容 hash / 标题作者 / tag / 文件夹名 / 资产版本，任一变化自动失效；
- 打开谱系图（assign_clusters）时全部命中直接返回，不再全量重算与回写 DB。
"""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utcnow
from app.models.asset import BookAsset
from app.models.book import Book, Folder
from app.repositories.assets import get_asset, read_asset_content
from app.repositories.books import book_tags
from app.services.graph.keywords import book_keywords, sanitize_cluster_name
from app.services.graph.lexicon import (
    _GENERIC_DOMAIN_TERMS,
    _domain_candidates,
    _first_meaningful_term,
    _pick_domain_name,
    _posterior_keywords,
    cache_domain_term,
    load_domain_lexicon,
)

T_POST = 3

T_MERGE = 5


def _cluster_cache_path() -> Path:
    """聚类结果落盘缓存路径（性能优化第一梯队）：data/cache/graph_clusters.json。"""
    return settings.data_dir / "cache" / "graph_clusters.json"


def _load_cluster_cache() -> dict:
    """读取聚类缓存；缺失/损坏返回空（全量重算并回写）。"""
    try:
        data = json.loads(_cluster_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cluster_cache(data: dict) -> None:
    """原子写聚类缓存（先写 .tmp 再替换）；写失败不影响主流程。"""
    path = _cluster_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _population_signature(sigs: dict[int, str]) -> str:
    """群体签名：全部书籍判定签名排序后整体哈希——任一书变化都会使整体签名变化。"""
    payload = json.dumps({str(k): v for k, v in sorted(sigs.items())}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cluster_signatures(db: Session, books: list[Book]) -> tuple[dict[int, str], dict[int, str]]:
    """聚类判定签名与文件夹名映射：内容/标题作者/标签/文件夹/资产版本任一变化 → 签名变化 → 缓存失效。"""
    folder_ids = {b.folder_id for b in books if b.folder_id}
    names: dict[int, str] = {}
    if folder_ids:
        rows = db.query(Folder).filter(Folder.id.in_(folder_ids)).all()
        names = {f.id: sanitize_cluster_name(f.name) for f in rows}
    sigs: dict[int, str] = {}
    folder_names: dict[int, str] = {}
    for b in books:
        folder_names[b.id] = names.get(b.folder_id or 0, "")
        parts = {
            "content_hash": b.content_hash or "",
            "title": b.title or "",
            "author": b.author or "",
            "tags": book_tags(b),
            "folder": folder_names[b.id],
            "classify_source": b.classify_source,
            "classify_version": b.classify_version or 0,
            "cluster_name": b.cluster_name or "",
        }
        sigs[b.id] = hashlib.sha256(
            json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
    return sigs, folder_names

def _classify_version_map(db: Session, book_ids: list[int]) -> dict[int, int]:
    """批量取书籍当前资产版本（懒校验 post-classify 是否失效用）。"""
    if not book_ids:
        return {}
    rows = (
        db.query(BookAsset.book_id, func.max(BookAsset.version))
        .filter(BookAsset.book_id.in_(book_ids))
        .group_by(BookAsset.book_id)
        .all()
    )
    return dict(rows)

def _write_classify(db: Session, book: Book, name: str, source: str, version: int) -> None:
    """落盘聚类归属（§9.5 两阶段分类）：聚类名统一清洗，值未变化不写库。"""
    name = sanitize_cluster_name(name) or name  # 清洗后为空则保留原值兜底
    if book.cluster_name == name and book.classify_source == source and book.classify_version == version:
        return
    book.cluster_name = name
    book.classify_source = source
    book.classified_at = utcnow()
    book.classify_version = version
    db.commit()
    db.refresh(book)

def post_classify_book(db: Session, book: Book) -> str:
    """两阶段分类 post-classify（知识图谱聚类算法文档 §9）：基于 RAG 资产后验信息修正该书聚类归属。

    规则：用户 tag/文件夹为硬约束（不改动用户意图）；否则以后验关键词做
    簇内一致性校验（重叠 ≥ T_POST 维持）→ 簇迁移（其它簇最高重叠 ≥ T_POST）→
    维持 pre 簇；落盘 cluster_name / classify_source=post / classified_at / classify_version。
    """
    asset = get_asset(db, book.id, "rag")
    if not asset:
        return book.cluster_name or ""
    version = asset.version
    tags = [t for t in (sanitize_cluster_name(t) for t in book_tags(book)) if t]
    if tags:
        _write_classify(db, book, tags[0], "tag", version)
        return tags[0]
    if book.folder_id:
        folder = db.get(Folder, book.folder_id)
        folder_name = sanitize_cluster_name(folder.name) if folder else ""
        if folder_name:
            _write_classify(db, book, folder_name, "folder", version)
            return folder_name

    posterior = _posterior_keywords(read_asset_content(db, book.id, "rag"))
    if not posterior:
        return book.cluster_name or ""

    others: list[tuple[Book, dict[str, float]]] = []
    for ob in (
        db.query(Book)
        .filter(Book.id != book.id, Book.classify_source == "post", Book.cluster_name.isnot(None))
        .all()
    ):
        content = read_asset_content(db, ob.id, "rag")
        if content:
            others.append((ob, _posterior_keywords(content)))

    def _cluster_repr(name: str) -> set[str]:
        keys: set[str] = set()
        for ob, kws in others:
            if ob.cluster_name == name:
                keys |= set(kws)
        return keys

    current = book.cluster_name or ""
    current_overlap = len(set(posterior) & _cluster_repr(current)) if current else 0
    if current_overlap >= T_POST:
        _write_classify(db, book, current, "post", version)
        return current

    best, best_overlap = current, current_overlap
    seen: set[str] = set()
    for ob, _kws in others:
        if ob.cluster_name in seen:
            continue
        seen.add(ob.cluster_name)
        ov = len(set(posterior) & _cluster_repr(ob.cluster_name))
        if ov > best_overlap:
            best, best_overlap = ob.cluster_name, ov
    if best and best_overlap >= T_POST and best != current:
        _write_classify(db, book, best, "post", version)
        return best
    if current:
        _write_classify(db, book, current, "post", version)
        return current
    name = _first_meaningful_term(posterior)
    cache_domain_term(name)
    _write_classify(db, book, name, "post", version)
    return name

def _union_keywords(by_book: dict[int, dict], members: list[Book]) -> set[str]:
    """簇内各书后验关键词并集（簇代表特征）。"""
    keys: set[str] = set()
    for m in members:
        keys |= set(by_book.get(m.id, {}))
    return keys

def merge_and_rename_clusters(db: Session) -> dict:
    """post-classify 簇合并（§9.4.4）与代表性术语重命名（§9.4.5）。

    - 合并：两簇代表特征（后验关键词并集）重叠 ≥ T_MERGE → 并入书更多的主簇；
    - 重命名：簇名取簇内出现于最多书的后验术语（众数），冲突时跳过。
    - 只处理 classify_source=post 的书；tag/文件夹硬约束不受影响。
    """
    books = (
        db.query(Book)
        .filter(Book.classify_source == "post", Book.cluster_name.isnot(None))
        .all()
    )
    if not books:
        return {"merged": 0, "renamed": 0}
    by_book: dict[int, dict] = {}
    for b in books:
        by_book[b.id] = _posterior_keywords(read_asset_content(db, b.id, "rag"))

    clusters: dict[str, list[Book]] = defaultdict(list)
    for b in books:
        clusters[b.cluster_name].append(b)

    merged = 0
    changed = True
    while changed:
        changed = False
        names = list(clusters)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if a not in clusters or b not in clusters or a == b:
                    continue
                overlap = len(_union_keywords(by_book, clusters[a]) & _union_keywords(by_book, clusters[b]))
                if overlap >= T_MERGE:
                    main, sub = (a, b) if len(clusters[a]) >= len(clusters[b]) else (b, a)
                    clusters[main].extend(clusters[sub])  # 被并入的书并入主簇成员，保证重命名/再合并覆盖全部书
                    for book in clusters[sub]:
                        book.cluster_name = main
                    del clusters[sub]
                    merged += 1
                    changed = True
                    break
            if changed:
                break

    renamed = 0
    used_names = set(clusters)
    for name, members in list(clusters.items()):
        counts: Counter = Counter()
        for m in members:
            for k in by_book.get(m.id, {}):
                counts[k] += 1
        if not counts:
            continue
        user, cached = load_domain_lexicon()
        top = ""
        for t, _c in counts.most_common():
            if t in user:
                top = t
                break
        if not top:
            for t, _c in counts.most_common():
                if t in cached:
                    top = t
                    break
        if not top:
            top = next((t for t, _c in counts.most_common() if t not in _GENERIC_DOMAIN_TERMS), "")
        top = sanitize_cluster_name(top) or name
        if top == name or top in used_names:
            continue
        for m in members:
            m.cluster_name = top
        clusters[top] = clusters.pop(name)
        used_names.discard(name)
        used_names.add(top)
        cache_domain_term(top)
        renamed += 1

    # 兜底清洗：历史遗留含标点的簇名（tag/文件夹来源）统一清洗，与现有簇名冲突则跳过
    for name, members in list(clusters.items()):
        clean = sanitize_cluster_name(name)
        if not clean or clean == name or clean in clusters:
            continue
        for m in members:
            m.cluster_name = clean
        clusters[clean] = clusters.pop(name)
        renamed += 1

    db.commit()
    return {"merged": merged, "renamed": renamed}

def assign_clusters(db: Session, books: list[Book] | None = None) -> dict[int, str]:
    """聚类分层：post 落盘（未失效）→ tag → 文件夹名 → 领域自动聚类；仍无归属归「其他」。

    获得 RAG/Skill 资产后的书由 post_classify_book 落盘 cluster_name（§9 两阶段分类），
    只要资产版本未变这里直接采用；否则实时重算并回写 classify_source/classified_at/classify_version。
    结果带落盘缓存：聚类是**全局群体依赖**的，缓存以「全书库签名」为键——
    同一批书（内容/tag/文件夹/资产版本均未变）重复打开谱系图直接命中，不再全量重算；
    任一书变化（增删改/归档）→ 群体签名变化 → 自动失效重算。
    """
    books = books or db.query(Book).order_by(Book.id).all()
    sigs: dict[int, str] = {}
    folder_names: dict[int, str] = {}
    if books:
        sigs, folder_names = _cluster_signatures(db, books)
        pop_sig = _population_signature(sigs)
        cache = _load_cluster_cache()
        if cache.get("population") == pop_sig:
            entries = cache.get("books") or {}
            if all(str(b.id) in entries for b in books):
                return {b.id: entries[str(b.id)]["cluster"] for b in books}
    versions = _classify_version_map(db, [b.id for b in books])
    result: dict[int, str] = {}
    pending: list[Book] = []
    for b in books:
        if b.classify_source == "post" and b.cluster_name and b.classify_version == versions.get(b.id):
            result[b.id] = b.cluster_name
        else:
            pending.append(b)

    keywords = {b.id: book_keywords(b, 40) for b in pending}
    for b in pending:
        tags = [t for t in (sanitize_cluster_name(t) for t in book_tags(b)) if t]
        if tags:
            result[b.id] = tags[0]
            continue
        folder_name = folder_names[b.id]
        if folder_name:
            result[b.id] = folder_name
            continue
        result[b.id] = ""  # 待领域聚类

    # 领域自动聚类：先按相似度成簇（吸收），再统一按专业术语命名
    groups: list[list[Book]] = []
    for b in pending:
        if result.get(b.id):
            continue
        kb = keywords.get(b.id, {})
        if not kb:
            result[b.id] = "其他"
            continue
        group = [b]
        result[b.id] = "\x00"  # 临时占位，避免重复归组
        for other in pending:
            if other.id == b.id or result.get(other.id):
                continue
            ko = keywords.get(other.id, {})
            common = set(kb) & set(ko)
            if common and sum(min(kb[t], ko[t]) for t in common) >= 2:
                group.append(other)
                result[other.id] = "\x00"
        groups.append(group)

    # 命名：候选词 = 章节标题/清洗后书名/正文 + RAG 后验，按簇内覆盖书数与词频挑领域专业术语
    candidates: dict[int, dict[str, float]] = {}
    for b in pending:
        posterior = read_asset_content(db, b.id, "rag") or None
        candidates[b.id] = _domain_candidates(b, posterior)
    for group in groups:
        name = _pick_domain_name(candidates, group)
        if not name:
            kb = keywords.get(group[0].id, {})
            name = next(iter(kb), "其他")
        if name and name != "其他":
            cache_domain_term(name)
        for m in group:
            result[m.id] = name

    # 回写 classify 字段（post 未失效的书不动）
    now = utcnow()
    for b in books:
        if b.classify_source == "post" and b.classify_version == versions.get(b.id):
            continue
        name = result.get(b.id) or "其他"
        tags = [t for t in (sanitize_cluster_name(t) for t in book_tags(b)) if t]
        if tags:
            src = "tag"
        elif b.folder_id:
            src = "folder" if folder_names[b.id] else "pre"
        else:
            src = "pre"
        if b.cluster_name != name or b.classify_source != src or b.classify_version != versions.get(b.id, 0):
            b.cluster_name = name
            b.classify_source = src
            b.classified_at = now
            b.classify_version = versions.get(b.id, 0)
    db.commit()
    # 写回落盘缓存（下次打开谱系图直接命中；任一书内容/tag/文件夹/资产版本变化由群体签名失效）
    if books:
        _save_cluster_cache(
            {
                "population": _population_signature(sigs),
                "books": {str(b.id): {"cluster": result.get(b.id) or "其他"} for b in books},
            }
        )
    return result
