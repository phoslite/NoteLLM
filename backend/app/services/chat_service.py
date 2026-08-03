"""按章节上下文问答服务（M4）。

职责：
- 把「当前章节 + 用户选中内容 + 问题」组织为带段落编号的上下文（隐私开关控制是否发正文）；
- 组装 RAG 片段与 Skill 注入（检索/引用解析等共享逻辑见 `ai_context`）；
- 调用 LLMClient.stream() 产出 SSE 事件流，结束后将对话写入 ChatMessage 历史。
"""
import json
from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.ai.client import LLMError
from app.ai.factory import build_client
from app.ai.prompts.chat import build_system_prompt, build_user_prompt
from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories import books as book_repo
from app.repositories.assets import load_skills, retrieve_rag_chunks
from app.repositories.chat import clear_messages, list_messages, persist_chat, recent_history_texts
from app.repositories.settings import load_ai_overrides, vision_configured
from app.services.ai_context import (
    build_context_block,
    build_page_context_block,
    page_image_data_uri,
)
from app.services.citations import extract_citations
from app.services.profile_service import get_all_profiles
from app.services.vision_extract import ensure_window_caches


def build_messages(
    book,
    chapter,
    question: str,
    selection: str,
    rag_chunks: list[dict],
    skills: list[dict],
    enable_body_send: bool,
    page_image: str | None = None,
    crop_image: str | None = None,
    crop_label: str = "",
    page_context: str | None = None,
    page_mode: bool = False,
    mode: str | None = None,
    history: list[dict] | None = None,
    profiles: dict | None = None,
) -> list[dict]:
    """构建 LLM messages；隐私开关关闭时不发送正文、页缓存与 RAG 片段。

    - page_context：PDF 按页阅读时注入 `[P-1,P,P+1]` 窗口的页缓存文本（出处「第 X 页」）；
      提供时跳过章节正文与 RAG 片段（页上下文已足够，避免章节式引用混淆）。
    - page_image：页缓存不可用时的回退——附加当前页原图（chat 模式，需模型支持视觉输入）。
    - crop_image：涂鸦划线区域裁剪图（data URI，chat 模式）；划线提问时用 crop_label 说明范围。
    - responses 模式由客户端降级为纯文本。
    """
    context_text, rag_block = build_context_block(chapter, rag_chunks, enable_body_send)
    if page_context:
        rag_block = ""
    user = build_user_prompt(
        book.title,
        chapter.index,
        chapter.title,
        context_text,
        rag_block,
        selection or "",
        question,
        page_context=page_context,
    )
    messages: list[dict] = [
        {
            "role": "system",
            "content": build_system_prompt(skills, page_mode=page_mode, mode=mode, profiles=profiles),
        }
    ]
    if history:
        messages.extend(history)
    images = [img for img in (page_image, crop_image) if img]
    if images and enable_body_send:
        content: list[dict] = [{"type": "text", "text": user}]
        if crop_label:
            content.append({"type": "text", "text": f"（用户划线的区域说明：{crop_label}）"})
        for img in images:
            # SiliconFlow 多模态文档：image_url 参数 url（支持 base64 data URI）+ detail（auto/low/high）
            content.append({"type": "image_url", "image_url": {"url": img, "detail": "high"}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user})
    return messages


def resolve_chat_chapter(db: Session, book_id: int, chapter_id: int | None) -> tuple[list, object | None]:
    """解析对话目标章节：返回 (chapters, chapter)；章节不存在或未指定时由调用方处理。"""
    chapters = book_repo.list_chapters(db, book_id)
    if not chapters:
        return [], None
    chapter = None
    if chapter_id is not None:
        chapter = next((c for c in chapters if c.id == chapter_id), None)
    return chapters, chapter


def prepare_chat_job(
    db: Session,
    book,
    chapter,
    question: str,
    selection: str = "",
    crop_image: str | None = None,
    crop_label: str = "",
    mode: str | None = None,
) -> dict:
    """组装一次对话请求任务：隐私/视觉覆盖、页缓存窗口或页图附件、RAG/Skill、messages、client。

    - PDF 按页阅读且隐私开启：优先注入 [P-1,P,P+1] 窗口页缓存；未配置多模态/提取失败回退页图附件。
    - crop_image：涂鸦划线区域裁剪图（chat 模式，需模型支持视觉输入）。
    """
    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    send_page = overrides.get("ai_send_page_image", settings.ai_send_page_image)
    page_mode = chapter.page_index is not None
    page_context = None
    page_image = None
    if page_mode and enable_body:
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
    rag_chunks = retrieve_rag_chunks(db, book.id, question)
    skills = load_skills(db, book.id, task_text=question)
    profiles = get_all_profiles(db) if enable_body else None
    history = None
    if enable_body:
        history = recent_history_texts(db, book.id, mode)
    messages = build_messages(
        book,
        chapter,
        question,
        selection,
        rag_chunks,
        skills,
        enable_body,
        page_image,
        crop_image if (enable_body and crop_image) else None,
        crop_label,
        page_context,
        page_mode,
        mode,
        history,
        profiles,
    )
    return {
        "client": build_client(db),
        "messages": messages,
        "persist": {
            "book_id": book.id,
            "chapter_id": chapter.id,
            "selection": selection,
            "question": question,
            "mode": mode,
        },
    }


def list_history(db: Session, book_id: int, mode: str | None = None) -> list:
    """读取本书指定会话的对话历史（按时间正序）。"""
    return list_messages(db, book_id, mode)


def clear_history(db: Session, book_id: int, mode: str | None = None) -> None:
    """清空本书指定会话的对话历史。"""
    clear_messages(db, book_id, mode)


def stream_chat(job: dict) -> Iterator[str]:
    """对话 SSE 事件生成器：data 行为 JSON 事件 {type: start/delta/end/error}。

    job 由路由预构建（含 client/messages/persist），确保 LLM 调用前的校验在请求作用域内完成。
    """
    yield _sse({"type": "start"})
    full = ""
    try:
        for delta in job["client"].stream(job["messages"]):
            full += delta
            yield _sse({"type": "delta", "text": delta})
    except LLMError as exc:
        yield _sse({"type": "error", "message": str(exc)})
        return
    yield _sse({"type": "end", "text": full, "citations": extract_citations(full)})
    # 历史落库使用独立会话，避免请求级会话在流式期间被关闭
    try:
        db = SessionLocal()
        try:
            persist_chat(
                db,
                book_id=job["persist"]["book_id"],
                chapter_id=job["persist"]["chapter_id"],
                selection=job["persist"]["selection"],
                question=job["persist"]["question"],
                mode=job["persist"].get("mode"),
                answer=full,
            )
        finally:
            db.close()
    except Exception:  # noqa: BLE001 历史落库失败不影响已输出的回答
        pass


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
