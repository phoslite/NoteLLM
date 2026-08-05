"""M9 三层画像：热画像回写、归档迁移（热→暖 / 暖→冷 / >3 沉淀）、暖记忆联动与画像 API。"""
from app.core.database import SessionLocal
from app.models.book import Book
from app.services.profile_service import (
    WARM_TO_COLD_THRESHOLD,
    get_all_profiles,
    migrate_profiles_on_archive,
    reset_profiles,
    update_hot_profile,
)


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


def _rag(title: str, key_points: list[str]) -> dict:
    return {"title": title, "summary": f"{title}的总结", "key_points": key_points}


def test_hot_profile_update_and_read(client):
    book_id = _import_md(client, "画像书.md", "# 第一章\n\n内容。\n")
    book = _get_book(book_id)
    db = SessionLocal()
    try:
        update_hot_profile(db, book, progress=0.5, chapter_title="第一章")
        hot = get_all_profiles(db)["hot"]
        assert hot["current_book_id"] == book_id
        assert hot["progress"] == 0.5
        assert hot["chapter_titles"] == ["第一章"]
        # 同书重复写不重复追加同章；换书重置
        update_hot_profile(db, book, progress=0.8, chapter_title="第一章")
        assert len(get_all_profiles(db)["hot"]["chapter_titles"]) == 1
        update_hot_profile(
            db,
            book,
            highlight={"chapter_id": 1, "type": "不理解", "text": "这条不懂"},
            question="为什么？",
        )
        hot = get_all_profiles(db)["hot"]
        assert hot["highlights"][0]["type"] == "不理解"
        assert hot["questions"] == ["为什么？"]
    finally:
        db.close()


def test_archive_migrates_hot_to_warm(client):
    book_id = _import_md(client, "迁移书.md", "# 第一章\n\n变分法内容。\n")
    book = _get_book(book_id)
    db = SessionLocal()
    try:
        update_hot_profile(db, book, progress=1.0, chapter_title="第一章")
        profiles = migrate_profiles_on_archive(db, book, rag=_rag("迁移书", ["变分法研究泛函极值"]))
        warm = profiles["warm"]
        hot = profiles["hot"]
        assert warm["archived_count"] == 1
        assert warm["recent_books"][0]["book_id"] == book_id
        assert warm["recent_books"][0]["key_points"] == ["变分法研究泛函极值"]
        assert hot["current_book_id"] is None  # 热画像已清空
        assert profiles["cold"] == {}  # 1 本未触发暖转冷
    finally:
        db.close()


def test_warm_to_cold_migration_at_threshold(client):
    """跨 3 本 → 暖画像归档至冷画像（domain_preferences / long_term_interests）。"""
    ids = [_import_md(client, f"阈值书{i}.md", f"# 第一章\n\n第{i}章内容。\n") for i in range(WARM_TO_COLD_THRESHOLD)]
    db = SessionLocal()
    try:
        for i, bid in enumerate(ids):
            book = db.get(Book, bid)
            profiles = migrate_profiles_on_archive(db, book, rag=_rag(f"阈值书{i}", [f"概念{i} 与 主题词"]))
        cold = profiles["cold"]
        assert cold["domain_preferences"], "暖转冷后冷画像应有领域偏好"
        assert cold["long_term_interests"]
        warm = profiles["warm"]
        assert warm["archived_count"] == WARM_TO_COLD_THRESHOLD
        assert len(warm["recent_books"]) <= 2
    finally:
        db.close()


def test_over_threshold_keeps_one_recent(client):
    """> 3 本 → 全部沉淀冷画像，暖画像只保留最近 1 本。"""
    ids = [_import_md(client, f"沉淀书{i}.md", f"# 第一章\n\n内容{i}。\n") for i in range(5)]
    db = SessionLocal()
    try:
        for i, bid in enumerate(ids):
            book = db.get(Book, bid)
            migrate_profiles_on_archive(db, book, rag=_rag(f"沉淀书{i}", [f"主题{i} 概念"]))
        warm = get_all_profiles(db)["warm"]
        assert len(warm["recent_books"]) == 1
    finally:
        db.close()


