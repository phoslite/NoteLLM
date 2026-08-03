"""M4 AI 接入测试：设置 API（查看/保存/掩码）、对话流式 SSE、历史落库。"""
import json

from app.ai.client import LLMClient, LLMError
from app.services.ai_context import paragraph_numbered
from app.services.citations import extract_citations


def _upload(client, text="# 第一章\n\n正文第一段\n\n# 第二章\n\n正文二\n"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _configure(client, **kw):
    body = {"base_url": "http://127.0.0.1:18999/v1", "api_key": "sk-test", "model": "mock", "mode": "responses"}
    body.update(kw)
    r = client.patch("/api/settings/ai", json=body)
    assert r.status_code == 200
    return r.json()["data"]


def test_ai_settings_view_and_save(client):
    view = client.get("/api/settings/ai").json()["data"]
    assert view["api_key_set"] is False
    assert view["api_key"] == ""

    data = _configure(client, base_url="http://127.0.0.1:18999/v1", api_key="sk-abcdef123456")
    assert data["base_url"] == "http://127.0.0.1:18999/v1"
    assert data["api_key_set"] is True
    assert "sk-" in data["api_key"] and "abcdef" not in data["api_key"]  # 掩码不回显明文

    # 空字符串视为未修改（保留旧值）
    data2 = _configure(client, api_key="")
    assert data2["api_key_set"] is True


def test_chat_requires_config(client):
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]
    r = client.post(f"/api/books/{book_id}/chat", json={"question": "你好", "chapter_id": ch})
    assert r.status_code == 400
    assert "API Key" in r.json()["detail"]


def test_chat_stream_and_persist(client, monkeypatch):
    _configure(client)
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]

    def fake_stream(self, messages):
        assert messages and messages[0]["role"] == "system"
        yield "第一段回复，引用【第1章 第1段】。"
        yield "第二段回复。"

    monkeypatch.setattr(LLMClient, "stream", fake_stream)
    with client.stream("POST", f"/api/books/{book_id}/chat", json={"question": "解读", "chapter_id": ch}) as resp:
        assert resp.status_code == 200
        events = [json.loads(line[5:]) for line in resp.iter_lines() if (line or "").startswith("data:")]

    types = [e["type"] for e in events]
    assert types == ["start", "delta", "delta", "end"]
    full = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "第一段回复" in full
    end = [e for e in events if e["type"] == "end"][0]
    assert end["citations"] == [{"chapter": 1, "para": "1"}]

    msgs = client.get(f"/api/books/{book_id}/chat/messages").json()["data"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[-1]["content"] == full


def test_chat_stream_error_event(client, monkeypatch):
    _configure(client)
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]

    def fail_stream(self, messages):
        raise LLMError("模拟网络失败")

    monkeypatch.setattr(LLMClient, "stream", fail_stream)
    with client.stream("POST", f"/api/books/{book_id}/chat", json={"question": "解读", "chapter_id": ch}) as resp:
        events = [json.loads(line[5:]) for line in resp.iter_lines() if (line or "").startswith("data:")]
    assert events[-1]["type"] == "error"
    assert "模拟网络失败" in events[-1]["message"]
    # 失败不落库
    msgs = client.get(f"/api/books/{book_id}/chat/messages").json()["data"]
    assert msgs == []


def test_chat_validation(client):
    _configure(client)
    book_id = _upload(client)
    assert client.post(f"/api/books/{book_id}/chat", json={"question": "  "}).status_code == 400
    assert client.post(f"/api/books/{book_id}/chat", json={"question": "x", "chapter_id": 99999}).status_code == 404


def test_citation_and_numbering_helpers():
    assert paragraph_numbered("a\n\nb").splitlines() == ["【第1段】a", "【第2段】b"]
    assert extract_citations("见【第2章 第3-4段】和【第1章 第5段】") == [
        {"chapter": 2, "para": "3-4"},
        {"chapter": 1, "para": "5"},
    ]
    assert extract_citations("无引用") == []

def test_chat_session_mode_pooling_and_history(client, monkeypatch):
    """决策 30：会话按 mode 分池 + 历史窗口注入（最近轮次回传 LLM）。"""
    _configure(client)
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]
    seen = []

    def fake_stream(self, messages):
        seen.append(messages)
        yield "回复占位"

    monkeypatch.setattr(LLMClient, "stream", fake_stream)

    def ask(question, mode=None):
        body = {"question": question, "chapter_id": ch}
        if mode:
            body["mode"] = mode
        with client.stream("POST", f"/api/books/{book_id}/chat", json=body) as resp:
            assert resp.status_code == 200
            for _ in resp.iter_lines():
                pass

    ask("默认第一问")
    ask("解读第一问", mode="解读")
    ask("解读追问", mode="解读")

    # 分池：默认会话只含默认问题，解读会话含两轮
    default_msgs = client.get(f"/api/books/{book_id}/chat/messages").json()["data"]
    interpret_msgs = client.get(f"/api/books/{book_id}/chat/messages?mode=解读").json()["data"]
    assert [m["content"] for m in default_msgs if m["role"] == "user"] == ["默认第一问"]
    assert [m["content"] for m in interpret_msgs if m["role"] == "user"] == ["解读第一问", "解读追问"]

    # 历史注入：第三轮请求 messages = [system, user(第一问), assistant, user(追问)]
    third = seen[2]
    assert [m["role"] for m in third] == ["system", "user", "assistant", "user"]
    assert third[1]["content"] == "解读第一问"
    assert "解读追问" in third[3]["content"]

    # 清空按模式：只清解读会话
    assert client.delete(f"/api/books/{book_id}/chat/messages?mode=解读").status_code == 200
    assert client.get(f"/api/books/{book_id}/chat/messages?mode=解读").json()["data"] == []
    assert len(client.get(f"/api/books/{book_id}/chat/messages").json()["data"]) == 2
