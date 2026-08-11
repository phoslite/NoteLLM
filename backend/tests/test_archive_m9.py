"""M9 读完归档链路：归档任务（视觉通读→文本总结→标记读完）与两阶段分类 post-classify。"""
import json

import pytest

from app.core.database import SessionLocal
from app.models.book import Book
from app.repositories.assets import get_asset
from app.services.rag_input import build_page_input, page_chunks
from app.services.rag_service import archive_book_task

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
    body = build_page_input({1: "内容A", 2: "内容B"})
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
def _long_md() -> str:
    """>64K 字符的长书 Markdown（约 73K），保证触发方案 B 分块（默认块大小 64K）。"""
    para = "很长的填充内容。" * 400  # 每章约 1600 字
    return "\n".join(f"# 第{i}章 第{i}章内容\n\n第{i}章正文段落。{para}" for i in range(1, 60))


def _chunk_reply(kps, skills):
    return json.dumps({"key_points": kps, "skills": skills}, ensure_ascii=False)


class _MapReduceClient:
    """长书方案 B 模拟：map 轮按块返回中间结果，reduce 轮返回合并结果。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        user = messages[-1]["content"]
        if "以下是本书各片段" in user:
            return json.dumps(
                {
                    "summary": "全书综合概述（合并后）。",
                    "key_points": ["第一块要点（第1章第1段）", "第二块要点（第30章第1段）"],
                    "tags": ["数学"],
                    "skills": [
                        {"name": "长书技能", "applicable": "综合", "usage": "合并后用法", "sources": ["第1章", "第30章"]}
                    ],
                },
                ensure_ascii=False,
            )
        if "第 1/" in user:
            return _chunk_reply(
                ["第一块要点（第1章第1段）"],
                [{"name": "块1技能", "applicable": "块1", "usage": "块1用法", "sources": ["第1章"]}],
            )
        return _chunk_reply(
            ["第二块要点（第30章第1段）"],
            [{"name": "块2技能", "applicable": "块2", "usage": "块2用法", "sources": ["第30章"]}],
        )


def test_long_book_map_reduce_merges_across_blocks(client, monkeypatch):
    """长书（>64K）走方案 B：map 逐块提炼 + reduce 合并，跨块 key_points 与 skills 齐全。"""
    from app.services.rag_service import generate_rag_skill

    book_id = _import_md(client, "长书.md", _long_md())
    fake = _MapReduceClient()
    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.rag_service.build_client", lambda db: fake)

    db = SessionLocal()
    try:
        result = generate_rag_skill(db, book_id)
    finally:
        db.close()

    map_calls = [m for m in fake.calls if "个片段" in m[-1]["content"]]
    reduce_calls = [m for m in fake.calls if "以下是本书各片段" in m[-1]["content"]]
    assert len(map_calls) >= 2, "长书应产生至少 2 个 map 块"
    assert len(reduce_calls) == 1
    assert result["version"] == 1
    assert result["rag"]["summary"] == "全书综合概述（合并后）。"
    assert any("第30章" in k for k in result["rag"]["key_points"])
    assert result["skill"]["skills"][0]["name"] == "长书技能"


def test_long_book_map_reduce_skips_failed_block(client, monkeypatch):
    """单块 map 失败应跳过，其余块照常 reduce 合并。"""
    from app.ai.client import LLMError
    from app.services.rag_service import generate_rag_skill

    book_id = _import_md(client, "长书失败.md", _long_md())

    class _PartialClient(_MapReduceClient):
        def chat(self, messages):
            user = messages[-1]["content"]
            if "个片段" in user and "第 2/" in user:
                raise LLMError("mock 第二块失败")
            return super().chat(messages)

    fake = _PartialClient()
    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.rag_service.build_client", lambda db: fake)

    db = SessionLocal()
    try:
        result = generate_rag_skill(db, book_id)
    finally:
        db.close()
    assert any("第1章" in k for k in result["rag"]["key_points"])
    assert result["skill"]["skills"][0]["name"] == "长书技能"  # reduce 合并仍成功


def test_long_book_incremental_map_reduce(client, monkeypatch):
    """增量模式同样分块：reduce 轮注入旧资产与新增素材，版本在旧资产上递增。"""
    from app.repositories.assets import upsert_asset
    from app.services.rag_service import generate_rag_skill

    book_id = _import_md(client, "长书增量.md", _long_md())

    class _IncMapClient(_MapReduceClient):
        def chat(self, messages):
            user = messages[-1]["content"]
            if "以下是本书各片段" in user:
                assert "已有 RAG 资产" in user, "增量 reduce 应注入旧资产"
                return json.dumps(
                    {
                        "summary": "增改后的全书概述。",
                        "key_points": ["旧要点", "第一块要点（第1章第1段）"],
                        "tags": ["数学"],
                        "skills": [{"name": "旧技能", "applicable": "a", "usage": "u", "sources": ["第1章"]}],
                    },
                    ensure_ascii=False,
                )
            return super().chat(messages)

    fake = _IncMapClient()
    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.rag_service.build_client", lambda db: fake)

    db = SessionLocal()
    try:
        upsert_asset(db, book_id, "rag", {"summary": "旧概要", "key_points": ["旧要点"]})
        upsert_asset(db, book_id, "skill", {"name": "旧技能包", "skills": [{"name": "旧技能", "applicable": "a", "usage": "u", "sources": ["第1章"]}]})
        db.commit()
        result = generate_rag_skill(db, book_id)
        assert result["version"] == 2
        assert "旧要点" in result["rag"]["key_points"]
    finally:
        db.close()
def test_page_input_and_chunks_skip_blank_pages():
    """空白页标记不进入 RAG 片段与 LLM 输入正文（视觉归一化后下游过滤，v1.84）。"""
    from app.services.blank_page import BLANK_PAGE_MARK
    from app.services.rag_input import build_page_input, chunk_page_texts_for_summary

    pages = {1: "第一页正文", 2: BLANK_PAGE_MARK, 3: "第三页正文", 4: "   "}
    chunks = page_chunks(pages)
    assert [c["chapter_index"] for c in chunks] == [1, 3]
    body = build_page_input(pages)
    assert "第一页正文" in body and "第三页正文" in body
    assert "空白页" not in body
    blocks = chunk_page_texts_for_summary(pages, 64000)
    assert len(blocks) == 1
    assert "空白页" not in blocks[0]

def test_archive_pdf_skips_vision_when_all_pages_cached(client, fake_llm, monkeypatch):
    """页缓存无缺失时归档不进入视觉提取：不调用 rebuild_book_caches，进度直接到文本总结。"""
    from pathlib import Path

    book_id = _import_md(client, "扫描书.md", "# 第一章\n\n内容\n")
    db = SessionLocal()
    book = db.get(Book, book_id)
    assert book is not None
    book.format = "pdf"
    book.page_count = 2
    db.commit()
    page_dir = Path(book.file_path).parent / "page_text"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page_001.md").write_text("第 1 页内容", encoding="utf-8")
    (page_dir / "page_002.md").write_text("第 2 页内容", encoding="utf-8")
    db.close()

    calls: list[str] = []

    def _fake_rebuild(db_, book_, force=False, progress=None, workers=None):
        calls.append("rebuild")
        return {"total": 2, "extracted": 1, "cached": 1, "failed": 0, "errors": []}

    monkeypatch.setattr("app.services.rag_service.rebuild_book_caches", _fake_rebuild)
    result = archive_book_task(book_id)
    assert calls == []  # 未进入视觉提取
    assert result["page_cache"]["total"] == 2
    assert result["page_cache"]["extracted"] == 0
    assert result["page_cache"]["cached"] == 2
    assert result["rag"]["key_points"]

def test_text_summary_block_progress(client, fake_llm, monkeypatch):
    """长书 map-reduce：文本块处理进度逐块上报（块 X/N 处理中/完成 + 合并总结）。"""
    from app.services import rag_service

    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(rag_service, "update_progress", lambda p, s="": calls.append((p, s)))
    monkeypatch.setattr("app.core.config.settings.rag_summary_chunk_chars", 60, raising=False)
    book_id = _import_md(
        client,
        "长书.md",
        "# 第一章\n\n" + "变分法研究泛函极值。" * 40
        + "\n\n# 第二章\n\n" + "泛函空间与范数。" * 40
        + "\n\n# 第三章\n\n" + "极值问题的对偶。" * 40 + "\n",
    )
    archive_book_task(book_id)
    block_stages = [s for _p, s in calls if "块" in s]
    assert len(block_stages) >= 4  # 至少 2 块 ×（处理中/完成）
    assert any("合并" in s for _p, s in calls)
    assert any("单块" in s for _p, s in calls) is False


def test_text_summary_single_block_progress(client, fake_llm, monkeypatch):
    """短书单块：显示单块总结进度，不出现块 X/N。"""
    from app.services import rag_service

    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(rag_service, "update_progress", lambda p, s="": calls.append((p, s)))
    book_id = _import_md(client, "短书.md", "# 第一章\n\n变分法内容。\n")
    archive_book_task(book_id)
    assert any("单块" in s for _p, s in calls)
    assert any("块" in s and "单块" not in s for _p, s in calls) is False

def test_rag_privacy_override_controls_body_send(client, monkeypatch):
    """三审 Major-2：设置页关闭隐私（DB 覆盖）后，RAG 总结只发章节标题不发正文。"""
    from app.repositories.settings import set_setting
    from app.services.rag_service import generate_rag_skill

    book_id = _import_md(client, "隐私书.md", "# 第一章\n\n变分法泛函极值内部正文。\n")
    calls: list = []

    class _CapClient:
        def chat(self, messages):
            calls.append(messages[-1]["content"])
            return REPLY_VAR

    monkeypatch.setattr("app.services.rag_service.is_configured", lambda db: True)
    monkeypatch.setattr("app.services.rag_service.build_client", lambda db: _CapClient())

    db = SessionLocal()
    try:
        set_setting(db, "ai_enable_body_send", "false")
        generate_rag_skill(db, book_id)
    finally:
        db.close()
    assert calls, "应产生一次 LLM 调用"
    prompt = calls[0]
    assert "第一章" in prompt
    assert "变分法泛函极值内部正文" not in prompt, "隐私关闭时正文不得发送给 LLM"