"""RAG/Skill 资产：切块、JSON 解析、资产版本递增与任务提交。"""
from types import SimpleNamespace

from app.ai.parsing import parse_llm_json
from app.core.database import SessionLocal
from app.repositories.assets import get_asset, upsert_asset
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


def test_summarize_route_returns_task(client):
    md = "# 第一章\n\n内容\n".encode()
    book_id = client.post("/api/books", files={"file": ("书.md", md, "text/markdown")}).json()["data"]["id"]
    r = client.post(f"/api/books/{book_id}/summarize")
    assert r.status_code == 200
    task_id = r.json()["data"]["task_id"]
    st = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert st["status"] in {"queued", "running", "success", "failed"}
    assert "error" in st and "result" in st
