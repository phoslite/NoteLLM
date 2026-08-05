"""聚类改进方案验证 demo（独立于主应用，纯标准库，零外部依赖）。

对照验证 docs/知识图谱聚类算法-改进方案.md（已定稿主路线 A+C 组合）：
  A. 术语层：同义词归一化（别名整词折叠，聚类输入）——解决输入质量
  C. 结构层：IDF 加权余弦 → tau 建边 → 自研并查集连通分量 → 虚胖分裂守卫——解决成簇结构
  B. 降级为可选向量辅助信号（feature flag 默认关，demo 仅保留对比）
  D. LLM 降分为离线修正层（别名生成/簇命名/方向证据/打分增强），不进入聚类主循环
  命名层：inject_lexicon 词库术语注入（仅命名用，不污染聚类输入）

内置示例语料复现真实库 D1 问题（「函数/分析/空间」等高 df 泛化词导致
多数书被误吸进一个大簇），便于直观对比三路聚类结果。

用法：
  python demo/clustering_demo.py            # 全部算法 + LLM 降分演示
  python demo/clustering_demo.py --algo ac  # 只跑 A+C 组合
  python demo/clustering_demo.py --input demo/real_corpus.json --eval demo/gold_clusters.json --no-fuse  # 真实库金标评估
  python demo/clustering_demo.py --no-synonyms  # 关闭同义词归一化（对照）
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict

# ---------------------------------------------------------------- 示例语料
# 每本书：(书名, {关键词: 词频})；词频为整数，模拟 extract_keywords 输出。
BOOKS = [
    (7, "泛函分析", {"函数": 6, "空间": 5, "线性": 4, "算子": 4, "拓扑": 3, "巴拿赫": 3, "泛函": 4, "分析": 5}, None),
    (8, "实变函数论", {"函数": 6, "测度": 4, "积分": 4, "勒贝格": 3, "空间": 3, "可测": 3, "分析": 4}, None),
    (9, "变分法基础", {"变分": 5, "泛函": 4, "极值": 4, "欧拉": 3, "微分": 3, "函数": 3}, None),
    (10, "变分学讲义", {"变分": 5, "泛函": 4, "极值": 3, "欧拉": 3, "拉格朗日": 3, "分析": 3}, None),
    (11, "数学分析习题", {"函数": 5, "极限": 4, "导数": 4, "积分": 4, "级数": 3, "连续": 3, "分析": 5}, None),
    (12, "线性代数讲义", {"矩阵": 5, "向量": 4, "线性": 4, "行列式": 3, "特征值": 3, "空间": 3}, None),
    (13, "点集拓扑", {"拓扑": 5, "开集": 4, "紧致": 3, "连通": 3, "连续": 3, "空间": 4, "度量": 3}, None),
    (14, "群论导论", {"群": 5, "子群": 4, "同态": 3, "环": 3, "域": 3, "代数": 3}, None),
    (15, "概率论与数理统计", {"概率": 5, "随机": 4, "分布": 4, "期望": 3, "方差": 3, "统计": 4}, None),
    (16, "数理统计教程", {"统计": 5, "抽样": 3, "估计": 4, "检验": 3, "分布": 3, "假设": 3}, None),
    (17, "在世界的关节处下刀", {"关节": 4, "下刀": 3, "图形": 3, "渲染": 3, "动画": 3, "函数": 2}, None),
]
IDS = [b[0] for b in BOOKS]
N = len(BOOKS)
TITLES = [t for _, t, _, _ in BOOKS]
SAMPLES = [s for _, _, _, s in BOOKS]
KEYWORDS = [k for _, _, k, _ in BOOKS]
NAMING_KEYWORDS = [dict(k) for _, _, k, _ in BOOKS]
INJECTED = [set() for _ in BOOKS]


# ---------------------------------------------------------------- 工具函数
def _norm(vec: dict) -> float:
    return math.sqrt(sum(v * v for v in vec.values()))


def _dot(a: dict, b: dict) -> float:
    return sum(min(a.get(t, 0), b.get(t, 0)) for t in set(a) & set(b))


def _idf() -> dict:
    """语料级 IDF：idf(t) = ln((N+1)/(df(t)+1)) + 1；df/N>0.7 的泛化词再乘 0.2（§2.2）。"""
    df = Counter()
    for kw in KEYWORDS:
        df.update(set(kw))
    out = {}
    for t, d in df.items():
        v = math.log((N + 1) / (d + 1)) + 1
        if d / N > 0.7:
            v *= 0.2
        out[t] = v
    return out


# A. 现行：min 型伪余弦 + 贪心吸收（Σ min >= 2）
def greedy_clusters() -> list[list[int]]:
    result: dict[int, str] = {}
    groups: list[list[int]] = []
    for i, kb in enumerate(KEYWORDS):
        if i in result:
            continue
        group = [i]
        result[i] = chr(0)
        for j in range(N):
            if j == i or j in result:
                continue
            ko = KEYWORDS[j]
            common = set(kb) & set(ko)
            if common and sum(min(kb[t], ko[t]) for t in common) >= 2:
                group.append(j)
                result[j] = chr(0)
        groups.append(group)
    return groups


# ---------------------------------------------------------------- 同义词归一化（改进方案 §2.1 术语层，demo 验证）
# 与 backend/domain_terms.txt 用户区预置的规范词一致；正式版解析上线前仅 demo 使用。
SYNONYM_GROUPS: list[tuple[str, list[str]]] = [
    ("数学分析", ["微积分", "分析学"]),
    ("实变函数", ["实变函数论"]),
    ("复变函数", ["复分析"]),
    ("泛函分析", ["函数分析"]),
    ("变分法", ["变分学", "变分"]),
    ("测度论", ["测度与积分"]),
    ("勒贝格积分", ["勒贝格测度"]),
    ("概率论", ["概率"]),
    ("数理统计", ["统计推断"]),
    ("线性代数", ["高等代数", "矩阵论"]),
    ("抽象代数", ["近世代数"]),
    ("拓扑学", ["点集拓扑"]),
    ("微分几何", ["黎曼几何"]),
    ("微分流形", ["流形"]),
    ("常微分方程", ["ode"]),
    ("偏微分方程", ["pde", "数学物理方程"]),
    ("数值分析", ["计算方法", "数值方法"]),
    ("最优化", ["优化理论", "数学规划"]),
    ("数论", ["初等数论"]),
    ("组合数学", ["组合学"]),
    ("傅里叶分析", ["傅里叶变换", "傅氏变换", "fourier transform"]),
    ("统计物理", ["统计力学"]),
    ("电动力学", ["电磁场理论"]),
    ("计算机视觉", ["机器视觉"]),
    ("自然语言处理", ["nlp"]),
    ("机器学习", ["统计学习"]),
    ("神经网络", ["人工神经网络", "ann"]),
    ("数据结构", ["数据结构与算法"]),
    ("操作系统", ["os"]),
    ("数据库", ["数据库系统", "数据库原理"]),
    ("编译原理", ["编译技术", "编译器设计"]),
    ("分布式系统", ["分布式计算"]),
    ("金融数学", ["数理金融"]),
    ("计量经济学", ["经济计量学"]),
    ("经济学", ["经济理论"]),
    ("微观经济学", ["价格理论"]),
    ("宏观经济学", ["总体经济学"]),
    ("密码学", ["密码编码学"]),
    ("因果推断", ["因果分析"]),
    ("金融", ["固定收益", "固定收益证券", "固收", "fixed income"]),
    ("自然种类", ["natural kinds", "natural kind", "自然类"]),
    ("形而上学", ["本体论", "metaphysics"]),
    ("实在论", ["唯实论", "realism"]),
    ("唯名论", ["nominalism"]),
    ("认识论", ["知识论", "epistemology"]),
    ("科学哲学", ["科学方法论", "philosophy of science"]),
    ("资产定价", ["定价理论"]),
]
_ALIAS_TO_CANONICAL = {a: c for c, aliases in SYNONYM_GROUPS for a in aliases}


def _hit_words(sample: str | None, term_freq: dict) -> list[tuple[str, str]]:
    """词库术语命中（模拟正式版 _lexicon_hits 的子串匹配）：
    规范词/别名在样本文本中命中（中文子串 / 英文子串忽略大小写）；
    无样本时退化为关键词整词命中。返回 [(规范词, 命中的词)]，长词优先按词长降序。"""
    hits: list[tuple[str, str]] = []
    if sample:
        lowered = sample.lower()
        for c, aliases in SYNONYM_GROUPS:
            for w in [c] + aliases:
                if not w:
                    continue
                if re.search(r"[\u4e00-\u9fff]", w):
                    ok = w in sample
                else:
                    ok = w.lower() in lowered
                if ok:
                    hits.append((c, w))
    else:
        for t in term_freq:
            low = t.lower()
            if low in _ALIAS_TO_CANONICAL:
                hits.append((_ALIAS_TO_CANONICAL[low], t))
            else:
                for c, aliases in SYNONYM_GROUPS:
                    if c == low or any(a == low for a in aliases):
                        hits.append((c, t))
                        break
    return sorted(hits, key=lambda h: len(h[1]), reverse=True)


def canonical_terms(term_freq: dict) -> dict:
    """同义词归一化（§2.1 术语层，纯折叠）：
    聚类输入仅做别名整词折叠（别名 → 规范词、权重求和），不做词库注入——
    注入只属于命名层（inject_lexicon），避免高权重术语把聚类成图吸入一簇（真实库 D1 实测）。"""
    out = dict(term_freq)
    for t, v in list(out.items()):
        low = t.lower()
        if low in _ALIAS_TO_CANONICAL:
            c = _ALIAS_TO_CANONICAL[low]
            out[c] = out.get(c, 0.0) + v
            del out[t]
    return out


def inject_lexicon(sample: str | None, term_freq: dict) -> tuple[dict, set]:
    """词库术语注入（§2.1/§2.4 命名层，demo 模拟版）：
    规范词/别名在样本文本中命中（正式版 _lexicon_hits 子串匹配）→ 规范词以 100 权重
    进入命名候选，同时其内部 token 权重 ×0.3（长词优先：如「傅里叶变换」命中时
    「傅里」「里叶」不再独立计分）；无样本文本时退化为关键词整词命中（内置示例库）。
    返回 (命名关键词表, 注入的规范词集合)。"""
    out = dict(term_freq)
    injected: set[str] = set()
    for c, w in _hit_words(sample, term_freq):
        for t in list(out):
            if t != w and t in w:  # 仅抑制命中词内部 token（如「傅里叶变换」→傅里/里叶）；
                                   # 不含「命中词⊂token」方向，避免误压其他规范词（金融 ⊂ 金融数学）
                out[t] = out.get(t, 0.0) * 0.3
        out[c] = max(out.get(c, 0.0), 100.0)  # 术语注入
        injected.add(c)
    # 别名整词折叠（与 canonical_terms 保持一致）
    for t, v in list(out.items()):
        low = t.lower()
        if low in _ALIAS_TO_CANONICAL:
            c = _ALIAS_TO_CANONICAL[low]
            out[c] = out.get(c, 0.0) + v
            del out[t]
    return out, injected


# B. 改进：IDF 加权余弦 + tau_cluster 建边 + 连通分量
def idf_cosine() -> list[list[float]]:
    idf = _idf()
    w = [{t: v * idf[t] for t, v in kw.items()} for kw in KEYWORDS]
    sim = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(i + 1, N):
            common = set(w[i]) & set(w[j])
            s = sum(w[i][t] * w[j][t] for t in common) / (_norm(w[i]) * _norm(w[j]))
            sim[i][j] = sim[j][i] = s
    return sim


def connected_components(sim: list[list[float]], tau: float = 0.10) -> list[list[int]]:
    parent = list(range(N))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(N):
        for j in range(i + 1, N):
            if sim[i][j] >= tau:
                union(i, j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(N):
        groups[find(i)].append(i)
    return [sorted(m) for m in groups.values()]


# AC. A+C 组合（改进方案 §2）：术语归一化 + IDF + 成图 + 自研连通分量 + 虚胖分裂守卫
def build_adj(sim: list[list[float]], tau: float) -> dict[int, dict[int, float]]:
    """相似度成图（蓝本 §1.1）：Sim ≥ τ 建无向加权边，双向邻接表。"""
    adj: dict[int, dict[int, float]] = {i: {} for i in range(N)}
    for i in range(N):
        for j in range(i + 1, N):
            if sim[i][j] >= tau:
                adj[i][j] = adj[j][i] = sim[i][j]
    return adj


class UnionFind:
    """自研并查集：路径压缩 + 按秩合并（蓝本 §3.2；确定性：固定 union 顺序）。"""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # 路径压缩
            x = self.parent[x]
        return x

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


def cc_components(adj: dict[int, dict[int, float]], nodes: list[int]) -> list[list[int]]:
    """自研连通分量：nodes 升序，并查集 union 全部边，输出分量（成员升序）。"""
    uf = UnionFind(N)
    for u in nodes:
        for v in adj.get(u, {}):
            uf.union(u, v)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in nodes:
        groups[uf.find(i)].append(i)
    return [sorted(m) for m in groups.values()]


def _intra_avg_sim(members: list[int], sim: list[list[float]]) -> float:
    """簇内平均两两 Sim（含无边对计 0；蓝本 §2.3 虚胖判定）。"""
    n = len(members)
    if n < 2:
        return 1.0
    return sum(sim[a][b] for a in members for b in members if a < b) / (n * (n - 1) / 2)


def split_bloated(groups: list[list[int]], sim: list[list[float]], tau: float,
                  bloat: float = 0.8, depth: int = 0) -> list[list[int]]:
    """虚胖簇分裂守卫（蓝本 §2.3/§5.4）：成员 ≥4 且簇内平均两两 Sim < τ×bloat
    → 以更高阈值（×1.5）在子图重连通（桥节点断开）；递归深度 ≤2，切不开保留。
    bloat 为分裂强度（demo 敏感性实验参数，正式版阈值见 thresholds.BLOAT_FACTOR=0.8）。"""
    if depth >= 2:
        return groups
    out: list[list[int]] = []
    for g in groups:
        if len(g) < 4 or _intra_avg_sim(g, sim) >= tau * bloat:
            out.append(g)
            continue
        sub = build_adj(sim, tau * 1.5)
        sub_groups = [m for m in cc_components(sub, g) if m]
        if len(sub_groups) <= 1:  # 子图仍连通（切不开）→ 维持原样
            out.append(g)
            continue
        out.extend(split_bloated(sub_groups, sim, tau, bloat, depth + 1))
    return out


def ac_clusters(sim: list[list[float]], tau: float, bloat: float = 0.8) -> list[list[int]]:
    """A+C 主流程：成图(τ) → 自研连通分量 → 虚胖分裂守卫（LPA 默认关，蓝本 P2 基线）。"""
    adj = build_adj(sim, tau)
    return split_bloated(cc_components(adj, list(range(N))), sim, tau, bloat)


# C. 加权标签传播（LPA）：固定 seed 顺序，防吞并守卫 1.05
def label_propagation(sim: list[list[float]], tau: float = 0.10,
                      max_rounds: int = 10, guard: float = 1.05) -> list[list[int]]:
    labels = list(range(N))
    for _ in range(max_rounds):
        changed = False
        for v in sorted(range(N)):  # 固定 seed：book id 升序
            nbrs = [(u, sim[v][u]) for u in range(N) if u != v and sim[v][u] >= tau]
            if not nbrs:
                continue
            scores: dict[int, float] = defaultdict(float)
            for u, s in nbrs:
                scores[labels[u]] += s
            best = max(scores, key=lambda c: (scores[c], -len([x for x in labels if x == c])))
            cur = labels[v]
            cur_w = sum(s for u, s in nbrs if labels[u] == cur)
            if best != cur and scores[best] > cur_w * guard:
                labels[v] = best
                changed = True
        if not changed:
            break
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(N):
        groups[labels[i]].append(i)
    return [sorted(m) for m in groups.values()]


# ---------------------------------------------------------------- 命名（简化版 §2.4）
# 泛化词表对齐正式版 lexicon._GENERIC_DOMAIN_TERMS 核心词（真实库 D1：定理/动机/演化等
# 学术元词高 df 会把多数书误吸进一簇；命名与 IDF 抑制共用同一概念）。
_GENERIC = {
    "函数", "分析", "空间", "线性", "连续", "定理", "定义", "证明", "引理", "推论",
    "方法", "理论", "概念", "性质", "结论", "例子", "公式", "假设", "条件",
    "问题", "结果", "意义", "作用", "方式", "过程", "方面", "部分", "情况",
    "笔记", "习题", "答案", "详解", "教程", "讲义", "目录", "前言", "附录",
    "动机", "演化", "核心", "工具", "本质", "体系",
    # LaTeX/SVG/图片噪声记号（真实库关键词含 mathbf/frac/fill/stroke 等）
    "mathbf", "text", "frac", "infty", "hat", "lambda", "sum", "int",
    "fill", "stroke", "class", "style", "png", "figures", "stroke-width",
    "line", "delta", "alpha", "beta", "gamma", "script", "width", "height",
}  # 命名时剔除


def cluster_name(members: list[int]) -> str:
    """簇命名（命名层，§2.4）：领域名一律中文——
    1. 剔除 _GENERIC 与纯 ASCII/记号 token（如 rate/bond/mathbf）；
    2. 词库注入术语优先（inject_lexicon 命中，如「金融」覆盖 fixed income），
       其次词频累计，平局长词优先（让「自然种类」胜过「种类」）。"""
    cand: Counter = Counter()
    injected: set[str] = set()
    for i in members:
        for t, v in NAMING_KEYWORDS[i].items():
            if t not in _GENERIC and len(t) >= 2 and re.search(r"[\u4e00-\u9fff]", t):
                cand[t] += v
        injected.update(INJECTED[i])
    if not cand:
        return "其他"
    return max(cand, key=lambda t: (t in injected, cand[t], len(t)))


def show(groups: list[list[int]], label: str) -> None:
    print(f"\n=== {label} ===")
    for g in groups:
        names = [f"{i}:{TITLES[i]}" for i in g]
        print(f"  [{cluster_name(g)}]  {', '.join(names)}")


# ---------------------------------------------------------------- 金标评估（--eval）
def load_gold(path: str) -> dict[int, str]:
    """金标簇：{"书id": "簇名"}；返回 {行号: 簇名}（按语料 IDS 映射，未覆盖行跳过）。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    by_id = {int(k): v for k, v in data.items()}
    return {i: by_id[bid] for i, bid in enumerate(IDS) if bid in by_id}


