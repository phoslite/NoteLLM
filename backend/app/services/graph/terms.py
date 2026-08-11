"""术语归一折叠层（聚类术语层 L1）：别名整词折叠，聚类/建边共用。

设计约束（改进方案 §2.1）：
- `canonical_terms` 只做别名→规范词折叠与权重求和，**不做词库注入**
  （注入属于命名层，避免高权重术语把聚类成图吸入一簇）；
- `extract_keywords` 本身不改（保持缓存与下游行为冻结），归一是其上的薄层；
- 别名映射经 `lexicon.load_synonym_aliases` 读取（用户词库同义词区），mtime 缓存失效。
"""
import re
from collections import Counter

import jieba

from app.services.graph import lexicon as _lexicon
from app.services.graph.keywords import _CJK_RE, _STOPWORDS
from app.services.graph.lexicon import load_synonym_aliases


def canonical_terms(term_freq: dict[str, float], aliases: dict[str, str] | None = None) -> dict[str, float]:
    """别名整词折叠：别名（小写匹配）→ 规范词，权重求和；返回新字典，不修改入参。

    - term_freq: 关键词词频字典（{词: 权重}）；
    - aliases: 别名映射；缺省自动读取用户词库同义词区。
    """
    if not term_freq:
        return {}
    if aliases is None:
        aliases = load_synonym_aliases()
    out: dict[str, float] = {}
    for term, weight in term_freq.items():
        canonical = aliases.get(term.lower(), term)
        out[canonical] = out.get(canonical, 0.0) + weight
    return out


# ==================== 画像术语层（冷/暖记忆关键词，2026-08-11 修复） ====================
# 冷记忆/暖记忆的关键词来源与聚类不同：直接喂 RAG key_points 的整句文本。
# 修复前直接用 extract_keywords 会残留：跨词二元组碎片（类客/题骑）、虚词碎片（的稳/德的）、
# 泛化词（定义/任意/函数）、LaTeX 命令残留（mathrm/frac）。
# 画像层抽取管线：LaTeX 清理 → 泛化词剔除 → 虚词字碎片过滤 → 别名折叠 → 词库整词提权与碎片抑制。
_LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+")
_LATEX_ARG_RE = re.compile(r"\{[^{}\n]*[A-Za-z0-9\\][^{}\n]*\}")
_PROFILE_STOP_CHARS = frozenset(
    "的 了 么 呢 吗 吧 啊 之 其 及 也 都 而 但 且 被 把 从 将 这 那 或 所 与 为 是 在 以".split()
)
# 画像专用泛化补充词（不进入聚类共享泛化词表，避免影响聚类行为冻结）
# 词库沉淀专用次泛词（v1.134）：覆盖多本书的次泛词也不沉淀进专业术语词库，
# 防止污染聚类命名/画像抽取的优先匹配（专业词如「角动量/自伴/Banach」保留）。
_PROFILE_SYNC_STOPWORDS = frozenset({
    "阅读", "空间", "变分", "fixed", "中文", "section", "task", "函数", "表示",
    "对象", "方程", "分类", "结构", "类型", "世界", "工具", "是否", "分析", "收敛",
    "核心", "跨书", "关联", "演化", "未知", "数学", "方法论", "线性", "价格", "变量",
    "映射", "运动", "系统", "坐标", "时间", "频率", "持续", "无穷", "引擎", "完备",
    "代数", "拉格朗",
})

_PROFILE_GENERIC_EXTRA = frozenset({
    "任意", "一些", "一定", "各种", "称为", "给出", "得到", "使得",
    "如下", "上述", "以下", "以上", "从而", "因此", "于是",
})
# 旧数据清洗用 LaTeX 命令补充黑名单（新抽取路径已在抽取前移除 \cmd，无需命中本表）
_PROFILE_LATEX_EXTRA = frozenset({
    "overline", "underline", "approx", "equiv", "sim", "simeq", "cong", "propto",
    "subset", "supset", "subseteq", "supseteq", "cup", "cap", "bigcup", "bigcap",
    "prod", "coprod", "oplus", "otimes", "langle", "rangle", "lfloor", "rfloor",
    "lceil", "rceil", "forall", "exists", "neg", "wedge", "vee", "mapsto", "circ",
    "bullet", "ast", "diamond", "triangle", "square", "vdots", "ddots",
    "phi", "tau", "rho", "chi", "psi", "eta", "xi", "nu", "mu", "pi",
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "theta", "sigma", "omega",
    "varphi", "vartheta", "varepsilon", "varpi", "varrho", "varsigma", "varkappa",
    "digamma", "qquad", "hspace", "vspace", "align", "equation", "displaystyle",
    "textstyle", "boldsymbol", "mathcal", "mathscr", "mathfrak", "emph",
})


