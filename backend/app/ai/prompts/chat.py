"""章节上下文问答提示词（M4）。

约定：回答必须基于提供的书籍内容；引用原文须标注【第X章 第Y段】出处；
数学符号只能使用 LaTeX 或 Markdown，禁止输出 Unicode 数学字符。
"""
# 数学表达硬性规则（需求：AI 输出涉及数学符号只能用 LaTeX/Markdown，禁 Unicode）
MATH_RULE = (
    "数学符号与公式必须使用 LaTeX 或 Markdown 表达：行内公式用 $...$，独立成块的公式用 $$...$$；"
    "禁止输出无定界符的裸 LaTeX，也禁止输出 Unicode 数学字符（如 Λ、∈、ℝ、√、≥、∀、∃ 等），"
    "一律写成 LaTeX 命令（如 \\Lambda、\\in、\\mathbb{R}、\\sqrt、\\ge、\\forall、\\exists）"
    "或 Markdown 文本；不要用单独的圆括号或方括号代替公式定界符。"
)

SYSTEM_PROMPT = (
    "你是一位阅读辅导专家，熟悉读者已投喂书籍的内容。回答要求：\n"
    "1) 必须基于用户提供的书籍正文与相关片段回答，不要编造书中没有的内容；\n"
    "2) 引用书中原文或关键结论时，必须在句末标注出处：来自当前章节用【第X章 第Y段】；"
    "来自检索片段用【第X章 第Y-Z段】；跨书片段（其他书）用【《书名》第X章 第Y段】；\n"
    "3) 回答使用 Markdown（支持 LaTeX 公式），结构清晰、先结论后展开；" + MATH_RULE + "\n"
    "4) 如果问题超出书籍内容，先说明书中未涉及，再结合常识简要回答。"
)

# 预设能力按钮的结构化任务模板（解读 / 概论 / 思考逻辑）
MODE_INSTRUCTIONS: dict[str, str] = {
    "解读": (
        "当前任务：对本章（或选中内容）进行逐层解读。输出结构：\n"
        "- 结论：先用 2~4 句给出核心要义与最终结论（含关键公式，按公式规范输出）；\n"
        "- 逐层解读：按逻辑层次（前提 → 断言 → 推论）分点展开，每层说明「是什么、为什么成立、与上下文的关系」；\n"
        "- 意义与应用：说明该内容的价值、适用范围与可延伸的方向；\n"
        "引用原文或关键结论须在句末标注【第X章 第Y段】出处。"
    ),
    "概论": (
        "当前任务：为本章生成概论。输出结构：\n"
        "- 核心观点：本章要解决的问题与给出的结论（3~5 句）；\n"
        "- 主要内容：按主题分节概括，每节 1~3 句；\n"
        "- 关键结论：列出最重要的定理/公式/定义，公式按公式规范输出并标注出处；\n"
        "引用须在句末标注【第X章 第Y段】出处。"
    ),
    "思考逻辑": (
        "当前任务：梳理本章的思考逻辑。输出结构：\n"
        "- 论证链条：用编号步骤还原推理主线（A → B → C），每步说明依据；\n"
        "- 关键假设：指出论证依赖的前提与隐含假设；\n"
        "- 薄弱点与追问：指出可能的疑点、反例或可继续追问的问题；\n"
        "引用须在句末标注【第X章 第Y段】出处；公式按公式规范输出。"
    ),
}


def build_profile_block(profiles: dict | None) -> str:
    """把三层画像（热/暖/冷）压缩为系统提示词片段；无画像或为空时返回空串。

    仅注入摘要级信息用于调整讲解深度与偏好，不要求模型向用户复述画像。
    """
    if not profiles:
        return ""
    hot = profiles.get("hot") or {}
    warm = profiles.get("warm") or {}
    cold = profiles.get("cold") or {}
    lines = ["\n\n【读者个性化画像（仅用于调整讲解深度与风格偏好，不要向用户复述）】"]
    if hot.get("current_book_id"):
        try:
            pct = round(float(hot.get("progress", 0)) * 100)
        except (TypeError, ValueError):
            pct = 0
        lines.append(f"- 热画像（当前书）：《{hot.get('current_title', '')}》阅读进度 {pct}%")
        titles = hot.get("chapter_titles") or []
        if titles:
            lines.append("  已读章节脉络：" + " → ".join(str(t) for t in titles[-8:]))
        highlights = hot.get("highlights") or []
        if highlights:
            lines.append(f"  近期划线/笔记（共 {len(highlights)} 条，最新 {min(5, len(highlights))} 条）：")
            for item in highlights[-5:]:
                lines.append(f"    - {str(item)[:120]}")
        questions = hot.get("questions") or []
        if questions:
            lines.append(
                f"  进行中的问题（最新 {min(3, len(questions))} 条）："
                + "；".join(str(q)[:80] for q in questions[-3:])
            )
    recent = warm.get("recent_books") or []
    if recent:
        lines.append("- 暖画像（近期读过的书）：")
        for r in recent[-2:]:
            summary = str(r.get("summary") or "")[:160]
            lines.append(f"  - 《{r.get('title', '')}》：{summary}")
    related = warm.get("related_books") or []
    if related:
        lines.append(
            f"- 相关领域书籍（{len(related)} 本）："
            + "、".join(str(r.get("title", "")) for r in related[:5])
        )
    cold_domains = cold.get("domain_preferences") or {}
    if cold_domains:
        try:
            top = sorted(cold_domains.items(), key=lambda kv: -int(kv[1]))[:10]
        except (TypeError, ValueError):
            top = list(cold_domains.items())[:10]
        lines.append("- 冷画像·领域偏好：" + "、".join(f"{k}({v})" for k, v in top))
    if cold.get("knowledge_level"):
        lines.append(f"- 冷画像·知识水平：{cold.get('knowledge_level')}")
    if cold.get("language_style"):
        lines.append(f"- 冷画像·语言风格：{cold.get('language_style')}")
    interests = cold.get("long_term_interests") or []
    if interests:
        lines.append("- 冷画像·长期兴趣：" + "、".join(str(i) for i in interests[:10]))
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_system_prompt(
    skills: list[dict],
    page_mode: bool = False,
    mode: str | None = None,
    profiles: dict | None = None,
) -> str:
    """系统提示词；PDF 按页阅读时补充页引用约定；mode 为解读/概论/思考逻辑时附加结构化任务模板；
    profiles 非空时注入三层画像（热全量摘要 + 暖近期书 + 冷领域偏好）；Skill 资产注入可复用技能指令。"""
    prompt = SYSTEM_PROMPT
    if page_mode:
        prompt += (
            "\n本书记载为 PDF 按页阅读：当前页与相邻页内容引用出处标注为【第X页】；"
            "同时注入的跨书检索片段仍标注【《书名》第X章 第Y段】。"
        )
    if mode and mode in MODE_INSTRUCTIONS:
        prompt += "\n\n" + MODE_INSTRUCTIONS[mode]
    prompt += build_profile_block(profiles)
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
    if rag_block:
        parts.append("\n【检索到的相关片段（含出处）】")
        parts.append(rag_block)
    if selection:
        parts.append("\n【用户选中内容】")
        parts.append(selection)
    parts.append(f"\n用户问题：{question}")
    return "\n".join(parts)
