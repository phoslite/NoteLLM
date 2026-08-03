"""专业术语词库与领域命名：用户词库/系统缓存区、领域候选词与专业术语选择。"""
import re
from collections import Counter
from pathlib import Path

from app.core.config import settings
from app.models.book import Book
from app.services.graph.keywords import _CJK_RE, extract_keywords, sanitize_cluster_name

_GENERIC_DOMAIN_TERMS = {
    # 数学/学术通用词
    "定理", "定义", "证明", "引理", "推论", "公理", "命题", "方法", "理论", "概念",
    "性质", "结论", "例子", "例题", "公式", "假设", "条件", "充分", "必要",
    "一般", "特殊", "主要", "重要", "基本", "基础", "简单", "常见", "常用", "经典",
    "存在", "问题", "结果", "意义", "作用", "方式", "过程", "方面", "部分", "情况",
    "准备", "行动", "清单",
    # 学习/出版元词（阅读、精读本身可作为阅读类书籍的领域名，不纳入过滤）
    "笔记", "习题", "答案", "详解", "教程", "讲义", "目录", "前言",
    "附录", "索引", "复习", "考试", "练习", "参考", "摘要", "概述", "简介", "内容",
    "介绍", "引言", "导论", "综述",
    # 版本/出版/文件名元词
    "第一章", "第一", "一章", "第二", "第三", "新版", "版本", "出版", "出版社",
    "系列", "全集", "选集", "卷", "册", "页",
}

def generic_domain_terms() -> frozenset[str]:
    """通用领域过滤词（学术/出版元词），供图谱与总结链路过滤泛化词。"""
    return _GENERIC_DOMAIN_TERMS


_LEXICON_CACHE_MARKER = "# ================= 系统缓存区（自动追加，可编辑/删除） ================="

_DOMAIN_LEXICON_CACHE: tuple[frozenset[str], frozenset[str], float] | None = None

def _lexicon_path() -> Path:
    return Path(settings.domain_terms_file)

def load_domain_lexicon() -> tuple[frozenset[str], frozenset[str]]:
    """读取专业术语词库：返回 (用户区术语, 系统缓存区术语)；文件缺失/异常返回空集。"""
    path = _lexicon_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return frozenset(), frozenset()
    global _DOMAIN_LEXICON_CACHE
    if _DOMAIN_LEXICON_CACHE is not None and _DOMAIN_LEXICON_CACHE[2] == mtime:
        return _DOMAIN_LEXICON_CACHE[0], _DOMAIN_LEXICON_CACHE[1]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return frozenset(), frozenset()
    user: set[str] = set()
    cached: set[str] = set()
    in_cached = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            if _LEXICON_CACHE_MARKER in line:
                in_cached = True
            continue
        term = sanitize_cluster_name(line)
        if term:
            (cached if in_cached else user).add(term)
    result = (frozenset(user), frozenset(cached))
    _DOMAIN_LEXICON_CACHE = (result[0], result[1], mtime)
    return result

def _lexicon_hits(text: str, terms: frozenset[str]) -> set[str]:
    """术语在文本中的命中：中文词组按子串；英文/数字词组按词边界（大小写不敏感）。"""
    if not terms or not text:
        return set()
    lowered = text.lower()
    hits: set[str] = set()
    for term in terms:
        if _CJK_RE.search(term):
            if term in text:
                hits.add(term)
        else:
            pattern = r"(?<![A-Za-z0-9\-])" + re.escape(term.lower()) + r"(?![A-Za-z0-9\-])"
            if re.search(pattern, lowered):
                hits.add(term)
    return hits

def cache_domain_term(term: str) -> bool:
    """把自动选定的专业术语写入词库【系统缓存区】，作为以后命名优先备选。

    - 泛化词不缓存；用户区/缓存区已存在则不重复写入；
    - 文件不存在时自动创建（含使用说明头）。
    """
    term = sanitize_cluster_name(term)
    if not term or term in _GENERIC_DOMAIN_TERMS:
        return False
    user, cached = load_domain_lexicon()
    if term in user or term in cached:
        return False
    path = _lexicon_path()
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            if _LEXICON_CACHE_MARKER in text:
                lines.append(term)
            else:
                lines.extend(["", _LEXICON_CACHE_MARKER, term])
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        else:
            header = (
                "# 专业术语词库（领域命名优先匹配本文件中的术语）\n"
                "# 每行一个术语（中文词组 / 英文词组均可；# 开头为注释，空行忽略）\n"
                "# 上方为【用户自定义区】（最高优先级），修改后即时生效\n"
                "\n"
                + _LEXICON_CACHE_MARKER
                + "\n"
                + term
                + "\n"
            )
            path.write_text(header, encoding="utf-8")
        global _DOMAIN_LEXICON_CACHE
        _DOMAIN_LEXICON_CACHE = None
        return True
    except OSError:
        return False

