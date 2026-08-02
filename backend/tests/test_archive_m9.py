"""M9 读完归档链路：归档任务（视觉通读→文本总结→标记读完）与两阶段分类 post-classify。"""
import json

import pytest

from app.core.database import SessionLocal
from app.models.book import Book
from app.repositories.assets import get_asset
from app.services.rag_service import _build_page_input, archive_book_task, page_chunks

REPLY_VAR = json.dumps(
    {
        "summary": "本书介绍变分法与泛函分析，变分法研究泛函极值问题。",
        "key_points": ["变分法研究泛函极值", "泛函分析是基础", "极值问题在优化中常见"],
        "tags": ["数学"],
        "skills": [{"name": "变分求解", "applicable": "优化问题", "usage": "步骤", "sources": ["第1章"]}],
    },
    ensure_ascii=False,
)
REPLY_PROB = json.dumps(
    {
        "summary": "本书介绍概率空间与随机变量理论。",
        "key_points": ["概率空间定义", "随机变量与分布", "期望与方差计算"],
        "tags": ["统计学"],
        "skills": [{"name": "概率建模", "applicable": "随机问题", "usage": "步骤", "sources": ["第1章"]}],
    },
    ensure_ascii=False,
)


class _FakeClient:
    def __init__(self, replies: dict[str, str]):
        self.replies = replies

    def chat(self, messages):
        user = messages[-1]["content"] if isinstance(messages[-1]["content"], str) else str(messages[-1]["content"])
        if "概率" in user:
            return self.replies["prob"]
        return self.replies["var"]


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr(
        "app.services.rag_service.build_client", lambda db: _FakeClient({"var": REPLY_VAR, "prob": REPLY_PROB})
    )
    monkeypatch.setattr("app.core.config.settings.ai_enable_body_send", True, raising=False)


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _get_book(book_id: int) -> Book:
    db = SessionLocal()
    try:
        return db.get(Book, book_id)
    finally:
        db.close()


def test_page_chunks_and_page_input(fake_llm):
    chunks = page_chunks({1: "第 1 页内容", 3: "  "})
    assert len(chunks) == 1
    assert chunks[0]["chapter_index"] == 1
    assert chunks[0]["page_index"] == 1
    assert chunks[0]["para_pos"] == "页"
    body = _build_page_input({1: "内容A", 2: "内容B"})
    assert "【第 1 页】" in body and "内容B" in body


def test_archive_route_returns_task(client):
    book_id = _import_md(client, "归档书.md", "# 第一章\n\n内容\n")
    r = client.post(f"/api/books/{book_id}/archive")
    assert r.status_code == 200
    task_id = r.json()["data"]["task_id"]
    st = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert st["status"] in {"queued", "running", "success", "failed"}
    assert "result" in st and "error" in st


def test_archive_task_marks_read_and_assets(client, fake_llm):
    book_id = _import_md(client, "归档书B.md", "# 第一章 变分法\n\n变分法研究泛函极值。\n\n# 第二章 泛函\n\n泛函空间。\n")
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    assert detail["status"] != "读完"

    result = archive_book_task(book_id)
    assert result["book_id"] == book_id
    assert result["version"] == 1
    assert result["rag"]["key_points"]
    assert result["skill"]["skills"][0]["name"] == "变分求解"

    detail = client.get(f"/api/books/{book_id}").json()["data"]
    assert detail["status"] == "读完"
    assert detail["progress"] == 1.0
    assert all(c["read_flag"] for c in detail["chapters"])

    db = SessionLocal()
    try:
        asset = get_asset(db, book_id, "rag")
        assert asset is not None and asset.version == 1
    finally:
        db.close()
    book = _get_book(book_id)
    assert book.classify_source == "post"
    assert book.classify_version == 1
    assert book.cluster_name


def test_post_classify_groups_similar_and_splits_dissimilar(client, fake_llm):
    a = _import_md(client, "变分书.md", "# 第一章\n\n变分法研究泛函极值问题。\n")
    b = _import_md(client, "泛函书.md", "# 第一章\n\n泛函与极值问题在变分法中常见。\n")
    c = _import_md(client, "概率书.md", "# 第一章\n\n概率空间与随机变量理论。\n")

    archive_book_task(a)
    archive_book_task(b)
    archive_book_task(c)

    book_a = _get_book(a)
    book_b = _get_book(b)
    book_c = _get_book(c)
    assert book_a.classify_source == "post"
    assert book_b.classify_source == "post"
    assert book_c.classify_source == "post"
    # A、B 后验关键词重叠高 → 同簇（迁移合并）；C 与它们不同领域 → 独立簇
    assert book_a.cluster_name == book_b.cluster_name
    assert book_a.cluster_name != book_c.cluster_name

    # 谱系图懒加载应采用 post 落盘结果
    data = client.get("/api/graph/books").json()["data"]
    by_id = {n["id"]: n["cluster"] for n in data["nodes"]}
    assert by_id[a] == by_id[b]
    assert by_id[a] != by_id[c]


