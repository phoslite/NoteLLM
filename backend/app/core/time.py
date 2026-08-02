"""UTC 时间辅助：SQLite 存 naive UTC，避免 datetime.utcnow 弃用告警。"""
from datetime import UTC, datetime


def utcnow() -> datetime:
    """返回 naive UTC 当前时间（兼容 SQLite 存储）。"""
    return datetime.now(UTC).replace(tzinfo=None)