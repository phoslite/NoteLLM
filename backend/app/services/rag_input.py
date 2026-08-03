"""RAG 输入准备：章节/页缓存切块与 LLM 输入正文构建（纯函数，无仓储依赖）。"""

from app.core.config import settings

CHUNK_CHARS = 1600   # 长章节按段落切块的字数阈值
SEND_BUDGET = 8000   # 发送给 LLM 的正文总字数上限（防止超长书籍超 token）


def chunk_chapter(chapter, chunk_chars: int = CHUNK_CHARS) -> list[dict]:
    """单个章节 → RAG 片段列表；每段记录 chapter_index/chapter_title/para_pos 出处。"""
    paras = [p.strip() for p in (chapter.content_text or "").splitlines() if p.strip()]
    chunks: list[dict] = []
    buf: list[str] = []
    start: int | None = None

    def flush(end: int):
        nonlocal buf, start
        if buf:
            chunks.append(
                {
                    "chapter_index": chapter.index,
                    "chapter_title": chapter.title,
                    "para_pos": f"{start}-{end}",
                    "text": "\n".join(buf),
                }
            )
            buf, start = [], None

    for i, para in enumerate(paras, 1):
        if start is None:
            start = i
        buf.append(para)
        if sum(len(x) for x in buf) >= chunk_chars:
            flush(i)
    flush(len(paras))
    if not chunks:  # 空章节兜底
        chunks.append(
            {
                "chapter_index": chapter.index,
                "chapter_title": chapter.title,
                "para_pos": "-",
                "text": chapter.content_text or "",
            }
        )
    return chunks


def chunk_book(chapters) -> list[dict]:
    """整本书 → 全部 RAG 片段（按章节顺序）。"""
    return [c for ch in chapters for c in chunk_chapter(ch)]


def page_chunks(page_texts: dict[int, str]) -> list[dict]:
    """PDF 页缓存 → RAG 片段列表；每段记录页号出处（chapter_index=页号，para_pos=页）。"""
    chunks: list[dict] = []
    for page_index in sorted(page_texts):
        text = (page_texts[page_index] or "").strip()
        if not text:
            continue
        chunks.append(
            {
                "chapter_index": page_index,
                "chapter_title": f"第 {page_index} 页",
                "para_pos": "页",
                "page_index": page_index,
                "text": text,
            }
        )
    return chunks


def normalize_skills(raw: list) -> list[dict]:
    """把 LLM 返回的技能列表归一化为 dict 结构（兼容字符串列表）。"""
    out = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"name": item, "applicable": "", "usage": "", "sources": []})
        elif isinstance(item, dict):
            out.append(
                {
                    "name": item.get("name", ""),
                    "applicable": item.get("applicable", item.get("场景", "")),
                    "usage": item.get("usage", item.get("用法", "")),
                    "sources": item.get("sources", []),
                }
            )
    return out


def build_llm_input(chapters, chunks: list[dict]) -> str:
    """按章节组织正文（chunks 由调用方一次性切好）；隐私开关关闭时仅发送章节标题。"""
    if not settings.ai_enable_body_send:
        return "\n".join(f"第{ch.index}章 {ch.title}" for ch in chapters)

    by_chapter: dict[int, list[str]] = {}
    for c in chunks:
        by_chapter.setdefault(c["chapter_index"], []).append(c["text"])

    parts: list[str] = []
    used = 0
    for ch in chapters:
        block = f"【第{ch.index}章 {ch.title}】\n" + "\n".join(by_chapter.get(ch.index, []))
        if used + len(block) > SEND_BUDGET and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts) if parts else "(无可发送的正文内容)"


def build_page_input(page_texts: dict[int, str]) -> str:
    """PDF 页缓存 → LLM 输入正文（隐私开关关闭时仅发送页标题；超 SEND_BUDGET 截断）。"""
    if not settings.ai_enable_body_send:
        return "\n".join(f"第 {n} 页" for n in sorted(page_texts))
    parts: list[str] = []
    used = 0
    for n in sorted(page_texts):
        text = (page_texts[n] or "").strip()
        if not text:
            continue
        block = f"【第 {n} 页】\n{text}"
        if used + len(block) > SEND_BUDGET and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts) if parts else "(无可发送的正文内容)"
