"""ChatMessage 仓储：按「书 × 能力模式」会话读写对话历史。

会话键约定（决策 30）：
- 默认对话：`book:{book_id}`（兼容旧数据）；
- 能力模式：`book:{book_id}:{mode}`（解读 / 概论 / 思考逻辑分池，任务类型互相隔离）。

历史保留策略（性能优化决策 1，docs/性能优化路径.md §7）：
每会话只保留最近 `chat_history_limit` 条（默认 200，.env 可配，0=不限制），
写入后顺带裁剪；用户也可手动清空（DELETE /api/books/{id}/chat/messages）。
"""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.activity import ChatMessage


def chat_session_id(book_id: int, mode: str | None = None) -> str:
    """本书对话会话 ID（历史落库与查询共用同一约定）。

    mode 为空 / None / 空白时返回 `book:{book_id}`（默认对话，兼容旧数据）；
    否则返回 `book:{book_id}:{mode}`（能力模式分池）。
    """
    mode = (mode or "").strip()
    if not mode:
        return f"book:{book_id}"
    return f"book:{book_id}:{mode}"


def list_messages(db: Session, book_id: int, mode: str | None = None) -> list[ChatMessage]:
    """读取本书指定会话的对话历史（按时间正序）。"""
    return list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session_id(book_id, mode))
            .order_by(ChatMessage.id)
        )
    )


def trim_history(db: Session, session_id: str, limit: int | None = None) -> int:
    """裁剪会话历史：保留最近 limit 条（默认取 settings.chat_history_limit；0/None 表示不限制）。

    返回删除条数；在 persist_chat 后调用，本地单用户默认每会话 200 条封顶，
    既控制库体积也让历史注入窗口（recent_history_texts 已按 max_rounds/max_chars 截断）保持稳定。
    """
    if limit is None:
        limit = settings.chat_history_limit
    if not limit or limit <= 0:
        return 0
    extra_ids = list(
        db.scalars(
            select(ChatMessage.id)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .offset(limit)
            .limit(1000)
        )
    )
    if not extra_ids:
        return 0
    db.execute(delete(ChatMessage).where(ChatMessage.id.in_(extra_ids)))
    db.commit()
    return len(extra_ids)


def list_recent_messages(db: Session, book_id: int, limit: int = 20) -> list[ChatMessage]:
    """本书最近对话（按 ref_book_id）：时间倒序取最近 limit 条，返回时按时间正序。"""
    rows = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.ref_book_id == book_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    )
    return list(reversed(rows))


def recent_history_texts(
    db: Session,
    book_id: int,
    mode: str | None = None,
    max_rounds: int = 10,
    max_chars: int = 8000,
) -> list[dict]:
    """最近 N 轮对话（按会话）作为 LLM 多轮上下文。

    - 按 `max_rounds` 轮（每轮 user+assistant 两条）取最近记录；
    - 按字符预算 `max_chars` 从**新到旧**选择、保留最近部分，返回时间正序的
      `[{"role", "content"}]` 列表，供注入 `build_messages`。
    """
    rows = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session_id(book_id, mode))
            .order_by(ChatMessage.id.desc())
            .limit(max_rounds * 2)
        )
    )
    selected: list[ChatMessage] = []
    used = 0
    for row in rows:  # 新 → 旧
        cost = len(row.content)
        if selected and used + cost > max_chars:
            break
        selected.append(row)
        used += cost
    selected.reverse()
    return [{"role": r.role, "content": r.content} for r in selected]


def clear_messages(db: Session, book_id: int, mode: str | None = None) -> None:
    """清空本书指定会话的对话历史。"""
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == chat_session_id(book_id, mode)))
    db.commit()


def persist_chat(
    db: Session,
    book_id: int,
    chapter_id: int,
    selection: str,
    question: str,
    answer: str,
    mode: str | None = None,
) -> None:
    """写入一条用户消息与一条助手消息（按书 × 模式会话）。"""
    db.add(
        ChatMessage(
            session_id=chat_session_id(book_id, mode),
            role="user",
            content=question,
            ref_book_id=book_id,
            ref_chapter_id=chapter_id,
            ref_para_pos=selection or None,
        )
    )
    db.add(
        ChatMessage(
            session_id=chat_session_id(book_id, mode),
            role="assistant",
            content=answer,
            ref_book_id=book_id,
            ref_chapter_id=chapter_id,
            ref_para_pos=selection or None,
        )
    )
    db.commit()
    trim_history(db, chat_session_id(book_id, mode))  # 性能决策 1：只留最近 N 条（0=不限制）