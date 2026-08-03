"""RAG/Skill 资产：切块、JSON 解析、资产版本递增、去重合并与任务提交。"""
import json
from types import SimpleNamespace

from app.ai.parsing import parse_llm_json
from app.core.database import SessionLocal
from app.models.asset import BookAsset
from app.repositories.assets import (
    content_hash,
    delete_asset,
    delete_assets,
    get_asset,
    merge_duplicate_assets,
    read_asset_content,
    save_asset_content,
    upsert_asset,
)
from app.services.rag_service import _normalize_skills, chunk_chapter


def _chapter(index: int, title: str, text: str):
    return SimpleNamespace(index=index, title=title, content_text=text)


def test_chunk_chapter_splits_by_paragraphs():
    ch = _chapter(1, "第一章", ("段一内容" * 30) + "\n\n" + ("段二内容" * 30) + "\n\n" + "短段")
    chunks = chunk_chapter(ch, chunk_chars=50)
    assert len(chunks) >= 2
    assert chunks[0]["chapter_index"] == 1
    assert chunks[0]["chapter_title"] == "第一章"
    assert chunks[0]["para_pos"] == "1-1"
    assert "段一内容" in chunks[0]["text"]


def test_chunk_chapter_empty_content():
    chunks = chunk_chapter(_chapter(2, "空章", "   \n\n "))
    assert len(chunks) == 1
    assert chunks[0]["text"].strip() == ""


def test_parse_llm_json_tolerates_fences():
    text = '```json\n{"summary": "s", "key_points": ["k"]}\n```'
    assert parse_llm_json(text) == {"summary": "s", "key_points": ["k"]}


def test_normalize_skills_mixed():
    out = _normalize_skills(
        [
            "速读法",
            {"name": "精读", "applicable": "非虚构", "usage": "步骤", "sources": ["第1章"]},
        ]
    )
    assert out[0]["name"] == "速读法"
    assert out[1]["sources"] == ["第1章"]


def test_asset_version_increments(client):
    md = "# 第一章\n\n内容\n".encode()
    book_id = client.post("/api/books", files={"file": ("书.md", md, "text/markdown")}).json()["data"]["id"]
    db = SessionLocal()
    try:
        a1 = upsert_asset(db, book_id, "rag", {"summary": "v1"})
        assert a1.version == 1
        a2 = upsert_asset(db, book_id, "rag", {"summary": "v2"})
        assert a2.version == 2
        assert a2.id == a1.id
        assert get_asset(db, book_id, "rag").content_json == '{"summary": "v2"}'
    finally:
        db.close()


def _seed_asset(client, kind: str):
    md = "# 第一章\n\n内容\n".encode()
    book_id = client.post("/api/books", files={"file": ("书.md", md, "text/markdown")}).json()["data"]["id"]
    content = (
        {"summary": "摘要", "key_points": ["要点A", "要点B"], "chunks": [{"text": "c1"}]}
        if kind == "rag"
        else {"name": "技能包", "skills": [{"name": "技能1"}, {"name": "技能2"}]}
    )
    db = SessionLocal()
    try:
        upsert_asset(db, book_id, kind, content)
    finally:
        db.close()
    return book_id


def test_delete_asset_whole_kind(client):
    book_id = _seed_asset(client, "rag")
    r = client.delete(f"/api/books/{book_id}/asset", params={"kind": "rag"})
    assert r.status_code == 200
    assert r.json()["data"]["deleted"] is True
    db = SessionLocal()
    try:
        assert get_asset(db, book_id, "rag") is None
    finally:
        db.close()
    # 再次删除（不存在）返回 deleted=False
    r2 = client.delete(f"/api/books/{book_id}/asset", params={"kind": "rag"})
    assert r2.json()["data"]["deleted"] is False


def test_delete_asset_rejects_bad_kind(client):
    book_id = _seed_asset(client, "rag")
    r = client.delete(f"/api/books/{book_id}/asset", params={"kind": "xxx"})
    assert r.status_code == 200
    assert "未知资产类型" in r.json()["message"]


def test_delete_asset_item_updates_version(client):
    book_id = _seed_asset(client, "skill")
    db = SessionLocal()
    try:
        assert get_asset(db, book_id, "skill").version == 1
    finally:
        db.close()
    r = client.delete(f"/api/books/{book_id}/asset/skill/skills/0")
    assert r.status_code == 200
    data = r.json()["data"]
    assert [s["name"] for s in data["content"]["skills"]] == ["技能2"]
    db = SessionLocal()
    try:
        assert get_asset(db, book_id, "skill").version == 2
    finally:
        db.close()
    # 索引越界：不删、version 不变
    r2 = client.delete(f"/api/books/{book_id}/asset/skill/skills/9")
    assert "资产项不存在" in r2.json()["message"]
    db = SessionLocal()
    try:
        assert get_asset(db, book_id, "skill").version == 2
    finally:
        db.close()


