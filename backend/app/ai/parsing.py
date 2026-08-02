"""LLM 输出解析公共工具：从回复中容忍地提取 JSON 对象（去代码围栏、取首个 { 到末个 }）。

供 AI 相关服务共用：graph_sync（跨书联动）、llm_score（关联打分）、rag_service（资产生成）、
mindmap_service（脑图生成）此前各自维护一份同类解析，统一收敛到此处。
"""
import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", flags=re.MULTILINE)


def parse_llm_json(text: str) -> dict:
    """解析 LLM 输出 JSON：容忍代码围栏与前后杂文，取首个 { 到末个 } 块。

    - 找不到 JSON 块抛 ValueError；
    - JSON 语法非法抛 json.JSONDecodeError；
    由调用方按自身回退策略捕获处理。
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 输出中未找到 JSON")
    return json.loads(cleaned[start : end + 1])