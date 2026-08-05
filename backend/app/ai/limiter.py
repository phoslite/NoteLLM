"""LLM 并发限流（决策 35）：文本 / 视觉信号量分池；=0 表示不限制。

后期 LLM 并发改造（决策 34 挑选器、打分并发）统一经 get_limiter 取信号量，
禁止调用方自行开线程绕过限流（8.4 统一限流入口）。
"""
import threading

from app.core.config import settings

_lock = threading.Lock()
_limiters: dict[str, threading.Semaphore | None] = {}


def _count_for(kind: str) -> int:
    if kind == "vision":
        return settings.vision_concurrency
    return settings.ai_concurrency


def get_limiter(kind: str) -> threading.Semaphore | None:
    """返回对应池的信号量；配置为 0（不限制）或未知类型时返回 None（不限流）。"""
    key = kind.lower()
    with _lock:
        if key not in _limiters:
            count = _count_for(key)
            _limiters[key] = threading.Semaphore(count) if count and count > 0 else None
        return _limiters[key]


