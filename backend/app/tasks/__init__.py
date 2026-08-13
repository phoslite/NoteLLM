"""后台任务系统（决策 35）：落库 + 全局线程池 + 同类型配额 + progress/stage。

- 状态持久化到 tasks 表（重启不丢）；完成任务保留 7 天，提交新任务时顺带清理。
- 全局线程池（TASK_WORKERS，=0 时每任务独立线程）；同类型配额信号量（TASK_QUOTA_*，=0 不限制）。
- 进度上报：任务函数内直接调用 `tasks.update_progress(progress, stage)`，
  经线程本地变量自动路由到当前任务（500ms 节流写库）。
- 接口：submit(type, name, fn, quota=None, related_id=None) / get_status / list_tasks。
- 防重：submit_dedupe 提供进程内原子「防重检查 + 提交」（I-3 修复）；多进程部署需额外 DB 唯一索引。
"""
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.time import utcnow
from app.models.task import Task

RETENTION_DAYS = 7  # 完成任务保留时长（决策 35）

# 视觉提取任务统一防重前缀（B-I2）：导入预提取 / 重建页缓存共用，
# 同书同时只跑一路全书提取（防双倍多模态费用）；显式 force 重建用独立前缀绕开防重。
VISION_TASK_PREFIX = "vision-"

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
        "result": _safe_load_json(t.result_json),
        "error": t.error,
        "related_id": t.related_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
    }