def evaluate(groups: list[list[int]], gold: dict[int, str]) -> dict:
    """聚类质量指标（改进方案 §4）：pair-F、簇纯度、簇数/最大簇/孤立簇。"""
    n = sum(len(g) for g in groups)
    tp = fp = fn = pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            gi, gj = gold.get(i), gold.get(j)
            if gi is None or gj is None:
                continue
            same_gold = gi == gj
            same_cluster = any(i in g and j in g for g in groups)
            pairs += 1
            if same_cluster and same_gold:
                tp += 1
            elif same_cluster and not same_gold:
                fp += 1
            elif not same_cluster and same_gold:
                fn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    pair_f = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    purity = sum(
        max(sum(1 for i in g if gold.get(i) == c) for c in set(gold.get(i) for i in g if i in gold))
        / len(g)
        for g in groups
        if any(i in gold for i in g)
    )
    purity /= sum(1 for g in groups if any(i in gold for i in g))
    return {
        "pair_f": pair_f, "precision": precision, "recall": recall,
        "purity": purity, "clusters": len(groups),
        "max_size": max((len(g) for g in groups), default=0),
        "singletons": sum(1 for g in groups if len(g) == 1),
    }


def eval_row(label: str, groups: list[list[int]], gold: dict[int, str]) -> None:
    m = evaluate(groups, gold)
    print(f"  {label:<28} pairF={m['pair_f']:.3f} P={m['precision']:.3f} R={m['recall']:.3f} "
          f"purity={m['purity']:.3f} 簇数={m['clusters']} 最大簇={m['max_size']} 单点簇={m['singletons']}")


