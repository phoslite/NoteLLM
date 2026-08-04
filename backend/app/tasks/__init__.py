"""后台任务系统（决策 35）：落库 + 全局线程池 + 同类型配额 + progress/stage。

- 状态持久化到 tasks 表（重启不丢）；完成任务保留 7 天，提交新任务时顺带清理。
- 全局线程池（TASK_WORKERS，=0 时每任务独立线程）；同类型配额信号量（TASK_QUOTA_*，=0 不限制）。
- 进度上报：任务函数内直接调用 `tasks.update_progress(progress, stage)`，
  经线程本地变量自动路由到当前任务（500ms 节流写库）。
- 接口：submit(type, name, fn, quota=None, related_id=None) / get_status / list_tasks。
"""
import json
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.task import Task

RETENTION_DAYS = 7  # 完成任务保留时长（决策 35）

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_quotas: dict[str, threading.Semaphore | None] = {}
_quota_lock = threading.Lock()
_progress_lock = threading.Lock()
_last_progress_write: dict[str, float] = {}
_current = threading.local()  # 当前执行线程所属 task_id


def _get_executor() -> ThreadPoolExecutor | None:
    """全局线程池；TASK_WORKERS=0 时返回 None（每任务独立线程，旧行为）。"""
    global _executor
    with _executor_lock:
        if _executor is None and settings.task_workers and settings.task_workers > 0:
            _executor = ThreadPoolExecutor(max_workers=settings.task_workers, thread_name_prefix="task-pool")
        return _executor


def _quota_for(task_type: str) -> threading.Semaphore | None:
    """同类型任务配额信号量（B 方案：多任务可同时、总量受限；0=不限制）。"""
    with _quota_lock:
        if task_type not in _quotas:
            count = 0
            if task_type == "text":
                count = settings.task_quota_text
            elif task_type == "vision":
                count = settings.task_quota_vision
            elif task_type == "render":
                count = settings.page_render_concurrency
            _quotas[task_type] = threading.Semaphore(count) if count and count > 0 else None
        return _quotas[task_type]


def _db_write(action: Callable[[Any], None]) -> None:
    """短事务写库：SQLite 并发写冲突（database is locked）时忙等重试（决策 4）。"""
    last: Exception | None = None
    for attempt in range(5):
        try:
            with SessionLocal() as db:
                action(db)
                db.commit()
            return
        except OperationalError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    if last is not None:
        raise last


def _row_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "type": t.type,
        "name": t.name,
        "status": t.status,
        "progress": t.progress,
        "stage": t.stage,
        "result": json.loads(t.result_json) if t.result_json else None,
        "error": t.error,
        "related_id": t.related_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
    }


def submit(
    task_type: str,
    task_name: str,
    fn: Callable[[], Any],
    *,
    quota: threading.Semaphore | None = None,
    related_id: int | None = None,
) -> str:
    """提交后台任务，立即返回 task_id。

    - task_type：text / vision / render / generic，决定占用哪类配额信号量；
    - 任务函数内可调用 `tasks.update_progress(progress, stage)` 上报进度；
    - quota：显式传入自定义信号量（默认按 task_type 取全局配额）。
    """
    task_id = uuid.uuid4().hex[:12]
    sem = quota if quota is not None else _quota_for(task_type)
    _db_write(lambda db: db.add(Task(id=task_id, type=task_type, name=task_name, related_id=related_id)))
    _cleanup_old_tasks()  # 顺带清理过期任务（尽力而为，失败不影响提交）

    executor = _get_executor()
    if executor is not None:
        executor.submit(lambda: _run_task(task_id, sem, fn))
    else:
        threading.Thread(
            target=lambda: _run_task(task_id, sem, fn),
            name=f"task-{task_name[:20]}-{task_id[:6]}",
            daemon=True,
        ).start()
    return task_id


def submit_sync(
    task_type: str,
    task_name: str,
    fn: Callable[[], Any],
    *,
    quota: threading.Semaphore | None = None,
    related_id: int | None = None,
) -> str:
    """同步执行版本（测试/调试用）：落库后立即执行 fn 并写结果，返回 task_id。

    与 submit 共用同一套落库/进度/配额逻辑，仅不在后台线程运行，
    保证单元测试内任务立即可见、无跨测试异步竞态。
    """
    task_id = uuid.uuid4().hex[:12]
    sem = quota if quota is not None else _quota_for(task_type)
    _db_write(lambda db: db.add(Task(id=task_id, type=task_type, name=task_name, related_id=related_id)))
    _run_task(task_id, sem, fn)
    return task_id


