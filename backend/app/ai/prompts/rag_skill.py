"""RAG/Skill 总结提示词（书籍 → 可检索摘要 + 可复用技能）。

约定：LLM 必须只输出一个 JSON 对象，字段结构由生成方解析（见 rag_service）。
"""
SYSTEM_PROMPT = (
    "你是一位知识整理专家。你的任务是把用户提供的书籍内容整理为两类资产：\n"
    "1) RAG 资产：全书概述 summary（200 字内）与关键知识点 key_points（每条都要标注出自哪一章哪一段，"
    "格式如『第2章第3段』）；\n"
    "2) Skill 资产：可从本书提炼的可复用技能列表 skills，每项包含技能名 name、适用场景 applicable、"
    "使用步骤 usage、出处章节 sources。\n"
    "必须严格输出一个 JSON 对象，不要输出任何其他内容或代码围栏。JSON 结构：\n"
    '{"summary": "…", "key_points": ["…（第x章第y段）", …], '
    '"skills": [{"name": "…", "applicable": "…", "usage": "…", "sources": ["第x章", …]}, …]}'
)


def build_user_prompt(book_title: str, chapters_text: str) -> str:
    """构造用户侧输入：书名 + 按章节划分的正文。"""
    return f"书籍：《{book_title}》\n\n以下是书籍内容（已按章节划分并标注章节号）：\n\n{chapters_text}"


INCREMENTAL_SYSTEM_PROMPT = (
    "你是一位知识整理专家。用户之前已把某本书总结为 RAG 与 Skill 资产，"
    "现在再次读完该书并产生了新的笔记、划线、对话与理解。请在**原资产基础上增改**：\n"
    "1) RAG 资产：合并新的要点、修正/扩展原 summary 与 key_points，不要丢失已有内容；"
    "每条 key_point 标注出处（如『第2章第3段』或『第 X 页』）；\n"
    "2) Skill 资产：合并/修正技能，去除重复项；\n"
    "必须严格输出一个 JSON 对象（结构同首次总结），不要输出任何其他内容或代码围栏。JSON 结构：\n"
    '{"summary": "…", "key_points": ["…（第x章第y段）", …], '
    '"skills": [{"name": "…", "applicable": "…", "usage": "…", "sources": ["第x章", …]}, …]}'
)


def build_incremental_user_prompt(
    book_title: str,
    old_rag: dict | None,
    old_skill: dict | None,
    new_material: str,
    body_text: str,
) -> str:
    """构造增量增改的用户输入：旧资产概要 + 本轮新增素材（笔记/划线/对话）+ 全书正文。"""
    old_rag = old_rag or {}
    old_skill = old_skill or {}
    kps = old_rag.get("key_points") or []
    kp_lines = "\n".join(
        k if isinstance(k, str) else str(k.get("title") or k.get("point") or "") for k in kps
    )
    skills = old_skill.get("skills") or []
    skill_lines = "\n".join(
        f"- {s.get('name', '')}（适用：{s.get('applicable', '')}）用法：{s.get('usage', '')}"
        if isinstance(s, dict)
        else f"- {s}"
        for s in skills
    )
    return (
        f"书籍：《{book_title}》\n\n"
        f"【已有 RAG 资产】\nsummary: {old_rag.get('summary', '')}\n"
        f"key_points:\n{kp_lines or '（无）'}\n\n"
        f"【已有 Skill 资产】\n{skill_lines or '（无）'}\n\n"
        f"【本轮新增素材（笔记/划线/不理解/对话）】\n{new_material}\n\n"
        f"【全书正文（供核实出处，可忽略无关部分）】\n{body_text}\n\n"
        "请输出增改合并后的完整 JSON 资产。"
    )
