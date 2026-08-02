"""按章节上下文问答服务（M4）。

职责：
- 把「当前章节 + 用户选中内容 + 问题」组织为带段落编号的上下文（隐私开关控制是否发正文）；
- 组装 RAG 片段与 Skill 注入（检索/引用解析等共享逻辑见 `ai_context`）；
- 调用 LLMClient.stream() 产出 SSE 事件流，结束后将对话写入 ChatMessage 历史。
"""
import json
from collections.abc import Iterator

from app.ai.client import LLMError
from app.ai.prompts.chat import build_system_prompt, build_user_prompt
from app.core.database import SessionLocal
from app.repositories.chat import persist_chat
from app.services.ai_context import build_context_block
from app.services.citations import extract_citations


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
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(skills, page_mode=page_mode)}]
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
                answer=full,
            )
        finally:
            db.close()
    except Exception:  # noqa: BLE001 历史落库失败不影响已输出的回答
        pass


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