def test_delete_asset_item_rag_key_points(client):
    book_id = _seed_asset(client, "rag")
    r = client.delete(f"/api/books/{book_id}/asset/rag/key_points/0")
    data = r.json()["data"]
    assert data["content"]["key_points"] == ["要点B"]
    assert data["content"]["chunks"] == [{"text": "c1"}]


def test_delete_asset_item_missing_asset(client):
    md = "# 第一章\n\n内容\n".encode()
    book_id = client.post("/api/books", files={"file": ("书.md", md, "text/markdown")}).json()["data"]["id"]
    r = client.delete(f"/api/books/{book_id}/asset/rag/key_points/0")
    assert "没有 rag 资产" in r.json()["message"]

def _book(client, name: str) -> int:
    md = ("# 第一章\n\n内容\n").encode()
    r = client.post("/api/books", files={"file": (name, md, "text/markdown")})
    return r.json()["data"]["id"]


def test_content_hash_stable_and_ignores_meta():
    a = {"summary": "s", "key_points": ["k"], "merged_book_ids": [1, 2]}
    b = {"summary": "s", "key_points": ["k"], "merged_book_ids": [3]}
    assert content_hash(a) == content_hash(b)
    assert content_hash({"k": "v", "a": 1}) == content_hash({"a": 1, "k": "v"})


def test_upsert_dedupes_items_by_hash(client):
    book_id = _book(client, "去重.md")
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A", "A", "B"], "chunks": [{"text": "c"}, {"text": "c"}]}
        upsert_asset(db, book_id, "rag", rag)
        content = read_asset_content(db, book_id, "rag")
        assert content["key_points"] == ["A", "B"]
        assert len(content["chunks"]) == 1
        skill = {"name": "包", "skills": [{"name": "s1"}, {"name": "s1"}], "domains": ["数学", "数学"]}
        upsert_asset(db, book_id, "skill", skill)
        s_content = read_asset_content(db, book_id, "skill")
        assert len(s_content["skills"]) == 1
        assert s_content["domains"] == ["数学"]
    finally:
        db.close()


def test_merge_duplicate_assets_shares_one_row(client):
    b1 = _book(client, "相同1.md")
    b2 = _book(client, "相同2.md")
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A"]}
        upsert_asset(db, b1, "rag", rag)
        upsert_asset(db, b2, "rag", rag)
        assert db.query(BookAsset).filter(BookAsset.kind == "rag").count() == 2

        stats = merge_duplicate_assets(db)
        assert stats["rag"] == 1
        rows = db.query(BookAsset).filter(BookAsset.kind == "rag").all()
        assert len(rows) == 1
        main = rows[0]
        assert main.book_id in {b1, b2}
        member = b2 if main.book_id == b1 else b1
        assert main.book_id != member
        assert read_asset_content(db, b1, "rag") == rag
        assert read_asset_content(db, b2, "rag") == rag
        assert member in json.loads(main.content_json)["merged_book_ids"]
        # 幂等：再次合并不再变化
        assert merge_duplicate_assets(db)["rag"] == 0
    finally:
        db.close()


def test_delete_shared_member_detaches_only(client):
    b1 = _book(client, "成员1.md")
    b2 = _book(client, "成员2.md")
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A"]}
        upsert_asset(db, b1, "rag", rag)
        upsert_asset(db, b2, "rag", rag)
        merge_duplicate_assets(db)
        main = db.query(BookAsset).filter(BookAsset.kind == "rag").one()
        member = b2 if main.book_id == b1 else b1
        removed = delete_asset(db, member, "rag")
        assert removed is True
        # 成员书解除引用，主书资产仍在
        assert read_asset_content(db, member, "rag") == {}
        assert read_asset_content(db, main.book_id, "rag") == {"summary": "s", "key_points": ["A"]}
        merged = json.loads(main.content_json)["merged_book_ids"]
        assert member not in merged
    finally:
        db.close()


