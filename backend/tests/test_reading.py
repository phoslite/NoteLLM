"""阅读闭环测试：进度记录/恢复、已读标记、笔记 CRUD 与 Markdown 导出。"""


def _upload(client, text="# 第一章\n\n正文一\n\n# 第二章\n\n正文二\n"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode(), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def test_progress_roundtrip(client):
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch1, ch2 = detail["chapters"][0]["id"], detail["chapters"][1]["id"]

    r = client.post(f"/api/books/{book_id}/progress", json={"chapter_id": ch1, "position": 0.5})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["chapter_id"] == ch1
    assert 0.2 < data["progress"] < 0.4  # (0 + 0.5) / 2

    # 重新打开恢复上次位置
    saved = client.get(f"/api/books/{book_id}/progress").json()["data"]
    assert saved["chapter_id"] == ch1
    assert saved["position"] == 0.5

    # 仅保存进度不标记已读；显式 mark_read 才标记
    detail2 = client.get(f"/api/books/{book_id}").json()["data"]
    assert detail2["chapters"][0]["read_flag"] is False
    assert detail2["read_chapters"] == 0
    assert detail2["latest_chapter"] is not None  # 最近阅读章节仍会记录

    r = client.post(
        f"/api/books/{book_id}/progress", json={"chapter_id": ch1, "position": 1.0, "mark_read": True}
    )
    detail3 = client.get(f"/api/books/{book_id}").json()["data"]
    assert detail3["chapters"][0]["read_flag"] is True
    assert detail3["read_chapters"] == 1
    assert detail3["latest_chapter"]["index"] == 1

    # 全部章节读完 → 书籍自动标记读完
    r = client.post(
        f"/api/books/{book_id}/progress", json={"chapter_id": ch2, "position": 1.0, "mark_read": True}
    )
    detail4 = client.get(f"/api/books/{book_id}").json()["data"]
    assert detail4["chapters"][1]["read_flag"] is True
    assert detail4["read_chapters"] == 2
    assert detail4["status"] == "读完"
    assert detail4["latest_chapter"]["index"] == 2

    # 手动标记回在读
    patched = client.patch(f"/api/books/{book_id}", json={"status": "在读"})
    assert patched.json()["data"]["status"] == "在读"


def test_chapter_read_toggle(client):
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch1, ch2 = detail["chapters"][0]["id"], detail["chapters"][1]["id"]

    # 全部标记已读 → 自动读完
    for cid in (ch1, ch2):
        r = client.post(f"/api/books/{book_id}/progress", json={"chapter_id": cid, "position": 1.0, "mark_read": True})
        assert r.status_code == 200
    d = client.get(f"/api/books/{book_id}").json()["data"]
    assert d["status"] == "读完"
    assert d["read_chapters"] == 2

    # 手动取消一章已读 → 状态回退为在读
    r = client.patch(f"/api/books/{book_id}/chapters/{ch1}/read", json={"read": False})
    assert r.status_code == 200
    assert r.json()["data"]["read_flag"] is False
    d2 = client.get(f"/api/books/{book_id}").json()["data"]
    assert d2["read_chapters"] == 1
    assert d2["status"] == "在读"

    # 再次标记已读 → 全部读完 → 读完
    r = client.patch(f"/api/books/{book_id}/chapters/{ch1}/read", json={"read": True})
    assert r.status_code == 200
    d3 = client.get(f"/api/books/{book_id}").json()["data"]
    assert d3["read_chapters"] == 2
    assert d3["status"] == "读完"

    # 章节不存在/跨书 → 404
    assert client.patch(f"/api/books/{book_id}/chapters/99999/read", json={"read": True}).status_code == 404


def test_read_all_chapters_flag(client):
    """整本标记：read-all 一键全部已读（读完/100%）或全部未读（在读/0%）。"""
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    total = len(detail["chapters"])
    assert total >= 2

    r = client.patch(f"/api/books/{book_id}/read-all", json={"read": True})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "读完"
    assert data["progress"] == 1.0
    assert data["read_chapters"] == total

    detail2 = client.get(f"/api/books/{book_id}").json()["data"]
    assert all(c["read_flag"] for c in detail2["chapters"])

    r = client.patch(f"/api/books/{book_id}/read-all", json={"read": False})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "在读"
    assert data["progress"] == 0.0
    assert data["read_chapters"] == 0

    detail3 = client.get(f"/api/books/{book_id}").json()["data"]
    assert not any(c["read_flag"] for c in detail3["chapters"])


def test_list_books_bulk_summary(client):
    """书架列表应一次性返回每本书的已读章节数与最新章节（批量聚合，避免 N+1）。"""
    b1 = _upload(client, "# 第一章\n\n正文一\n\n# 第二章\n\n正文二\n")
    b2 = _upload(client, "# 甲章\n\n甲文\n\n# 乙章\n\n乙文\n\n# 丙章\n\n丙文\n")
    d1 = client.get(f"/api/books/{b1}").json()["data"]
    ch1 = d1["chapters"][0]["id"]

    # 标记 b1 第 1 章已读（最新日志也指向它）
    client.post(f"/api/books/{b1}/progress", json={"chapter_id": ch1, "position": 0.8, "mark_read": True})

    books = client.get("/api/books").json()["data"]
    by_id = {b["id"]: b for b in books}
    assert by_id[b1]["read_chapters"] == 1
    assert by_id[b1]["latest_chapter"]["index"] == 1
    assert by_id[b1]["chapter_count"] == 2
    assert by_id[b2]["read_chapters"] == 0
    assert by_id[b2]["latest_chapter"] is None
    assert by_id[b2]["chapter_count"] == 3


def test_notes_crud_and_export(client):
    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]

    r = client.post(
        f"/api/books/{book_id}/notes",
        json={"chapter_id": ch, "quote_text": "正文一", "note_text": "精读要点", "note_type": "批注"},
    )
    assert r.status_code == 200
    note_id = r.json()["data"]["id"]

    r = client.post(
        f"/api/books/{book_id}/notes",
        json={"chapter_id": ch, "quote_text": "正文一", "note_text": "没看懂", "note_type": "不理解"},
    )
    assert r.status_code == 200

    notes = client.get(f"/api/books/{book_id}/notes").json()["data"]
    assert len(notes) == 2
    assert {n["note_type"] for n in notes} == {"批注", "不理解"}

    bad = client.post(f"/api/books/{book_id}/notes", json={"note_type": "乱写"})
    assert bad.status_code == 422
    bad_patch = client.patch(f"/api/notes/{note_id}", json={"note_type": "乱写"})
    assert bad_patch.status_code == 422

    patched = client.patch(f"/api/notes/{note_id}", json={"note_text": "改为精读步骤"})
    assert patched.json()["data"]["note_text"] == "改为精读步骤"
    assert client.delete(f"/api/notes/{note_id}").status_code == 200
    assert len(client.get(f"/api/books/{book_id}/notes").json()["data"]) == 1

    exp = client.get(f"/api/books/{book_id}/notes/export")
    assert exp.status_code == 200
    assert "没看懂" in exp.text
    assert "[不理解]" in exp.text


