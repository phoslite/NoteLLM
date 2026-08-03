"""设置页「强制载入 .env」：以 .env 文件内容为准重置运行时 AI/视觉配置。"""

import pytest

from app.core.database import SessionLocal
from app.repositories.settings import reload_ai_overrides_from_env, save_ai_overrides


def test_reload_env_applies_env_and_clears_missing(client, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "AI_BASE_URL=https://env.example.com/v1\n"
        "AI_API_KEY=sk-env-key-12345\n"
        "AI_MODEL=env-model\n"
        "AI_MODE=chat\n"
        "VISION_MODEL=env-vision-model\n",
        encoding="utf-8",
    )
    db = SessionLocal()
    save_ai_overrides(
        db,
        {
            "ai_base_url": "https://old.example.com",
            "ai_model": "old-model",
            "ai_temperature": 0.7,  # .env 无此键 → 应被清除
            "vision_model": "old-vision",
        },
    )
    view = reload_ai_overrides_from_env(db, env_path=env)
    assert view["base_url"] == "https://env.example.com/v1"
    assert view["model"] == "env-model"
    assert view["mode"] == "chat"
    assert view["api_key_set"] is True
    assert "sk-env" not in view["api_key"]  # API Key 掩码，不回显明文
    assert view["vision_model"] == "env-vision-model"
    assert view["temperature"] != 0.7  # .env 无 AI_TEMPERATURE → 覆盖被清除（回落默认）
    # 幂等：再次执行结果一致
    view2 = reload_ai_overrides_from_env(db, env_path=env)
    assert view2 == view


def test_reload_env_missing_file_raises(client, tmp_path):
    with pytest.raises(FileNotFoundError):
        reload_ai_overrides_from_env(SessionLocal(), env_path=tmp_path / "nope.env")


def test_reload_env_endpoint(client, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("AI_MODEL=endpoint-model\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.api.routes.settings.reload_ai_overrides_from_env",
        lambda db: reload_ai_overrides_from_env(db, env_path=env),
    )
    r = client.post("/api/settings/ai/reload-env")
    assert r.status_code == 200
    assert r.json()["data"]["model"] == "endpoint-model"

    def boom(db):
        raise FileNotFoundError("no env")

    monkeypatch.setattr("app.api.routes.settings.reload_ai_overrides_from_env", boom)
    r2 = client.post("/api/settings/ai/reload-env")
    assert r2.status_code == 404