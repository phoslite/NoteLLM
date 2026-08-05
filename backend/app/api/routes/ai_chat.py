"""主页全局 AI 对话 API（决策 37）：不绑定书籍/章节，SSE 流式问答 + 历史读写。

编排见 chat_service.prepare_global_job；会话键 `global:{session_id}`（前端生成）。
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.factory import is_configured
from app.core.database import get_db
from app.schemas.common import ok
from app.schemas.serializers import chat_message_to_dict
from app.services.chat_service import (
    clear_global_history,
    list_global_history,
    prepare_global_job,
    stream_chat,
)
from app.services.rag_router import clear_global_selection_cache

router = APIRouter(prefix="/api/ai", tags=["ai-chat"])


class GlobalChatIn(BaseModel):
    question: str
    # 会话标识（决策 37）：前端每次打开全局 AI 面板生成；历史与挑选缓存共用
    session_id: str | None = None
    # 方案2 流式滚动落库键（同书级对话）
    stream_key: str | None = None


@router.post("/chat")
def global_chat_stream(body: GlobalChatIn, db: Session = Depends(get_db)):
    """主页全局 AI 对话，返回 SSE 流（text/event-stream）。"""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if not is_configured(db):
        raise HTTPException(status_code=400, detail="未配置 AI API Key，请先在设置页填写")
    job = prepare_global_job(db, question, body.session_id, body.stream_key)
    return StreamingResponse(
        stream_chat(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/messages")
def list_global_messages(session_id: str, db: Session = Depends(get_db)):
    """读取全局对话历史（session_id 为前端生成的面板会话标识）。"""
    return ok([chat_message_to_dict(m) for m in list_global_history(db, session_id)])


@router.delete("/chat/messages")
def clear_global_messages(session_id: str, db: Session = Depends(get_db)):
    """清空全局对话历史。"""
    clear_global_history(db, session_id)
    return ok(None, "已清空")


@router.delete("/chat/session")
def delete_global_session(session_id: str, db: Session = Depends(get_db)):
    """删除主页全局会话：清空对话历史 + 清除该会话的挑选缓存（需求 v1.73）。"""
    clear_global_history(db, session_id)
    clear_global_selection_cache(session_id)
    return ok(None, "已删除会话")
