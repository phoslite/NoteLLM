"""M9 第五轮：相关度阈值函数（需求 3.4.1 / 9.1 决策 20 落地）。

- relatedness.compute_relatedness：谱系边强度 + 暖/冷画像术语覆盖率 + 同簇 → 0~100 分数与判定；
- profile_learning 行为样本学习：related_samples 低分位与确认边低分位取 min 学习 related_strength；
- 归档集成：相关书入暖记忆（含 score）、每次归档记录相关度行为样本。
"""
from app.core.database import SessionLocal
from app.models.book import Book
from app.models.graph import BookRelation
from app.repositories.assets import upsert_asset
from app.services.profile_learning import (
    learn_thresholds,
    learning_state,
    record_relatedness_sample,
    save_thresholds,
)
from app.services.profile_service import (
    COLD,
    WARM,
    _save,
    migrate_profiles_on_archive,
)
from app.services.relatedness import compute_relatedness, is_related_book


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _rag(title: str, key_points: list[str]) -> dict:
    return {"title": title, "summary": f"{title}的总结", "key_points": key_points}


def _attach_rag(book_id: int, rag: dict) -> None:
    db = SessionLocal()
    try:
        upsert_asset(db, book_id, "rag", rag)
    finally:
        db.close()


def _edge(a: int, b: int, strength: float) -> None:
    db = SessionLocal()
    try:
        db.add(
            BookRelation(
                book_a_id=a,
                book_b_id=b,
                strength=strength,
                direction="无",
                relation_type="概念共现",
                reasons_json="[]",
            )
        )
        db.commit()
    finally:
        db.close()


def test_relatedness_default_low_and_not_related(client):
    """无边、无画像：分数低（谱系 0 + 画像 0），related=False，信号三要素齐全。"""
    book_id = _import_md(client, "孤立书.md", "# 第一章\n\n泛函分析基础。\n")
    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        rel = compute_relatedness(db, book)
        assert rel["related"] is False
        assert rel["score"] == 0
        assert rel["threshold"] == 60.0
        assert {s["signal"] for s in rel["signals"]} == {"跨书关联", "暖画像主题", "冷画像领域"}
        assert is_related_book(db, book) is False
    finally:
        db.close()


def test_relatedness_high_edge_related(client):
    """高关联边：谱系信号主导 → related=True。"""
    a = _import_md(client, "谱系A.md", "# 第一章\n\n变分法。\n")
    b = _import_md(client, "谱系B.md", "# 第一章\n\n变分法进阶。\n")
    _edge(a, b, 82.0)
    db = SessionLocal()
    try:
        book_b = db.get(Book, b)
        rel = compute_relatedness(db, book_b)
        assert rel["related"] is True
        assert rel["score"] >= 82
        graph_signal = next(s for s in rel["signals"] if s["signal"] == "跨书关联")
        assert graph_signal["value"] == 82.0
    finally:
        db.close()


def test_relatedness_same_cluster_always_related(client):
    """同 post 簇：即使分数低也直接判定相关，分数抬升到阈值。"""
    a = _import_md(client, "同簇A.md", "# 第一章\n\n内容。\n")
    b = _import_md(client, "同簇B.md", "# 第一章\n\n内容。\n")
    db = SessionLocal()
    try:
        book_a = db.get(Book, a)
        book_b = db.get(Book, b)
        book_a.classify_source = "post"
        book_a.cluster_name = "泛函"
        book_b.classify_source = "post"
        book_b.cluster_name = "泛函"
        db.commit()
        rel = compute_relatedness(db, book_b)
        assert rel["same_cluster"] is True
        assert rel["related"] is True
        assert rel["score"] >= int(rel["threshold"])
        assert any(s["signal"] == "同簇" for s in rel["signals"])
    finally:
        db.close()


def test_relatedness_profile_terms_raise_score(client):
    """暖/冷画像术语覆盖率：写入画像后分数提升。"""
    book_id = _import_md(client, "画像信号书.md", "# 第一章\n\n变分法研究泛函极值。\n")
    _attach_rag(book_id, _rag("画像信号书", ["变分法研究泛函极值"]))
    db = SessionLocal()
    try:
        book = db.get(Book, book_id)
        before = compute_relatedness(db, book)["score"]
        _save(db, WARM, "default", {"themes": {"变分": 3, "分法": 2, "泛函": 1, "极值": 1}, "recent_books": []})
        _save(db, COLD, "default", {"domain_preferences": {"变分": 5, "分法": 3}, "long_term_interests": []})
        after = compute_relatedness(db, book)["score"]
        assert after > before, f"画像术语应提升分数: {before} -> {after}"
        warm_signal = next(s for s in compute_relatedness(db, book)["signals"] if s["signal"] == "暖画像主题")
        assert warm_signal["value"] > 0
    finally:
        db.close()


