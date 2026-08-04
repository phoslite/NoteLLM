"""设置 API：AI 配置查看/保存/测试连接（M4）。

约定（技术栈规范 §3.4）：API Key 前端不回显明文，测试连接仅返回成功与否。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.client import LLMClient, LLMError
from app.core.database import get_db
from app.repositories.settings import (
    CLIENT_KWARG_KEYS,
    VISION_CLIENT_KWARG_KEYS,
    ai_settings_view,
    client_kwargs,
    reload_ai_overrides_from_env,
    save_ai_overrides,
    vision_client_kwargs,
)
from app.schemas.common import ok

router = APIRouter(prefix="/api/settings", tags=["settings"])

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
}


class AiSettingsIn(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    mode: str | None = None
    timeout: int | None = None
    verify_ssl: bool | None = None
    enable_body_send: bool | None = None
    send_page_image: bool | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    thinking_type: str | None = None
    reasoning_effort: str | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_model: str | None = None
    vision_timeout: int | None = None
    vision_verify_ssl: bool | None = None
    vision_max_tokens: int | None = None
    vision_temperature: float | None = None
    vision_top_p: float | None = None
    vision_frequency_penalty: float | None = None
    vision_presence_penalty: float | None = None
    vision_enable_thinking: bool | None = None
    vision_thinking_budget: int | None = None


def _to_store(body: AiSettingsIn | None) -> dict:
    if body is None:
        return {}
    return {FIELD_TO_KEY[k]: v for k, v in body.model_dump().items() if v is not None}


@router.get("/ai")
def get_ai_settings(db: Session = Depends(get_db)):
    """读取当前 AI 配置（API Key 掩码后返回）。"""
    return ok(ai_settings_view(db))


@router.patch("/ai")
def put_ai_settings(body: AiSettingsIn, db: Session = Depends(get_db)):
    """保存 AI 配置（空值忽略，保留旧值）；返回掩码后的最新视图。"""
    view = save_ai_overrides(db, _to_store(body))
    return ok(view, "已保存")


@router.post("/ai/test")
def test_ai_settings(body: AiSettingsIn | None = None, db: Session = Depends(get_db)):
    """用当前配置（可带临时覆盖）发起一次最小对话，验证连通性与鉴权。"""
    kwargs = client_kwargs(db)
    if body:
        for key, value in _to_store(body).items():
            if key in CLIENT_KWARG_KEYS:
                kwargs[CLIENT_KWARG_KEYS[key]] = value
    if not kwargs.get("api_key"):
        raise HTTPException(status_code=400, detail="请先配置 AI Base URL 与 API Key")
    try:
        client = LLMClient(**kwargs)
        reply = client.chat([{"role": "user", "content": "ping"}])
    except LLMError as exc:
        return ok({"ok": False, "message": str(exc)}, "连接失败")
    except Exception as exc:  # noqa: BLE001 兜底：未知异常也按失败返回
        return ok({"ok": False, "message": f"未知错误: {exc}"}, "连接失败")
    return ok({"ok": True, "message": "连接成功，回复：" + (reply or "")[:50]}, "连接成功")


@router.post("/ai/reload-env")
def reload_env_ai_settings(db: Session = Depends(get_db)):
    """强制载入 .env 配置文件：清除/覆盖运行时 AI 与视觉配置，全部以 .env 当前内容为准。

    适用于：手工编辑 .env 后立即生效（无需重启）、或误改设置页后一键还原到 .env。
    """
    try:
        view = reload_ai_overrides_from_env(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok(view, "已从 .env 强制载入")


@router.post("/ai/test-vision")
def test_vision_settings(body: AiSettingsIn | None = None, db: Session = Depends(get_db)):
    """用多模态视觉配置发起一次最小请求（文本 ping），验证连通性与鉴权。"""
    kwargs = vision_client_kwargs(db)
    if body:
        for key, value in _to_store(body).items():
            if key in VISION_CLIENT_KWARG_KEYS:
                kwargs[VISION_CLIENT_KWARG_KEYS[key]] = value
    if not kwargs.get("api_key") or not kwargs.get("base_url") or not kwargs.get("model"):
        raise HTTPException(status_code=400, detail="请先配置多模态 Base URL、API Key 与模型")
    try:
        client = LLMClient(**kwargs, kind="vision")
        reply = client.chat([{"role": "user", "content": "ping"}])
    except LLMError as exc:
        return ok({"ok": False, "message": str(exc)}, "连接失败")
    except Exception as exc:  # noqa: BLE001 兜底：未知异常也按失败返回
        return ok({"ok": False, "message": f"未知错误: {exc}"}, "连接失败")
    return ok({"ok": True, "message": "连接成功，回复：" + (reply or "")[:50]}, "连接成功")
