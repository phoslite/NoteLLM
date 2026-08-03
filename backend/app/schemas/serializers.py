"""实体 → 响应 dict 的统一序列化（各路由不再各自 _to_out，避免重复与漂移）。"""
import json

from app.models.activity import Bookmark, ChatMessage, Note, ReadingLog
from app.models.asset import BookAsset
from app.models.book import Book, Chapter, Folder


def book_to_dict(book: Book, read_chapters: int | None = None, latest_chapter: Chapter | None = None) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "format": book.format,
        "content_hash": book.content_hash,
        "status": book.status,
        "progress": book.progress,
        "total_chapters": book.total_chapters,
        "is_scanned": book.is_scanned,
        "page_count": book.page_count,
        "cover_url": f"/api/books/{book.id}/cover" if book.cover else None,
        "graph_built": book.graph_built,
        "tags": json.loads(book.tags_json or "[]"),
        "folder_id": book.folder_id,
        "position": book.position,
        "created_at": book.created_at.isoformat() if book.created_at else None,
        "last_opened_at": book.last_opened_at.isoformat() if book.last_opened_at else None,
        "chapter_count": len(book.chapters),
        "read_chapters": read_chapters if read_chapters is not None else 0,
        "latest_chapter": (
            {"index": latest_chapter.index, "title": latest_chapter.title} if latest_chapter else None
        ),
    }


def chapter_to_dict(chapter: Chapter) -> dict:
    return {
        "id": chapter.id,
        "index": chapter.index,
        "title": chapter.title,
        "page_index": chapter.page_index,
        "word_count": chapter.word_count,
        "read_flag": chapter.read_flag,
    }


def folder_to_dict(folder: Folder) -> dict:
    return {"id": folder.id, "name": folder.name, "parent_id": folder.parent_id}


def asset_to_dict(asset: BookAsset) -> dict:
    return {
        "kind": asset.kind,
        "content": json.loads(asset.content_json or "{}"),
        "version": asset.version,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }


def chapter_content_to_dict(chapter: Chapter) -> dict:
    return {
        "id": chapter.id,
        "index": chapter.index,
        "title": chapter.title,
        "content_text": chapter.content_text,
        "page_index": chapter.page_index,
        "word_count": chapter.word_count,
        "read_flag": chapter.read_flag,
    }


def bookmark_to_dict(bm: Bookmark) -> dict:
    return {
        "id": bm.id,
        "book_id": bm.book_id,
        "chapter_id": bm.chapter_id,
        "page_index": bm.page_index,
        "para_pos": bm.para_pos,
        "title": bm.title,
        "note": bm.note,
        "group_name": bm.group_name,
        "created_at": bm.created_at.isoformat() if bm.created_at else None,
    }


def note_to_dict(note: Note) -> dict:
    return {
        "id": note.id,
        "book_id": note.book_id,
        "chapter_id": note.chapter_id,
        "quote_text": note.quote_text,
        "note_text": note.note_text,
        "note_type": note.note_type,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


def chat_message_to_dict(msg: ChatMessage) -> dict:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "book_id": msg.ref_book_id,
        "chapter_id": msg.ref_chapter_id,
        "ref_para_pos": msg.ref_para_pos,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def progress_to_dict(book: Book, log: ReadingLog | None) -> dict:
    return {
        "chapter_id": log.chapter_id if log else None,
        "position": log.position if log else 0.0,
        "progress": book.progress,
        "status": book.status,
        "last_opened_at": book.last_opened_at.isoformat() if book.last_opened_at else None,
    }