"""运行时设置仓储：AI 配置等存 Setting 表（key/value），可覆盖 .env 默认值。

约定（技术栈规范 §3.4）：API Key 禁止硬编码、禁止写日志、前端不回显明文。
"""
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.profile import Setting

# 运行时允许覆盖的 AI 配置项（key → .env 对应名）
AI_OVERRIDE_KEYS: dict[str, str] = {
    "ai_base_url": "AI_BASE_URL",
    "ai_api_key": "AI_API_KEY",
    "ai_model": "AI_MODEL",
    "ai_mode": "AI_MODE",
    "ai_timeout": "AI_TIMEOUT",
    "ai_verify_ssl": "AI_VERIFY_SSL",
    "ai_enable_body_send": "AI_ENABLE_BODY_SEND",
    "ai_send_page_image": "AI_SEND_PAGE_IMAGE",
    "ai_temperature": "AI_TEMPERATURE",
    "ai_max_tokens": "AI_MAX_TOKENS",
    "ai_thinking_type": "AI_THINKING_TYPE",
    "ai_reasoning_effort": "AI_REASONING_EFFORT",
    "ai_top_p": "AI_TOP_P",
    "ai_frequency_penalty": "AI_FREQUENCY_PENALTY",
    "ai_presence_penalty": "AI_PRESENCE_PENALTY",
    "ai_stop": "AI_STOP",
    "ai_anthropic_version": "AI_ANTHROPIC_VERSION",
    # 多模态视觉配置（M7）：独立于文本 AI
    "vision_base_url": "VISION_BASE_URL",
    "vision_api_key": "VISION_API_KEY",
    "vision_model": "VISION_MODEL",
    "vision_timeout": "VISION_TIMEOUT",
    "vision_verify_ssl": "VISION_VERIFY_SSL",
    "vision_max_tokens": "VISION_MAX_TOKENS",
    "vision_temperature": "VISION_TEMPERATURE",
    "vision_top_p": "VISION_TOP_P",
    "vision_frequency_penalty": "VISION_FREQUENCY_PENALTY",
    "vision_presence_penalty": "VISION_PRESENCE_PENALTY",
    "vision_enable_thinking": "VISION_ENABLE_THINKING",
    "vision_thinking_budget": "VISION_THINKING_BUDGET",
}

# 布尔/数值字段类型转换
_BOOL_KEYS = {"ai_verify_ssl", "ai_enable_body_send", "ai_send_page_image", "vision_verify_ssl", "vision_enable_thinking"}
_INT_KEYS = {"ai_timeout", "ai_max_tokens", "vision_timeout", "vision_max_tokens", "vision_thinking_budget"}
_FLOAT_KEYS = {
    "ai_temperature",
    "ai_top_p",
    "ai_frequency_penalty",
    "ai_presence_penalty",
    "vision_temperature",
    "vision_top_p",
    "vision_frequency_penalty",
    "vision_presence_penalty",
}


def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(Setting, key)
    return row.value if row else default


def delete_setting(db: Session, key: str) -> None:
    """删除单条运行时覆盖（不存在时静默）。"""
    row = db.get(Setting, key)
    if row:
        db.delete(row)
        db.commit()


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()


# LLMClient 构造参数映射（settings 的 ai_* 键 → client 关键字）
CLIENT_KWARG_KEYS: dict[str, str] = {
    "ai_base_url": "base_url",
    "ai_api_key": "api_key",
    "ai_model": "model",
    "ai_mode": "mode",
    "ai_timeout": "timeout",
    "ai_verify_ssl": "verify_ssl",
    "ai_temperature": "temperature",
    "ai_max_tokens": "max_tokens",
    "ai_thinking_type": "thinking_type",
    "ai_reasoning_effort": "reasoning_effort",
    "ai_top_p": "top_p",
    "ai_frequency_penalty": "frequency_penalty",
    "ai_presence_penalty": "presence_penalty",
    "ai_stop": "stop",
    "ai_anthropic_version": "anthropic_version",
}


