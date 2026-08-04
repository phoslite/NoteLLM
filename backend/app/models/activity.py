"""阅读活动模型：进度、笔记、对话消息。"""
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utcnow


class ReadingLog(Base):
    __tablename__ = "reading_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True, index=True)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True, index=True)
    quote_text: Mapped[str] = mapped_column(Text, default="")
    note_text: Mapped[str] = mapped_column(Text, default="")
    note_type: Mapped[str] = mapped_column(String(20), default="高亮")  # 高亮/批注/思考/不理解
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Bookmark(Base):
    """位置书签：任意格式书籍均可保存，PDF 为整页、文本书为章节+段落。"""

    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True, index=True)
    page_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # PDF 整页书签

    __table_args__ = (Index("ix_bookmarks_book_created", "book_id", "created_at"),)  # 书签列表按时间倒序（性能优化第一梯队）
    para_pos: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 文本书：段落位置
    title: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    group_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user/assistant
    content: Mapped[str] = mapped_column(Text, default="")
    ref_book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True, index=True)
    ref_chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True, index=True)
    ref_para_pos: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 出处标注
    created_at: Mapped[datetime] = mapped_column(default=utcnow)