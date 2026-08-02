"""书籍服务：跨仓储与文件系统的编排（保持 API 层薄）。"""
import shutil
from pathlib import Path

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.models.activity import Bookmark, ChatMessage, Note, ReadingLog
from app.models.asset import BookAsset
from app.models.graph import BookRelation, KnowledgePoint
from app.repositories import books as repo


def _remove_book_files(file_path: Path) -> None:
    """删除书籍文件与媒体资源：新布局（<root>/<file_id>/）删除整个子目录；旧扁平布局尽力清理独立文件。"""
    if not file_path.exists():
        return
    parent = file_path.parent
    if parent.name == file_path.stem:
        shutil.rmtree(parent, ignore_errors=True)
        return
    for candidate in (file_path, parent / "cover.jpg", parent / "pages", parent / "annotations"):
        try:
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
            else:
                candidate.unlink(missing_ok=True)
        except OSError:
            pass


def delete_book(db: Session, book_id: int) -> bool:
    """删除书籍：先清理引用章节/书籍的子表（部分外键无 CASCADE，直接删书会触发外键冲突），
    再删除书籍记录与磁盘文件；返回是否删除成功。"""
    book = repo.get_book(db, book_id)
    if not book:
        return False
    file_path = Path(book.file_path)
    db.execute(delete(ChatMessage).where(ChatMessage.ref_book_id == book_id))
    db.execute(delete(ReadingLog).where(ReadingLog.book_id == book_id))
    db.execute(delete(Bookmark).where(Bookmark.book_id == book_id))
    db.execute(delete(Note).where(Note.book_id == book_id))
    db.execute(delete(BookAsset).where(BookAsset.book_id == book_id))
    db.execute(delete(KnowledgePoint).where(KnowledgePoint.book_id == book_id))
    db.execute(delete(BookRelation).where(or_(BookRelation.book_a_id == book_id, BookRelation.book_b_id == book_id)))
    if repo.delete_book(db, book_id):
        _remove_book_files(file_path)
    return True