def client_kwargs(db: Session) -> dict:
    """运行时 AI 配置 → LLMClient 构造参数（跳过与客户端无关的 ai_enable_body_send）。"""
    overrides = load_ai_overrides(db)
    return {CLIENT_KWARG_KEYS[k]: v for k, v in overrides.items() if k in CLIENT_KWARG_KEYS}


# 多模态视觉客户端构造参数映射（settings 的 vision_* 键 → client 关键字）
VISION_CLIENT_KWARG_KEYS: dict[str, str] = {
    "vision_base_url": "base_url",
    "vision_api_key": "api_key",
    "vision_model": "model",
    "vision_timeout": "timeout",
    "vision_verify_ssl": "verify_ssl",
    "vision_max_tokens": "max_tokens",
    "vision_temperature": "temperature",
    "vision_top_p": "top_p",
    "vision_frequency_penalty": "frequency_penalty",
    "vision_presence_penalty": "presence_penalty",
    "vision_enable_thinking": "enable_thinking",
    "vision_thinking_budget": "thinking_budget",
}


def vision_client_kwargs(db: Session) -> dict:
    """运行时多模态视觉配置 → LLMClient 构造参数；未覆盖项取 .env 的 vision_*（不能回退到文本 AI 配置）。"""
    overrides = load_ai_overrides(db)
    kwargs: dict = {}
    for key, client_key in VISION_CLIENT_KWARG_KEYS.items():
        kwargs[client_key] = overrides.get(key, getattr(settings, key))
    # SiliconFlow 仅支持 /chat/completions，强制 chat 模式（responses 会 404）
    kwargs["mode"] = "chat"
    return kwargs


def vision_configured(db: Session) -> bool:
    """是否已配置可用的多模态视觉 API（base_url + api_key + model 均非空）。"""
    kwargs = vision_client_kwargs(db)
    return bool(kwargs.get("base_url") and kwargs.get("api_key") and kwargs.get("model"))


def load_ai_overrides(db: Session) -> dict:
    """读取运行时 AI 配置（仅返回 DB 中已覆盖的项），未覆盖项沿用 .env。"""
    rows = db.scalars(select(Setting).where(Setting.key.in_(AI_OVERRIDE_KEYS))).all()
    overrides: dict = {}
    for row in rows:
        key = row.key
        raw = row.value
        if key in _BOOL_KEYS:
            overrides[key] = raw.strip().lower() in ("1", "true", "yes", "on")
        elif key in _INT_KEYS:
            try:
                overrides[key] = int(raw)
            except ValueError:
                continue
        elif key in _FLOAT_KEYS:
            try:
                overrides[key] = float(raw)
            except ValueError:
                continue
        else:
            overrides[key] = raw
    return overrides


def save_ai_overrides(db: Session, data: dict) -> dict:
    """保存运行时 AI 配置；返回掩码后的当前视图。空字符串/None 视为未修改（保留旧值）。"""
    for key, value in data.items():
        if key not in AI_OVERRIDE_KEYS or value is None:
            continue
        if isinstance(value, bool):
            text = "1" if value else "0"
        elif isinstance(value, (int, float)):
            text = str(value)
        else:
            text = str(value).strip()
        if not text:
            continue
        set_setting(db, key, text)
    return ai_settings_view(db)