def _run_task(task_id: str, sem: threading.Semaphore | None, fn: Callable[[], Any]) -> None:
    """任务执行主体：配额获取、状态流转、进度路由、结果/异常落库（submit 与 submit_sync 共用）。"""
    if sem is not None:
        sem.acquire()
    _current.task_id = task_id
    try:
        _db_write(lambda db: _set_task_fields(db, task_id, status="running"))
        result = fn()
        _finish(task_id, "success", result=result)
    except Exception as exc:  # noqa: BLE001 任务异常以 error 字段透出
        _finish(task_id, "failed", error=str(exc))
    finally:
        _current.task_id = None
        if sem is not None:
            sem.release()


def _set_task_fields(db: Any, task_id: str, **fields: Any) -> None:
    task = db.get(Task, task_id)
    if not task:
        return
    for key, value in fields.items():
        setattr(task, key, value)


def _finish(task_id: str, status: str, *, result: Any = None, error: str | None = None) -> None:
    fields: dict[str, Any] = {"status": status, "finished_at": datetime.now()}
    if error is not None:
        fields["error"] = error
    elif result is not None:
        try:
            fields["result_json"] = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            fields["result_json"] = json.dumps({"raw": str(result)}, ensure_ascii=False)
    _db_write(lambda db: _set_task_fields(db, task_id, **fields))
    with _progress_lock:
        _last_progress_write.pop(task_id, None)


def update_progress(progress: int, stage: str = "") -> None:
    """任务内上报进度（0~100 + 阶段文案），自动路由到当前任务；500ms 节流写库。"""
    task_id = getattr(_current, "task_id", None)
    if not task_id:
        return
    now = time.monotonic()
    with _progress_lock:
        if now - _last_progress_write.get(task_id, 0.0) < 0.5:
            return
        _last_progress_write[task_id] = now
    _db_write(lambda db: _set_task_fields(db, task_id, progress=max(0, min(100, progress)), stage=stage))


def find_active(task_type: str, related_id: int | None = None, name_prefix: str | None = None) -> str | None:
    """查找同类型进行中（queued/running）任务，避免重复提交（决策 35 幂等）。

    - related_id 非 None：仅匹配同 related_id；None：仅匹配 related_id IS NULL 的全局任务；
    - name_prefix：可选按任务名前缀精确匹配（如 graph-rebuild 与 graph-sync 区分）。
    """
    with SessionLocal() as db:
        q = db.query(Task).filter(Task.type == task_type, Task.status.in_(["queued", "running"]))
        if related_id is not None:
            q = q.filter(Task.related_id == related_id)
        else:
            q = q.filter(Task.related_id.is_(None))
        if name_prefix:
            q = q.filter(Task.name.like(f"{name_prefix}%"))
        task = q.order_by(Task.created_at.desc()).first()
    return task.id if task else None


def get_status(task_id: str) -> dict:
    """查询任务状态：{status, progress, stage, result, error}；不存在返回 not_found。"""
    with SessionLocal() as db:
        task = db.get(Task, task_id)
    if not task:
        return {"status": "not_found", "result": None, "error": None}
    return _row_to_dict(task)


def list_tasks(task_type: str | None = None, status: str | None = None, limit: int = 20) -> list[dict]:
    """任务列表（创建时间倒序），供前端任务中心轮询。"""
    with SessionLocal() as db:
        q = db.query(Task).order_by(Task.created_at.desc())
        if task_type:
            q = q.filter(Task.type == task_type)
        if status:
            q = q.filter(Task.status == status)
        rows = q.limit(max(1, min(limit, 100))).all()
    return [_row_to_dict(t) for t in rows]


def mark_interrupted() -> int:
    """服务启动时调用：把遗留的 queued/running 任务标记为 failed（进程重启中断）。

    防止重启后 find_active 复用永不完成的死任务（决策 35 幂等安全）；
    前端任务中心会把中断任务显示为失败，提示用户重新提交。
    """
    now = datetime.now()

    def _mark(db: Any) -> None:
        rows = db.query(Task).filter(Task.status.in_(["queued", "running"])).all()
        for t in rows:
            t.status = "failed"
            t.error = "服务重启，任务中断，请重新提交"
            t.finished_at = now

    try:
        _db_write(_mark)
    except Exception:  # noqa: BLE001 尽力而为，失败不影响启动
        return 0
    return 1


def _cleanup_old_tasks() -> None:
    """清理超过保留期的已完成任务（决策 35：保留 7 天）。"""
    deadline = datetime.now() - timedelta(days=RETENTION_DAYS)

    def _clean(db: Any) -> None:
        db.query(Task).filter(
            Task.status.in_(["success", "failed"]),
            Task.finished_at.isnot(None),
            Task.finished_at < deadline,
        ).delete(synchronize_session=False)

    try:
        _db_write(_clean)
    except Exception:  # noqa: BLE001 清理失败不影响主流程
        pass