def _strip_latex(text: str) -> str:
    """移除 LaTeX 命令与纯公式参数花括号块（含中文的参数块保留，避免误删正文）。"""
    text = _LATEX_ARG_RE.sub(" ", text)
    return _LATEX_CMD_RE.sub(" ", text)


def _is_fragment_term(term: str) -> bool:
    """画像术语虚词字碎片：中文二元组含虚词字（的/与/为…）即为跨词或语气碎片。"""
    return len(term) == 2 and (term[0] in _PROFILE_STOP_CHARS or term[1] in _PROFILE_STOP_CHARS)


def _inner_bigrams(term: str) -> set[str]:
    """词库整词的内部中文二元组（用于碎片抑制；2 字词内部只有自身，忽略）。"""
    frags: set[str] = set()
    for run in _CJK_RE.findall(term):
        if len(run) <= 2:
            continue
        for i in range(len(run) - 1):
            frags.add(run[i : i + 2])
    return frags


_JIEBA_SIGNATURE: tuple | None = None
_JIEBA_READY = False


def _ensure_jieba_lexicon() -> None:
    """把用户/系统词库注入 jieba 词典（lazy；词库变更后重新注入，mtime 缓存已由 lexicon 层处理）。"""
    global _JIEBA_READY, _JIEBA_SIGNATURE
    user, cached = _lexicon.load_domain_lexicon()
    signature = (user, cached)
    if _JIEBA_READY and signature == _JIEBA_SIGNATURE:
        return
    jieba.setLogLevel(60)
    for term in user | cached:
        if term and _CJK_RE.search(term):
            jieba.add_word(term)
    _JIEBA_READY = True
    _JIEBA_SIGNATURE = signature


def extract_profile_terms(text: str, top_n: int = 10) -> dict[str, float]:
    """画像术语抽取（v1.133 jieba 分词版，冷/暖记忆关键词）。

    管线：LaTeX 清理 → jieba 整词切分（用户词库注入词典，整词不被切碎）→
    泛化词/停用词/单字/数字过滤 → 别名折叠 → 词库整词提权。
    修复二元组时代的跨词碎片（由度/度定/义坐）——jieba 按词边界切分天然不产生此类碎片；
    聚类链路 `extract_keywords` 冻结不受影响。
    """
    if not text:
        return {}
    clean = _strip_latex(str(text))
    _ensure_jieba_lexicon()
    generic = _lexicon.generic_domain_terms() | _PROFILE_GENERIC_EXTRA
    counter: Counter = Counter()
    for token in jieba.lcut(clean):
        token = token.strip()
        if len(token) < 2:
            continue
        if token in generic or token in _STOPWORDS:
            continue
        if not _CJK_RE.search(token):
            if token in _PROFILE_LATEX_EXTRA or token.replace("-", "").isdigit():
                continue
        counter[token] += 1
    cands = canonical_terms(dict(counter))
    user, cached = _lexicon.load_domain_lexicon()
    hits = _lexicon._lexicon_hits(clean, user | cached)
    for term in hits:
        cands[term] = cands.get(term, 0.0) * 2 + 1
    return dict(sorted(cands.items(), key=lambda kv: -kv[1])[:top_n])


def sanitize_profile_term_freq(term_freq: dict[str, float]) -> dict[str, float]:
    """清洗既有画像术语字典（旧数据迁移）：泛化词/LaTeX 命令词/虚词碎片剔除 + 别名折叠。

    用于一次性旧数据清洗与冷画像迁移前的兜底过滤；无原文时不做碎片抑制。
    """
    if not term_freq:
        return {}
    generic = _lexicon.generic_domain_terms() | _PROFILE_LATEX_EXTRA | _PROFILE_GENERIC_EXTRA
    cands = {t: w for t, w in term_freq.items() if t not in generic and not _is_fragment_term(t)}
    return canonical_terms(cands)
