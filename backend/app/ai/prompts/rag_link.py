"""跨书联动 RAG/Skill 增量增改提示词（需求 3.4.7/3.4.9 图谱联动沉淀）。"""
SYSTEM_PROMPT = (
    "你是一位知识整理专家。跨书知识谱系构建/更新后，需要把某本书与另一本书的关联沉淀进该书资产：\n"
    "1) RAG 资产：在原 summary 与 key_points 基础上**增改**——合并跨书关联与共同概念条目、"
    "跨书对比/串联得出的新理解，不要丢失已有内容；每条 key_point 标注出处（如『第2章第3段』"
    "或『跨书关联：《另一本书》』）；\n"
    "2) Skill 资产：融合跨书对比/串联得出的新方法或改进后的使用步骤，去除重复项；\n"
    "必须严格输出一个 JSON 对象，不要输出任何其他内容或代码围栏。JSON 结构：\n"
    '{"summary": "…", "key_points": ["…（出处）", …], '
    '"skills": [{"name": "…", "applicable": "…", "usage": "…", "sources": ["第x章"]}, …]}'
)


def build_link_user_prompt(
    book_title: str,
    other_title: str,
    relation_desc: str,
    reasons: list[str],
    old_rag: dict | None,
    old_skill: dict | None,
    materials: str,
) -> str:
    """构造跨书联动的用户侧输入：旧资产概要 + 本轮关联描述 + 轻量素材。"""
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
    reason_line = "、".join(reasons) if reasons else "（无）"
    return (
        f"书籍：《{book_title}》\n\n"
        f"【本轮跨书关联】与《{other_title}》{relation_desc}\n"
        f"关联原因：{reason_line}\n\n"
        f"【已有 RAG 资产】\nsummary: {old_rag.get('summary', '')}\n"
        f"key_points:\n{kp_lines or '（无）'}\n\n"
        f"【已有 Skill 资产】\n{skill_lines or '（无）'}\n\n"
        f"【本书轻量素材（章节标题/要点，供核实）】\n{materials}\n\n"
        "请输出增改合并后的完整 JSON 资产。"
    )