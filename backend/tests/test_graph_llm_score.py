"""M8 待办落地测试：跨书关联 LLM 打分与方向/原因增强。

- 未配置 AI 时回退关键词分（direction 无 / from_book null）；
- LLM 结果合并：强度取 max、方向/类型/原因/源头以 LLM 为准；
- LLM 输出非法时回退（不阻塞图谱构建）；
- 有界调用（MAX_LLM_PAIRS 截断）；
- 新书导入增量更新同样走 LLM 增强；
- from_book_id 增量迁移列存在。
"""
import json

from app.services.graph.llm_score import MAX_LLM_PAIRS


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


BOOK_A = "# 第一章 变分法基础\n\n变分法研究泛函极值问题。\n\n# 第二章 泛函分析\n\n泛函空间与范数。\n"
BOOK_B = "# 第一章 泛函分析入门\n\n泛函与极值问题在变分法中常见。\n\n# 第二章 变分方法\n\n变分法应用。\n"


class _EdgeClient:
    """固定返回跨书关联打分 JSON，并记录调用次数。"""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def chat(self, messages) -> str:
        self.calls += 1
        assert len(messages) == 2
        return json.dumps(self.payload, ensure_ascii=False)


def _enable_llm(monkeypatch, client_obj):
    monkeypatch.setattr("app.services.graph.llm_score.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.graph.llm_score.build_client", lambda db: client_obj)


def test_llm_score_not_configured_falls_back(client):
    """未配置 AI：方向无、from_book null，强度来自关键词共现。"""
    _import_md(client, "书A.md", BOOK_A)
    _import_md(client, "书B.md", BOOK_B)
    data = client.get("/api/graph/books").json()["data"]
    edge = data["edges"][0]
    assert edge["direction"] == "无"
    assert edge["from_book"] is None
    assert edge["strength"] > 0


def test_llm_score_enriches_rebuild(client, monkeypatch):
    """重建（懒构建）时 LLM 结果合并：强度取 max、方向/类型/原因/源头生效。"""
    fake = _EdgeClient(
        {
            "strength": 88,
            "from_book": "A",
            "direction": "承接",
            "relation_type": "理论传承",
            "reasons": ["变分法与泛函分析术语高度重叠", "B 承接 A 的变分法思想"],
        }
    )
    _enable_llm(monkeypatch, fake)
    a = _import_md(client, "书A.md", BOOK_A)
    _import_md(client, "书B.md", BOOK_B)

    data = client.get("/api/graph/books").json()["data"]
    edge = data["edges"][0]
    assert edge["direction"] == "承接"
    assert edge["from_book"] == a
    assert edge["relation_type"] == "理论传承"
    assert edge["reasons"][0].startswith("变分法")
    assert edge["strength"] >= 88  # 与关键词分取 max
    assert fake.calls >= 1


def test_llm_score_parse_failure_falls_back(client, monkeypatch):
    """LLM 输出非法：回退关键词分，不阻塞图谱构建。"""
    fake = _EdgeClient("这不是 JSON {{{")
    _enable_llm(monkeypatch, fake)
    _import_md(client, "书A.md", BOOK_A)
    _import_md(client, "书B.md", BOOK_B)

    data = client.get("/api/graph/books").json()["data"]
    edge = data["edges"][0]
    assert edge["direction"] == "无"
    assert edge["from_book"] is None
    assert edge["strength"] > 0


def test_llm_score_validates_weird_output(client, monkeypatch):
    """非法枚举被规范化为安全值：from_book 未知 → 无方向；空原因保留关键词原因。"""
    fake = _EdgeClient(
        {
            "strength": "abc",
            "from_book": "C",
            "direction": "乱写",
            "relation_type": "乱写",
            "reasons": "不是列表",
        }
    )
    _enable_llm(monkeypatch, fake)
    _import_md(client, "书A.md", BOOK_A)
    _import_md(client, "书B.md", BOOK_B)

    data = client.get("/api/graph/books").json()["data"]
    edge = data["edges"][0]
    assert edge["direction"] == "无"
    assert edge["from_book"] is None
    assert edge["relation_type"] == "概念共现"
    assert edge["reasons"]  # 保留关键词共现原因
    assert edge["strength"] > 0


def test_llm_score_candidates_bounded(client, monkeypatch):
    """有界调用：单次重建候选对数多于上限时只调用 MAX_LLM_PAIRS 次。"""
    # 先禁用 LLM 导入 12 本书（66 对候选，避免导入增量叠加干扰计数）
    for i in range(12):
        _import_md(client, f"书{i}.md", "# 第一章 泛函分析\n\n泛函与变分法极值问题常见。\n")

    fake = _EdgeClient(
        {
            "strength": 60,
            "from_book": None,
            "direction": "无",
            "relation_type": "概念共现",
            "reasons": ["共享术语"],
        }
    )
    _enable_llm(monkeypatch, fake)
    client.post("/api/graph/rebuild")
    assert fake.calls <= MAX_LLM_PAIRS
    assert fake.calls == MAX_LLM_PAIRS  # 66 对 > 40，截断到上限


def test_llm_score_enriches_incremental_import(client, monkeypatch):
    """新书导入增量更新同样应用 LLM 增强。"""
    a = _import_md(client, "书A.md", BOOK_A)
    fake = _EdgeClient(
        {
            "strength": 75,
            "from_book": "B",
            "direction": "发展",
            "relation_type": "应用扩展",
            "reasons": ["B 将 A 的变分法应用到新场景"],
        }
    )
    _enable_llm(monkeypatch, fake)
    b = _import_md(client, "书B.md", BOOK_B)

    data = client.get("/api/graph/books").json()["data"]
    edge = next(e for e in data["edges"] if e["book_a"] in (a, b) and e["book_b"] in (a, b))
    assert edge["direction"] == "发展"
    assert edge["from_book"] == b
    assert edge["relation_type"] == "应用扩展"
    assert edge["strength"] >= 75


def test_from_book_column_migrated(client):
    """from_book_id 列存在（create_all 建表含新列；既有库由 _ensure_columns ALTER 补齐）。"""
    from sqlalchemy import text

    from app.core.database import engine

    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(book_relations)")).fetchall()]
    assert "from_book_id" in cols