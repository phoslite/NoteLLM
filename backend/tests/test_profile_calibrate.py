"""知识水平校准（v1.135，用户主动触发）：建议打分 + 手动设置归一化。"""
import json

import pytest

from app.core.database import SessionLocal
from app.models.asset import BookAsset
from app.models.book import Book
from app.services.profile_service import (
    COLD,
    WARM,
    _save,
    calibrate_knowledge_level,
    get_all_profiles,
    update_cold_profile,
)


def test_calibrate_empty_profile_suggests_beginner(client):
    db = SessionLocal()
    try:
        suggestion = calibrate_knowledge_level(db)
        assert suggestion["suggested"] == "beginner"
        assert suggestion["current"] == "intermediate"  # 默认兜底值
        assert suggestion["score"] == 0.0
        assert len(suggestion["signals"]) == 4
        assert set(suggestion["levels"]) == {"beginner", "intermediate", "advanced"}
    finally:
        db.close()


def test_calibrate_rich_profile_suggests_advanced_and_does_not_write(client):
    db = SessionLocal()
    try:
        _save(db, WARM, "default", {"archived_count": 12})
        _save(db, COLD, "default", {
            "domain_preferences": {"函数": 9.0, "空间": 8.0},
            "long_term_interests": ["实分析"] * 18,
        })
        for i in range(12):
            book = Book(title=f"校准书{i}", format="md", file_path=f"tmp/cal{i}.md")
            db.add(book)
            db.flush()
            db.add(BookAsset(
                book_id=book.id, kind="rag", version=1,
                content_json=json.dumps({"summary": "变分法", "key_points": []}),
            ))
        db.commit()
        suggestion = calibrate_knowledge_level(db)
        assert suggestion["suggested"] == "advanced"
        assert suggestion["score"] >= 4.5
        # 只建议不写入：冷画像 knowledge_level 不被修改
        assert get_all_profiles(db)["cold"].get("knowledge_level") is None
    finally:
        db.close()


def test_update_cold_profile_knowledge_level_normalizes(client):
    db = SessionLocal()
    try:
        cold = update_cold_profile(db, knowledge_level="入门")
        assert cold["knowledge_level"] == "beginner"
        cold2 = update_cold_profile(db, knowledge_level="advanced")
        assert cold2["knowledge_level"] == "advanced"
        # 其他字段不受影响（未传入则不创建/不修改）
        assert cold2.get("long_term_interests") is None
        assert cold2.get("domain_preferences") is None
    finally:
        db.close()


def test_update_cold_profile_invalid_level_raises(client):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            update_cold_profile(db, knowledge_level="???unknown")
    finally:
        db.close()


def test_calibrate_route_and_patch_route(client):
    r = client.get("/api/profile/calibrate")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["suggested"] in ("beginner", "intermediate", "advanced")
    assert data["evidence"]["archived_books"] >= 0

    r2 = client.patch("/api/profile/cold", json={"knowledge_level": "深入"})
    assert r2.status_code == 200
    assert r2.json()["data"]["knowledge_level"] == "advanced"

    r3 = client.patch("/api/profile/cold", json={"knowledge_level": "???unknown"})
    assert r3.status_code == 400
