"""章节上下文问答提示词（M4）。

约定：回答必须基于提供的书籍内容；引用原文须标注【第X章 第Y段】出处。
"""
SYSTEM_PROMPT = (
    "你是一位阅读辅导专家，熟悉读者已投喂书籍的内容。回答要求：\n"
    "1) 必须基于用户提供的书籍正文与相关片段回答，不要编造书中没有的内容；\n"
    "2) 引用书中原文或关键结论时，必须在句末标注出处，格式为【第X章 第Y段】（来自当前章节）"
    "或【第X章 第Y-Z段】（来自检索片段）；\n"
    "3) 回答使用 Markdown（支持 LaTeX 公式），结构清晰、先结论后展开；数学公式必须使用标准定界符：行内公式用 $...$，独立成块的公式用 $$...$$，不要用单独的圆括号或方括号代替公式定界符；\n"
    "4) 如果问题超出书籍内容，先说明书中未涉及，再结合常识简要回答。"
)


def build_system_prompt(skills: list[dict], page_mode: bool = False) -> str:
    """系统提示词；PDF 按页阅读时补充页引用约定；若该书存在 Skill 资产则注入可复用技能指令。"""
    prompt = SYSTEM_PROMPT
    if page_mode:
        prompt += "\n本书记载为 PDF 按页阅读：引用出处标注为【第X页】（来自当前页或相邻页窗口）。"
    if skills:
        lines = ["\n\n用户这本书沉淀了以下可复用技能，请在合适场景按其步骤使用："]
        for s in skills:
            name = s.get("name", "")
            applicable = s.get("applicable", "")
            usage = s.get("usage", "")
            lines.append(f"- {name}（适用场景：{applicable}）步骤：{usage}")
        prompt += "\n".join(lines)
    return prompt


def build_user_prompt(
    book_title: str,
    chapter_index: int,
    chapter_title: str,
    context_text: str,
    rag_block: str,
    selection: str,
    question: str,
    page_context: str | None = None,
) -> str:
    """构造用户侧输入：书籍/章节元信息 + 当前章节正文或 PDF 页窗口缓存 + RAG 片段 + 选中内容 + 问题。"""
    parts = [f"书籍：《{book_title}》", f"当前章节：第{chapter_index}章 {chapter_title}", ""]
    if page_context:
        parts.append("【当前页及相邻页内容（页缓存）】")
        parts.append(page_context)
    else:
        parts.append("【当前章节正文】")
        parts.append(context_text or "（正文未发送，遵循隐私设置）")
    if rag_block and not page_context:
        parts.append("\n【检索到的相关片段（含出处）】")
        parts.append(rag_block)
    if selection:
        parts.append("\n【用户选中内容】")
        parts.append(selection)
    parts.append(f"\n用户问题：{question}")
    return "\n".join(parts)