# ---------------------------------------------------------------- D. O3 LLM 降分融合
def llm_fuse_demo() -> None:
    print("\n=== O3 LLM 允许降分融合（0.4*kw + 0.6*llm）===")
    cases = [
        ("现行为 max(kw,llm)=70（LLM 臆测虚高，无法下调）", 30, 70, False),
        ("融合后 0.4*30+0.6*70=54（虚高被拉回）", 30, 70, False),
        ("关键词高分+LLM 高分保持（0.4*80+0.6*75=77）", 80, 75, False),
        ("用户确认边冻结不降（保持 90，不做融合）", 90, 20, True),
    ]
    for desc, kw, llm, frozen in cases:
        if frozen:
            final = kw  # 冻结：保持现价
        else:
            final = round(0.4 * kw + 0.6 * llm)
        print(f"  kw={kw:>3} llm={llm:>3} -> {final:>3}  {desc}")


# ---------------------------------------------------------------- main
def _load_input(path: str | None) -> tuple[int, str]:
    """加载语料：默认内置示例库；--input 为 JSON [{title, keywords}]（真实库导出见 export_real_corpus.py）。"""
    global BOOKS, TITLES, KEYWORDS, SAMPLES, IDS, N
    if not path:
        return N, "内置示例库（复现 D1：函数/分析/空间高 df 泛化词误吸）"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("books") or []
    rows = [(b.get("id", i), b["title"], dict(b.get("keywords") or {}), b.get("sample")) for i, b in enumerate(data) if b.get("title")]
    BOOKS, TITLES, KEYWORDS, SAMPLES = rows, [t for _, t, _, _ in rows], [kw for _, _, kw, _ in rows], [s for _, _, _, s in rows]
    IDS = [b[0] for b in BOOKS]
    N = len(BOOKS)
    return N, f"实际语料 {path}（{N} 本）"


