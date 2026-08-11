"""书籍/章节/文件夹数据访问层。"""

import json

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.book import Book, Chapter, Folder


def list_books(db: Session, folder_id: int | None = None, q: str | None = None) -> list[Book]:
    """书架列表：按 position 升序（同位置回退创建时间倒序）；q 搜索书名/作者/tag。"""
    stmt = select(Book).options(selectinload(Book.chapters)).order_by(
        Book.position.asc(), Book.created_at.desc()
    )
    if folder_id is not None:
        stmt = stmt.where(Book.folder_id == folder_id)
    if q and q.strip():
        keyword = q.strip()
        stmt = stmt.where(
            or_(
                Book.title.contains(keyword),
                Book.author.contains(keyword),
                Book.tags_json.contains(keyword),
            )
        )
    return list(db.scalars(stmt))


def get_book(db: Session, book_id: int) -> Book | None:
    return db.get(Book, book_id)


def book_tags(book: Book) -> list[str]:
    """读取书籍 tag 列表（tags_json 反序列化）。"""
    try:
        tags = json.loads(book.tags_json or "[]")
    except (ValueError, TypeError):
        return []
    return tags if isinstance(tags, list) else []


def create_book_with_chapters(
    db: Session,
    chapters: list[tuple[int, str, str, int | None]],
    word_counts: list[int] | None = None,
    **kwargs,
) -> Book:
    """新建书籍并批量写入章节（m-6 修复）：单事务一次提交，任一步失败整体回滚。

    import 链路「建书-写章」原为两次独立提交——create_book 先 commit 后 add_chapters
    失败会留下孤儿书行（有行无文件）；合并为单事务后失败即无残留，
    同时消除「commit 后 refresh」的重复。
    """
    if "position" not in kwargs:
        top = db.scalar(select(func.max(Book.position)))
        kwargs["position"] = int(top or 0) + 1
    book = Book(**kwargs)
    db.add(book)
    db.flush()  # 取得 book.id，尚未提交（失败整体回滚）
    for i, (index, title, content, page_index) in enumerate(chapters):
        db.add(
            Chapter(
                book_id=book.id,
                index=index,
                title=title,
                content_text=content,
                page_index=page_index,
                word_count=word_counts[i] if word_counts is not None else len(content),
            )
        )
    db.commit()
    db.refresh(book)
    return book


def update_book(
    db: Session,
    book_id: int,
    title: str | None = None,
    author: str | None = None,
    status: str | None = None,
    progress: float | None = None,
    folder_id: int | None = None,
    tags: list[str] | None = None,
    position: int | None = None,
) -> Book | None:
    """按字段更新书籍；tags 以 JSON 文本存储。返回 None 表示书籍不存在。"""
    book = db.get(Book, book_id)
    if not book:
        return None
    if title is not None:
        book.title = title
    if author is not None:
        book.author = author
    if status is not None:
        book.status = status
    if progress is not None:
        book.progress = progress
    if folder_id is not None:
        book.folder_id = folder_id
    if tags is not None:
        book.tags_json = json.dumps(tags, ensure_ascii=False)
    if position is not None:
        book.position = int(position)
    db.commit()
    db.refresh(book)
    return book


def delete_book(db: Session, book_id: int) -> bool:
    book = db.get(Book, book_id)
    if not book:
        return False
    db.delete(book)
    db.commit()
    return True


def list_chapters(db: Session, book_id: int) -> list[Chapter]:
    return list(db.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index)))


def reorder_books(db: Session, ordered_ids: list[int]) -> None:
    """按给定顺序批量重排书架（position = 1..N）；不存在的 id 忽略。"""
    books = {b.id: b for b in db.scalars(select(Book).where(Book.id.in_(ordered_ids)))}
    for pos, book_id in enumerate(ordered_ids, start=1):
        book = books.get(book_id)
        if book:
            book.position = pos
    db.commit()


def list_folders(db: Session) -> list[Folder]:
    return list(db.scalars(select(Folder).order_by(Folder.created_at)))


def create_folder(db: Session, name: str, parent_id: int | None = None) -> Folder:
    folder = Folder(name=name, parent_id=parent_id)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def rename_folder(db: Session, folder_id: int, name: str) -> Folder | None:
    folder = db.get(Folder, folder_id)
    if not folder:
        return None
    folder.name = name
    db.commit()
    db.refresh(folder)
    return folder


def delete_folder(db: Session, folder_id: int) -> bool:
    """删除文件夹，其中书籍转为未归类（folder_id=None）。"""
    folder = db.get(Folder, folder_id)
    if not folder:
        return False
    for book in db.scalars(select(Book).where(Book.folder_id == folder_id)):
        book.folder_id = None
    db.delete(folder)
    db.commit()
    return True
