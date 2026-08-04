"""知识图谱模型：书籍关联、知识点、知识点关系。"""
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utcnow


class BookRelation(Base):
    __tablename__ = "book_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_a_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    book_b_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    strength: Mapped[float] = mapped_column(Float, default=0.0)  # 0~100
    direction: Mapped[str] = mapped_column(String(20), default="无")  # 无/承接/发展/批判
    from_book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=True, index=True)  # 有向边理论源头（无方向为 NULL）
    relation_type: Mapped[str] = mapped_column(String(50), default="主题相似")  # 主题相似/概念共现/理论传承/应用扩展
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    user_feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 确认/忽略/修改
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True, index=True)
    para_pos: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 段落位置
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[int] = mapped_column(Integer, default=1)  # 1~5
    level: Mapped[str] = mapped_column(String(20), default="章节级")  # 章节级/重要段落/用户标记
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class KpRelation(Base):
    __tablename__ = "kp_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    to_kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(30), default="前置依赖")  # 前置依赖/总分/承接/并列
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")