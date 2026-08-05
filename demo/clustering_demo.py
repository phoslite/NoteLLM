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
import math
from collections import Counter, defaultdict

# ---------------------------------------------------------------- 示例语料
# 每本书：(书名, {关键词: 词频})；词频为整数，模拟 extract_keywords 输出。
BOOKS = [
    ("泛函分析", {"函数": 6, "空间": 5, "线性": 4, "算子": 4, "拓扑": 3, "巴拿赫": 3, "泛函": 4, "分析": 5}),
    ("实变函数论", {"函数": 6, "测度": 4, "积分": 4, "勒贝格": 3, "空间": 3, "可测": 3, "分析": 4}),
    ("变分法基础", {"变分": 5, "泛函": 4, "极值": 4, "欧拉": 3, "微分": 3, "函数": 3}),
    ("变分学讲义", {"变分": 5, "泛函": 4, "极值": 3, "欧拉": 3, "拉格朗日": 3, "分析": 3}),
    ("数学分析习题", {"函数": 5, "极限": 4, "导数": 4, "积分": 4, "级数": 3, "连续": 3, "分析": 5}),
    ("线性代数讲义", {"矩阵": 5, "向量": 4, "线性": 4, "行列式": 3, "特征值": 3, "空间": 3}),
    ("点集拓扑", {"拓扑": 5, "开集": 4, "紧致": 3, "连通": 3, "连续": 3, "空间": 4, "度量": 3}),
    ("群论导论", {"群": 5, "子群": 4, "同态": 3, "环": 3, "域": 3, "代数": 3}),
    ("概率论与数理统计", {"概率": 5, "随机": 4, "分布": 4, "期望": 3, "方差": 3, "统计": 4}),
    ("数理统计教程", {"统计": 5, "抽样": 3, "估计": 4, "检验": 3, "分布": 3, "假设": 3}),
    ("在世界的关节处下刀", {"关节": 4, "下刀": 3, "图形": 3, "渲染": 3, "动画": 3, "函数": 2}),
]
N = len(BOOKS)
TITLES = [t for t, _ in BOOKS]
KEYWORDS = [dict(kw) for _, kw in BOOKS]


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
_GENERIC = {"函数", "分析", "空间", "线性", "连续"}  # 泛化词，命名时剔除


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
def main() -> None:
    parser = argparse.ArgumentParser(description="聚类改进方案验证 demo")
    parser.add_argument("--algo", choices=["all", "greedy", "cc", "lpa"], default="all")
    parser.add_argument("--tau", type=float, default=0.10, help="聚类图边门槛（默认 0.10）")
    parser.add_argument("--no-fuse", action="store_true", help="跳过 LLM 降分演示")
    args = parser.parse_args()

    sim = idf_cosine()
    print(f"示例库 {N} 本书，高 df 泛化词：函数/分析/空间（复现 D1 误吸场景）")
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
