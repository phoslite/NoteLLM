"""ChatMessage 仓储：按书会话读写对话历史。"""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.activity import ChatMessage


def chat_session_id(book_id: int) -> str:
    """本书对话会话 ID（历史落库与查询共用同一约定）。"""
    return f"book:{book_id}"


def list_messages(db: Session, book_id: int) -> list[ChatMessage]:
    """读取本书对话历史（按时间正序）。"""
    return list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session_id(book_id))
            .order_by(ChatMessage.id)
        )
    )


def clear_messages(db: Session, book_id: int) -> None:
    """清空本书对话历史。"""
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == chat_session_id(book_id)))
    db.commit()


def persist_chat(db: Session, book_id: int, chapter_id: int, selection: str, question: str, answer: str) -> None:
    """写入一条用户消息与一条助手消息（按书会话）。"""
    db.add(
        ChatMessage(
            session_id=chat_session_id(book_id),
            role="user",
            content=question,
            ref_book_id=book_id,
            ref_chapter_id=chapter_id,
            ref_para_pos=selection or None,
        )
    )
    db.add(
        ChatMessage(
            session_id=chat_session_id(book_id),
            role="assistant",
            content=answer,
            ref_book_id=book_id,
            ref_chapter_id=chapter_id,
            ref_para_pos=selection or None,
        )
    )
    db.commit()
