"""知识图谱基础文本工具：中文/英文关键词抽取与聚类名清洗（停用词、全角映射）。"""
import re
from collections import Counter

_STOPWORDS = {
    "我们", "你们", "他们", "这个", "那个", "这些", "那些", "一个", "一种", "可以", "需要",
    "如果", "那么", "因为", "所以", "但是", "以及", "并且", "或者", "不是", "没有", "进行",
    "通过", "对于", "关于", "之间", "之后", "之前", "同时", "由于",
    "第一", "一章", "第二", "第三", "中的", "目录", "附录", "前言", "引言", "序言", "摘要",
    "本书", "书介", "绍本", "介绍", "内容", "主要", "研究", "问题", "用于", "相关", "其中", "包括",
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had", "her",
    "was", "one", "our", "out", "that", "with", "have", "this", "will", "from", "they",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

_EN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")

_THEOREM_RE = re.compile(
    r"(定理|定义|引理|推论|公理|命题|证明|Theorem|Definition|Lemma|Corollary|Axiom|Proposition|Proof)"
)

def _cjk_bigrams(run: str):
    for i in range(len(run) - 1):
        yield run[i : i + 2]

def extract_keywords(text: str, top_n: int = 80) -> dict[str, float]:
    """从文本抽取关键词：中文连续串拆二元组 + 英文词，返回 {词: 词频}（按频次取前 top_n）。"""
    if not text:
        return {}
    counter: Counter = Counter()
    for run in _CJK_RE.findall(text):
        for term in _cjk_bigrams(run):
            if term not in _STOPWORDS:
                counter[term] += 1
    for word in _EN_RE.findall(text.lower()):
        if word not in _STOPWORDS:
            counter[word] += 1
    return dict(counter.most_common(top_n))

_FW_ALNUM: dict[int, int] = {}
for _fw, _hw in (
    ("ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    ("ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ", "abcdefghijklmnopqrstuvwxyz"),
    ("０１２３４５６７８９", "0123456789"),
):
    _FW_ALNUM.update({ord(c): ord(a) for c, a in zip(_fw, _hw, strict=True)})
_FW_ALNUM[ord("　")] = ord(" ")

def sanitize_cluster_name(name: str) -> str:
    """聚类名清洗：只保留汉字/英文字母/数字与单词间空格，去除特殊标点符号。"""
    if not name:
        return ""
    text = str(name).translate(_FW_ALNUM)
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9 ]+", " ", text)
    cleaned = " ".join(cleaned.split())
    # 中文标点产生的空格不应保留：去掉夹在两个汉字之间的空格
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", cleaned)
    return cleaned.strip()