def test_upsert_log_concurrent_duplicate_leaves_single_row(client, monkeypatch):
    """审查 P2-2：并发双会话重复插入同一 (book_id, chapter_id) 只留一行（唯一约束 + 冲突转更新）。"""
    from app.core.database import SessionLocal
    from app.models.activity import ReadingLog
    from app.repositories.reading import upsert_log

    book_id = _upload(client)
    ch = client.get(f"/api/books/{book_id}").json()["data"]["chapters"][0]["id"]
    db1 = SessionLocal()
    db2 = SessionLocal()
    try:
        injected = {"done": False}
        orig_commit = db1.commit

        def racing_commit():
            if not injected["done"]:
                injected["done"] = True
                db2.add(ReadingLog(book_id=book_id, chapter_id=ch, position=0.1))
                db2.commit()
            orig_commit()

        monkeypatch.setattr(db1, "commit", racing_commit)
        log = upsert_log(db1, book_id, ch, 0.5)
        assert log.position == 0.5
        rows = db1.query(ReadingLog).filter(ReadingLog.book_id == book_id, ReadingLog.chapter_id == ch).all()
        assert len(rows) == 1, "并发双写后同一 (book_id, chapter_id) 只能有一行"
        assert rows[0].position == 0.5, "冲突转更新应保留本次写入的最新 position"
    finally:
        db1.close()
        db2.close()


def test_reading_log_dedup_migration_keeps_latest(client):
    """审查 P2-2：存量重复 (book_id, chapter_id) 去重迁移——保留 updated_at 最新、同值取 id 最大。"""
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.core.database import _ensure_indexes, engine

    legacy_ddl = (
        "CREATE TABLE reading_logs (id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, "
        "chapter_id INTEGER, position FLOAT NOT NULL DEFAULT 0.0, updated_at DATETIME)"
    )
    dupes = (
        "INSERT INTO reading_logs (id, book_id, chapter_id, position, updated_at) VALUES "
        "(1, 10, 100, 0.1, '2026-01-01 10:00:00'),"
        "(2, 10, 100, 0.9, '2026-01-02 10:00:00'),"
        "(3, 10, 100, 0.5, '2026-01-02 10:00:00'),"
        "(4, 10, 101, 0.2, '2026-01-03 10:00:00'),"
        "(5, 10, NULL, 0.1, '2026-01-01 10:00:00'),"
        "(6, 10, NULL, 0.7, '2026-01-02 10:00:00')"
    )
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS reading_logs"))
        conn.execute(text(legacy_ddl))
        conn.execute(text(dupes))
    _ensure_indexes()  # 走真实启动迁移：去重 + 建唯一索引
    with engine.begin() as conn:
        remaining = [r[0] for r in conn.execute(text("SELECT id FROM reading_logs ORDER BY id")).fetchall()]
        assert remaining == [3, 4, 6], f"应保留最新行（同值取 id 大），实际 {remaining}"
        # 唯一索引已生效：再次插入同 (book_id, chapter_id) 被拒绝
        with pytest.raises(IntegrityError):
            conn.execute(
                text("INSERT INTO reading_logs (id, book_id, chapter_id, position, updated_at) "
                     "VALUES (7, 10, 100, 0.3, '2026-01-04 10:00:00')")
            )