def _clean_title_segment(seg: str) -> str:
    """书名/标题清洗：去掉括号内（作者/版本/出版社等）与文件名下划线段。"""
    seg = re.sub(r"[（(【\[].*?[）)】\]]", " ", seg or "")
    seg = re.sub(r"_+", " ", seg)
    return seg

def _domain_candidates(book: Book, posterior: dict | None = None) -> dict[str, float]:
    """领域命名候选词（带权重）：章节标题×3 + 清洗后书名×2 + 正文×1 + RAG 后验×5。

    只取汉字二元组与英文词（复用 extract_keywords），剔除 _GENERIC_DOMAIN_TERMS 泛化词。
    """
    parts: list[str] = []
    for ch in book.chapters:
        title = _clean_title_segment(ch.title or "")
        if title:
            parts.append((title + "\n") * 3)
        if ch.content_text:
            parts.append(ch.content_text)
    clean_title = _clean_title_segment(book.title or "")
    if clean_title:
        parts.append((clean_title + "\n") * 2)
    if posterior:
        texts = [str(posterior.get("summary") or "")]
        for k in posterior.get("key_points") or []:
            texts.append(k if isinstance(k, str) else str(k.get("title") or k.get("point") or ""))
        parts.append(("\n".join(texts) + "\n") * 5)
    text = "\n".join(parts)
    kw = extract_keywords(text, 60)
    cands = {t: w for t, w in kw.items() if t not in _GENERIC_DOMAIN_TERMS}
    user, cached = load_domain_lexicon()
    if user or cached:
        for term in _lexicon_hits(text, user | cached):
            cands[term] = max(cands.get(term, 0.0), 100.0)  # 词库术语：高权重优先备选
    return cands

def _first_meaningful_term(keywords: dict[str, float]) -> str:
    """取领域专业术语：用户词库 → 系统缓存词库 → 第一个未被泛化过滤的关键词（无则取最高频词）。"""
    user, cached = load_domain_lexicon()
    for t in keywords:
        if t in user:
            return t
    for t in keywords:
        if t in cached:
            return t
    for t in keywords:
        if t not in _GENERIC_DOMAIN_TERMS:
            return t
    return next(iter(keywords), "")

def _pick_domain_name(candidates_by_book: dict[int, dict[str, float]], members: list[Book]) -> str:
    """从簇成员候选词中挑领域专业术语：
    用户词库命中优先 → 自动候选（含系统缓存词库，覆盖书数优先 → 词频次之）；无候选返回空串。

    说明：系统缓存词库作为「备选候选」参与覆盖书数优先的正常竞争，
    避免仅 1 本书正文旁及的缓存词凌驾于覆盖多本书的强候选之上。
    """
    coverage: Counter = Counter()
    freq: Counter = Counter()
    for m in members:
        cand = candidates_by_book.get(m.id, {})
        if cand:
            coverage.update(set(cand))
        for t, w in cand.items():
            freq[t] += w
    if not freq:
        return ""
    user, _cached = load_domain_lexicon()
    user_hits = {t for t in freq if t in user}
    if user_hits:
        return max(user_hits, key=lambda t: (coverage[t], freq[t]))
    return max(freq, key=lambda t: (coverage[t], freq[t]))


def _posterior_keywords(content: dict) -> dict[str, float]:
    """从 RAG 资产内容提取后验特征：summary + key_points（top 60，比正文关键词更聚焦）。"""
    kps = content.get("key_points") or []
    texts = [content.get("summary") or ""]
    for kp in kps:
        if isinstance(kp, str):
            texts.append(kp)
        elif isinstance(kp, dict):
            texts.append(str(kp.get("title") or kp.get("point") or ""))
    return extract_keywords(" ".join(texts), 60)
