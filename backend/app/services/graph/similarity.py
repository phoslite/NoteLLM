"""IDF 加权余弦相似度（聚类/跨书建边共用，L2；避免两处公式漂移）。

公式（改进方案 §2.2）：
- 语料级 IDF：idf(t) = ln((N+1)/(df(t)+1)) + 1；df/N > IDF_CUT 的泛化词再乘 0.2；
- 书级权重向量：W_b(t) = tf_norm(t, b) · idf(t)（来源加权已在关键词抽取层完成）；
- 相似度：Sim(a,b) = Σ W_a·W_b / (√Σ W_a² · √Σ W_b²)。

刻度差异说明（A-M2，2026-08-11）：聚类侧（clustering.py）先剔除 `_GENERIC_DOMAIN_TERMS`
再算 IDF/建边；跨书建边侧（cross_book.py）用全量关键词 IDF（不剔泛词），两处 df/N 分布
与 IDF_CUT 泛词惩罚作用对象不同，分数刻度略有差异——属既有设计，行为不改。
"""

import math

from app.services.graph.thresholds import (
    FLOAT_EPS,
    GENERIC_MIN_N,
    IDF_CUT,
    MIN_SHARED_TERMS,
    TAU_EDGE,
)


def idf_weights(keywords: dict[int, dict[str, float]], cut: float = IDF_CUT) -> dict[str, float]:
    """语料级 IDF：N=书数，df=含该规范词的书数；随书增删惰性重算并缓存由调用方控制。"""
    n = len(keywords)
    if n == 0:
        return {}
    df: dict[str, int] = {}
    for kw in keywords.values():
        for t in set(kw):
            df[t] = df.get(t, 0) + 1
    out: dict[str, float] = {}
    for t, d in df.items():
        v = math.log((n + 1) / (d + 1)) + 1
        if n >= GENERIC_MIN_N and d / n > cut:
            v *= 0.2
        out[t] = v
    return out


def weighted_vectors(
    vectors: dict[int, dict[str, float]], idf: dict[str, float],
) -> dict[int, tuple[dict[str, float], float]]:
    """预计算每书 idf 加权向量与 L2 范数（复杂度审查 H2）：返回 {bid: (wa, norm)}。

    语义与 pair_similarity 内部即时构建完全一致（wa[t] = kw[t]·idf.get(t, 1.0)，
    norm = √Σwa²），调用方在入口一次算好，逐对计算只对 common 词做 dot——
    消除 O(P·K) 中每对重复构建加权向量/范数的冗余（实测 4.4x）。
    """
    out: dict[int, tuple[dict[str, float], float]] = {}
    for bid, kw in vectors.items():
        if not kw:
            out[bid] = ({}, 0.0)
            continue
        wa = {t: v * idf.get(t, 1.0) for t, v in kw.items()}
        norm = sum(v * v for v in wa.values()) ** 0.5
        out[bid] = (wa, norm)
    return out


def pair_similarity_weighted(
    ka: dict[str, float],
    kb: dict[str, float],
    wa: dict[str, float],
    norm_a: float,
    wb: dict[str, float],
    norm_b: float,
    tau: float = TAU_EDGE,
) -> tuple[float, list[str]] | None:
    """IDF 加权余弦（H2 主路径，基于预计算加权向量/范数）：返回 (sim 0~1, 共享规范词 top5) 或 None。

    判定顺序与 pair_similarity 完全一致：共享规范词 < MIN_SHARED_TERMS 不建边 →
    范数为 0 不建边 → Sim + FLOAT_EPS < tau 不建边；reasons 取 -(wa+wb) 降序 top5。
    """
    if not ka or not kb:
        return None
    common = [t for t in ka if t in kb]
    if len(common) < MIN_SHARED_TERMS:
        return None
    if not norm_a or not norm_b:
        return None
    dot = sum(wa[t] * wb[t] for t in common)
    sim = dot / (norm_a * norm_b)
    if sim + FLOAT_EPS < tau:
        return None
    reasons = sorted(common, key=lambda t: -(wa[t] + wb[t]))[:5]
    return sim, reasons


def pair_similarity(
    ka: dict[str, float], kb: dict[str, float], idf: dict[str, float], tau: float = TAU_EDGE,
) -> tuple[float, list[str]] | None:
    """IDF 加权余弦（兼容入口）：即时构建加权向量/范数后委托 pair_similarity_weighted。

    语义与 H2 优化前完全一致（供测试/单对调用点使用）；批量场景请用
    weighted_vectors + pair_similarity_weighted 预计算路径。
    """
    if not ka or not kb:
        return None
    wa = {t: ka[t] * idf.get(t, 1.0) for t in ka}
    wb = {t: kb[t] * idf.get(t, 1.0) for t in kb}
    norm_a = sum(v * v for v in wa.values()) ** 0.5
    norm_b = sum(v * v for v in wb.values()) ** 0.5
    return pair_similarity_weighted(ka, kb, wa, norm_a, wb, norm_b, tau)
