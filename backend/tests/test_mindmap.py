"""M5 脑图生成：JSON 解析、Markdown 回退、接口与鉴权。"""
from types import SimpleNamespace

from app.services import mindmap_service


def _configure(client, **kw):
    body = {"base_url": "http://127.0.0.1:18999/v1", "api_key": "sk-test", "model": "mock", "mode": "responses"}
    body.update(kw)
    r = client.patch("/api/settings/ai", json=body)
    assert r.status_code == 200


def _upload(client, text="# 第一章\n\n正文第一段\n\n# 第二章\n\n正文二\n"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def test_parse_mindmap_json():
    assert mindmap_service.parse_mindmap_json('{"title":"根","children":[]}')["title"] == "根"
    fenced = "```json\n{\"title\":\"y\",\"children\":[{\"name\":\"a\",\"children\":[]}]}\n```"
    data = mindmap_service.parse_mindmap_json(fenced)
    assert data["title"] == "y" and data["children"][0]["name"] == "a"
    assert mindmap_service.parse_mindmap_json("没有 JSON 的纯文本") is None
    assert mindmap_service.parse_mindmap_json("") is None


def test_clean_node_normalizes_ref_and_type():
    tree = mindmap_service._clean_node(
        {
            "name": "根",
            "children": [
                {"name": "定理A", "nodeType": "重要定理", "ref": {"chapter": 2, "para": "3-4"}, "children": []},
                {"name": "未知类型", "nodeType": "啥", "ref": None, "children": []},
            ],
        }
    )
    th = tree["children"][0]
    assert th["nodeType"] == "重要定理" and th["ref"] == {"chapter": 2, "para": "3-4"}
    assert tree["children"][1]["nodeType"] == "大纲"


def test_markdown_fallback_tree():
    md = "- 大纲A\n  - 细节1\n  - 定理：勾股定理\n    - 推论1\n- 大纲B\n"
    tree = mindmap_service.markdown_to_tree(md, "根")
    assert tree["name"] == "根"
    a, b = tree["children"]
    assert a["name"] == "大纲A"
    assert a["children"][0]["nodeType"] == "细节"
    th = a["children"][1]
    assert th["name"].startswith("定理") and th["nodeType"] == "重要定理"
    assert th["children"][0]["name"] == "推论1"
    assert b["name"] == "大纲B"


def test_tree_to_markdown_roundtrip():
    tree = {"name": "根", "nodeType": "大纲", "ref": None, "children": [{"name": "定理X", "nodeType": "重要定理", "ref": None, "children": []}]}
    md = mindmap_service.tree_to_markdown(tree)
    assert md.startswith("- 根")
    assert "重要定理" in md


def test_mindmap_endpoint_generates(client, monkeypatch):
    _configure(client)
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]

    captured = {}

    class FakeClient:
        def chat(self, messages):
            captured["messages"] = messages
            return (
                '{"title":"第1章 第一章","children":['
                '{"name":"核心概念","nodeType":"大纲","ref":null,"children":['
                '{"name":"定理1","nodeType":"重要定理","ref":{"chapter":1,"para":"2"},"children":[]}]}]}'
            )

    monkeypatch.setattr(mindmap_service, "build_client", lambda db: FakeClient())
    assert captured.get("messages") is None
    r = client.post(f"/api/books/{book_id}/mindmap", json={"chapter_id": ch})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["tree"]["children"][0]["children"][0]["nodeType"] == "重要定理"
    assert data["markdown"].startswith("- 第1章")
    # 脑图已写入对话历史
    msgs = client.get(f"/api/books/{book_id}/chat/messages").json()["data"]
    assert msgs and msgs[-1]["content"] == data["markdown"]


def test_mindmap_requires_config(client):
    book_id = _upload(client)
    r = client.post(f"/api/books/{book_id}/mindmap", json={})
    assert r.status_code == 400
    assert "API Key" in r.json()["detail"]


def test_mindmap_llm_error(client, monkeypatch):
    from app.ai.client import LLMError

    _configure(client)
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]

    class FailClient:
        def chat(self, messages):
            raise LLMError("模拟网络失败")

    monkeypatch.setattr(mindmap_service, "build_client", lambda db: FailClient())
    r = client.post(f"/api/books/{book_id}/mindmap", json={"chapter_id": ch})
    assert r.status_code == 502
    assert "模拟网络失败" in r.json()["detail"]


def test_build_mindmap_messages_placeholder_scanned_book():
    """脑图：扫描件（正文空）在隐私开启时不得注入「未发送」占位（审查报告 2-3 同源修复）。"""
    book = SimpleNamespace(title="变分学讲义")
    chapter = SimpleNamespace(index=1, title="第 1 页", content_text="", page_index=1)

    # 隐私关闭：保留原占位
    msgs = mindmap_service.build_mindmap_messages(
        book, chapter, "", "", [], [], False
    )
    assert "正文未发送，遵循隐私设置" in msgs[-1]["content"]

    # 隐私开启 + 扫描件按页阅读：扫描件说明，不得出现「未发送」
    msgs = mindmap_service.build_mindmap_messages(
        book, chapter, "", "", [], [], True
    )
    assert "未发送" not in msgs[-1]["content"]
    assert "扫描版 PDF" in msgs[-1]["content"]

    # 有页缓存时正常注入页缓存
    msgs = mindmap_service.build_mindmap_messages(
        book, chapter, "", "", [], [], True, "【第 1 页】变分法基本概念"
    )
    assert "页缓存" in msgs[-1]["content"]
    assert "扫描版" not in msgs[-1]["content"]
