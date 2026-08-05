"""按章节上下文问答服务（M4）。

职责：
- 把「当前章节 + 用户选中内容 + 问题」组织为带段落编号的上下文（隐私开关控制是否发正文）；
- 组装 RAG 片段与 Skill 注入（检索/引用解析等共享逻辑见 `ai_context`）；
- 调用 LLMClient.stream() 产出 SSE 事件流，结束后将对话写入 ChatMessage 历史。
"""
import json
import time
from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.ai.client import LLMError
from app.ai.factory import build_client
from app.ai.prompts.chat import build_system_prompt, build_user_prompt
from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories import books as book_repo
from app.repositories.chat import clear_messages, list_messages, persist_chat, recent_history_texts
from app.repositories.settings import load_ai_overrides, vision_configured
from app.services.ai_context import (
    build_page_context_block,
    paragraph_numbered,
)
from app.services.citations import extract_citations
from app.services.html_util import chapter_plain_text
from app.services.llm_cache import cache_key, chapter_fingerprint, get_llm_cache, set_llm_cache
from app.services.media_service import markdown_image_data_uris
from app.services.profile_service import get_all_profiles
from app.services.rag_router import select_knowledge
from app.services.vision_extract import ensure_window_caches, extract_image_attachment


def build_messages(
    book,
    chapter,
    question: str,
    selection: str,
    rag_block: str,
    skills: list[dict],
    enable_body_send: bool,
    crop_text: str | None = None,
    crop_label: str = "",
    page_context: str | None = None,
    page_mode: bool = False,
    mode: str | None = None,
    history: list[dict] | None = None,
    profiles: dict | None = None,
    media_texts: list[str] | None = None,
) -> list[dict]:
    """构建 LLM messages；隐私开关关闭时不发送正文、页缓存与 RAG 片段（Skill 仍注入）。

    - rag_block：跨书检索片段块（决策 34，出处【《书名》第X章 第Y段】），由调用方组装；
      PDF 页模式下与页缓存文本一同注入（页模式 RAG 注入已定稿）。
    - page_context：PDF 按页阅读时注入 `[P-1,P,P+1]` 窗口的页缓存文本（出处「第 X 页」）。
    - crop_text：划线裁剪图经视觉模型提取的文本（决策 36）；划线提问时用 crop_label 说明范围。
    - media_texts：Markdown 内嵌插图经视觉模型提取的文本列表（决策 36）。
    - 决策 36：主模型只收文本——所有图片附件由视觉模型提取为文本（带缓存），不再直发 image_url。
    """
    context_text = paragraph_numbered(chapter_plain_text(getattr(book, "format", None), chapter.content_text or "")) if enable_body_send else ""
    user = build_user_prompt(
        book.title,
        chapter.index,
        chapter.title,
        context_text,
        rag_block,
        selection or "",
        question,
        page_context=page_context,
        enable_body_send=enable_body_send,
        page_mode=page_mode,
    )
    messages: list[dict] = [
        {
            "role": "system",
            "content": build_system_prompt(skills, page_mode=page_mode, mode=mode, profiles=profiles),
        }
    ]
    if history:
        messages.extend(history)
    if enable_body_send:
        extra_blocks: list[str] = []
        if crop_text:
            label = f"（用户划线的区域说明：{crop_label}）" if crop_label else ""
            extra_blocks.append(f"【用户划线区域图片内容（视觉提取）】\n{crop_text}{label}")
        for i, t in enumerate(media_texts or [], 1):
            extra_blocks.append(f"【正文插图 {i} 内容（视觉提取）】\n{t}")
        if extra_blocks:
            user += "\n\n" + "\n\n".join(extra_blocks)
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


def _cross_book_rag_block(chunks: list[dict]) -> str:
    """跨书 chunks → 检索片段块：出处统一【《书名》第X章 第Y段】（决策 34）。"""
    return "\n".join(
        f"【《{c.get('book_title', '')}》第{c['chapter_index']}章 第{c.get('para_pos', '-')}段】{c.get('text', '')}"
        for c in chunks
    )


