"""画像阈值自动学习：默认值、手动覆盖、样本学习、归档迁移接入（需求 3.4.1）。"""
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.book import Book
from app.repositories.settings import get_setting
from app.services.profile_learning import (
    KEY_LEARNING_STATE,
    MIN_LEARN_SAMPLES,
    get_thresholds,
    learn_thresholds,
    record_archive,
    save_thresholds,
)


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _rag(title: str, key_points: list[str]) -> dict:
    return {"title": title, "summary": f"{title}的总结", "key_points": key_points}


def _confirmed_edges(db, strengths: list[float]):
    """构造确认关联边样本：先建真实书籍记录满足外键约束。"""
    from app.models.book import Book
    from app.models.graph import BookRelation

    books = [
        Book(title=f"确认样本{i}", format="md", file_path=f"c{i}.md", status="未读", progress=0.0)
        for i in range(len(strengths) + 1)
    ]
    db.add_all(books)
    db.commit()
    for i, s in enumerate(strengths):
        # 唯一约束（审查 P1-3）：同 pair 先删后插
        from sqlalchemy import delete as _delete

        db.execute(
            _delete(BookRelation).where(
                BookRelation.book_a_id == books[0].id,
                BookRelation.book_b_id == books[i + 1].id,
            )
        )
        db.add(
            BookRelation(
                book_a_id=books[0].id,
                book_b_id=books[i + 1].id,
                strength=s,
                direction="无",
                relation_type="概念共现",
                reasons_json="[]",
                user_feedback="确认",
            )
        )
    db.commit()


def test_thresholds_default_and_manual_override(client):
    """默认值 = 常量；PATCH 保存并裁剪越界值。"""
    r = client.get("/api/profile/thresholds")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["warm_threshold"] == 3
    assert data["related_strength"] == 60.0
    assert data["review_days"] == 1
    assert "learning" in data and "sample_count" in data["learning"]

    r2 = client.patch(
        "/api/profile/thresholds",
        json={"warm_threshold": 4, "related_strength": 50, "review_days": 3},
    )
    assert r2.status_code == 200
    assert r2.json()["data"] == {"warm_threshold": 4, "related_strength": 50.0, "review_days": 3}

    # 越界裁剪到学习范围
    r3 = client.patch(
        "/api/profile/thresholds",
        json={"warm_threshold": 99, "related_strength": 1, "review_days": 99},
    )
    data3 = r3.json()["data"]
    assert data3["warm_threshold"] == 5
    assert data3["related_strength"] == 45.0
    assert data3["review_days"] == 7


def test_learning_requires_min_samples(client):
    """样本不足：learn_thresholds 不改阈值（退化为默认常量，保证既有行为）。"""
    db = SessionLocal()
    try:
        for i in range(MIN_LEARN_SAMPLES - 1):
            record_archive(db, f"2026-08-0{i + 1}T10:00:00")
        assert learn_thresholds(db) == {"warm_threshold": 3, "related_strength": 60.0, "review_days": 1}
        assert get_setting(db, KEY_LEARNING_STATE) is not None  # 时间戳已记录
    finally:
        db.close()


def test_learning_updates_and_persists(client):
    """样本足够：快节奏 → review_days=1 / warm_threshold=2；确认关联低分位 → related_strength。"""
    db = SessionLocal()
    try:
        start = datetime(2026, 8, 1, 8, 0, 0)
        for i in range(MIN_LEARN_SAMPLES):
            record_archive(db, (start + timedelta(days=0.5 * i)).isoformat())
        _confirmed_edges(db, [55.0, 55.0, 80.0, 90.0])
        thresholds = learn_thresholds(db)
        assert thresholds["review_days"] == 1
        assert thresholds["warm_threshold"] == 2
        assert thresholds["related_strength"] == 55.0
        # 已持久化，后续读取一致
        assert get_setting(db, "profile.review_days") == "1"
        assert get_setting(db, "profile.warm_threshold") == "2"
        assert get_setting(db, "profile.related_strength") == "55.0"
        assert get_thresholds(db) == thresholds
    finally:
        db.close()


def test_migrate_uses_learned_warm_threshold(client):
    """手动覆盖 warm_threshold=2 后，归档 2 本即触发暖转冷。"""
    from app.services.profile_service import migrate_profiles_on_archive

    db = SessionLocal()
    try:
        save_thresholds(db, warm_threshold=2)
    finally:
        db.close()

    ids = [_import_md(client, f"阈值学习书{i}.md", f"# 第一章\n\n第{i}章内容。\n") for i in range(2)]
    db = SessionLocal()
    try:
        profiles = None
        for i, bid in enumerate(ids):
            book = db.get(Book, bid)
            profiles = migrate_profiles_on_archive(db, book, rag=_rag(f"阈值学习书{i}", [f"概念{i} 与 主题词"]))
        assert profiles["cold"]["domain_preferences"], "warm_threshold=2 时归档 2 本应触发暖转冷"
        assert profiles["warm"]["archived_count"] == 2
    finally:
        db.close()


def test_migrate_keeps_default_without_learning(client):
    """未手动覆盖、样本不足：归档 3 本仍按默认阈值 3 触发暖转冷（既有行为不回退）。"""
    from app.services.profile_service import migrate_profiles_on_archive

    ids = [_import_md(client, f"默认阈值书{i}.md", f"# 第一章\n\n内容{i}。\n") for i in range(3)]
    db = SessionLocal()
    try:
        profiles = None
        for i, bid in enumerate(ids):
            book = db.get(Book, bid)
            profiles = migrate_profiles_on_archive(db, book, rag=_rag(f"默认阈值书{i}", [f"主题{i} 概念"]))
        assert profiles["cold"]["domain_preferences"], "默认阈值 3 本应触发暖转冷"
    finally:
        db.close()