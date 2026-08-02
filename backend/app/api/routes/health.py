"""健康检查。"""
from fastapi import APIRouter

from app.schemas.common import ok

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return ok({"status": "ok", "app": "读书阅读助手"})