def prepare_chat_job(
    db: Session,
    book,
    chapter,
    question: str,
    selection: str = "",
    crop_image: str | None = None,
    crop_label: str = "",
    mode: str | None = None,
    session_id: str | None = None,
    stream_key: str | None = None,
) -> dict:
    """组装一次对话请求任务：隐私/视觉覆盖、页缓存窗口或页图附件、跨书 RAG/Skill、messages、client。

    - 跨书注入（决策 34）：LLM 自主挑选相关书与 Skill（会话内缓存按 session_id），
      降级回退规则方案；隐私关闭时只注入 Skill、不注入 chunks。
    - PDF 按页阅读且隐私开启：优先注入 [P-1,P,P+1] 窗口页缓存（决策 36：未配置视觉/提取失败
      不再回退直发页图，主模型只收文本）。
    - crop_image：划线裁剪图经视觉模型提取文本后注入（send_page 开启时）。
    """
    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    send_page = overrides.get("ai_send_page_image", settings.ai_send_page_image)
    page_mode = chapter.page_index is not None
    page_context = None
    # 决策 36：主模型只收文本——PDF 页模式优先注入 [P-1,P,P+1] 窗口页缓存文本
    # （视觉模型已提取并缓存，命中不重复调用）；未配置视觉/提取失败时不再回退直发页图。
    if page_mode and enable_body and vision_configured(db):
        try:
            window = ensure_window_caches(db, book, chapter.page_index)
            page_context = build_page_context_block(window, enable_body)
        except Exception:  # noqa: BLE001 提取失败仅降级为文本
            page_context = None
    knowledge = select_knowledge(
        db, book, chapter, question, selection, mode, session_id
    )
    rag_chunks = knowledge["chunks"] if enable_body else []
    skills = knowledge["skills"]
    profiles = get_all_profiles(db) if enable_body else None
    rag_block = _cross_book_rag_block(rag_chunks)
    history = None
    if enable_body:
        history = recent_history_texts(db, book.id, mode)
    # 决策 36：附件统一走视觉模型提取文本——划线裁剪图 / Markdown 插图（send_page 开启时）
    crop_text = None
    if enable_body and send_page and crop_image:
        try:
            crop_text = extract_image_attachment(
                db, crop_image, hint="用户划线的区域截图，请完整转录其中的文字与公式"
            )
        except Exception:  # noqa: BLE001 提取失败降级纯文本
            crop_text = None
    media_texts = None
    if enable_body and send_page and not page_mode and book.format in ("md", "txt", "epub"):
        try:
            uris = markdown_image_data_uris(book, chapter.content_text or "")
            media_texts = [
                t
                for t in (
                    extract_image_attachment(db, u, hint="正文插图，请完整描述其中的内容") for u in uris
                )
                if t
            ] or None
        except Exception:  # noqa: BLE001 单图失败不中断
            media_texts = None

    messages = build_messages(
        book,
        chapter,
        question,
        selection,
        rag_block,
        skills,
        enable_body,
        crop_text,
        crop_label,
        page_context,
        page_mode,
        mode,
        history,
        profiles,
        media_texts=media_texts,
    )
    # 发送前断言（审查 2-3）：隐私开启时正文不得携带「未发送」占位文案，占位符泄漏直接拦截
    if enable_body:
        user_content = messages[-1].get("content")
        leaked = isinstance(user_content, str) and "（正文未发送" in user_content
        if isinstance(user_content, list):
            leaked = leaked or any(
                isinstance(part, dict) and part.get("type") == "text"
                and "（正文未发送" in str(part.get("text", ""))
                for part in user_content
            )
        if leaked:
            raise RuntimeError("内部错误：正文占位符泄漏到 AI 请求，已拦截发送")
    return {
        "client": build_client(db),
        "messages": messages,
        "persist": {
            "book_id": book.id,
            "chapter_id": chapter.id,
            "selection": selection,
            "question": question,
            "mode": mode,
            "stream_key": stream_key,
        },
    }


CACHEABLE_MODES = ("解读", "概论", "思考逻辑")


def build_mode_cache_key(
    db: Session, book, chapter, question: str, selection: str, mode: str | None, session_id: str | None = None
) -> str | None:
    """预设模式问答的缓存键：仅对可缓存模式（解读/概论/思考逻辑）且缓存开启时返回 key，否则 None。

    key 覆盖：模式 + 提问 + 选区 + 章节内容指纹 + 隐私/页图开关 + 页模式 + 会话（决策 34 跨书挑选按会话变化），
    任一输入变化都会得到新 key（长正文只取指纹，不占 key 空间）。
    """
    if mode not in CACHEABLE_MODES or not settings.llm_cache_max_entries:
        return None
    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    send_page = overrides.get("ai_send_page_image", settings.ai_send_page_image)
    return cache_key({
        "mode": mode,
        "question": question,
        "selection": selection or "",
        "chapter": chapter.id,
        "content": chapter_fingerprint(chapter),
        "body": enable_body,
        "send_page": send_page,
        "page_index": chapter.page_index,
        "session": session_id or "",
    })


