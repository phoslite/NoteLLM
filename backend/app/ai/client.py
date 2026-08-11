"""LLM 客户端（stdlib 实现，零额外依赖），支持三种接口格式（均含普通与流式 SSE）：

- responses：POST {endpoint}/responses（instructions/input，DeepSeek 官方用法）
- chat：     POST {endpoint}/chat/completions（messages，OpenAI 兼容）
- anthropic：POST {endpoint}/v1/messages（Anthropic Messages API，x-api-key 鉴权）

`base_url` 支持两种写法（见 resolve_endpoint）：
1. 基础地址（如 https://api.deepseek.com 或 https://host/v1），系统按接口模式自动补全路径；
2. 完整接口 URL（如 https://host/v1/chat/completions），系统直接使用不再补全。

`stream()` 返回逐块文本生成器，供 M4 对话 SSE 使用。
"""
import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterable

from app.ai.limiter import get_limiter
from app.core.config import settings


class LLMError(RuntimeError):
    """LLM 调用失败（网络/鉴权/解析）。"""


# 部分服务商（如 opencode.ai 前的 Cloudflare）会拦截 urllib 默认 UA（HTTP 403 error 1010）
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


# 各接口模式的完整路径后缀（用于识别「已填写完整 URL」）与自动补全路径
_PATH_SUFFIXES: dict[str, tuple[str, ...]] = {
    "responses": ("/responses",),
    "anthropic": ("/v1/messages", "/messages"),
    "chat": ("/chat/completions",),
}
_AUTO_PATHS: dict[str, tuple[str, str]] = {
    # (base 不含 /v1 时补全, base 以 /v1 结尾时补全)
    "responses": ("/v1/responses", "/responses"),
    "anthropic": ("/v1/messages", "/messages"),
    "chat": ("/v1/chat/completions", "/chat/completions"),
}


def _stream_error(exc: Exception, url: str) -> LLMError:
    """流式迭代中的网络异常 → LLMError（审查 C-问题9：原来异常直接穿透，SSE 静默断流）。

    与 _request 同口径：Windows 下 errno 映射为 POSIX 值（10013→13），真实错误码在 winerror。
    """
    reason = getattr(exc, "reason", exc)
    errno_val = getattr(reason, "errno", None)
    winerror_val = getattr(reason, "winerror", None)
    if winerror_val == 10013 or errno_val == 10013:
        return LLMError(f"网络连接被拦截（WinError 10013），流式输出中断，无法继续访问 {url}。")
    return LLMError(f"网络错误（流式中断）: {exc}（errno={errno_val}, winerror={winerror_val}）")


