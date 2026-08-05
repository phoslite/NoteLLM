"""聚类改进方案验证 demo（独立于主应用，纯标准库，零外部依赖）。

对照验证 docs/知识图谱聚类算法-改进方案.md 中的三处核心改动：
  A. 现行算法：min 型伪余弦 + 贪心吸收成簇（clustering.py 现状）
  B. 改进方案：IDF 加权余弦 + tau_cluster 建边 + 连通分量成簇（§2.2/§2.3 O1 基线）
  C. 加权标签传播 LPA（§2.3 O1 增强项，顺序无关增强）
  D. O3 LLM 允许降分融合：strength = 0.4*kw + 0.6*llm（§2.2，用户确认边豁免）

内置示例语料复现真实库 D1 问题（「函数/分析/空间」等高 df 泛化词导致
多数书被误吸进一个大簇），便于直观对比三路聚类结果。

用法：
  python demo/clustering_demo.py            # 全部三路聚类 + LLM 降分演示
  python demo/clustering_demo.py --algo cc  # 只跑连通分量
  python demo/clustering_demo.py --no-fuse  # 跳过 LLM 降分演示
"""
import argparse
import json
import math
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
    ("固定收益", ["固定收益证券", "固收", "fixed income"]),
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


def canonical_terms(term_freq: dict, sample: str | None = None) -> dict:
    """同义词归一化（§2.1 归一注入点，demo 模拟版）：
    1. 词库术语命中注入——规范词/别名在样本文本中命中（正式版 _lexicon_hits 子串匹配），
       规范词以 100 权重进入候选（别名命中折叠到规范词），同时其内部 token 权重 ×0.3
       （长词优先：如「傅里叶变换」命中时「傅里」「里叶」不再独立计分）；
    2. 无样本文本时退化为关键词整词折叠（内置示例库）。"""
    out = dict(term_freq)
    for c, _w in _hit_words(sample, term_freq):
        for t in list(out):
            if c in t or _w in t:
                out[t] = out.get(t, 0.0) * 0.3  # 长词内部子串抑制
        out[c] = max(out.get(c, 0.0), 100.0)  # 术语注入
    # 别名整词折叠（未作为术语注入路径处理的）
    for t, v in list(out.items()):
        low = t.lower()
        if low in _ALIAS_TO_CANONICAL:
            c = _ALIAS_TO_CANONICAL[low]
            out[c] = out.get(c, 0.0) + v
            del out[t]
    return out


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
}  # 命名时剔除


def cluster_name(members: list[int]) -> str:
    cand: Counter = Counter()
    for i in members:
        for t, v in KEYWORDS[i].items():
            if t not in _GENERIC and len(t) >= 2:
                cand[t] += v
    if not cand:
        return "其他"
    return cand.most_common(1)[0][0]


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
    global BOOKS, TITLES, KEYWORDS, IDS, N
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
    parser.add_argument("--algo", choices=["all", "greedy", "cc", "lpa"], default="all")
    parser.add_argument("--tau", type=float, default=0.10, help="聚类图边门槛（默认 0.10）")
    parser.add_argument("--input", default=None, help="实际语料 JSON [{title, keywords}]")
    parser.add_argument("--no-synonyms", action="store_true", help="关闭同义词归一化（对照）")
    parser.add_argument("--no-fuse", action="store_true", help="跳过 LLM 降分演示")
    parser.add_argument("--eval", default=None, help="金标簇 JSON（书id: 簇名），打印 A/B/C 质量指标")
    args = parser.parse_args()

    count, desc = _load_input(args.input)
    global KEYWORDS
    if not args.no_synonyms:
        KEYWORDS = [canonical_terms(kw, s) for kw, s in zip(KEYWORDS, SAMPLES, strict=True)]
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
        return
    if args.algo in ("all", "greedy"):
        show(greedy_clusters(), "A 现行：min 伪余弦 + 贪心吸收")
    if args.algo in ("all", "cc"):
        show(connected_components(sim, args.tau), f"B 改进：IDF 余弦 + 连通分量 (tau={args.tau})")
    if args.algo in ("all", "lpa"):
        show(label_propagation(sim, args.tau), f"C 改进：加权标签传播 (tau={args.tau})")
    if not args.no_fuse:
        llm_fuse_demo()


if __name__ == "__main__":
    main()
