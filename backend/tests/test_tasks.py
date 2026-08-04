"""任务系统测试（决策 35）：落库生命周期 / 失败透出 / 进度上报 / 配额串行 / 7 天清理。"""
import threading
import time
from datetime import timedelta

import pytest

from app.core.database import SessionLocal, init_db
from app.core.time import utcnow
from app.models.task import Task
from app.tasks import get_status, list_tasks, submit, update_progress


@pytest.fixture(autouse=True)
def _db_ready():
    init_db()
    yield


def _wait_status(task_id: str, wanted: set[str], timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    st: dict = {}
    while time.time() < deadline:
        st = get_status(task_id)
        if st["status"] in wanted:
            return st
        time.sleep(0.05)
    return st


def test_submit_success_lifecycle():
    task_id = submit("text", "test-lifecycle", lambda: {"ok": 1, "msg": "完成"})
    st = _wait_status(task_id, {"success", "failed"})
    assert st["status"] == "success"
    assert st["result"] == {"ok": 1, "msg": "完成"}
    assert st["finished_at"] is not None
    with SessionLocal() as db:
        row = db.get(Task, task_id)
    assert row is not None
    assert row.type == "text" and row.name == "test-lifecycle"
    assert row.status == "success"


def test_submit_failure_captures_error():
    def boom():
        raise RuntimeError("任务爆炸")

    task_id = submit("vision", "test-fail", boom)
    st = _wait_status(task_id, {"failed"})
    assert st["status"] == "failed"
    assert "任务爆炸" in (st["error"] or "")


def test_update_progress_records_stage():
    task_id = submit("render", "test-progress", lambda: update_progress(66, "页图渲染"))
    assert _wait_status(task_id, {"success", "failed"})["status"] == "success"
    with SessionLocal() as db:
        row = db.get(Task, task_id)
    assert row is not None
    assert row.progress == 66
    assert row.stage == "页图渲染"


def test_quota_serializes_same_type():
    entered = threading.Event()
    release = threading.Event()

    def slow():
        entered.set()
        release.wait(5)
        return "done"

    quota = threading.Semaphore(1)
    submit("text", "quota-1", slow, quota=quota)
    assert entered.wait(3), "第一个任务未进入执行"
    t2 = submit("text", "quota-2", slow, quota=quota)
    time.sleep(0.4)  # 给第二个任务的 run 一点时间尝试获取信号量
    assert get_status(t2)["status"] == "queued", "配额应阻塞第二个任务"
    release.set()
    assert _wait_status(t2, {"success", "failed"})["status"] == "success"


def test_get_status_not_found():
    assert get_status("no-such-task")["status"] == "not_found"


def test_list_tasks_ordered_and_filtered():
    a = submit("text", "list-a", lambda: None)
    b = submit("vision", "list-b", lambda: None)
    _wait_status(a, {"success", "failed"})
    _wait_status(b, {"success", "failed"})
    rows = list_tasks(limit=50)
    ids = [r["id"] for r in rows]
    assert a in ids and b in ids
    assert ids.index(b) < ids.index(a)  # 创建时间倒序：后提交的在前
    vis = list_tasks(task_type="vision", limit=10)
    assert vis and all(r["type"] == "vision" for r in vis)


def test_retention_cleanup():
    old_id = "oldtask000001"
    with SessionLocal() as db:
        db.add(
            Task(
                id=old_id,
                type="text",
                name="old",
                status="success",
                finished_at=utcnow() - timedelta(days=8),
            )
        )
        db.commit()
    nid = submit("text", "cleanup-trigger", lambda: None)  # 提交触发顺带清理
    assert _wait_status(nid, {"success", "failed"})["status"] == "success"
    with SessionLocal() as db:
        assert db.get(Task, old_id) is None
