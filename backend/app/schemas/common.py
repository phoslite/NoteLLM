"""统一响应结构与公共 Schema。"""
from typing import Any

from pydantic import BaseModel


def ok(data: Any = None, message: str = "ok") -> dict:
    """统一成功响应：{code, message, data}。"""
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


class BookOut(BaseModel):
    id: int
    title: str
    author: str | None = None
    format: str
    status: str
    progress: float
    total_chapters: int
    graph_built: bool
    tags: list[str] = []
    folder_id: int | None = None
    created_at: str | None = None
    last_opened_at: str | None = None
    chapter_count: int = 0


class ChapterOut(BaseModel):
    id: int
    index: int
    title: str
    word_count: int
    read_flag: bool
