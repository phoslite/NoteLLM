"""RAG 输入准备：章节/页缓存切块与 LLM 输入正文构建（纯函数，无仓储依赖）。"""

from app.core.config import settings
from app.services.blank_page import is_blank_page_text
from app.services.html_util import html_to_text

CHUNK_CHARS = 1600   # 长章节按段落切块的字数阈值（RAG 检索片段）


def chunk_chapter(chapter, chunk_chars: int = CHUNK_CHARS, is_html: bool = False) -> list[dict]:
    """单个章节 → RAG 片段列表；每段记录 chapter_index/chapter_title/para_pos 出处。

    is_html：EPUB 章节正文为消毒后 HTML（方案 A），切块前经 html_to_text 转纯文本。
    """
    content = html_to_text(chapter.content_text or "") if is_html else (chapter.content_text or "")
    paras = [p.strip() for p in content.splitlines() if p.strip()]
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
                "text": content,
            }
        )
    return chunks


def chunk_book(chapters, is_html: bool = False) -> list[dict]:
    """整本书 → 全部 RAG 片段（按章节顺序）。"""
    return [c for ch in chapters for c in chunk_chapter(ch, is_html=is_html)]


def page_chunks(page_texts: dict[int, str]) -> list[dict]:
    """PDF 页缓存 → RAG 片段列表；每段记录页号出处（chapter_index=页号，para_pos=页）。"""
    chunks: list[dict] = []
    for page_index in sorted(page_texts):
        text = (page_texts[page_index] or "").strip()
        if not text or is_blank_page_text(text):
            continue  # 空白页标记不进入 RAG 片段（视觉提取已归一化，v1.84）
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
    """按章节组织正文（chunks 由调用方一次性切好）；隐私开关关闭时仅发送章节标题。
    预算取 settings.rag_summary_chunk_chars（方案 B：64K 字符），超长由调用方分块。"""
    if not settings.ai_enable_body_send:
        return "\n".join(f"第{ch.index}章 {ch.title}" for ch in chapters)

    by_chapter: dict[int, list[str]] = {}
    for c in chunks:
        by_chapter.setdefault(c["chapter_index"], []).append(c["text"])

    parts: list[str] = []
    used = 0
    for ch in chapters:
        block = f"【第{ch.index}章 {ch.title}】\n" + "\n".join(by_chapter.get(ch.index, []))
        if used + len(block) > settings.rag_summary_chunk_chars and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts) if parts else "(无可发送的正文内容)"


def build_page_input(page_texts: dict[int, str]) -> str:
    """PDF 页缓存 → LLM 输入正文（隐私开关关闭时仅发送页标题；超预算截断）。"""
    if not settings.ai_enable_body_send:
        return "\n".join(f"第 {n} 页" for n in sorted(page_texts))
    parts: list[str] = []
    used = 0
    for n in sorted(page_texts):
        text = (page_texts[n] or "").strip()
        if not text or is_blank_page_text(text):
            continue  # 空白页标记不发送给 LLM（v1.84）
        block = f"【第 {n} 页】\n{text}"
        if used + len(block) > settings.rag_summary_chunk_chars and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts) if parts else "(无可发送的正文内容)"
def chunk_page_texts_for_summary(page_texts: dict[int, str], chunk_chars: int) -> list[str]:
    """PDF 页缓存 → 方案 B map 轮输入分块。

    按页号顺序组装「【第 N 页】\n文本」后按 chunk_chars 切块；单页超长时从行处切开并保留页标题。
    隐私开关关闭时仅返回页号标题（单块，走旧单次调用路径）。
    """
    if not settings.ai_enable_body_send:
        titles = "\n".join(f"第 {n} 页" for n in sorted(page_texts))
        return [titles or "(无可发送的正文内容)"]
    blocks = [
        f"【第 {n} 页】\n{(page_texts[n] or '').strip()}"
        for n in sorted(page_texts)
        if (page_texts[n] or "").strip() and not is_blank_page_text(page_texts[n])
    ]
    return _split_blocks(blocks, chunk_chars)


def chunk_chapters_for_summary(chapters, chunks: list[dict], chunk_chars: int) -> list[str]:
    """章节正文 → 方案 B map 轮输入分块，按章节顺序组装。

    隐私开关关闭时仅返回章节标题（单块，走旧单次调用路径）。
    """
    if not settings.ai_enable_body_send:
        titles = "\n".join(f"第{ch.index}章 {ch.title}" for ch in chapters)
        return [titles or "(无可发送的正文内容)"]
    by_chapter: dict[int, list[str]] = {}
    for c in chunks:
        by_chapter.setdefault(c["chapter_index"], []).append(c["text"])
    blocks: list[str] = []
    for ch in chapters:
        body = "\n".join(by_chapter.get(ch.index, []))
        if body:
            blocks.append(f"【第{ch.index}章 {ch.title}】\n{body}")
    return _split_blocks(blocks, chunk_chars) if blocks else ["(无可发送的正文内容)"]


def _split_blocks(blocks: list[str], chunk_chars: int) -> list[str]:
    """带标题正文块 → 按 chunk_chars 切块（标题行不拆分；单块超长按行再切）。"""
    if chunk_chars <= 0:  # 0=不限制：单次发送全文
        return ["\n\n".join(blocks) or "(无可发送的正文内容)"]
    out: list[str] = []
    buf: list[str] = []
    used = 0

    def flush() -> None:
        nonlocal buf, used
        if buf:
            out.append("\n\n".join(buf))
            buf, used = [], 0

    for b in blocks:
        if len(b) > chunk_chars:
            flush()
            header, _, body = b.partition("\n")
            lines = [header]
            cur_len = len(header) + 1
            for ln in body.splitlines():
                if cur_len + len(ln) + 1 > chunk_chars and len(lines) > 1:
                    out.append("\n".join(lines))
                    lines = [header]
                    cur_len = len(header) + 1
                lines.append(ln)
                cur_len += len(ln) + 1
            out.append("\n".join(lines))
            continue
        if used + len(b) > chunk_chars and buf:
            flush()
        buf.append(b)
        used += len(b)
    flush()
    return out or ["(无可发送的正文内容)"]

