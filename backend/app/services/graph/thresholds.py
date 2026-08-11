"""聚类/建边阈值集中常量（改进方案 §2.2；替代散落魔法数，L2 起用）。

阈值保留「画像自动学习覆盖」钩子（沿用 profile_learning.related_strength 机制），
初值由 demo 评估集标定（A1 拍板：IDF_CUT=0.5）。
"""

# ---- 语料级 IDF ----
IDF_CUT = 0.5  # 泛化词 df 占比门槛：df/N > 0.5 的词 idf 再乘 0.2（A1 拍板 0.5）
GENERIC_MIN_N = 8  # 小语料守卫：N < 8 时 df/N 不可靠，不启用泛词惩罚（防共享词被全压制）

# ---- 建边与聚类阈值 ----
TAU_EDGE = 0.06  # 跨书建边：Sim ≥ τ_edge 且共享规范词 ≥2 才建「概念共现」边
TAU_CLUSTER = 0.15  # 聚类图边门槛（高于建边，簇更紧；2026-08-10 试验：0.10 产生 11~12 本大簇，改 0.15 评估）
TAU_POST = 0.15  # post-classify 归属校验（预留；现行词重叠逻辑切换后启用）
TAU_MERGE = 0.35  # 簇合并（预留；现行词重叠逻辑切换后启用）
MIN_SHARED_TERMS = 2  # 共享规范词数下限（建边与成图共用剪枝）

# ---- 成簇引擎 ----
BLOAT_FACTOR = 0.8  # 分裂守卫强度（30 本后按簇规模/边密度自适应，O9）
BLOAT_ADAPT_MIN_N = 30  # O9 b 启用门槛：评估集达标（书籍数 ≥ 30）后才启用自适应
BLOAT_HUB_DEGREE_RATIO = 0.6  # 枢纽节点判定：簇内度 ≥ (m-1)×ratio 视为枢纽
BLOAT_HUB_FRACTION = 0.15  # 枢纽节点占比超此值 → 判定枢纽链并提档
BLOAT_ADAPT_STEP = 0.2  # 每档提升幅度（0.8→1.0→1.2）
BLOAT_MAX = 1.2  # 上限（demo 已验证 1.2 有效，clustering_demo --bloat 校准）
FRAGMENT_RECHECK_RATIO = 0.8  # 碎片合并回检放松因子（回检阈值 = τ×ratio，2026-08-10 拍板保留 0.8）
MAX_SPLIT_DEPTH = 2  # 分裂递归深度上限
LPA_MAX_ITER = 10  # 加权标签传播迭代上限
ANTI_ABSORB = 1.05  # LPA 防吞并守卫：新簇权重和须 > 当前 ×1.05
FLOAT_EPS = 1e-9  # 浮点容差比较
