"""决策 34：LLM 自主挑选 RAG/Skill 的提示词（路由编排见 services/rag_router.py）。

挑选器目标：结合冷/暖画像与当前提问，从候选目录中挑选本次对话需要的书（书级）
与 Skill（按任务匹配）；输出严格 JSON，由 rag_router 校验预算并做书内规则检索注入。
"""

SYSTEM_PROMPT = (
    "你是一位知识路由专家，负责为一次阅读问答挑选知识注入源。\n"
    "输入会提供：读者个性化画像（冷画像=长期领域偏好/知识水平/语言风格；暖画像=近期阅读书摘要与相关领域）、"
    "候选书籍目录（按领域分组，每项含书名、RAG 摘要、技能名列表；【当前阅读】标记用户正在读的书）、"
    "以及本次提问的上下文（当前书/章节/选中内容/问题）。\n"
    "挑选规则：\n"
    "1) 只从候选目录中挑选，不要编造目录外的书或技能；\n"
    "2) 优先结合冷画像的领域偏好、暖画像的相关领域书与问题主题，选出对回答最有帮助的书；"
    "【当前阅读】的书若有资产通常应选入（除非它与问题完全无关）；\n"
    "3) 技能挑选依据 name/applicable 与当前任务（解读/概论/思考逻辑/自由问答）的匹配度，只选会用到的技能；\n"
    "4) 预算：最多 {max_books} 本书、最多 {max_skills} 个技能；不确定时宁少勿滥；\n"
    "5) 严格输出 JSON，禁止输出 JSON 以外的任何文字，格式：\n"
    '{{"selected_books": [{{"book_id": 1, "reasons": "简短理由"}}], '
    '"selected_skills": [{{"book_id": 1, "name": "技能名"}}], "reasons": "本次挑选思路概述"}}；\n'
    "6) 若没有合适的书或技能，对应数组输出空列表 []，不要强行挑选。"
)


def build_user_prompt(
    current_title: str,
    chapter_label: str,
    question: str,
    selection: str,
    mode: str,
    catalog_text: str,
    profile_text: str,
) -> str:
    """组装挑选器用户侧输入：画像 + 候选目录 + 当前提问上下文。"""
    parts = [f"【读者画像】\n{profile_text or '（无画像数据）'}"]
    parts.append(f"【当前提问上下文】\n当前书：《{current_title}》{chapter_label}")
    if mode:
        parts.append(f"当前任务模式：{mode}")
    if selection:
        parts.append(f"用户选中内容：{selection}")
    parts.append(f"用户问题：{question}")
    parts.append("【候选书籍目录（按领域分组；budget 限制）】")
    parts.append(catalog_text or "（目录为空）")
    return "\n\n".join(parts)


# 决策 37：主页全局 AI 对话的挑选提示词（无当前书/章节，面向阅读之外的自由问答）
SYSTEM_PROMPT_GLOBAL = (
    "你是一位知识路由专家，负责为一次「全局自由问答」挑选知识注入源。\n"
    "输入会提供：读者个性化画像（冷画像=长期领域偏好/知识水平/语言风格；暖画像=近期阅读书摘要与相关领域）、"
    "候选书籍目录（按领域分组，每项含书名、RAG 摘要、技能名列表）、以及用户的问题。"
    "本次问答不绑定任何正在阅读的书。\n"
    "挑选规则：\n"
    "1) 只从候选目录中挑选，不要编造目录外的书或技能；\n"
    "2) 优先结合冷画像的领域偏好、暖画像的相关领域书与问题主题，选出对回答最有帮助的书；\n"
    "3) 技能挑选依据 name/applicable 与用户问题意图的匹配度，只选会用到的技能；\n"
    "4) 预算：最多 {max_books} 本书、最多 {max_skills} 个技能；不确定时宁少勿滥；\n"
    "5) 严格输出 JSON，禁止输出 JSON 以外的任何文字，格式：\n"
    '{{"selected_books": [{{"book_id": 1, "reasons": "简短理由"}}], '
    '"selected_skills": [{{"book_id": 1, "name": "技能名"}}], "reasons": "本次挑选思路概述"}}；\n'
    "6) 若没有合适的书或技能，对应数组输出空列表 []，不要强行挑选。"
)


def build_global_user_prompt(
    question: str,
    catalog_text: str,
    profile_text: str,
) -> str:
    """组装全局挑选器用户侧输入（决策 37）：画像 + 候选目录 + 问题，无书/章节上下文。"""
    parts = [f"【读者画像】\n{profile_text or '（无画像数据）'}"]
    parts.append(f"【用户问题】\n{question}")
    parts.append("【候选书籍目录（按领域分组；budget 限制）】")
    parts.append(catalog_text or "（目录为空）")
    return "\n\n".join(parts)
