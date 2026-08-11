"""「重新生成画像」：暖主题重算 + 冷画像清洗（v1.132 spec §2.1）。"""
from app.core.database import SessionLocal
from app.services.profile_service import (
    COLD,
    HOT,
    WARM,
    _save,
    get_all_profiles,
    refresh_profiles,
)


def _seed(db):
    _save(db, WARM, "default", {
        "recent_books": [{
            "book_id": 1, "title": "甲", "archived_at": "2026-08-11T00:00:00",
            "summary": "变分法研究泛函极值", "key_points": ["线性代数核心"],
        }],
        "related_books": [],
        "themes": {"定义": 100.0, "的稳": 50.0, "系统": 55.0, "质点": 44.0},
        "archived_count": 3,
    })
    _save(db, COLD, "default", {
        "domain_preferences": {"定义": 515.0, "任意": 234.0, "的稳": 22.0, "Hilbert": 5.0},
        "long_term_interests": ["实分析", "的稳"],
    })
    _save(db, HOT, "current", {
        "current_book_id": 7, "current_title": "热书", "progress": 0.5,
        "chapter_titles": [], "highlights": [], "questions": [],
    })


def test_refresh_rebuilds_warm_themes_and_cleans_cold(client):
    db = SessionLocal()
    try:
        _seed(db)
        hot_before = get_all_profiles(db)["hot"]
        stats = refresh_profiles(db)
        profiles = get_all_profiles(db)
        warm, cold = profiles["warm"], profiles["cold"]
        # 暖主题按近期书原文重算（不再含脏词/旧累积）
        assert "定义" not in warm["themes"] and "的稳" not in warm["themes"]
        assert "变分" in warm["themes"] and "泛函" in warm["themes"]
        # 冷画像脏词剔除、手动整词保留
        assert "定义" not in cold["domain_preferences"] and "任意" not in cold["domain_preferences"]
        assert cold["domain_preferences"].get("Hilbert") == 5.0
        assert cold["long_term_interests"] == ["实分析"]
        # 热画像不变
        assert profiles["hot"] == hot_before
        # 统计字段齐全
        assert stats["themes_before"] == 4 and stats["themes_after"] > 0
        assert stats["cold_before"] == 4
        assert stats["removed_sample"]
    finally:
        db.close()


def test_refresh_empty_profiles_ok(client):
    db = SessionLocal()
    try:
        stats = refresh_profiles(db)
        assert stats["themes_before"] == 0 and stats["themes_after"] == 0
        assert stats["cold_before"] == 0 and stats["cold_after"] == 0
    finally:
        db.close()


def test_refresh_idempotent_second_run_no_change(client):
    db = SessionLocal()
    try:
        _seed(db)
        refresh_profiles(db)
        stats2 = refresh_profiles(db)
        assert stats2["themes_before"] == stats2["themes_after"]
        assert stats2["cold_before"] == stats2["cold_after"]
    finally:
        db.close()