def _safe_load_json(raw: str | None) -> Any:
    """解析任务结果 JSON；损坏时返回 None（终审 §6.9：防单条脏数据打挂任务接口）。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


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
        try:
            executor.submit(lambda: _run_task(task_id, sem, fn))
        except RuntimeError:  # 池已 shutdown（进程退出竞态）：降级独立线程，任务不丢失
            executor = None
    if executor is None:
        threading.Thread(
            target=lambda: _run_task(task_id, sem, fn),
            name=f"task-{task_name[:20]}-{task_id[:6]}",
            daemon=True,
        ).start()
    return task_id


_dedupe_lock = threading.Lock()  # I-3 修复：find_active→submit 检查-提交序列的进程内互斥


def submit_dedupe(
    task_type: str,
    task_name: str,
    fn: Callable[[], Any],
    *,
    related_id: int | None = None,
    name_prefix: str | None = None,
) -> tuple[str, bool]:
    """原子「防重检查 + 提交」（I-3 修复）：消除 find_active→submit 的 TOCTOU 窗口。

    并发请求同时通过防重检查导致重复任务（资产 version/内容互相覆盖）时，
    返回 (existing_task_id, False)；本次新建则返回 (new_task_id, True)。
    """
    _cleanup_old_tasks()  # 终审 §6.9：清理移出锁外，缩短防重锁竞争窗口
    with _dedupe_lock:
        existing = find_active(task_type, related_id=related_id, name_prefix=name_prefix)
        if existing:
            return existing, False
        task_id = submit(task_type, task_name, fn, related_id=related_id)
        return task_id, True


def submit_dedupe_sync(
    task_type: str,
    task_name: str,
    fn: Callable[[], Any],
    *,
    related_id: int | None = None,
    name_prefix: str | None = None,
) -> tuple[str, bool]:
    """同步防重提交（测试用）：锁内仅「防重检查 + 落库」，执行移出锁外。

    修复 I-3 收敛缺口：原实现在 _dedupe_lock 内同步执行 fn，慢任务会阻塞所有
    防重提交路径，且 fn 内嵌套 submit_dedupe 会死锁；现与 submit_dedupe 语义对齐。
    任务立即可见、无后台线程污染。"""
    with _dedupe_lock:
        existing = find_active(task_type, related_id=related_id, name_prefix=name_prefix)
        if existing:
            return existing, False
        task_id = uuid.uuid4().hex[:12]
        sem = _quota_for(task_type)
        _db_write(lambda db: db.add(Task(id=task_id, type=task_type, name=task_name, related_id=related_id)))
    _run_task(task_id, sem, fn)
    return task_id, True


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
    prev_task_id = getattr(_current, "task_id", None)  # 终审 §6.9：嵌套任务执行后恢复外层进度路由
    _current.task_id = task_id
    settled = False  # F5：是否已成功写入终态（success/failed）
    try:
        _db_write(lambda db: _set_task_fields(db, task_id, status="running"))
        result = fn()
        _finish(task_id, "success", result=result)
        settled = True
    except Exception as exc:  # noqa: BLE001 任务异常以 error 字段透出
        # 任务异常或状态写失败：先尝试写 failed；写失败时交给 finally 兜底
        try:
            _finish(task_id, "failed", error=str(exc))
            settled = True
        except Exception:  # noqa: BLE001
            pass
    finally:
        _current.task_id = prev_task_id
        if sem is not None:
            sem.release()
        if not settled:
            # F5 兜底：独立尽力写置 failed，防任务永久卡 queued/running 阻塞 find_active 防重
            try:
                _db_write(lambda db: _set_task_fields(db, task_id, status="failed", error="任务未写入终态（状态写库失败）"))
            except Exception:  # noqa: BLE001 写库失败已无法挽回，仅记录日志
                logging.getLogger("tasks").warning("task %s fallback status write failed", task_id)

def _set_task_fields(db: Any, task_id: str, **fields: Any) -> None:
    task = db.get(Task, task_id)
    if not task:
        return
    for key, value in fields.items():
        setattr(task, key, value)


def _finish(task_id: str, status: str, *, result: Any = None, error: str | None = None) -> None:
    fields: dict[str, Any] = {"status": status, "finished_at": utcnow()}
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
    """任务内上报进度（0~100 + 阶段文案），自动路由到当前任务；500ms 节流写库。

    B-I5：进度上报是「尽力而为」副作用——写库失败（如 SQLite busy 超过重试上限）
    仅记日志，绝不能让已完成业务的任务因进度写失败被 _run_task 判为 failed。
    """
    task_id = getattr(_current, "task_id", None)
    if not task_id:
        return
    now = time.monotonic()
    with _progress_lock:
        if now - _last_progress_write.get(task_id, 0.0) < 0.5:
            return
        _last_progress_write[task_id] = now
    try:
        _db_write(lambda db: _set_task_fields(db, task_id, progress=max(0, min(100, progress)), stage=stage))
    except OperationalError:
        logging.getLogger(__name__).warning("进度上报写库失败（任务 %s）", task_id, exc_info=True)


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


def find_recent_success(
    task_type: str,
    name_prefix: str | None = None,
    within_minutes: float | None = None,
) -> dict | None:
    """查找最近一次成功完成的任务（终审 F7：构建已完成则不再重复提交）。

    与 find_active 互补：find_active 只防「进行中」重复提交；本函数用于
    「构建已成功但结果为空（如单书库无跨书关联）」时，路由层据此跳过
    重复全量重建。within_minutes=None 表示不限时间窗（由调用方结合
    result 中的书籍数判定是否需要重建）。返回 _row_to_dict(task) 或 None。
    """
    with SessionLocal() as db:
        q = db.query(Task).filter(Task.type == task_type, Task.status == "success")
        if name_prefix:
            q = q.filter(Task.name.like(f"{name_prefix}%"))
        if within_minutes is not None:
            deadline = utcnow() - timedelta(minutes=within_minutes)
            q = q.filter(Task.finished_at.isnot(None), Task.finished_at >= deadline)
        task = q.order_by(Task.finished_at.desc()).first()
    return _row_to_dict(task) if task else None


def find_recent_finished(
    task_type: str,
    name_prefix: str | None = None,
    within_minutes: float | None = None,
) -> dict | None:
    """查找最近一次已结束（success/failed）的任务（审查 P1：失败风暴防护）。

    与 find_recent_success 互补：路由层在「无成功记录」时据此判断最近是否失败，
    避免构建持续失败时每次请求都重提全量重建 + LLM 打分（失败风暴）。"""
    with SessionLocal() as db:
        q = db.query(Task).filter(Task.type == task_type, Task.status.in_(["success", "failed"]))
        if name_prefix:
            q = q.filter(Task.name.like(f"{name_prefix}%"))
        if within_minutes is not None:
            deadline = utcnow() - timedelta(minutes=within_minutes)
            q = q.filter(Task.finished_at.isnot(None), Task.finished_at >= deadline)
        task = q.order_by(Task.finished_at.desc()).first()
    return _row_to_dict(task) if task else None


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
        q = db.query(Task).order_by(Task.created_at.desc(), text("rowid DESC"))  # 审查 P2-3：同微秒撞车按插入序决胜（后提交在前）
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
    now = utcnow()

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
    deadline = utcnow() - timedelta(days=RETENTION_DAYS)

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