def test_post_classify_tag_is_hard_constraint(client, fake_llm):
    book_id = _import_md(client, "带标签书.md", "# 第一章\n\n变分法内容。\n")
    client.patch(f"/api/books/{book_id}", json={"tags": ["分析学"]})
    archive_book_task(book_id)

    book = _get_book(book_id)
    assert book.classify_source == "tag"
    assert book.cluster_name == "分析学"

def test_incremental_rag_skill_updates_in_place(client, monkeypatch):
    """再次归档：已有资产走增量提示词，version 递增、资产行不变。"""
    from app.models.activity import Note
    from app.services.rag_service import generate_rag_skill

    book_id = _import_md(client, "增量书.md", "# 第一章\n\n变分法研究泛函极值。\n")
    calls: list = []

    class _IncClient:
        def chat(self, messages):
            calls.append(messages)
            user = messages[-1]["content"]
            if "已有 RAG 资产" in user:
                return json.dumps(
                    {
                        "summary": "本书介绍变分法，并补充了对偶空间的深入理解。",
                        "key_points": ["变分法研究泛函极值", "对偶空间与极值的关系（新增理解）"],
                        "tags": ["数学"],
                        "skills": [
                            {"name": "变分求解", "applicable": "优化问题", "usage": "步骤", "sources": ["第1章"]}
                        ],
                    },
                    ensure_ascii=False,
                )
            return REPLY_VAR

    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.rag_service.build_client", lambda db: _IncClient())

    db = SessionLocal()
    try:
        first = generate_rag_skill(db, book_id)
        assert first["version"] == 1
        asset_id = get_asset(db, book_id, "rag").id

        db.add(Note(book_id=book_id, quote_text="对偶空间", note_text="为什么对偶空间重要", note_type="不理解"))
        db.commit()

        second = generate_rag_skill(db, book_id)
        assert second["version"] == 2
        asset = get_asset(db, book_id, "rag")
        assert asset.id == asset_id  # 同一资产行，仅版本递增
        assert asset.version == 2
        assert "对偶空间" in asset.content_json
    finally:
        db.close()
    assert any("已有 RAG 资产" in m[-1]["content"] for m in calls), "第二次总结应使用增量提示词"


def test_merge_and_rename_post_clusters(client):
    """两 post 簇后验关键词重叠 >= T_MERGE 合并；代表性术语众数重命名。"""
    from app.repositories.assets import upsert_asset
    from app.services.graph import merge_and_rename_clusters

    a = _import_md(client, "合并书A.md", "# 第一章\n\n泛函空间内容。\n")
    b = _import_md(client, "合并书B.md", "# 第一章\n\n变分极值内容。\n")
    db = SessionLocal()
    try:
        book_a = db.get(Book, a)
        book_b = db.get(Book, b)
        book_a.classify_source = "post"
        book_a.cluster_name = "旧簇甲"
        book_b.classify_source = "post"
        book_b.cluster_name = "旧簇乙"
        upsert_asset(db, a, "rag", {"summary": "泛函", "key_points": ["泛函 空间 线性 算子 范数 完备 谱系", "凸 集"]})
        upsert_asset(db, b, "rag", {"summary": "变分", "key_points": ["泛函 空间 线性 算子 范数 完备 谱系", "极值 问题"]})
        db.commit()

        result = merge_and_rename_clusters(db)
        assert result["merged"] == 1
        assert result["renamed"] == 1
        db.refresh(book_a)
        db.refresh(book_b)
        assert book_a.cluster_name == book_b.cluster_name
        assert book_a.cluster_name == "泛函"  # 多数术语成为新簇名
    finally:
        db.close()

def test_post_classify_uses_sanitized_tag(client, fake_llm):
    """归档后 post-classify：含标点的 tag 保存即清洗，清洗后的 tag 作为簇名（硬约束不变）。"""
    book_id = _import_md(client, "脏标签书.md", "# 第一章\n\n变分法研究泛函极值。\n")
    client.patch(f"/api/books/{book_id}", json={"tags": ["分析学：变分（考研）"]})
    archive_book_task(book_id)

    book = _get_book(book_id)
    assert book.classify_source == "tag"
    assert book.cluster_name == "分析学变分考研"

def test_skill_domains_sanitized(client, monkeypatch):
    """LLM 自动总结的 skill domains（tags）保存前清洗：只保留汉字/英文词组，空项丢弃、去重。"""
    from app.services.rag_service import generate_rag_skill

    book_id = _import_md(client, "领域书.md", "# 第一章\n\n变分法研究泛函极值。\n")

    class _DomClient:
        def chat(self, messages):
            return json.dumps(
                {
                    "summary": "变分法概述。",
                    "key_points": ["变分法研究泛函极值"],
                    "tags": ["数学：分析", "《泛函》", "Math, Vol.2", "！！！", "数学：分析"],
                    "skills": [{"name": "变分求解", "applicable": "优化", "usage": "步骤", "sources": ["第1章"]}],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.rag_service.build_client", lambda db: _DomClient())
    db = SessionLocal()
    try:
        result = generate_rag_skill(db, book_id)
        assert result["skill"]["domains"] == ["数学分析", "泛函", "Math Vol 2"]
    finally:
        db.close()
