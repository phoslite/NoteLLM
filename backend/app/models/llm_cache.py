"""LLM 结果缓存模型（性能优化路径 §7 决策 5：脑图/预设模式内容寻址缓存）。"""
from datetime import datetime, timedelta

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.core.time import utcnow


class LlmCache(Base):
    __tablename__ = "llm_caches"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # mindmap / 解读 / 概论 / 思考逻辑
    input_hash: Mapped[str] = mapped_column(String(32))  # 输入指纹（章节内容摘要 + 提问/选区）
    content_json: Mapped[str] = mapped_column(Text, default="")  # 缓存结果（脑图数据或 LLM 回答）
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        default=lambda: utcnow() + timedelta(days=settings.llm_cache_ttl_days)
    )

    __table_args__ = (
        UniqueConstraint("book_id", "kind", "input_hash", name="uq_llm_caches_book_kind_hash"),
    )