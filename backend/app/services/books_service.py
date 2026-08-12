"""书籍服务：跨仓储与文件系统的编排（保持 API 层薄）。"""
import shutil
from pathlib import Path

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.activity import Bookmark, ChatMessage, Note, ReadingLog
from app.models.graph import BookRelation, KnowledgePoint
from app.repositories import books as repo
from app.repositories.assets import delete_assets


def clean_tags(raw_tags: list[str]) -> list[str]:
    """清洗书籍 tag：去除首尾空白/空值/重复，保留用户输入原样（含连字符等标点）。

    说明（E2E M-2，2026-08-11）：手动 tag 原样保留、与展示一致；聚类消费端
    （clustering.py 的 book_tags）在生成簇名时再按聚类规范清洗，互不影响。
    """

    seen: list[str] = []
    for raw in raw_tags:
        clean = raw.strip()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


def _remove_book_files(file_path: Path) -> None:
    """删除书籍文件与媒体资源：新布局（<root>/<file_id>/）删除整个子目录；旧扁平布局尽力清理独立文件。"""
    if not file_path.exists():
        return
    parent = file_path.parent
    # 审查 P2 加固：仅当父目录是书籍根目录的直接子目录（新布局 <books_root>/<file_id>/<file_id><suffix>）
    # 且目录名与文件主名一致时才 rmtree 父目录；防止极端布局（如书库根目录名恰等于书文件主名）误删整个书库
    books_root = settings.data_dir / "books"
    if parent.name == file_path.stem and parent.parent == books_root:
        shutil.rmtree(parent, ignore_errors=True)
        return
    for candidate in (file_path, parent / "cover.jpg", parent / "pages", parent / "pages_vlm", parent / "annotations"):
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
    # P2 接线（2026-08-11）：删书后失效会话挑选缓存，避免回放已删书的挑选结果
    try:
        from app.services.rag_router import clear_session_cache

        clear_session_cache()
    except Exception:  # noqa: BLE001 缓存清理失败不阻塞删除
        pass
    file_path = Path(book.file_path)
    db.execute(delete(ChatMessage).where(ChatMessage.ref_book_id == book_id))
    db.execute(delete(ReadingLog).where(ReadingLog.book_id == book_id))
    db.execute(delete(Bookmark).where(Bookmark.book_id == book_id))
    db.execute(delete(Note).where(Note.book_id == book_id))
    delete_assets(db, book_id)  # 共享资产：主书转移/成员解除引用后删除
    db.execute(delete(KnowledgePoint).where(KnowledgePoint.book_id == book_id))
    db.execute(delete(BookRelation).where(or_(BookRelation.book_a_id == book_id, BookRelation.book_b_id == book_id)))
    if repo.delete_book(db, book_id):
        _remove_book_files(file_path)
    return True