def mask_api_key(api_key: str | None) -> str:
    """掩码 API Key：保留前 3 位与后 4 位，其余以 * 代替。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}{'*' * (len(api_key) - 7)}{api_key[-4:]}"


def ai_settings_view(db: Session) -> dict:
    """AI 配置视图（API Key 掩码）：运行时覆盖优先，未覆盖取 .env。"""
    overrides = load_ai_overrides(db)
    base_url = overrides.get("ai_base_url", settings.ai_base_url)
    api_key = overrides.get("ai_api_key", settings.ai_api_key)
    mode = overrides.get("ai_mode", settings.ai_mode)
    return {
        "base_url": base_url,
        "api_key": mask_api_key(api_key),
        "api_key_set": bool(api_key),
        "model": overrides.get("ai_model", settings.ai_model),
        "mode": mode,
        "timeout": overrides.get("ai_timeout", settings.ai_timeout),
        "verify_ssl": overrides.get("ai_verify_ssl", settings.ai_verify_ssl),
        "enable_body_send": overrides.get("ai_enable_body_send", settings.ai_enable_body_send),
        "send_page_image": overrides.get("ai_send_page_image", settings.ai_send_page_image),
        "temperature": overrides.get("ai_temperature", getattr(settings, "ai_temperature", None)),
        "max_tokens": overrides.get("ai_max_tokens", getattr(settings, "ai_max_tokens", None)),
        "thinking_type": overrides.get("ai_thinking_type", getattr(settings, "ai_thinking_type", "")),
        "reasoning_effort": overrides.get("ai_reasoning_effort", getattr(settings, "ai_reasoning_effort", "")),
        "top_p": overrides.get("ai_top_p", getattr(settings, "ai_top_p", None)),
        "frequency_penalty": overrides.get("ai_frequency_penalty", getattr(settings, "ai_frequency_penalty", None)),
        "presence_penalty": overrides.get("ai_presence_penalty", getattr(settings, "ai_presence_penalty", None)),
        "stop": overrides.get("ai_stop", getattr(settings, "ai_stop", "")),
        "vision_base_url": overrides.get("vision_base_url", settings.vision_base_url),
        "vision_api_key": mask_api_key(overrides.get("vision_api_key", settings.vision_api_key)),
        "vision_api_key_set": bool(overrides.get("vision_api_key", settings.vision_api_key)),
        "vision_model": overrides.get("vision_model", settings.vision_model),
        "vision_timeout": overrides.get("vision_timeout", settings.vision_timeout),
        "vision_verify_ssl": overrides.get("vision_verify_ssl", settings.vision_verify_ssl),
        "vision_max_tokens": overrides.get("vision_max_tokens", settings.vision_max_tokens),
        "vision_temperature": overrides.get("vision_temperature", settings.vision_temperature),
        "vision_top_p": overrides.get("vision_top_p", settings.vision_top_p),
        "vision_frequency_penalty": overrides.get("vision_frequency_penalty", settings.vision_frequency_penalty),
        "vision_presence_penalty": overrides.get("vision_presence_penalty", settings.vision_presence_penalty),
        "vision_enable_thinking": overrides.get("vision_enable_thinking", settings.vision_enable_thinking),
        "vision_thinking_budget": overrides.get("vision_thinking_budget", settings.vision_thinking_budget),
    }

def find_env_file() -> Path | None:
    """定位 .env 配置文件：兼容 uvicorn 在 backend/ 下启动与从仓库根目录运行。"""
    candidates = [
        Path(".env"),
        Path("backend/.env"),
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def reload_ai_overrides_from_env(db: Session, env_path: Path | None = None) -> dict:
    """强制载入 .env 配置文件：以 .env 当前内容为准重置运行时 AI/视觉配置。

    - .env 中存在的 AI_OVERRIDE_KEYS 项 → 写入 DB 覆盖（与 .env 一致，立即生效）；
    - .env 中不存在的项 → 删除 DB 覆盖（回落默认值）；
    - 返回掩码后的最新视图（API Key 不回显明文）。
    """
    env = env_path or find_env_file()
    if env is None or not env.is_file():
        raise FileNotFoundError(".env 配置文件不存在（backend/.env）")
    values = dotenv_values(env)  # 只读解析，不回写文件
    changed = False
    for settings_key, env_name in AI_OVERRIDE_KEYS.items():
        raw = values.get(env_name)
        row = db.get(Setting, settings_key)
        if raw is None or not str(raw).strip():
            if row is not None:
                db.delete(row)
                changed = True
            continue
        text = str(raw).strip()
        if row is None:
            db.add(Setting(key=settings_key, value=text))
            changed = True
        elif row.value != text:
            row.value = text
            changed = True
    if changed:
        db.commit()
    return ai_settings_view(db)