"""I-7：get_db 请求级会话的隐式提交契约（路由层直接 db.add 也必须持久化）。"""
import pytest

from app.core.database import SessionLocal, get_db, init_db
from app.models.book import Book


@pytest.fixture(autouse=True)
def _db_ready():
    init_db()
    yield
    # 审查：本模块不使用 client 夹具（无 drop_all），直插的书籍行会残留并污染
    # 后续依赖 client 的测试（如书架排序）；测试结束清理本模块专属行。
    with SessionLocal() as db:
        db.query(Book).filter(Book.title.like("请求级%契约书")).delete()
        db.commit()


def test_book_relations_unique_pair_constraint():
    """审查 P1-3 回归：book_relations 同 (book_a_id, book_b_id) 不得插入两行（并发重建防重复边）。

    本模块约定不使用 conftest client 夹具（其 teardown drop_all 与 _db_ready 清理冲突），
    测试内自建 TestClient。
    """
    import json as _json

    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError

    from app.core.database import SessionLocal
    from app.main import app
    from app.models.graph import BookRelation

    with TestClient(app) as c:
        a = c.post("/api/books", files={"file": ("约束A.md", "# 第一章 变分\n\n变分法内容。\n".encode(), "text/markdown")}).json()["data"]["id"]
        b = c.post("/api/books", files={"file": ("约束B.md", "# 第一章 泛函\n\n泛函分析内容。\n".encode(), "text/markdown")}).json()["data"]["id"]
    lo, hi = min(a, b), max(a, b)
    db = SessionLocal()
    try:
        db.add(BookRelation(book_a_id=lo, book_b_id=hi, strength=80.0, direction="无", relation_type="概念共现", reasons_json=_json.dumps(["变分"], ensure_ascii=False)))
        db.commit()
        db.add(BookRelation(book_a_id=lo, book_b_id=hi, strength=60.0, direction="无", relation_type="概念共现", reasons_json=_json.dumps(["变分"], ensure_ascii=False)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return  # 唯一约束生效（同 pair 第二行被拒绝）
        raise AssertionError("同 pair 第二行未被唯一约束拦截")
    finally:
        db.close()


def test_get_db_commits_pending_changes():
    gen = get_db()
    db = next(gen)
    db.add(Book(title="请求级提交契约书", file_path="/tmp/x.md", format="md"))
    with pytest.raises(StopIteration):
        next(gen)  # yield 之后应执行请求级 commit
    with SessionLocal() as check:
        assert check.query(Book).filter_by(title="请求级提交契约书").first() is not None, "请求结束后新增行应已提交"


def test_get_db_rolls_back_on_exception():
    """I-7：请求抛出异常时，get_db 应回滚未提交改动而非残留半态。"""
    gen = get_db()
    db = next(gen)
    db.add(Book(title="请求级回滚契约书", file_path="/tmp/y.md", format="md"))
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("请求中断"))
    with SessionLocal() as check:
        assert check.query(Book).filter_by(title="请求级回滚契约书").first() is None, "请求异常后新增行应回滚"
