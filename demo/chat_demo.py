# -*- coding: utf-8 -*-
"""LLM 简易对话 Demo（零第三方依赖，OpenAI 兼容接口）。

支持两种接口模式：
- responses：POST {base_url}/responses，body {model, instructions, input}（DeepSeek 官方用法）
- chat：     POST {base_url}/chat/completions，body {model, messages}（通用 Chat Completions）

配置来源（优先级从高到低）：命令行参数 > 环境变量 > demo/.env
用法示例：
  python demo/chat_demo.py --mock --prompt "请生成本书的思维导图"
  python demo/chat_demo.py --prompt "你好，请简单介绍自己"          # 使用 demo/.env 的真实配置
  python demo/chat_demo.py --mode chat --prompt "1+1=?"             # 切换接口模式
不传 --prompt 时进入交互式多轮对话（输入 exit 退出）。
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"
DEFAULT_MOCK = "http://127.0.0.1:18999/v1"


def load_env_file(path: Path) -> dict:
    """读取 KEY=VALUE 形式的 .env 文件（跳过注释与空行）。"""
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def parse_args():
    p = argparse.ArgumentParser(description="LLM 简易对话 demo（OpenAI 兼容）")
    p.add_argument("--base-url", help="OpenAI 兼容 base_url，如 https://api.deepseek.com")
    p.add_argument("--api-key", help="API Key（默认读 demo/.env 的 AI_API_KEY）")
    p.add_argument("--model", help="模型名，如 deepseek-v4-flash")
    p.add_argument("--mode", choices=["responses", "chat"], help="接口模式")
    p.add_argument("--timeout", type=int, default=120, help="请求超时秒数")
    p.add_argument("--no-verify-ssl", action="store_true", help="关闭 SSL 证书校验")
    p.add_argument("--prompt", help="单轮提问（不传则进入交互式多轮对话）")
    p.add_argument("--mock", action="store_true", help="指向本地 mock 服务")
    return p.parse_args()


def build_payload(mode: str, model: str, messages: list) -> dict:
    """按接口模式构造请求体。"""
    if mode == "responses":
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n".join(m["content"] for m in messages if m["role"] == "user")
        return {"model": model, "instructions": system or None, "input": user}
    return {"model": model, "messages": messages}


def extract_reply(mode: str, data: dict) -> str:
    """从响应体中提取回复文本。"""
    if mode == "responses":
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        return c.get("text", "")
        return ""
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


def call_llm(base_url: str, api_key: str, model: str, mode: str, messages: list,
             timeout: int, verify_ssl: bool) -> str:
    """发送一次对话请求，返回模型回复文本。失败抛异常。"""
    path = "/responses" if mode == "responses" else "/chat/completions"
    url = base_url.rstrip("/") + path
    payload = json.dumps(build_payload(mode, model, messages)).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    reply = extract_reply(mode, data)
    if not reply:
        raise RuntimeError("响应中未找到文本内容: " + json.dumps(data, ensure_ascii=False)[:300])
    return reply


def mask_key(key: str) -> str:
    """隐藏 API Key 中间部分，避免日志泄露。"""
    if not key:
        return "(空)"
    return key[:6] + "***" + key[-4:] if len(key) > 12 else "***"


def main() -> int:
    args = parse_args()
    env = load_env_file(ENV_FILE)

    base_url = args.base_url or env.get("AI_BASE_URL") or (DEFAULT_MOCK if args.mock else "")
    if args.mock:
        base_url = args.base_url or DEFAULT_MOCK
    if not base_url:
        print("缺少 base_url：请通过 --base-url 或 demo/.env 的 AI_BASE_URL 提供")
        return 2
    api_key = args.api_key or env.get("AI_API_KEY") or ""
    model = args.model or env.get("AI_MODEL") or "demo-model"
    mode = args.mode or env.get("AI_MODE") or "responses"
    timeout = args.timeout or int(env.get("AI_TIMEOUT") or 120)
    verify_ssl = not args.no_verify_ssl

    print(f"[配置] base_url={base_url}  model={model}  mode={mode}  api_key={mask_key(api_key)}")

    messages = [{"role": "system", "content": "你是一个乐于助人的中文助手，回答简洁准确。"}]
    if args.prompt:
        messages.append({"role": "user", "content": args.prompt})
        try:
            reply = call_llm(base_url, api_key, model, mode, messages, timeout, verify_ssl)
        except Exception as exc:
            print(f"[失败] {exc}")
            return 1
        print(f"\n[用户] {args.prompt}\n[助手] {reply}")
        return 0

    print("（交互模式：输入 exit 退出）")
    while True:
        try:
            user = input("\n[用户] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("exit", "quit", "q"):
            break
        messages.append({"role": "user", "content": user})
        try:
            reply = call_llm(base_url, api_key, model, mode, messages, timeout, verify_ssl)
        except Exception as exc:
            print(f"[失败] {exc}")
            continue
        print(f"[助手] {reply}")
        messages.append({"role": "assistant", "content": reply})
    return 0


if __name__ == "__main__":
    sys.exit(main())