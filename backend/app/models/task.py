"""后台任务模型（决策 35）：任务落库 + 进度/阶段，完成后保留 7 天。"""
from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utcnow


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), default="generic", index=True)  # text / vision / render / generic
    name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued/running/success/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0~100
    stage: Mapped[str] = mapped_column(String(64), default="")  # 阶段文案（解析/页图/总结…）
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 关联书 id（任务中心展示用）
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
