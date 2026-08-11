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


def test_submit_dedupe_atomic_under_concurrency(monkeypatch):
    """I-3：并发提交同 related_id 的重复任务，只允许一个创建成功（TOCTOU 修复）。"""
    from app.tasks import find_active as real_find_active
    from app.tasks import submit_dedupe

    entered = threading.Event()
    results: list[tuple[str, bool]] = []
    lock = threading.Lock()
    task_started = threading.Event()
    release_task = threading.Event()

    def patched_find_active(*args, **kwargs):
        # 无锁时两个线程都会同时通过检查；有锁时第二个线程阻塞在锁外，第一个超时继续
        entered.set()
        entered.wait(timeout=2.0)
        return real_find_active(*args, **kwargs)

    monkeypatch.setattr("app.tasks.find_active", patched_find_active)

    def worker():
        # 任务保持「running」直到 release_task 释放：确保第二个线程防重检查时任务仍在进行中
        tid, created = submit_dedupe(
            "text", "test-dedupe", lambda: (task_started.set(), release_task.wait(5)), related_id=777
        )
        with lock:
            results.append((tid, created))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    release_task.set()  # 收尾：释放后台任务，避免跨测试污染
    assert task_started.wait(3), "后台任务未进入执行"
    for tid, _ in results:
        _wait_status(tid, {"success", "failed"})  # 等待任务真正落库完成再结束测试
    created = [c for _, c in results]
    assert created.count(True) == 1, f"并发提交应恰好 1 个创建成功，实际 {created}"
    assert results[0][0] == results[1][0], "两个线程应拿到同一个 task_id"


def test_submit_dedupe_sync_nested_no_deadlock():
    """审查 I-2：submit_dedupe_sync 执行移出锁外——fn 内嵌套防重提交不死锁。"""
    from app.tasks import submit_dedupe_sync

    inner: list[tuple[str, bool]] = []

    def outer_fn():
        tid, created = submit_dedupe_sync("text", "nested-dedupe", lambda: None, related_id=999)
        inner.append((tid, created))
        return tid

    tid, created = submit_dedupe_sync("text", "outer-dedupe", outer_fn, related_id=998)
    assert created is True
    assert len(inner) == 1, "嵌套防重提交应正常返回"
    assert inner[0][1] is True
    assert inner[0][0] != tid


def test_update_progress_write_failure_does_not_fail_task(monkeypatch):
    """B-I5：进度写库失败（SQLite busy）仅记日志，已完成业务的任务仍为 success。"""
    from sqlalchemy.exc import OperationalError

    import app.tasks as tasks_mod

    original_set = tasks_mod._set_task_fields

    def flaky_set(db, task_id, **fields):
        # 仅模拟「进度字段」写失败（update_progress 专属）；状态/结果写不受影响
        if "progress" in fields:
            raise OperationalError("database is locked", None, None)
        return original_set(db, task_id, **fields)

    monkeypatch.setattr(tasks_mod, "_set_task_fields", flaky_set)
    task_id = submit("text", "test-progress-flaky", lambda: update_progress(50, "进行中"))
    st = _wait_status(task_id, {"success", "failed"})
    assert st["status"] == "success", "进度写库失败不得拖垮业务任务（B-I5）"


def test_vision_prefix_dedupes_import_and_rebuild():
    """B-I2：VISION_TASK_PREFIX 统一导入预提取与普通重建的防重键；force 重建独立。"""
    from app.tasks import VISION_TASK_PREFIX, submit_dedupe

    hold = threading.Event()

    def slow():
        hold.wait(5)
        return {"ok": 1}

    task_id, created = submit_dedupe(
        "vision", "vision-import-extract", slow, related_id=777, name_prefix=VISION_TASK_PREFIX
    )
    try:
        assert created is True
        # 普通重建（非 force）：同前缀 → 复用进行中任务，不新起一路全书提取
        tid2, created2 = submit_dedupe(
            "vision", "vision-rebuild", lambda: {"ok": 1}, related_id=777, name_prefix=VISION_TASK_PREFIX
        )
        assert created2 is False and tid2 == task_id
        # 显式 force 重建：独立前缀 → 允许新任务（用户显式全量重提取）
        tid3, created3 = submit_dedupe(
            "vision", "vision-rebuild-force", lambda: {"ok": 1},
            related_id=777, name_prefix="vision-rebuild-force",
        )
        assert created3 is True and tid3 != task_id
    finally:
        hold.set()
