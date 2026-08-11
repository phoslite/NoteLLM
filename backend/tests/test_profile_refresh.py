"""「重新生成画像」：暖主题重算 + 冷画像清洗/领域偏好重建/词库沉淀（v1.132~v1.134）。"""
import json
import os
from pathlib import Path

from app.core.database import SessionLocal
from app.models.asset import BookAsset
from app.services.profile_service import (
    COLD,
    HOT,
    WARM,
    _rebuild_domain_preferences,
    _save,
    get_all_profiles,
    refresh_profiles,
    update_cold_profile,
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
        "manual_interests": ["实分析"],  # v1.136 手动编辑快照：refresh 仅保留快照内整词
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
        assert "变分法" in warm["themes"] and "泛函" in warm["themes"]  # jieba 整词
        # 冷画像 v1.133：领域偏好从 RAG 重建（本测试未造 RAG → 旧碎片/旧词全部清除）
        assert "定义" not in cold["domain_preferences"] and "任意" not in cold["domain_preferences"]
        assert "Hilbert" not in cold["domain_preferences"]
        assert cold["long_term_interests"] == ["实分析"]  # 手动整词保留
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


def test_refresh_rebuilds_domain_preferences_from_rag(client):
    """领域偏好从有 RAG 资产的书重建（v1.133）：可溯源术语、无跨词碎片；手动整词保留。"""
    r = client.post("/api/books", files={"file": ("领域书.md", "# 第一章\n\n自由度与广义坐标的变分法内容。\n".encode(), "text/markdown")})
    assert r.status_code == 200
    book_id = r.json()["data"]["id"]
    db = SessionLocal()
    try:
        db.add(BookAsset(
            book_id=book_id, kind="rag", version=1,
            content_json=json.dumps({
                "summary": "变分法研究泛函极值",
                "key_points": ["自由度与广义坐标的确定"],
            }, ensure_ascii=False),
        ))
        db.commit()
        _save(db, COLD, "default", {
            "domain_preferences": {"由度": 545.0, "度定": 317.0, "函数": 410.0},
            "long_term_interests": ["实分析"],
            "manual_interests": ["实分析"],  # v1.136 手动编辑快照
        })
        stats = refresh_profiles(db)
        cold = get_all_profiles(db)["cold"]
        prefs = cold["domain_preferences"]
        assert "由度" not in prefs and "度定" not in prefs  # 跨词碎片
        assert "函数" not in prefs  # 泛化词
        assert "变分法" in prefs or "变分" in prefs  # 书内可溯源术语
        assert stats["cold_before"] == 3 and stats["cold_after"] <= 60
        assert "实分析" in cold["long_term_interests"]  # 手动整词保留
    finally:
        db.close()


def test_refresh_interests_drop_legacy_fragments_and_generic(client):
    """v1.136：无手动编辑标记时，旧二元组碎片（由度/度定/性映/然种）与次泛词（空间/系统）全部清除。"""
    db = SessionLocal()
    try:
        _save(db, WARM, "default", {"recent_books": [], "related_books": [], "themes": {}, "archived_count": 3})
        _save(db, COLD, "default", {
            "domain_preferences": {"定义": 5.0},
            "long_term_interests": ["实分析", "由度", "度定", "性映", "然种", "空间", "系统"],
        })
        refresh_profiles(db)
        interests = get_all_profiles(db)["cold"]["long_term_interests"]
        assert "由度" not in interests and "度定" not in interests
        assert "性映" not in interests and "然种" not in interests
        assert "空间" not in interests and "系统" not in interests
    finally:
        db.close()


def test_refresh_interests_keep_manual_edited_words_only(client):
    """v1.136：manual_interests 快照内的整词保留；快照外的旧词（即使非碎片）不保留。"""
    db = SessionLocal()
    try:
        _save(db, WARM, "default", {"recent_books": [], "related_books": [], "themes": {}, "archived_count": 3})
        _save(db, COLD, "default", {
            "long_term_interests": ["实分析", "复分析"],
            "manual_interests": ["实分析"],
        })
        refresh_profiles(db)
        interests = get_all_profiles(db)["cold"]["long_term_interests"]
        assert "实分析" in interests
        assert "复分析" not in interests
    finally:
        db.close()


def test_update_cold_profile_records_manual_interests(client):
    """v1.136：手动保存长期兴趣时同步记录 manual_interests 快照（去重+清洗后）。"""
    db = SessionLocal()
    try:
        cold = update_cold_profile(db, long_term_interests=["实分析", "实分析", "参数论（不动点）"])
        assert cold["long_term_interests"] == ["实分析", "参数论 不动点"]
        assert cold["manual_interests"] == ["实分析", "参数论 不动点"]
    finally:
        db.close()


def test_refresh_rebuilt_interests_skip_sync_stopwords(client):
    """v1.136：长期兴趣的重建 top10 也过滤次泛词（函数/方程/空间…），专业词保留。"""
    r = client.post("/api/books", files={"file": ("兴趣重建.md", "# 第一章\n\n内容。\n".encode(), "text/markdown")})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        db.add(BookAsset(
            book_id=r.json()["data"]["id"], kind="rag", version=1,
            content_json=json.dumps({"summary": "变分法研究函数方程与空间", "key_points": ["角动量守恒与能量"]}, ensure_ascii=False),
        ))
        db.commit()
        refresh_profiles(db)
        interests = get_all_profiles(db)["cold"]["long_term_interests"]
        assert "变分法" in interests or "角动量" in interests
        assert "函数" not in interests and "方程" not in interests and "空间" not in interests
    finally:
        db.close()


def test_rebuild_fragments_cover_deeper_book_terms(client):
    """v1.136：fragments 从每本书 top80 抽取词构建——父整词落在 top15 之外的碎片（由度）也能被抑制。"""
    elements = ["hydrogen", "helium", "lithium", "beryllium", "boron", "carbon", "nitrogen",
                "oxygen", "fluorine", "neon", "sodium", "magnesium", "aluminum", "silicon",
                "phosphorus", "sulfur", "chlorine", "argon", "potassium", "calcium"]
    kps = [elem for elem in elements for _ in range(4)] + ["自由度与广义坐标"]
    r = client.post("/api/books", files={"file": ("碎片书.md", "# 第一章\n\n内容。\n".encode(), "text/markdown")})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        db.add(BookAsset(
            book_id=r.json()["data"]["id"], kind="rag", version=1,
            content_json=json.dumps({"summary": "测试", "key_points": kps}, ensure_ascii=False),
        ))
        db.commit()
        prefs, fragments = _rebuild_domain_preferences(db)
        assert "由度" in fragments  # 「自由度」的内部二元组（父整词不在 top15，旧实现会漏）
    finally:
        db.close()


def test_refresh_syncs_domain_terms_to_lexicon(client):
    """v1.134 联动：覆盖≥2 本书的领域词沉淀词库系统缓存区；单书词不沉淀；重复 refresh 幂等。"""
    rag_text = "# 第一章\n\n内容。\n"
    book_ids = []
    for name in ("联动A.md", "联动B.md"):
        r = client.post("/api/books", files={"file": (name, rag_text.encode("utf-8"), "text/markdown")})
        assert r.status_code == 200
        book_ids.append(r.json()["data"]["id"])
    db = SessionLocal()
    try:
        contents = [
            {"summary": "变分法研究泛函极值与空间", "key_points": ["角动量守恒定律"]},
            {"summary": "变分法在力学中的应用与空间", "key_points": ["变分法核心"]},
        ]
        for bid, content in zip(book_ids, contents, strict=True):
            db.add(BookAsset(
                book_id=bid, kind="rag", version=1,
                content_json=json.dumps(content, ensure_ascii=False),
            ))
        db.commit()
        refresh_profiles(db)
        lexicon_path = os.environ.get("DOMAIN_TERMS_FILE", "domain_terms.txt")
        text = Path(lexicon_path).read_text(encoding="utf-8")
        assert "变分法" in text  # 两本书共享 → 沉淀
        assert "角动量" not in text  # 仅 A 书 → 不沉淀
        assert "空间" not in text  # 次泛词即使覆盖 2 本也不沉淀
        refresh_profiles(db)  # 幂等：不重复写入
        assert Path(lexicon_path).read_text(encoding="utf-8").count("变分法") == 1
    finally:
        db.close()
