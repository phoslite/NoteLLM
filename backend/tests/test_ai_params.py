"""AI 精细参数（DeepSeek 思考模式 / SiliconFlow）：LLMClient 请求体与设置链路。"""
from app.ai.client import LLMClient
from app.core.database import SessionLocal
from app.repositories.settings import client_kwargs, vision_client_kwargs


def _chat(**kw) -> dict:
    c = LLMClient(base_url="http://x", api_key="k", model="m", mode="chat", **kw)
    return c._build_body([{"role": "user", "content": "hi"}])


def test_build_body_chat_fine_params():
    body = _chat(
        temperature=0.6,
        max_tokens=4096,
        top_p=0.9,
        frequency_penalty=0.1,
        presence_penalty=0.2,
        stop="a,b",
        thinking_type="enabled",
        reasoning_effort="high",
    )
    assert body["max_tokens"] == 4096
    assert body["top_p"] == 0.9
    assert body["frequency_penalty"] == 0.1
    assert body["presence_penalty"] == 0.2
    assert body["stop"] == ["a", "b"]
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


def test_build_body_thinking_disabled_skips_effort():
    body = _chat(thinking_type="disabled", reasoning_effort="high")
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_build_body_bare_chat_no_extra_fields():
    assert set(_chat()) == {"model", "messages"}


def test_build_body_responses_uses_max_output_tokens():
    c = LLMClient(base_url="http://x", api_key="k", model="m", mode="responses", max_tokens=8192)
    body = c._build_body([{"role": "user", "content": "hi"}])
    assert body["max_output_tokens"] == 8192
    assert "thinking" not in body and "max_tokens" not in body


def test_build_body_siliconflow_thinking():
    body = _chat(enable_thinking=True, thinking_budget=4096)
    assert body["enable_thinking"] is True
    assert body["thinking_budget"] == 4096


def test_settings_roundtrip_fine_params(client):
    r = client.patch(
        "/api/settings/ai",
        json={
            "base_url": "http://127.0.0.1:18999/v1",
            "api_key": "sk-test",
            "model": "m",
            "mode": "chat",
            "max_tokens": 8192,
            "thinking_type": "enabled",
            "reasoning_effort": "high",
            "top_p": 0.9,
            "frequency_penalty": 0.1,
            "presence_penalty": 0.2,
            "stop": "结论,总结",
            "vision_temperature": 0.7,
            "vision_top_p": 0.95,
            "vision_enable_thinking": False,
            "vision_thinking_budget": 4096,
        },
    )
    assert r.status_code == 200
    view = r.json()["data"]
    assert view["max_tokens"] == 8192
    assert view["thinking_type"] == "enabled"
    assert view["reasoning_effort"] == "high"
    assert view["top_p"] == 0.9
    assert view["frequency_penalty"] == 0.1
    assert view["presence_penalty"] == 0.2
    assert view["stop"] == "结论,总结"
    assert view["vision_temperature"] == 0.7
    assert view["vision_top_p"] == 0.95
    assert view["vision_enable_thinking"] is False
    assert view["vision_thinking_budget"] == 4096

    kwargs = client_kwargs(SessionLocal())
    assert kwargs["max_tokens"] == 8192
    assert kwargs["thinking_type"] == "enabled"
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["top_p"] == 0.9
    assert kwargs["stop"] == "结论,总结"


def test_vision_client_kwargs_fine_params_defaults(client):
    kwargs = vision_client_kwargs(SessionLocal())
    assert kwargs["mode"] == "chat"
    assert "temperature" in kwargs and "top_p" in kwargs
    assert "enable_thinking" in kwargs and "thinking_budget" in kwargs
