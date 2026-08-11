"""2026-08-10 全库复审修复回归测试（F3~F7，见 docs/审查报告-20260810.md §8）。

- F3：rag_router 会话缓存命中时按当前问题重取 chunks（不回放旧问题片段）；
- F4：summarize 提交任务带 related_id（find_active 幂等防重可命中）；
- F5：任务状态写库失败时 finally 兜底置 failed（防永久 queued/running 卡死）；
- F6：簇合并剔除数学/学术泛词（防 5 个共用泛词错误合并）；
- F7：_purge_vlm 同时删除 OCR 文本缓存（page_*.txt）。
"""
from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal
from app.models.book import Book, Chapter
from app.models.task import Task
from app.repositories.assets import save_asset_content
from app.services import rag_router, vision_image
from app.services.graph import merge_and_rename_clusters
from app.services.rag_router import SelectionResult, clear_session_cache, select_knowledge


def _upload(client, title):
    body = f"# {title}\n\n正文第一段\n\n# 第二章\n\n正文二\n"
    r = client.post("/api/books", files={"file": (f"{title}.md", body.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _configure(client):
    r = client.patch(
        "/api/settings/ai",
        json={"base_url": "http://127.0.0.1:18999/v1", "api_key": "sk-test", "model": "mock", "mode": "responses"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------- F3

def test_f3_session_cache_recomputes_chunks_for_new_question(client, monkeypatch):
    """F3 回归：同 session 同章不同问题，缓存仅复用挑选结果，chunks 按当前问题重取。"""
    _configure(client)
    db = SessionLocal()
    try:
        a = _upload(client, "缓存书")
        save_asset_content(db, a, "rag", {
            "summary": "摘要",
            "chunks": [
                {"chapter_index": 1, "chapter_title": "第一章", "para_pos": "1", "text": "苹果种植技术要点"},
                {"chapter_index": 1, "chapter_title": "第一章", "para_pos": "2", "text": "香蕉运输保存方法"},
            ],
        })

        def fake_select_llm(*args, **kwargs):  # noqa: ARG001 固定挑选结果
            return SelectionResult(source="llm", book_ids=[a], skill_refs=[])

        monkeypatch.setattr(rag_router, "_select_llm", fake_select_llm)
        asked = []
        orig_retrieve = rag_router.retrieve_rag_chunks

        def spy_retrieve(*args, **kwargs):
            asked.append(args[2] if len(args) > 2 else kwargs["question"])
            return orig_retrieve(*args, **kwargs)

        monkeypatch.setattr(rag_router, "retrieve_rag_chunks", spy_retrieve)
        chapter = db.query(Chapter).filter_by(book_id=a).first()
        sid = "f3-session"
        out1 = select_knowledge(db, db.get(Book, a), chapter, "苹果怎么种", session_id=sid)
        assert out1["source"] == "llm"
        out2 = select_knowledge(db, db.get(Book, a), chapter, "香蕉怎么运", session_id=sid)
        assert out2["source"] == "cache"
        assert any("香蕉" in c["text"] for c in out2["chunks"]), "命中缓存也应按当前问题重新检索"
        assert asked == ["苹果怎么种", "香蕉怎么运"], "第二次调用必须按新问题重取 chunks"
    finally:
        db.close()
        clear_session_cache()


# ---------------------------------------------------------------- F4

def test_f4_summarize_task_records_related_id(client):
    """F4 回归：summarize 提交任务带 related_id=book_id（find_active 幂等防重可命中）。"""
    r0 = client.post("/api/books", files={"file": ("f4.md", "# 第一章\n\n正文\n".encode(), "text/markdown")})
    book_id = r0.json()["data"]["id"]
    r = client.post(f"/api/books/{book_id}/summarize")
    task_id = r.json()["data"]["task_id"]
    db = SessionLocal()
    try:
        row = db.get(Task, task_id)
        assert row is not None
        assert row.related_id == book_id, "submit 必须带 related_id，find_active 才能命中防重"
    finally:
        db.close()


# ---------------------------------------------------------------- F5

def test_f5_task_status_write_failure_falls_back_to_failed(client, monkeypatch):
    """F5 回归：状态写库失败时 finally 兜底置 failed，防任务永久卡 queued/running。"""
    import app.tasks as tasks_mod
    from app.tasks import submit_sync

    calls = {"n": 0}
    real_write = tasks_mod._db_write

    def flaky_write(action):
        calls["n"] += 1
        if calls["n"] in (2, 3):  # running 写与 failed 写各失败一次，交由 finally 兜底
            raise OperationalError("模拟写库失败", None, None)
        real_write(action)

    monkeypatch.setattr(tasks_mod, "_db_write", flaky_write)
    task_id = submit_sync("text", "f5-fallback", lambda: "ok")
    db = SessionLocal()
    try:
        row = db.get(Task, task_id)
        assert row is not None and row.status == "failed", "状态写失败后必须兜底置 failed"
        assert row.error, "兜底错误信息应落库"
    finally:
        db.close()


# ---------------------------------------------------------------- F6

def test_f6_cluster_merge_ignores_generic_terms(client):
    """F6 回归：仅共享数学/学术泛词的两簇不合并。"""
    a = _upload(client, "矩阵书")
    b = _upload(client, "拓扑书")
    db = SessionLocal()
    try:
        save_asset_content(db, a, "rag", {"summary": "矩阵 线性 代数", "key_points": ["定义", "定理", "引理", "推论", "证明"]})
        save_asset_content(db, b, "rag", {"summary": "几何 拓扑", "key_points": ["定义", "定理", "引理", "推论", "证明"]})
        book_a = db.get(Book, a)
        book_b = db.get(Book, b)
        book_a.classify_source = "post"
        book_a.cluster_name = "矩阵簇"
        book_b.classify_source = "post"
        book_b.cluster_name = "拓扑簇"
        db.commit()
        result = merge_and_rename_clusters(db)
        assert result["merged"] == 0, "仅共享泛词（定义/定理/引理/推论/证明）不应合并"
    finally:
        db.close()


# ---------------------------------------------------------------- F7

def test_f7_purge_vlm_removes_ocr_text_cache(tmp_path):
    """F7 回归：_purge_vlm 同时删除 OCR 文本缓存（page_*.txt），meta 由调用方重写不动。"""
    root = tmp_path / "books" / "b" / "pages_vlm"
    root.mkdir(parents=True)
    (root / "page_001.jpg").write_bytes(b"j")
    (root / "page_001.txt").write_text("OCR 文本", encoding="utf-8")
    (root / "meta.json").write_text("{}", encoding="utf-8")
    book = SimpleNamespace(file_path=str(tmp_path / "books" / "b" / "book.pdf"))
    vision_image._purge_vlm(book)
    assert not (root / "page_001.jpg").exists()
    assert not (root / "page_001.txt").exists(), "purge 必须连带删除 OCR 文本缓存"
    assert (root / "meta.json").exists()