def test_related_book_enters_warm_memory(client):
    """相关领域书入暖记忆：同 post 簇或关联边 ≥ 阈值 → related_books。"""
    a = _import_md(client, "相关A.md", "# 第一章\n\n变分法内容。\n")
    b = _import_md(client, "相关B.md", "# 第一章\n\n变分法进阶。\n")
    db = SessionLocal()
    try:
        book_a = db.get(Book, a)
        book_b = db.get(Book, b)
        migrate_profiles_on_archive(db, book_a, rag=_rag("相关A", ["变分法 泛函"]))
        # 手工给 A、B 打同 post 簇（模拟 post-classify 结果），验证相关书入暖记忆
        book_a.classify_source = "post"
        book_a.cluster_name = "变分"
        book_b.classify_source = "post"
        book_b.cluster_name = "变分"
        db.commit()
        profiles = migrate_profiles_on_archive(db, book_b, rag=_rag("相关B", ["变分法 泛函 极值"]))
        related = profiles["warm"]["related_books"]
        assert any(r["book_id"] == b for r in related)
    finally:
        db.close()


def test_profile_api_get_and_reset(client):
    client.post("/api/profile/reset")
    r = client.get("/api/profile")
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {"cold", "warm", "hot"}
    r2 = client.post("/api/profile/reset")
    assert r2.status_code == 200
    assert client.get("/api/profile").json()["data"]["hot"] == {}


def test_reset_clears_all_layers(client):
    book_id = _import_md(client, "重置书.md", "# 第一章\n\n内容。\n")
    book = _get_book(book_id)
    db = SessionLocal()
    try:
        update_hot_profile(db, book, progress=0.3, chapter_title="第一章")
        migrate_profiles_on_archive(db, book, rag=_rag("重置书", ["关键词"]))
        reset_profiles(db)
        assert get_all_profiles(db) == {"cold": {}, "warm": {}, "hot": {}}
    finally:
        db.close()

def test_recommendations_api(client):
    """阅读建议 API：统计、薄弱概念（不理解聚合）、复习提醒、节奏文案。"""
    book_id = _import_md(client, "建议书.md", "# 第一章\n\n变分法研究泛函极值。\n")
    r = client.post(
        f"/api/books/{book_id}/notes",
        json={"note_type": "不理解", "quote_text": "对偶空间与极值", "note_text": "不清楚对偶空间的作用"},
    )
    assert r.status_code == 200
    resp = client.get("/api/profile/recommendations")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"stats", "weak_concepts", "review", "rhythm"}
    assert data["stats"]["books_total"] == 1
    assert data["weak_concepts"], "「不理解」笔记应聚合出薄弱概念"
    assert data["weak_concepts"][0]["count"] >= 1
    assert data["rhythm"]["level"] in {"start", "building", "stable"}
    assert data["review"] == []


def test_recommendations_review_due_and_rhythm(client):
    """暖画像近期书超过复习间隔 -> due=True；沉淀 5 本 -> stable 节奏文案。"""
    from datetime import datetime, timedelta

    from app.services.profile_service import COLD, WARM, _save

    db = SessionLocal()
    try:
        warm = get_all_profiles(db)["warm"]
        warm["archived_count"] = 5
        warm["recent_books"] = [
            {"book_id": 1, "title": "旧书", "archived_at": (datetime.now() - timedelta(days=3)).isoformat()}
        ]
        _save(db, WARM, "default", warm)
        _save(db, COLD, "default", {"domain_preferences": {"数学": 5, "统计学": 3}})
    finally:
        db.close()

    data = client.get("/api/profile/recommendations").json()["data"]
    assert data["review"][0]["due"] is True
    assert data["review"][0]["days_ago"] == 3
    assert data["rhythm"]["level"] == "stable"
    assert "数学" in data["rhythm"]["tip"]

def test_update_cold_profile_edits_domains_and_interests(client):
    """方案 A：仅冷画像可编辑——领域偏好 / 长期兴趣，名称清洗与分数裁剪。"""
    r = client.patch(
        "/api/profile/cold",
        json={
            "domain_preferences": {"数学：分析": 12, "概率论": 3, "!!!": 5},
            "long_term_interests": ["实分析", "实分析", "参数论（不动点）"],
        },
    )
    assert r.status_code == 200
    cold = r.json()["data"]
    assert cold["domain_preferences"] == {"数学 分析": 10, "概率论": 3}  # 清洗标点 + 裁剪上限
    assert cold["long_term_interests"] == ["实分析", "参数论 不动点"]  # 去重 + 清洗
    # 仅更新传入字段：再次仅传领域时长期兴趣不变；分数 0 裁为 1
    r2 = client.patch("/api/profile/cold", json={"domain_preferences": {"解析数论": 0}})
    assert r2.status_code == 200
    cold2 = r2.json()["data"]
    assert cold2["domain_preferences"] == {"解析数论": 1}
    assert cold2["long_term_interests"] == ["实分析", "参数论 不动点"]
