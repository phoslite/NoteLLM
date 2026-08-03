"""AI 精细参数（DeepSeek 思考模式 / SiliconFlow）：LLMClient 请求体与设置链路。"""
from app.ai.client import LLMClient, resolve_endpoint
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


# ---------- Anthropic Messages API 模式 ----------
def _anthropic(**kw) -> LLMClient:
    return LLMClient(base_url="https://api.anthropic.com", api_key="k", model="m", mode="anthropic", **kw)


def test_anthropic_path_and_headers():
    c = _anthropic()
    assert resolve_endpoint(c.base_url, c.mode) == "https://api.anthropic.com/v1/messages"
    headers = c._headers()
    assert headers["x-api-key"] == "k"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers
    assert LLMClient(base_url="http://x", api_key="k", mode="chat")._headers()["Authorization"] == "Bearer k"


def test_build_body_anthropic_basic():
    body = _anthropic()._build_body(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
    )
    assert body["model"] == "m"
    assert body["system"] == "你是助手"
    assert body["max_tokens"] == 4096  # 必填默认
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "你好"}]}]


def test_build_body_anthropic_merge_same_role():
    body = _anthropic()._build_body(
        [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]


def test_build_body_anthropic_image():
    body = _anthropic()._build_body(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ]
    )
    img = body["messages"][0]["content"][1]
    assert img == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}


def test_build_body_anthropic_fine_params():
    body = _anthropic(max_tokens=8192, temperature=0.5, top_p=0.9, stop="a,b")._build_body(
        [{"role": "user", "content": "hi"}]
    )
    assert body["max_tokens"] == 8192
    assert body["temperature"] == 0.5
    assert body["top_p"] == 0.9
    assert body["stop_sequences"] == ["a", "b"]


def test_extract_reply_anthropic():
    c = _anthropic()
    assert c._extract_reply({"content": [{"type": "text", "text": "答案"}, {"type": "text", "text": "二"}]}) == "答案二"
    assert c._extract_reply({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}) == "ok"


def test_extract_delta_anthropic():
    c = _anthropic()
    assert (
        c._extract_delta({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "增量"}}, "anthropic")
        == "增量"
    )
    assert c._extract_delta({"type": "message_delta"}, "anthropic") == ""

# ---------- base_url 两种写法：短地址自动补全 / 完整 URL 直接使用 ----------
def test_resolve_endpoint_short_base_auto_suffix():
    # 不含 /v1 的基础地址：自动补 /v1 前缀完整路径
    assert resolve_endpoint("https://api.deepseek.com", "chat") == "https://api.deepseek.com/v1/chat/completions"
    assert resolve_endpoint("https://api.deepseek.com", "responses") == "https://api.deepseek.com/v1/responses"
    assert resolve_endpoint("https://api.anthropic.com", "anthropic") == "https://api.anthropic.com/v1/messages"


def test_resolve_endpoint_v1_base_auto_suffix():
    # 以 /v1 结尾的基础地址：补相对路径，避免 /v1/v1
    assert resolve_endpoint("https://opencode.ai/zen/go/v1", "chat") == "https://opencode.ai/zen/go/v1/chat/completions"
    assert resolve_endpoint("https://host/v1", "responses") == "https://host/v1/responses"
    assert resolve_endpoint("https://host/v1", "anthropic") == "https://host/v1/messages"


def test_resolve_endpoint_full_url_used_as_is():
    # 完整接口 URL：直接使用，不再补全
    assert resolve_endpoint("https://host/v1/chat/completions", "chat") == "https://host/v1/chat/completions"
    assert resolve_endpoint("https://host/chat/completions", "chat") == "https://host/chat/completions"
    assert resolve_endpoint("https://host/v1/responses", "responses") == "https://host/v1/responses"
    assert resolve_endpoint("https://host/v1/messages", "anthropic") == "https://host/v1/messages"


def test_resolve_endpoint_trailing_slash_and_unknown_mode():
    # 尾斜杠会被去掉；未知模式回退 chat 补全
    assert resolve_endpoint("https://host/v1/", "chat") == "https://host/v1/chat/completions"
    assert resolve_endpoint("https://host", "openai") == "https://host/v1/chat/completions"


def test_resolve_endpoint_empty_base_raises():
    from app.ai.client import LLMError

    try:
        resolve_endpoint("", "chat")
    except LLMError:
        return
    raise AssertionError("空 base_url 应抛 LLMError")