def resolve_endpoint(base_url: str, mode: str) -> str:
    """解析最终请求端点，支持两种 base_url 写法：

    1. 完整接口 URL：以当前模式的接口路径结尾（如 /chat/completions、/responses、/v1/messages）
       ——直接使用，不再补全；
    2. 基础地址：其余情况自动补全 —— base 以 /v1 结尾补相对路径（/chat/completions 等），
       否则补带 /v1 前缀的完整路径（/v1/chat/completions 等）。
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise LLMError("base_url 未配置")
    for suffix in _PATH_SUFFIXES.get(mode, _PATH_SUFFIXES["chat"]):
        if base.endswith(suffix):
            return base
    with_v1, without_v1 = _AUTO_PATHS.get(mode, _AUTO_PATHS["chat"])
    return base + (without_v1 if base.endswith("/v1") else with_v1)


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        mode: str | None = None,
        anthropic_version: str | None = None,
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
        kind: str = "text",  # 限流池：text / vision（决策 35，=0 不限制）
    ):
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.ai_api_key
        self.model = model or settings.ai_model
        self.mode = mode or settings.ai_mode
        self.anthropic_version = anthropic_version or getattr(settings, "ai_anthropic_version", "2023-06-01")
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
        self.kind = kind

    def _headers(self) -> dict:
        """请求头：anthropic 用 x-api-key + 版本头，其余用 Bearer。"""
        headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
        if self.mode == "anthropic":
            if self.api_key:
                headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = self.anthropic_version
        elif self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _request(self, body: dict, stream: bool = False):
        """构造并发送请求，返回响应体（流式时返回可迭代行）。"""
        url = resolve_endpoint(self.base_url, self.mode)
        if stream:
            body["stream"] = True
        payload = json.dumps(body).encode("utf-8")
        headers = self._headers()
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
            # Windows 下 errno 被映射为 POSIX 值（WinError 10013 → errno 13/EACCES），
            # 真实错误码在 winerror：两者都判断，否则友好提示永远不命中（修复 2026-08-05）。
            errno_val = getattr(reason, "errno", None)
            winerror_val = getattr(reason, "winerror", None)
            if winerror_val == 10013 or errno_val == 10013:
                raise LLMError(
                    f"网络连接被拦截（WinError 10013），无法访问 {url}。"
                    "请检查：1) 防火墙/安全软件是否放行本程序；2) 是否开启了代理/VPN；"
                    "3) 用浏览器能否打开该 API 地址；4) 若程序由受限/沙盒环境启动"
                    "（如 Codex/IDE 内置终端），请用普通终端或 start.bat 重启后端。"
                ) from exc
            raise LLMError(f"网络错误: {exc}（errno={errno_val}, winerror={winerror_val}）") from exc
        return resp

    @staticmethod
    def _content_text(content) -> str:
        """消息内容转纯文本：字符串原样返回；parts 列表（多模态）仅取 text 部分。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        return ""

    @staticmethod
    def _anthropic_image_block(part: dict) -> dict:
        """OpenAI 兼容 image_url 部件 → Anthropic image 块（data URI → base64 source）。"""
        raw = part.get("image_url")
        url = raw.get("url", "") if isinstance(raw, dict) else ""
        if isinstance(url, str) and url.startswith("data:"):
            head, _, data = url.partition(",")
            media_type = head[len("data:"):].split(";")[0] or "image/png"
            return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
        return {"type": "image", "source": {"type": "url", "url": url}}

    def _anthropic_content(self, content) -> list[dict]:
        """消息内容 → Anthropic content 块列表（文本 / 图片）。"""
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        blocks: list[dict] = []
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image_url":
                blocks.append(self._anthropic_image_block(part))
        return blocks

    def _build_body(self, messages: list[dict]) -> dict:
        if self.mode == "anthropic":
            system = "\n".join(self._content_text(m["content"]) for m in messages if m["role"] == "system")
            merged: list[dict] = []
            for m in messages:
                if m["role"] == "system":
                    continue
                blocks = self._anthropic_content(m["content"])
                if merged and merged[-1]["role"] == m["role"]:
                    merged[-1]["content"] += blocks
                else:
                    merged.append({"role": m["role"], "content": blocks})
            body: dict = {"model": self.model, "max_tokens": self.max_tokens or 4096, "messages": merged}
            if system:
                body["system"] = system
            if self.temperature is not None:
                body["temperature"] = self.temperature
            if self.top_p is not None:
                body["top_p"] = self.top_p
            if self.stop:
                body["stop_sequences"] = self.stop.split(",") if isinstance(self.stop, str) else list(self.stop)
            return body
        if self.mode == "responses":
            system = "\n".join(self._content_text(m["content"]) for m in messages if m["role"] == "system")
            inputs: list[dict] = [
                {"role": m["role"], "content": self._content_text(m["content"])}
                for m in messages
                if m["role"] != "system"
            ]
            body: dict = {"model": self.model, "instructions": system or None, "input": inputs}
            if self.max_tokens is not None:
                body["max_output_tokens"] = self.max_tokens  # DeepSeek responses 命名（含思考 token）
            if self.reasoning_effort and self.thinking_type != "disabled":
                body["reasoning"] = {"effort": self.reasoning_effort}
            if self.enable_thinking is not None:
                body["enable_thinking"] = self.enable_thinking
            if self.thinking_budget is not None:
                body["thinking_budget"] = self.thinking_budget
            # B-I3：responses 模式此前静默丢弃采样参数（默认 AI_MODE=responses 时
            # 挑选器 RAG_SELECT_TEMPERATURE=0.0 的确定性意图落空）；DeepSeek responses 支持
            if self.temperature is not None:
                body["temperature"] = self.temperature
            if self.top_p is not None:
                body["top_p"] = self.top_p
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
        if isinstance(data.get("content"), list):  # anthropic messages 模式
            return "".join(
                c.get("text", "") for c in data["content"] if isinstance(c, dict) and c.get("type") == "text"
            )
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
        if mode == "anthropic":
            if data.get("type") == "content_block_delta" and (data.get("delta") or {}).get("type") == "text_delta":
                return data["delta"].get("text", "") or ""
            return ""
        if mode == "responses":
            if data.get("type") == "response.output_text.delta":
                return data.get("delta", "") or ""
            return ""
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("delta", {}).get("content", "") or ""
        return ""

    def chat(self, messages: list[dict]) -> str:
        """发送一轮对话，返回回复文本。messages 为 [{role, content}, ...]。

        经 get_limiter(kind) 限流（决策 35）：并发受限时排队等待。
        """
        limiter = get_limiter(self.kind)
        if limiter:
            limiter.acquire()
        try:
            body = self._build_body(messages)
            resp = self._request(body)
            with resp:
                try:
                    raw = resp.read()
                except (OSError, TimeoutError) as exc:  # B-M1：连接中断/超时统一转 LLMError
                    raise LLMError(f"响应读取失败：{exc}") from exc
                try:
                    data = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:  # 审查 I-2：非 JSON 响应统一包装为 LLMError
                    raise LLMError(f"响应解析失败（非 JSON）：{exc}") from exc
            reply = self._extract_reply(data)
            if not reply:
                raise LLMError("响应中未找到文本内容")
            return reply
        finally:
            if limiter:
                limiter.release()

    def stream(self, messages: list[dict]) -> Iterable[str]:
        """流式对话：逐块产出回复文本（SSE）。失败抛 LLMError。

        生成器首次迭代时获取限流信号量，耗尽 / 关闭（客户端断开）时释放。
        """
        limiter = get_limiter(self.kind)
        if limiter:
            limiter.acquire()
        try:
            body = self._build_body(messages)
            url = resolve_endpoint(self.base_url, self.mode)
            resp = self._request(body, stream=True)
            with resp:
                try:
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
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise _stream_error(exc, url) from exc
        finally:
            if limiter:
                limiter.release()

    def stream_events(self, messages: list[dict]) -> Iterable[dict]:
        """流式对话：逐块产出事件 dict（{\"kind\": \"thinking\" | \"delta\", \"text\": str}）。

        与 stream() 的区别：thinking 模式下（如 DeepSeek enable_thinking）先输出
        reasoning_content（思考过程）再输出 content。thinking 事件供前端展示「思考中」
        实况，避免用户在思考阶段看到长时间空白（方案2 固定频率刷新配套）。
        """
        limiter = get_limiter(self.kind)
        if limiter:
            limiter.acquire()
        try:
            body = self._build_body(messages)
            url = resolve_endpoint(self.base_url, self.mode)
            resp = self._request(body, stream=True)
            with resp:
                try:
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
                        if self.mode == "anthropic":
                            if obj.get("type") == "content_block_delta":
                                d = obj.get("delta") or {}
                                if d.get("type") == "thinking_delta" and d.get("thinking"):
                                    yield {"kind": "thinking", "text": d["thinking"]}
                                elif d.get("type") == "text_delta" and d.get("text"):
                                    yield {"kind": "delta", "text": d["text"]}
                            continue
                        if self.mode == "responses":
                            if obj.get("type") == "response.output_text.delta" and obj.get("delta"):
                                yield {"kind": "delta", "text": obj["delta"]}
                            elif obj.get("type") == "response.reasoning_summary_text.delta" and obj.get("delta"):
                                yield {"kind": "thinking", "text": obj["delta"]}
                            elif obj.get("type") == "response.reasoning_text.delta" and obj.get("delta"):
                                # 审查 I-2：部分网关以 reasoning_text 而非 reasoning_summary_text 输出思考流
                                yield {"kind": "thinking", "text": obj["delta"]}
                            continue
                        choices = obj.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            if delta.get("reasoning_content"):
                                yield {"kind": "thinking", "text": delta["reasoning_content"]}
                            elif delta.get("content"):
                                yield {"kind": "delta", "text": delta["content"]}
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise _stream_error(exc, url) from exc
        finally:
            if limiter:
                limiter.release()
