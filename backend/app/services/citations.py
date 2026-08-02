"""引用出处解析：LLM 输出形如【第X章 第Y段】/【第X页】→ 结构化引用。"""
import re

# 引用出处：LLM 输出形如 【第X章 第Y段】 / 【第X章 第Y-Z段】 / 【第X页】（PDF 按页阅读）
CITATION_RE = re.compile(r"【第\s*(\d+)\s*章\s*第\s*([\d\-]+)\s*段】|【第\s*(\d+)\s*页】")


def extract_citations(text: str) -> list[dict]:
    """从回答中解析引用出处：返回 [{chapter, para}] 列表；PDF 页引用 para 记为「页」。"""
    out = []
    for m in CITATION_RE.finditer(text or ""):
        if m.group(1) is not None:
            out.append({"chapter": int(m.group(1)), "para": m.group(2)})
        else:
            out.append({"chapter": int(m.group(3)), "para": "页"})
    return out