def mode_cache_hit(db: Session, book_id: int, mode: str, key: str | None) -> dict | None:
    """预设模式缓存命中：返回 {answer, citations}；未命中/关闭返回 None。"""
    if not key:
        return None
    content = get_llm_cache(db, book_id, mode, key)
    if content and "answer" in content:
        return content
    return None


STREAM_PERSIST_INTERVAL_S = 1.5  # 方案2：流式中滚动落库节流（前端固定频率轮询历史可见增量）


def sse_event(event: dict) -> str:
    """SSE data 事件行（chat 路由与流式生成器共用）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def replay_cached_chat(
    db: Session,
    book,
    chapter,
    question: str,
    selection: str,
    mode: str | None,
    cache_key_val: str | None,
) -> str | None:
    """预设模式缓存回放（审查 P0-4）：命中时清洗答案、落库历史并返回 SSE end 事件；未命中返回 None。

    路由只负责把事件包成 StreamingResponse；持久化与清洗编排收敛在本层。
    """
    if cache_key_val is None:
        return None
    hit = mode_cache_hit(db, book.id, mode or "", cache_key_val)
    if hit is None:
        return None
    answer = _sanitize_answer(hit.get("answer") or "")
    try:
        persist_chat(db, book.id, chapter.id, selection or "", question, answer, mode)
    except Exception:  # noqa: BLE001 历史落库失败不影响回放
        pass
    return sse_event({
        "type": "end",
        "text": answer,
        "citations": hit.get("citations") or [],
        "cached": True,
    })


def list_history(db: Session, book_id: int, mode: str | None = None) -> list:
    """读取本书指定会话的对话历史（按时间正序）。"""
    return list_messages(db, book_id, mode)


def clear_history(db: Session, book_id: int, mode: str | None = None) -> None:
    """清空本书指定会话的对话历史。"""
    clear_messages(db, book_id, mode)


def _sanitize_answer(text: str) -> str:
    """清洗 LLM 输出的转义引号（\" → "）：转义引号紧贴 ** 会破坏 markdown 加粗解析
    （如 **\"算法先于理论\"**），落库前统一还原，前端 MdRender 另有同款兜底。"""
    return text.replace('\\"', '"')


def stream_chat(job: dict, cache: dict | None = None) -> Iterator[str]:
    """对话 SSE 事件生成器：data 行为 JSON 事件 {type: start/thinking/delta/end/error}。

    job 由路由预构建（含 client/messages/persist），确保 LLM 调用前的校验在请求作用域内完成。
    cache: {book_id, kind, key} 可选——流结束后把完整回答写入 LLM 缓存（预设模式复用，
    同 key 再次提问直接回放，见 chat 路由的 mode_cache_hit）。

    方案2（固定频率刷新）：流中每 STREAM_PERSIST_INTERVAL_S 秒把已累积内容按 stream_key
    幂等滚动落库，前端在 streaming 期间定时轮询历史即可看到增量；thinking 事件转发
    模型思考过程（如 DeepSeek reasoning_content），避免思考阶段长时间空白。
    """
    yield sse_event({"type": "start"})
    full = ""
    stream_key = job["persist"].get("stream_key")
    last_persist_at = 0.0
    try:
        for ev in job["client"].stream_events(job["messages"]):
            if ev["kind"] == "thinking":
                yield sse_event({"type": "thinking", "text": ev["text"]})
                continue
            chunk = _sanitize_answer(ev["text"])
            full += chunk
            yield sse_event({"type": "delta", "text": chunk})
            if stream_key and time.monotonic() - last_persist_at >= STREAM_PERSIST_INTERVAL_S:
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
                            stream_key=stream_key,
                        )
                    finally:
                        db.close()
                except Exception:  # noqa: BLE001 滚动落库失败不影响流式输出
                    pass
                last_persist_at = time.monotonic()
    except LLMError as exc:
        yield sse_event({"type": "error", "message": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001 审查 C-问题9：流中途非 LLMError 异常也发 error 事件，不再静默断流
        yield sse_event({"type": "error", "message": f"流式输出中断: {exc}"})
        return
    yield sse_event({"type": "end", "text": full, "citations": extract_citations(full), "cached": False})
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
                stream_key=stream_key,
            )
            if cache:
                set_llm_cache(db, cache["book_id"], cache["kind"], cache["key"], {
                    "answer": full,
                    "citations": extract_citations(full),
                })
        finally:
            db.close()
    except Exception:  # noqa: BLE001 历史落库/缓存写入失败不影响已输出的回答
        pass

