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

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utcnow
from app.models.book import Book
from app.repositories.assets import get_asset, read_asset_content
from app.repositories.books import book_tags
from app.repositories.graph import (
    asset_classify_versions,
    list_books,
    list_folders_by_ids,
    list_post_classified_books,
)
from app.services.graph.keywords import book_keywords, sanitize_cluster_name
from app.services.graph.lexicon import (
    _GENERIC_DOMAIN_TERMS,
    _domain_candidates,
    _first_meaningful_term,
    _pick_domain_name,
    _posterior_keywords,
    cache_domain_term,
    load_domain_lexicon,
    load_synonym_aliases,
)
from app.services.graph.similarity import idf_weights, pair_similarity
from app.services.graph.terms import canonical_terms
from app.services.graph.thresholds import (
    ANTI_ABSORB,
    BLOAT_ADAPT_MIN_N,
    BLOAT_ADAPT_STEP,
    BLOAT_FACTOR,
    BLOAT_HUB_DEGREE_RATIO,
    BLOAT_HUB_FRACTION,
    BLOAT_MAX,
    FRAGMENT_RECHECK_RATIO,
    GENERIC_MIN_N,
    IDF_CUT,
    LPA_MAX_ITER,
    MAX_SPLIT_DEPTH,
    MIN_SHARED_TERMS,
    TAU_CLUSTER,
)

T_POST = 3

T_MERGE = 5

# L4 成簇引擎版本：缓存键版本化，升级一次性全量重算（蓝本 §1.2 迁移策略）
CLUSTER_ALGO_VERSION = 2


