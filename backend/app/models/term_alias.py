"""术语别名模型（聚类术语层 L0）：规范词与别名的映射，含来源与置信度。"""
from datetime import datetime

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utcnow


class TermAlias(Base):
    """term_aliases：别名 → 规范词映射（用户手工 / LLM 离线生成 / 自动候选三路来源）。

    - canonical: 规范词（多字术语，如「傅里叶变换」）；
    - alias: 别名/变体（唯一，如「傅氏变换」），归一折叠时按整词匹配；
    - source: user | llm | auto（auto 候选未确认只参与边权加成、不参与归一折叠）；
    - confidence: auto 来源 <1，供人工复核排序。
    """

    __tablename__ = "term_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical: Mapped[str] = mapped_column(String(100), index=True)  # ix_aliases_canonical
    alias: Mapped[str] = mapped_column(String(100), unique=True)
    source: Mapped[str] = mapped_column(String(10), default="user")  # user | llm | auto
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
