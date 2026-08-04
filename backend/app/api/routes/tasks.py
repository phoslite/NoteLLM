"""后台任务 API（决策 35）：状态查询 + 任务列表（前端任务中心）。"""
from fastapi import APIRouter

from app.schemas.common import ok
from app.tasks import get_status, list_tasks

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_all_tasks(task_type: str | None = None, status: str | None = None, limit: int = 20):
    """任务列表（创建时间倒序），供前端任务中心轮询与进度展示。"""
    return ok(list_tasks(task_type=task_type, status=status, limit=limit))


@router.get("/{task_id}")
def task_status(task_id: str):
    """查询后台任务状态：{status, progress, stage, result, error}。"""
    return ok(get_status(task_id))