def test_relatedness_threshold_override_controls(client):
    """手动覆盖 related_strength=45：中等分数书由不相关变为相关。"""
    a = _import_md(client, "中关联A.md", "# 第一章\n\n内容。\n")
    b = _import_md(client, "中关联B.md", "# 第一章\n\n内容。\n")
    _edge(a, b, 50.0)
    db = SessionLocal()
    try:
        book_b = db.get(Book, b)
        rel_default = compute_relatedness(db, book_b)
        assert rel_default["related"] is False  # 50 < 默认 60
        save_thresholds(db, related_strength=45.0)
        rel_low = compute_relatedness(db, book_b)
        assert rel_low["related"] is True
        assert rel_low["threshold"] == 45.0
    finally:
        db.close()


def test_learning_from_relatedness_samples(client):
    """相关度行为样本 ≥ 下限：非簇样本 25% 低分位学习 related_strength（与确认边取 min）。"""
    db = SessionLocal()
    try:
        for i, score in enumerate([50.0, 50.0, 55.0, 60.0, 70.0, 80.0]):
            record_relatedness_sample(db, book_id=100 + i, score=score, same_cluster=False, archived_at=f"2026-08-0{i + 1}T10:00:00")
        assert learning_state(db)["related_sample_count"] == 6
        thresholds = learn_thresholds(db)
        assert thresholds["related_strength"] == 50.0  # 低分位 50（无确认边时）
    finally:
        db.close()


def test_learning_relatedness_min_with_confirmed(client):
    """行为样本低分位与确认边低分位取保守 min。"""
    from datetime import datetime, timedelta

    from app.services.profile_learning import record_archive

    db = SessionLocal()
    try:
        start = datetime(2026, 8, 1, 8, 0, 0)
        for i in range(6):
            record_archive(db, (start + timedelta(days=0.5 * i)).isoformat())
        for i, score in enumerate([58.0, 58.0, 60.0, 65.0, 70.0, 75.0]):
            record_relatedness_sample(db, book_id=200 + i, score=score, same_cluster=False, archived_at=f"2026-08-0{i + 1}T10:00:00")
        # 确认边低分位 62 > 行为样本低分位 58 → 取 min=58
        from app.models.book import Book as B
        from app.models.graph import BookRelation as BR

        books = [
            B(title=f"确认书{i}", format="md", file_path=f"r{i}.md", status="未读", progress=0.0)
            for i in range(5)
        ]
        db.add_all(books)
        db.commit()
        for i, s in enumerate([62.0, 62.0, 70.0, 80.0]):
            db.add(
                BR(
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
        thresholds = learn_thresholds(db)
        assert thresholds["related_strength"] == 58.0
    finally:
        db.close()


def test_archive_records_relatedness_sample_and_related_books(client):
    """归档集成：相关书（同簇）入暖记忆含 score；每次归档记录相关度样本。"""
    a = _import_md(client, "归档相关A.md", "# 第一章\n\n变分法内容。\n")
    b = _import_md(client, "归档相关B.md", "# 第一章\n\n变分法进阶。\n")
    db = SessionLocal()
    try:
        book_a = db.get(Book, a)
        book_b = db.get(Book, b)
        book_a.classify_source = "post"
        book_a.cluster_name = "变分"
        book_b.classify_source = "post"
        book_b.cluster_name = "变分"
        db.commit()
        migrate_profiles_on_archive(db, book_a, rag=_rag("归档相关A", ["变分法 泛函"]))
        profiles = migrate_profiles_on_archive(db, book_b, rag=_rag("归档相关B", ["变分法 泛函 极值"]))
        related = profiles["warm"]["related_books"]
        entry = next(r for r in related if r["book_id"] == b)
        assert entry["score"] >= 60
        assert learning_state(db)["related_sample_count"] == 2
    finally:
        db.close()