def test_delete_main_book_transfers_to_member(client):
    b1 = _book(client, "主书.md")
    b2 = _book(client, "成员书.md")
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A"]}
        upsert_asset(db, b1, "rag", rag)
        upsert_asset(db, b2, "rag", rag)
        merge_duplicate_assets(db)
        main = db.query(BookAsset).filter(BookAsset.kind == "rag").one()
        orig_main_id = main.book_id
        deleted = delete_asset(db, orig_main_id, "rag")
        assert deleted is True
        # 主书身份转移给成员书，成员书仍可读取
        rows = db.query(BookAsset).filter(BookAsset.kind == "rag").all()
        assert len(rows) == 1
        assert rows[0].book_id != orig_main_id
        assert read_asset_content(db, orig_main_id, "rag") == {}
        assert read_asset_content(db, rows[0].book_id, "rag") == {"summary": "s", "key_points": ["A"]}
    finally:
        db.close()


def test_delete_book_assets_handles_shared(client):
    b1 = _book(client, "共享1.md")
    b2 = _book(client, "共享2.md")
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A"]}
        upsert_asset(db, b1, "rag", rag)
        upsert_asset(db, b2, "rag", rag)
        merge_duplicate_assets(db)
        delete_assets(db, b1)
        rows = db.query(BookAsset).filter(BookAsset.kind == "rag").all()
        # 主书删除后资产转移给另一本，仍只有一条
        assert len(rows) == 1
        assert read_asset_content(db, b1, "rag") == {}
        assert read_asset_content(db, b2, "rag") == {"summary": "s", "key_points": ["A"]}
    finally:
        db.close()


def test_save_asset_content_no_bump(client):
    b = _book(client, "存根.md")
    db = SessionLocal()
    try:
        a1 = upsert_asset(db, b, "rag", {"summary": "", "key_points": [], "chunks": []})
        assert a1.version == 1
        # 存根更新（联动元数据）不递增版本
        a2 = save_asset_content(db, b, "rag", {"summary": "", "key_points": [], "chunks": [], "linked_books": [{"book_id": 1}]})
        assert a2.version == 1
        assert a2.id == a1.id
        # 无资产时创建 version=1
        a3 = save_asset_content(db, b, "skill", {"name": "包"})
        assert a3.version == 1
    finally:
        db.close()

def test_import_sets_content_hash(client):
    b = _book(client, "带hash.md")
    r = client.get(f"/api/books/{b}")
    assert r.status_code == 200
    ch = r.json()["data"]["content_hash"]
    assert ch and len(ch) == 64


def test_merge_requires_same_book_content(client):
    b1 = _book(client, "内容A.md")
    r = client.post(
        "/api/books",
        files={"file": ("内容B.md", "# 第一章\n\n完全不同的内容\n".encode(), "text/markdown")},
    )
    b2 = r.json()["data"]["id"]
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A"]}
        upsert_asset(db, b1, "rag", rag)
        upsert_asset(db, b2, "rag", rag)
        stats = merge_duplicate_assets(db)
        assert stats["rag"] == 0  # 书籍内容不同 → 不合并
        assert db.query(BookAsset).filter(BookAsset.kind == "rag").count() == 2
    finally:
        db.close()


def test_delete_book_removes_assets(client):
    b = _book(client, "待删.md")
    db = SessionLocal()
    try:
        upsert_asset(db, b, "rag", {"summary": "s", "key_points": ["A"]})
        upsert_asset(db, b, "skill", {"name": "包", "skills": [{"name": "s1"}]})
    finally:
        db.close()
    r = client.delete(f"/api/books/{b}")
    assert r.status_code == 200
    db = SessionLocal()
    try:
        # 删除书籍 = 移除知识库及其书籍：资产行一并清除
        assert db.query(BookAsset).filter(BookAsset.book_id == b).count() == 0
    finally:
        db.close()

def test_dedupe_api_endpoint(client):
    b1 = _book(client, "接口1.md")
    b2 = _book(client, "接口2.md")
    db = SessionLocal()
    try:
        rag = {"summary": "s", "key_points": ["A"]}
        upsert_asset(db, b1, "rag", rag)
        upsert_asset(db, b2, "rag", rag)
    finally:
        db.close()
    r = client.post("/api/assets/dedupe")
    assert r.status_code == 200
    assert r.json()["data"]["rag"] == 1
    assert r.json()["data"]["skill"] == 0

def test_summarize_route_returns_task(client):
    md = "# 第一章\n\n内容\n".encode()
    book_id = client.post("/api/books", files={"file": ("书.md", md, "text/markdown")}).json()["data"]["id"]
    r = client.post(f"/api/books/{book_id}/summarize")
    assert r.status_code == 200
    task_id = r.json()["data"]["task_id"]
    st = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert st["status"] in {"queued", "running", "success", "failed"}
    assert "error" in st and "result" in st
