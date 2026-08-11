"""AI 阅读上下文组装：章节段落编号、PDF 页窗口文本与 RAG/Skill 上下文块。"""

from app.services.html_util import chapter_plain_text


def paragraph_numbered(text: str) -> str:
    """把章节正文按行编号：每段前加【第N段】。"""
    paras = [p.strip() for p in (text or "").splitlines() if p.strip()]
    return "\n".join(f"【第{i}段】{p}" for i, p in enumerate(paras, 1))


def build_page_context_block(window_texts: dict[int, str], enable_body_send: bool) -> str:
    """PDF 页窗口上下文：把 {页号: 页缓存文本} 组装为带页号标记的文本块（隐私开关关闭时为空）。"""
    if not enable_body_send:
        return ""
    blocks = []
    for page in sorted(window_texts):
        text = (window_texts[page] or "").strip()
        if text:
            blocks.append(f"【第 {page} 页】\n{text}")
    return "\n\n".join(blocks)


def build_context_block(
    chapter, rag_chunks: list[dict], enable_body_send: bool, book_format: str | None = None
) -> tuple[str, str]:
    """组装「带段落编号的正文 + RAG 片段块」；隐私开关关闭时两者均为空字符串。"""
    if not enable_body_send:
        return "", ""
    context_text = paragraph_numbered(chapter_plain_text(book_format, chapter.content_text or ""))
    rag_block = "\n".join(
        f"【第{c['chapter_index']}章 第{c.get('para_pos', '-')}段】{c.get('text', '')}" for c in rag_chunks
    )
    return context_text, rag_block
