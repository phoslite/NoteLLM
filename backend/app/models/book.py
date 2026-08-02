"""书籍域模型：文件夹、书籍、章节。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.time import utcnow


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    children: Mapped[list["Folder"]] = relationship(back_populates="parent")
    parent: Mapped[Optional["Folder"]] = relationship(back_populates="children", remote_side=[id])


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cover: Mapped[str | None] = mapped_column(String(500), nullable=True)
    format: Mapped[str] = mapped_column(String(10))  # pdf/md/txt/epub
    file_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="未读")  # 未读/在读/读完
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    total_chapters: Mapped[int] = mapped_column(Integer, default=0)
    is_scanned: Mapped[bool] = mapped_column(default=False)  # 扫描版 PDF：按原始页读图
    page_count: Mapped[int] = mapped_column(Integer, default=0)  # 原始 PDF 页数
    graph_built: Mapped[bool] = mapped_column(default=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")  # 用户分类 tag 列表
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # 书架排序位（拖拽换位持久化）
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_opened_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # 聚类落盘（两阶段分类 §9.5）：post-classify 后验归属与版本/时间戳
    cluster_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    classify_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # tag/folder/pre/post
    classified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    classify_version: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 资产 version，失效判定用

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Chapter.index"
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    content_text: Mapped[str] = mapped_column(Text, default="")
    page_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 扫描版：原始 PDF 页号
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    read_flag: Mapped[bool] = mapped_column(default=False)

    book: Mapped["Book"] = relationship(back_populates="chapters")