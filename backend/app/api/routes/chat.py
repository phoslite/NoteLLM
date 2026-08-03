"""聊天 API：按章节上下文流式问答（SSE）+ 对话历史（编排见 chat_service）。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.factory import is_configured
from app.api.deps import require_book
from app.core.database import get_db
from app.schemas.common import ok
from app.schemas.serializers import chat_message_to_dict
from app.services.chat_service import (
    clear_history,
    list_history,
    prepare_chat_job,
    resolve_chat_chapter,
    stream_chat,
)

router = APIRouter(prefix="/api/books", tags=["chat"])


class ChatIn(BaseModel):
    question: str
    chapter_id: int | None = None
    selection: str | None = None
    # 涂鸦划线提问：划线区域裁剪图（data URI，chat 模式）与划线描述文本
    crop_image: str | None = None
    crop_label: str | None = None


@router.post("/{book_id}/chat")
def chat_stream(book_id: int, body: ChatIn, db: Session = Depends(get_db)):
    """按当前章节上下文问答，返回 SSE 流（text/event-stream）。"""
    book = require_book(db, book_id)
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if not is_configured(db):
        raise HTTPException(status_code=400, detail="未配置 AI API Key，请先在设置页填写")

    chapters, chapter = resolve_chat_chapter(db, book_id, body.chapter_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="本书没有可解析的章节")
    if body.chapter_id is not None and chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter is None:
        chapter = chapters[0]

    job = prepare_chat_job(
        db, book, chapter, question, body.selection or "", body.crop_image, body.crop_label or ""
    )
    return StreamingResponse(
        stream_chat(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{book_id}/chat/messages")
def list_chat_messages(book_id: int, db: Session = Depends(get_db)):
    """读取本书对话历史（按时间正序）。"""
    require_book(db, book_id)
    return ok([chat_message_to_dict(m) for m in list_history(db, book_id)])


@router.delete("/{book_id}/chat/messages")
def clear_chat_messages(book_id: int, db: Session = Depends(get_db)):
    """清空本书对话历史。"""
    require_book(db, book_id)
    clear_history(db, book_id)
    return ok(None, "已清空")