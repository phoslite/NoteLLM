"""术语归一折叠层（聚类术语层 L1）：别名整词折叠，聚类/建边共用。

设计约束（改进方案 §2.1）：
- `canonical_terms` 只做别名→规范词折叠与权重求和，**不做词库注入**
  （注入属于命名层，避免高权重术语把聚类成图吸入一簇）；
- `extract_keywords` 本身不改（保持缓存与下游行为冻结），归一是其上的薄层；
- 别名映射经 `lexicon.load_synonym_aliases` 读取（用户词库同义词区），mtime 缓存失效。
"""

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
