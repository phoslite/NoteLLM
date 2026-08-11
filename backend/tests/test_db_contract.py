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
