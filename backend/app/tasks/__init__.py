"""后台任务：解析、图谱构建、画像更新等耗时操作。

M2 提供最小实现（内存态任务状态 + 结果）；M4/M6 扩展持久化与进度回调。
"""
import asyncio
import inspect
import threading
import uuid
from typing import Any

_STATUS: dict[str, dict] = {}


def submit(task_name: str, fn: Any) -> str:
    """在独立线程的事件循环中执行函数（同步或协程均可），返回 task_id。

    - 同步函数直接调用；协程对象 await；async 函数先调用生成协程再 await。
    - 结果存入内存状态：{"status", "result", "error"}。
    """
    task_id = uuid.uuid4().hex[:12]
    _STATUS[task_id] = {"status": "queued", "result": None, "error": None}

    async def _wrap():
        _STATUS[task_id]["status"] = "running"
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn()
            elif inspect.isawaitable(fn):
                result = await fn()
            else:
                result = fn()
            _STATUS[task_id]["result"] = result
            _STATUS[task_id]["status"] = "success"
        except Exception as exc:  # noqa: BLE001 任务结果以 error 字段透出
            _STATUS[task_id]["error"] = str(exc)
            _STATUS[task_id]["status"] = "failed"

    def _run():
        asyncio.run(_wrap())

    threading.Thread(target=_run, name=f"task-{task_name}-{task_id[:6]}", daemon=True).start()
    return task_id


def get_status(task_id: str) -> dict:
    """查询任务状态：{status: queued/running/success/failed/not_found, result, error}。"""
    return _STATUS.get(task_id, {"status": "not_found", "result": None, "error": None})