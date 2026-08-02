"""聊天 API：按章节上下文流式问答（SSE）+ 对话历史。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.factory import build_client, is_configured
from app.api.deps import require_book
from app.core.config import settings
from app.core.database import get_db
from app.repositories import books as book_repo
from app.repositories.assets import load_skills, retrieve_rag_chunks
from app.repositories.chat import clear_messages, list_messages
from app.repositories.settings import load_ai_overrides, vision_configured
from app.schemas.common import ok
from app.schemas.serializers import chat_message_to_dict
from app.services.ai_context import build_page_context_block, page_image_data_uri
from app.services.chat_service import build_messages, stream_chat
from app.services.vision_extract import ensure_window_caches

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

    chapters = book_repo.list_chapters(db, book_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="本书没有可解析的章节")
    chapter = next((c for c in chapters if c.id == body.chapter_id), None)
    if body.chapter_id is not None and chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter is None:
        chapter = chapters[0]

    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    send_page = overrides.get("ai_send_page_image", settings.ai_send_page_image)
    page_mode = chapter.page_index is not None
    page_context = None
    page_image = None
    if page_mode and enable_body:
        # PDF 按页阅读：优先注入 [P-1,P,P+1] 窗口页缓存文本；未配置多模态/提取失败时回退当前页原图附件。
        if vision_configured(db):
            try:
                window = ensure_window_caches(db, book, chapter.page_index)
                page_context = build_page_context_block(window, enable_body)
            except Exception:  # noqa: BLE001 提取失败回退页图附件
                page_context = None
        if page_context is None:
            page_image = page_image_data_uri(book, chapter, enable_body and send_page)
    else:
        page_image = page_image_data_uri(book, chapter, enable_body and send_page)
    crop_image = body.crop_image if (enable_body and body.crop_image) else None
    rag_chunks = retrieve_rag_chunks(db, book_id, question)
    skills = load_skills(db, book_id)
    messages = build_messages(
        book,
        chapter,
        question,
        body.selection or "",
        rag_chunks,
        skills,
        enable_body,
        page_image,
        crop_image,
        body.crop_label or "",
        page_context,
        page_mode,
    )
    client = build_client(db)
    job = {
        "client": client,
        "messages": messages,
        "persist": {
            "book_id": book_id,
            "chapter_id": chapter.id,
            "selection": body.selection or "",
            "question": question,
        },
    }
    return StreamingResponse(
        stream_chat(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{book_id}/chat/messages")
def list_chat_messages(book_id: int, db: Session = Depends(get_db)):
    """读取本书对话历史（按时间正序）。"""
    require_book(db, book_id)
    return ok([chat_message_to_dict(m) for m in list_messages(db, book_id)])


@router.delete("/{book_id}/chat/messages")
def clear_chat_messages(book_id: int, db: Session = Depends(get_db)):
    """清空本书对话历史。"""
    require_book(db, book_id)
    clear_messages(db, book_id)
    return ok(None, "已清空")