"""统一响应结构与公共 Schema。"""
from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    """统一成功响应：{code, message, data}。"""
    return {"code": 0, "message": message, "data": data}
