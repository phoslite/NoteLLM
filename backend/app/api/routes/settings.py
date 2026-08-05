"""设置 API：AI 配置查看/保存/测试连接（M4）。

约定（技术栈规范 §3.4）：API Key 前端不回显明文，测试连接仅返回成功与否。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.settings import (
    ai_settings_view,
    reload_ai_overrides_from_env,
    save_ai_overrides,
)
from app.schemas.common import ok
from app.services.settings_service import submit_connect_test, to_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
    # 决策 34 挑选器（LLM 自主挑选 RAG/Skill）：独立模型配置，未填项回退主文本模型
    rag_select_enabled: bool | None = None
    rag_select_base_url: str | None = None
    rag_select_api_key: str | None = None
    rag_select_model: str | None = None
    rag_select_mode: str | None = None
    rag_select_timeout: int | None = None
    rag_select_verify_ssl: bool | None = None
    rag_select_max_tokens: int | None = None
    rag_select_temperature: float | None = None
    rag_select_thinking_type: str | None = None
    rag_select_reasoning_effort: str | None = None
    rag_select_max_books: int | None = None
    rag_select_max_skills: int | None = None
    rag_select_cache_ttl_minutes: int | None = None


@router.get("/ai")
def get_ai_settings(db: Session = Depends(get_db)):
    """读取当前 AI 配置（API Key 掩码后返回）。"""
    return ok(ai_settings_view(db))


@router.patch("/ai")
def put_ai_settings(body: AiSettingsIn, db: Session = Depends(get_db)):
    """保存 AI 配置（空值忽略，保留旧值）；返回掩码后的最新视图。"""
    view = save_ai_overrides(db, to_store(body))
    return ok(view, "已保存")


@router.post("/ai/test")
def test_ai_settings(body: AiSettingsIn | None = None, db: Session = Depends(get_db)):
    """用当前配置（可带临时覆盖）发起一次最小对话验证连通性（后台任务，返回 task_id）。"""
    try:
        task_id = submit_connect_test(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"task_id": task_id}, "已提交连接测试")


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
    try:
        task_id = submit_connect_test(db, body, vision=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"task_id": task_id}, "已提交视觉连接测试")

@router.post("/ai/test-selector")
def test_selector_settings(body: AiSettingsIn | None = None, db: Session = Depends(get_db)):
    """用挑选器配置（rag_select_*，未填项回退主文本模型）发起一次最小请求验证连通性。"""
    try:
        task_id = submit_connect_test(db, body, selector=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"task_id": task_id}, "已提交挑选器连接测试")
