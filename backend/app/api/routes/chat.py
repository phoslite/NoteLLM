"""聊天 API：按章节上下文流式问答（SSE）+ 对话历史（编排见 chat_service）。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.factory import is_configured
from app.api.deps import require_book
from app.core.database import get_db
from app.repositories.chat import persist_chat
from app.schemas.common import ok
from app.schemas.serializers import chat_message_to_dict
from app.services.chat_service import (
    build_mode_cache_key,
    clear_history,
    list_history,
    mode_cache_hit,
    prepare_chat_job,
    resolve_chat_chapter,
    sse_event,
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
    # 预设能力模式：解读 / 概论 / 思考逻辑（附加结构化 system 模板）
    mode: str | None = None


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

    # 预设模式问答缓存（性能优化 §7 决策 5）：同书同章同提问/选区命中时直接回放完整回答
    cache_key_val = build_mode_cache_key(db, book, chapter, question, body.selection or "", body.mode)
    hit = mode_cache_hit(db, book.id, body.mode or "", cache_key_val)
    if hit is not None:
        try:
            persist_chat(
                db, book.id, chapter.id, body.selection or "", question, hit["answer"], body.mode
            )
        except Exception:  # noqa: BLE001 历史落库失败不影响回放
            pass
        end_event = sse_event({
            "type": "end",
            "text": hit["answer"],
            "citations": hit.get("citations") or [],
            "cached": True,
        })
        return StreamingResponse(
            iter([end_event]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    job = prepare_chat_job(
        db, book, chapter, question, body.selection or "", body.crop_image, body.crop_label or "", body.mode
    )
    cache_meta = {"book_id": book.id, "kind": body.mode, "key": cache_key_val} if cache_key_val else None
    return StreamingResponse(
        stream_chat(job, cache_meta),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{book_id}/chat/messages")
def list_chat_messages(book_id: int, mode: str | None = None, db: Session = Depends(get_db)):
    """读取本书指定会话的对话历史（mode 为空=默认对话；解读/概论/思考逻辑为能力模式分池）。"""
    require_book(db, book_id)
    return ok([chat_message_to_dict(m) for m in list_history(db, book_id, mode)])


@router.delete("/{book_id}/chat/messages")
def clear_chat_messages(book_id: int, mode: str | None = None, db: Session = Depends(get_db)):
    """清空本书指定会话的对话历史。"""
    require_book(db, book_id)
    clear_history(db, book_id, mode)
    return ok(None, "已清空")
