"""LLM 客户端（OpenAI 兼容，stdlib 实现，零额外依赖）。

支持两种接口模式（均含普通与流式 SSE）：
- responses：POST {base_url}/responses（instructions/input，DeepSeek 官方用法）
- chat：     POST {base_url}/chat/completions（messages）

流式输出：`stream()` 返回逐块文本生成器，供 M4 对话 SSE 使用。
"""
import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterable

from app.core.config import settings


class LLMError(RuntimeError):
    """LLM 调用失败（网络/鉴权/解析）。"""


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        mode: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        stop: str | list[str] | None = None,
        thinking_type: str | None = None,
        reasoning_effort: str | None = None,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ):
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.ai_api_key
        self.model = model or settings.ai_model
        self.mode = mode or settings.ai_mode
        self.timeout = timeout or settings.ai_timeout
        self.verify_ssl = settings.ai_verify_ssl if verify_ssl is None else verify_ssl
        self.temperature = temperature if temperature is not None else getattr(settings, "ai_temperature", None)
        self.max_tokens = max_tokens
        self.top_p = top_p if top_p is not None else getattr(settings, "ai_top_p", None)
        self.frequency_penalty = (
            frequency_penalty if frequency_penalty is not None else getattr(settings, "ai_frequency_penalty", None)
        )
        self.presence_penalty = (
            presence_penalty if presence_penalty is not None else getattr(settings, "ai_presence_penalty", None)
        )
        self.stop = stop if stop is not None else getattr(settings, "ai_stop", "")
        self.thinking_type = thinking_type if thinking_type is not None else getattr(settings, "ai_thinking_type", "")
        self.reasoning_effort = (
            reasoning_effort if reasoning_effort is not None else getattr(settings, "ai_reasoning_effort", "")
        )
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget

    def _request(self, body: dict, stream: bool = False):
        """构造并发送请求，返回响应体（流式时返回可迭代行）。"""
        path = "/responses" if self.mode == "responses" else "/chat/completions"
        url = self.base_url + path
        if stream:
            body["stream"] = True
        payload = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        ctx = ssl.create_default_context()
        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout, context=ctx)
        except urllib.error.HTTPError as exc:
            raise LLMError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, OSError) and reason.errno == 10013:
                raise LLMError(
                    f"网络连接被拦截（WinError 10013），无法访问 {url}。"
                    "请检查：1) 防火墙/安全软件是否放行本程序；2) 是否开启了代理/VPN；"
                    "3) 用浏览器能否打开该 API 地址。"
                ) from exc
            raise LLMError(f"网络错误: {exc}") from exc
        return resp

    @staticmethod
    def _content_text(content) -> str:
        """消息内容转纯文本：字符串原样返回；parts 列表（多模态）仅取 text 部分。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        return ""

    def _build_body(self, messages: list[dict]) -> dict:
        if self.mode == "responses":
            system = "\n".join(self._content_text(m["content"]) for m in messages if m["role"] == "system")
            user = "\n".join(self._content_text(m["content"]) for m in messages if m["role"] == "user")
            body: dict = {"model": self.model, "instructions": system or None, "input": user}
            if self.max_tokens is not None:
                body["max_output_tokens"] = self.max_tokens  # DeepSeek responses 命名（含思考 token）
            return body
        body: dict = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            body["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            body["presence_penalty"] = self.presence_penalty
        if self.stop:
            body["stop"] = self.stop.split(",") if isinstance(self.stop, str) else list(self.stop)
        if self.thinking_type:
            body["thinking"] = {"type": self.thinking_type}
        if self.reasoning_effort and self.thinking_type != "disabled":
            body["reasoning_effort"] = self.reasoning_effort
        if self.enable_thinking is not None:
            body["enable_thinking"] = self.enable_thinking
        if self.thinking_budget is not None:
            body["thinking_budget"] = self.thinking_budget
        return body

    @staticmethod
    def _extract_reply(data: dict) -> str:
        """从普通响应中提取文本。"""
        if "output" in data:  # responses 模式
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            return c.get("text", "")
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""

    @staticmethod
    def _extract_delta(data: dict, mode: str) -> str:
        """从 SSE 事件中提取增量文本。"""
        if mode == "responses":
            if data.get("type") == "response.output_text.delta":
                return data.get("delta", "") or ""
            return ""
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("delta", {}).get("content", "") or ""
        return ""

    def chat(self, messages: list[dict]) -> str:
        """发送一轮对话，返回回复文本。messages 为 [{role, content}, ...]。"""
        body = self._build_body(messages)
        resp = self._request(body)
        with resp:
            data = json.loads(resp.read().decode("utf-8"))
        reply = self._extract_reply(data)
        if not reply:
            raise LLMError("响应中未找到文本内容")
        return reply

    def stream(self, messages: list[dict]) -> Iterable[str]:
        """流式对话：逐块产出回复文本（SSE）。失败抛 LLMError。"""
        body = self._build_body(messages)
        resp = self._request(body, stream=True)
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = self._extract_delta(obj, self.mode)
                if delta:
                    yield delta