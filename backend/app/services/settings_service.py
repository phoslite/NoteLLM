"""设置编排服务（审查 P0-3）：AI 配置字段映射、连接测试与临时覆盖合并从路由下沉。

路由只做请求解析与响应包装；前端字段名 → 仓储键映射、测试任务函数、覆盖合并统一在本层。
"""
from app.ai.client import LLMClient, LLMError
from app.repositories.settings import (
    CLIENT_KWARG_KEYS,
    SELECTOR_CLIENT_KWARG_KEYS,
    VISION_CLIENT_KWARG_KEYS,
    client_kwargs,
    selector_client_kwargs,
    vision_client_kwargs,
)
from app.tasks import submit

# 前端字段名 → 仓储键名（ai_*）
FIELD_TO_KEY: dict[str, str] = {
    "base_url": "ai_base_url",
    "api_key": "ai_api_key",
    "model": "ai_model",
    "mode": "ai_mode",
    "timeout": "ai_timeout",
    "verify_ssl": "ai_verify_ssl",
    "enable_body_send": "ai_enable_body_send",
    "send_page_image": "ai_send_page_image",
    "temperature": "ai_temperature",
    "max_tokens": "ai_max_tokens",
    "thinking_type": "ai_thinking_type",
    "reasoning_effort": "ai_reasoning_effort",
    "top_p": "ai_top_p",
    "frequency_penalty": "ai_frequency_penalty",
    "presence_penalty": "ai_presence_penalty",
    "stop": "ai_stop",
    "vision_base_url": "vision_base_url",
    "vision_api_key": "vision_api_key",
    "vision_model": "vision_model",
    "vision_timeout": "vision_timeout",
    "vision_verify_ssl": "vision_verify_ssl",
    "vision_max_tokens": "vision_max_tokens",
    "vision_temperature": "vision_temperature",
    "vision_top_p": "vision_top_p",
    "vision_frequency_penalty": "vision_frequency_penalty",
    "vision_presence_penalty": "vision_presence_penalty",
    "vision_enable_thinking": "vision_enable_thinking",
    "vision_thinking_budget": "vision_thinking_budget",
    "rag_select_enabled": "ai_rag_select_enabled",
    "rag_select_base_url": "rag_select_base_url",
    "rag_select_api_key": "rag_select_api_key",
    "rag_select_model": "rag_select_model",
    "rag_select_mode": "rag_select_mode",
    "rag_select_timeout": "rag_select_timeout",
    "rag_select_verify_ssl": "rag_select_verify_ssl",
    "rag_select_max_tokens": "rag_select_max_tokens",
    "rag_select_temperature": "rag_select_temperature",
    "rag_select_thinking_type": "rag_select_thinking_type",
    "rag_select_reasoning_effort": "rag_select_reasoning_effort",
    "rag_select_max_books": "rag_select_max_books",
    "rag_select_max_skills": "rag_select_max_skills",
    "rag_select_cache_ttl_minutes": "rag_select_cache_ttl_minutes",
}


def to_store(body) -> dict:
    """请求体 → 仓储键字典（空值忽略，保留旧值语义）。"""
    if body is None:
        return {}
    return {FIELD_TO_KEY[k]: v for k, v in body.model_dump().items() if v is not None}


def _run_connect_test(kwargs: dict, *, kind: str = "text") -> dict:
    """连接测试任务函数：发起一次最小对话，返回 {ok, message}；异常不外抛。"""
    try:
        client = LLMClient(**kwargs, kind=kind)
        reply = client.chat([{"role": "user", "content": "ping"}])
    except LLMError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 兜底：未知异常也按失败返回
        return {"ok": False, "message": f"未知错误: {exc}"}
    return {"ok": True, "message": "连接成功，回复：" + (reply or "")[:50]}


def build_test_kwargs(db, body, *, vision: bool = False, selector: bool = False) -> dict:
    """合并当前配置与请求临时覆盖；缺失关键项返回 None（由路由转 400）。

    selector=True 时用挑选器配置（rag_select_* 未填项自动回退主文本模型，
    故必填检查仅 api_key）。"""
    if selector:
        kwargs = selector_client_kwargs(db)
        mapping = SELECTOR_CLIENT_KWARG_KEYS
        required = ("api_key",)
    elif vision:
        kwargs = vision_client_kwargs(db)
        mapping = VISION_CLIENT_KWARG_KEYS
        required = ("api_key", "base_url", "model")
    else:
        kwargs = client_kwargs(db)
        mapping = CLIENT_KWARG_KEYS
        required = ("api_key",)
    if body:
        for key, value in to_store(body).items():
            if key in mapping:
                kwargs[mapping[key]] = value
    if any(not kwargs.get(k) for k in required):
        return None
    return kwargs


def submit_connect_test(db, body, *, vision: bool = False, selector: bool = False) -> str:
    """提交连接测试后台任务，返回 task_id。"""
    kwargs = build_test_kwargs(db, body, vision=vision, selector=selector)
    if kwargs is None:
        if selector:
            raise ValueError("请先配置挑选器或文本模型的 API Key（挑选器未填项自动回退主模型）")
        raise ValueError("请先配置 AI Base URL 与 API Key" if not vision else "请先配置多模态 Base URL、API Key 与模型")
    if selector:
        return submit("text", "test-selector-connection", lambda: _run_connect_test(kwargs, kind="text"))
    task_type = "vision" if vision else "text"
    task_name = "test-vision-connection" if vision else "test-text-connection"
    return submit(task_type, task_name, lambda: _run_connect_test(kwargs, kind=task_type))