def main() -> None:
    parser = argparse.ArgumentParser(description="聚类改进方案验证 demo")
    parser.add_argument("--algo", choices=["all", "greedy", "cc", "lpa", "ac"], default="all")
    parser.add_argument("--tau", type=float, default=0.10, help="聚类图边门槛（默认 0.10）")
    parser.add_argument("--bloat", type=float, default=0.8, help="分裂守卫强度系数（默认 0.8，敏感性实验用）")
    parser.add_argument("--input", default=None, help="实际语料 JSON [{title, keywords}]")
    parser.add_argument("--no-synonyms", action="store_true", help="关闭同义词归一化（对照）")
    parser.add_argument("--no-fuse", action="store_true", help="跳过 LLM 降分演示")
    parser.add_argument("--eval", default=None, help="金标簇 JSON（书id: 簇名），打印 A/B/C 质量指标")
    args = parser.parse_args()

    count, desc = _load_input(args.input)
    global KEYWORDS, NAMING_KEYWORDS, INJECTED
    if args.no_synonyms:
        NAMING_KEYWORDS = [dict(kw) for kw in KEYWORDS]
        INJECTED = [set() for _ in KEYWORDS]
    else:
        NAMING_KEYWORDS, INJECTED = zip(*[inject_lexicon(s, kw) for kw, s in zip(KEYWORDS, SAMPLES, strict=True)])
        NAMING_KEYWORDS, INJECTED = list(NAMING_KEYWORDS), list(INJECTED)
        KEYWORDS = [canonical_terms(kw) for kw in KEYWORDS]
    sim = idf_cosine()
    print(f"语料 {count} 本（{desc}）；同义词归一化={'开' if not args.no_synonyms else '关'}")
    if args.eval:
        gold = load_gold(args.eval)
        print(f"金标覆盖 {len(gold)}/{count} 本（{args.eval}）")
        if args.algo in ("all", "greedy"):
            eval_row("A 现行贪心吸收", greedy_clusters(), gold)
        if args.algo in ("all", "cc"):
            eval_row(f"B 连通分量 tau={args.tau}", connected_components(sim, args.tau), gold)
        if args.algo in ("all", "lpa"):
            eval_row(f"C 加权LPA tau={args.tau}", label_propagation(sim, args.tau), gold)
        if args.algo in ("all", "ac"):
            eval_row(f"AC A+C自研连通 tau={args.tau} bloat={args.bloat}", ac_clusters(sim, args.tau, args.bloat), gold)
        return
    if args.algo in ("all", "greedy"):
        show(greedy_clusters(), "A 现行：min 伪余弦 + 贪心吸收")
    if args.algo in ("all", "cc"):
        show(connected_components(sim, args.tau), f"B 改进：IDF 余弦 + 连通分量 (tau={args.tau})")
    if args.algo in ("all", "lpa"):
        show(label_propagation(sim, args.tau), f"C 改进：加权标签传播 (tau={args.tau})")
    if args.algo in ("all", "ac"):
        show(ac_clusters(sim, args.tau, args.bloat), f"AC A+C组合：自研连通分量+分裂守卫 (tau={args.tau}, bloat={args.bloat})")
    if not args.no_fuse:
        llm_fuse_demo()


if __name__ == "__main__":
    main()