def _algo_params_signature() -> str:
    """聚类参数签名：影响成簇结果的参数任一变化 → 缓存自动失效（免手动清缓存）。

    CLUSTER_ALGO_VERSION 管「引擎实现变更」（bump 版本号）；
    algo_params 管「参数调优」（τ/bloat/IDF/回检因子等，2026-08-10 决策）。
    """
    params = {
        "tau_cluster": TAU_CLUSTER,
        "min_shared_terms": MIN_SHARED_TERMS,
        "idf_cut": IDF_CUT,
        "generic_min_n": GENERIC_MIN_N,
        "cluster_use_lpa": settings.cluster_use_lpa,
        "lpa_max_iter": LPA_MAX_ITER,
        "anti_absorb": ANTI_ABSORB,
        "max_split_depth": MAX_SPLIT_DEPTH,
        "bloat": BLOAT_FACTOR,
        "bloat_adapt_min_n": BLOAT_ADAPT_MIN_N,
        "bloat_hub_degree_ratio": BLOAT_HUB_DEGREE_RATIO,
        "bloat_hub_fraction": BLOAT_HUB_FRACTION,
        "bloat_adapt_step": BLOAT_ADAPT_STEP,
        "bloat_max": BLOAT_MAX,
        "fragment_recheck_ratio": FRAGMENT_RECHECK_RATIO,
        "lexicon_state": _lexicon_state_signature(),
    }
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _lexicon_state_signature() -> str:
    """词库输入态签名（A-I2）：泛词集 + 用户区术语 + 同义词映射。

    系统缓存区是聚类运行自动追加的输出，若计入签名会导致自失效（写词库→签名变→缓存永不命中），
    故只覆盖用户可编辑的输入面；用户手动改缓存区后如遇缓存未失效，改用户区任一词或 bump 版本即可。
    """
    user, _cached = load_domain_lexicon()
    aliases = load_synonym_aliases()
    payload = json.dumps(
        {
            "generic": sorted(_GENERIC_DOMAIN_TERMS),
            "user": sorted(user),
            "aliases": sorted(aliases.items()),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cluster_cache_path() -> Path:
    """聚类结果落盘缓存路径（性能优化第一梯队）：data/cache/graph_clusters.json。"""
    return settings.data_dir / "cache" / "graph_clusters.json"


def _load_cluster_cache() -> dict:
    """读取聚类缓存；缺失/损坏/旧算法版本返回空（全量重算并回写）。"""
    try:
        data = json.loads(_cluster_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("algo_version") != CLUSTER_ALGO_VERSION:
        return {}
    if data.get("algo_params") != _algo_params_signature():
        return {}
    return data


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


def _cluster_signatures(
    db: Session,
    books: list[Book],
    include_asset_version: bool = True,
) -> tuple[dict[int, str], dict[int, str]]:
    """聚类判定签名与文件夹名映射：内容/标题作者/标签/文件夹/资产版本任一变化 → 签名变化 → 缓存失效。

    include_asset_version（M-1 修复）：L3 起 book_keywords 以权重 3.0 把 RAG 资产文本纳入
    聚类向量；资产内容变更但 classify_version 未联动（如删除资产条目仅 version+1、图谱联动
    存根不 bump 版本）时，签名不含资产版本会让缓存命中陈旧簇名——故默认把资产版本并入签名
    （复用 asset_classify_versions 批量查询，一次取全）；不消费 RAG 文本的调用方可传 False
    避免签名膨胀导致缓存频繁失效。签名变化会使现有 graph_clusters.json 缓存失效一次（可接受）。
    """
    folder_ids = {b.folder_id for b in books if b.folder_id}
    names: dict[int, str] = {}
    if folder_ids:
        rows = list_folders_by_ids(db, folder_ids)
        names = {f.id: sanitize_cluster_name(f.name) for f in rows}
    versions: dict[int, int] = {}
    if include_asset_version and books:
        versions = _classify_version_map(db, [b.id for b in books])
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
        if include_asset_version:
            parts["asset_version"] = versions.get(b.id, 0)
        sigs[b.id] = hashlib.sha256(
            json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
    return sigs, folder_names

def _classify_version_map(db: Session, book_ids: list[int]) -> dict[int, int]:
    """批量取书籍当前资产版本（懒校验 post-classify 是否失效用，查询下沉仓储）。"""
    return asset_classify_versions(db, book_ids)

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
        folders = list_folders_by_ids(db, {book.folder_id})
        folder_name = sanitize_cluster_name(folders[0].name) if folders else ""
        if folder_name:
            _write_classify(db, book, folder_name, "folder", version)
            return folder_name

    posterior = _posterior_keywords(read_asset_content(db, book.id, "rag"))
    if not posterior:
        return book.cluster_name or ""

    others: list[tuple[Book, dict[str, float]]] = []
    for ob in list_post_classified_books(db, exclude_book_id=book.id):
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

def _cluster_keywords(by_book: dict[int, dict], members: list[Book]) -> set[str]:
    """簇代表特征（剔除数学/学术泛词），防止仅共享泛词导致错误合并（F6 修复）。"""
    kw = _union_keywords(by_book, members)
    return {k for k in kw if k not in _GENERIC_DOMAIN_TERMS}


def merge_and_rename_clusters(db: Session) -> dict:
    """post-classify 簇合并（§9.4.4）与代表性术语重命名（§9.4.5）。

    - 合并：两簇代表特征（后验关键词并集）重叠 ≥ T_MERGE → 并入书更多的主簇；
    - 重命名：簇名取簇内出现于最多书的后验术语（众数），冲突时跳过。
    - 只处理 classify_source=post 的书；tag/文件夹硬约束不受影响。
    """
    books = list_post_classified_books(db)
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
                overlap = len(_cluster_keywords(by_book, clusters[a]) & _cluster_keywords(by_book, clusters[b]))
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

class _UnionFind:
    """自研并查集：路径压缩 + 按秩合并（蓝本 §3.2；确定性：固定 union 顺序）。"""

    def __init__(self, nodes: list[int]) -> None:
        self.parent = {x: x for x in nodes}
        self.rank = {x: 0 for x in nodes}

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True


def _build_sim_graph(
    node_ids: list[int], vectors: dict[int, dict[str, float]], idf: dict[str, float], tau: float,
) -> dict:
    """相似度成图（蓝本 §1.1）：Sim ≥ τ 建无向加权边；共享规范词 ≥2 剪枝。

    返回 {"nodes": 升序节点, "adj": 双向邻接表, "shared_terms": {(min,max): top5 规范词}}。
    """
    nodes = sorted(node_ids)
    adj: dict[int, dict[int, float]] = {}
    shared: dict[tuple[int, int], list[str]] = {}
    for i, a_id in enumerate(nodes):
        wa = vectors.get(a_id)
        if not wa:
            continue
        for b_id in nodes[i + 1 :]:
            wb = vectors.get(b_id)
            if not wb:
                continue
            result = pair_similarity(wa, wb, idf, tau)
            if result is None:
                continue
            sim, reasons = result
            adj.setdefault(a_id, {})[b_id] = sim
            adj.setdefault(b_id, {})[a_id] = sim
            shared[(a_id, b_id)] = reasons
    return {"nodes": nodes, "adj": adj, "shared_terms": shared}


def _connected_components(graph: dict) -> list[list[int]]:
    """自研连通分量（蓝本 Step 2）：并查集基线，各分量成员升序、分量按首成员升序。"""
    uf = _UnionFind(graph["nodes"])
    for u in graph["nodes"]:
        for v in graph["adj"].get(u, {}):
            if u < v:
                uf.union(u, v)
    groups: dict[int, list[int]] = defaultdict(list)
    for x in graph["nodes"]:
        groups[uf.find(x)].append(x)
    return [sorted(m) for m in groups.values()]


def _intra_avg_sim(members: list[int], adj: dict[int, dict[int, float]]) -> float:
    """簇内平均两两 Sim（无边对计 0；蓝本 §2.3 虚胖判定）。"""
    n = len(members)
    if n < 2:
        return 1.0
    total = 0.0
    for i in range(n):
        u = members[i]
        for v in members[i + 1 :]:
            total += adj.get(u, {}).get(v, 0.0)
    return total / (n * (n - 1) / 2)


def _cluster_hub_fraction(members: list[int], adj: dict[int, dict[int, float]]) -> float:
    """簇内枢纽度（O9 b）：度 ≥ (m-1)×BLOAT_HUB_DEGREE_RATIO 的节点占比；m<4 返回 0。"""
    m = len(members)
    if m < 4:
        return 0.0
    degrees = [sum(1 for y in members if y != x and adj.get(x, {}).get(y, 0.0) > 0.0) for x in members]
    hub_threshold = (m - 1) * BLOAT_HUB_DEGREE_RATIO
    return sum(1 for d in degrees if d >= hub_threshold) / m


def effective_bloat_factor(
    groups: list[list[int]], vectors: dict[int, dict[str, float]],
    idf: dict[str, float], tau: float, n_books: int,
) -> float:
    """分裂强度自适应（O9 b）：书籍数 ≥ BLOAT_ADAPT_MIN_N 起启用「枢纽度」检测——
    簇内枢纽节点占比 > BLOAT_HUB_FRACTION 判定枢纽链，bloat 提一档（0.8→1.0）；
    占比 > 2 倍阈值再提一档（1.2 上限）；未达标或未达门槛维持 BLOAT_FACTOR。"""
    if n_books < BLOAT_ADAPT_MIN_N:
        return BLOAT_FACTOR
    adj = _build_sim_graph([x for g in groups for x in g], vectors, idf, tau)["adj"]
    worst = max((_cluster_hub_fraction(g, adj) for g in groups), default=0.0)
    if worst > BLOAT_HUB_FRACTION * 2:
        return min(BLOAT_FACTOR + 2 * BLOAT_ADAPT_STEP, BLOAT_MAX)
    if worst > BLOAT_HUB_FRACTION:
        return min(BLOAT_FACTOR + BLOAT_ADAPT_STEP, BLOAT_MAX)
    return BLOAT_FACTOR


def _split_bloated_clusters(
    vectors: dict[int, dict[str, float]], idf: dict[str, float],
    groups: list[list[int]], tau: float, bloat: float = BLOAT_FACTOR, depth: int = 0,
) -> list[list[int]]:
    """虚胖簇分裂守卫（蓝本 §2.3）：成员 ≥4 且簇内平均 Sim < τ×bloat
    → 以更高阈值（τ×1.5）在子图重连通；递归深度 ≤2，切不开保留。"""
    if depth >= MAX_SPLIT_DEPTH:
        return groups
    main_adj = _build_sim_graph([x for g in groups for x in g], vectors, idf, tau)["adj"]
    out: list[list[int]] = []
    for g in groups:
        if len(g) < 4 or _intra_avg_sim(g, main_adj) >= tau * bloat:
            out.append(g)
            continue
        sub_graph = _build_sim_graph(g, vectors, idf, tau * 1.5)
        sub_groups = [m for m in _connected_components(sub_graph) if m]
        if len(sub_groups) <= 1:
            out.append(g)
            continue
        out.extend(_split_bloated_clusters(vectors, idf, sub_groups, tau, bloat, depth + 1))
    return out


def _merge_fragments(
    groups: list[list[int]], base_size: dict[int, int],
    vectors: dict[int, dict[str, float]], idf: dict[str, float], tau: float,
) -> list[list[int]]:
    """碎片合并回检（O9）：分裂产生的单点碎片（原属 ≥2 书分量）并入与其 Sim
    最高的相邻簇（阈值 τ×0.8）；确定性：书 id 升序处理，平局取簇序号小者。"""
    threshold = tau * FRAGMENT_RECHECK_RATIO
    # m-8 修复：相似度是静态纯函数、每节点唯一归属——单点碎片并入后其余碎片的
    # best-sim 取值不变（并入只改变候选组身份与组列表顺序，平局口径与旧实现一致），
    # 原「while changed 重启全量重算」等价收敛为按书 id 升序的单趟批量并入
    # （并入后组列表原位更新），最坏复杂度 O(n³)→O(n²)，输出与旧实现一致。
    fragments = sorted(
        (g for g in groups if len(g) == 1 and base_size.get(g[0], 0) >= 2),
        key=lambda m: m[0],
    )
    for g in fragments:
        if g not in groups or len(g) != 1:
            continue  # 已并入他簇 / 已随他簇合并（不再是单点）
        x = g[0]
        best_s, best_g = -1.0, None
        for og in groups:
            if og is g or not og:
                continue
            for y in og:
                result = pair_similarity(vectors.get(x, {}), vectors.get(y, {}), idf, threshold)
                if result is not None and result[0] > best_s:
                    best_s, best_g = result[0], og
        if best_g is not None and best_s >= threshold:
            best_g.append(x)
            best_g.sort()
            groups.remove(g)
    return groups


def _weighted_lpa(
    graph: dict,
    tau: float,
    max_iter: int = LPA_MAX_ITER,
    guard: float = ANTI_ABSORB,
    tiebreak_by_popularity: bool = True,
) -> list[list[int]]:
    """加权标签传播（A3：cluster_use_lpa 开启时替代连通分量基线）：
    固定 seed 书 id 升序遍历，平局取簇规模大者，防吞并守卫 1.05。

    M-3 修复：标签流行度在迭代前预计算 Counter(labels.values())，标签变更时增量维护
    （每次只更新新旧两个标签计数），复杂度由 O(iter×n×deg) 降为 O(iter×Σdeg)；
    tiebreak_by_popularity=False 时平局按候选标签首次出现顺序（评估集对照用）。
    """
    nodes = graph["nodes"]
    adj = graph["adj"]
    labels = {v: v for v in nodes}
    popularity = Counter(labels.values())
    for _ in range(max_iter):
        changed = False
        for v in sorted(nodes):
            nbrs = list(adj.get(v, {}).items())
            if not nbrs:
                continue
            scores: dict[int, float] = defaultdict(float)
            for u, s in nbrs:
                scores[labels[u]] += s
            if tiebreak_by_popularity:
                best = max(scores, key=lambda c: (scores[c], -popularity[c]))
            else:
                best = max(scores, key=lambda c: scores[c])
            cur = labels[v]
            cur_w = sum(s for u, s in nbrs if labels[u] == cur)
            if best != cur and scores[best] > cur_w * guard:
                labels[v] = best
                popularity[best] += 1
                popularity[cur] -= 1
                changed = True
        if not changed:
            break
    groups: dict[int, list[int]] = defaultdict(list)
    for v in nodes:
        groups[labels[v]].append(v)
    return [sorted(m) for m in groups.values()]


def assign_clusters(db: Session, books: list[Book] | None = None, persist: bool = True) -> dict[int, str]:
    """聚类分层：post 落盘（未失效）→ tag → 文件夹名 → 领域自动聚类；仍无归属归「其他」。

    获得 RAG/Skill 资产后的书由 post_classify_book 落盘 cluster_name（§9 两阶段分类），
    只要资产版本未变这里直接采用；否则实时重算并回写 classify_source/classified_at/classify_version。
    结果带落盘缓存：聚类是**全局群体依赖**的，缓存以「全书库签名」为键——
    persist=False 时（GET 只读链路）仅返回结果，不写库也不写缓存；落盘交给导入/后台任务。
    同一批书（内容/tag/文件夹/资产版本均未变）重复打开谱系图直接命中，不再全量重算；
    任一书变化（增删改/归档）→ 群体签名变化 → 自动失效重算。
    """
    books = books or list_books(db)
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

    # 领域自动聚类（L4 成簇引擎）：IDF 加权余弦成图（τ_cluster）→ 连通分量（或加权 LPA）
    # → 虚胖分裂守卫 → 碎片回检 → 统一按专业术语命名
    pending_ids = [b.id for b in pending if not result.get(b.id)]
    raw_vectors: dict[int, dict[str, float]] = {}
    for b in pending:
        if not result.get(b.id):
            raw_vectors[b.id] = canonical_terms(book_keywords(b, 80, db=db))
    # 聚类向量剔除数学/学术泛词（F6）：仅共享「定理/定义」等泛词的书不得成簇/吸收
    vectors = {
        b_id: {term: w for term, w in kw.items() if term not in _GENERIC_DOMAIN_TERMS}
        for b_id, kw in raw_vectors.items()
    }
    groups: list[list[Book]] = []
    if pending_ids:
        idf = idf_weights(vectors)
        graph = _build_sim_graph(pending_ids, vectors, idf, TAU_CLUSTER)
        if settings.cluster_use_lpa:
            group_ids = _weighted_lpa(graph, TAU_CLUSTER)
        else:
            group_ids = _connected_components(graph)
        bloat = effective_bloat_factor(group_ids, vectors, idf, TAU_CLUSTER, len(pending_ids))
        group_ids = _split_bloated_clusters(vectors, idf, group_ids, TAU_CLUSTER, bloat)
        base_size = {m: len(c) for c in _connected_components(graph) for m in c}
        group_ids = _merge_fragments(group_ids, base_size, vectors, idf, TAU_CLUSTER)
        groups = [[b for b in pending if b.id in g] for g in group_ids]

    # 命名：候选词 = 章节标题/清洗后书名/正文 + RAG 后验，按簇内覆盖书数与词频挑领域专业术语
    candidates: dict[int, dict[str, float]] = {}
    for b in pending:
        posterior = read_asset_content(db, b.id, "rag") or None
        candidates[b.id] = _domain_candidates(b, posterior)
    for group in groups:
        name = _pick_domain_name(candidates, group)
        if not name:
            kb = raw_vectors.get(group[0].id, {})
            name = next(iter(kb), "其他")
        if name and name != "其他" and persist:
            cache_domain_term(name)
        for m in group:
            result[m.id] = name
    # 无关键词/成图跳过 →「其他」；有词孤立书保留单书簇（与 v1 行为一致，m-4 注释订正）
    for b_id in pending_ids:
        if not result.get(b_id):
            result[b_id] = "其他"

    # 回写 classify 字段（post 未失效的书不动）；persist=False 仅读链路不落盘
    if persist:
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
        # A-C1 修复：缓存键必须用「写库后」状态重算——签名含本次回写的
        # classify_source/cluster_name/classify_version，若用函数入口处的写前签名保存，
        # 下次 GET 从 DB 算出的签名永不相等 → 磁盘缓存退化为摆设、每次打开谱系图全量重算。
        # 此时对象内存态 == commit 后 DB 态（循环已就地赋值），直接复用避免 commit 后逐属性刷新。
        post_sigs: dict[int, str] = {}
        if books:
            post_sigs, _ = _cluster_signatures(db, books)
        db.commit()
        # 写回落盘缓存（下次打开谱系图直接命中；任一书内容/tag/文件夹/资产版本变化由群体签名失效）
        if books:
            _save_cluster_cache(
                {
                    "algo_version": CLUSTER_ALGO_VERSION,
                    "algo_params": _algo_params_signature(),
                    "population": _population_signature(post_sigs),
                    "books": {str(b.id): {"cluster": result.get(b.id) or "其他"} for b in books},
                }
            )
    return result
