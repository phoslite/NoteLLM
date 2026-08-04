"""LLM 客户端工厂：按运行时配置（.env + 设置页覆盖）构建文本模型客户端。"""
from sqlalchemy.orm import Session

from app.ai.client import LLMClient
from app.core.config import settings
from app.repositories.settings import client_kwargs, selector_client_kwargs


def build_client(db: Session) -> LLMClient:
    """按运行时配置构建 LLM 客户端（.env + 设置页覆盖）。"""
    return LLMClient(**client_kwargs(db))


def build_selector_client(db: Session) -> LLMClient:
    """决策 34：构建 LLM 挑选器客户端（独立 rag_select_* 配置，未填项回退主模型，低 max_tokens 禁思考）。"""
    return LLMClient(**selector_client_kwargs(db))


def is_configured(db: Session) -> bool:
    """是否有可用 API Key（设置页覆盖或 .env）。"""
    return bool(client_kwargs(db).get("api_key") or settings.ai_api_key)
