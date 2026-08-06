"""RAG/Skill 总结提示词（书籍 → 可检索摘要 + 可复用技能）。

约定：LLM 必须只输出一个 JSON 对象，字段结构由生成方解析（见 rag_service）。
"""
SYSTEM_PROMPT = (
    "你是一位知识整理专家。你的任务是把用户提供的书籍内容整理为两类资产：\n"
    "1) RAG 资产：全书概述 summary（200 字内）与关键知识点 key_points（每条都要标注出自哪一章哪一段，"
    "格式如『第2章第3段』）；\n"
    "2) Skill 资产：可从本书提炼的可复用技能列表 skills，每项包含技能名 name、适用场景 applicable、"
    "使用步骤 usage、出处章节 sources。\n"
    "数学公式必须用行内 $...$ 或块级 $$...$$ 包裹（如 `$\\Lambda^n V$`），"
    "禁止输出无定界符的裸 LaTeX（如 `\\Lambda^n V`）或裸 Unicode 数学（如 `Λ^n V`）；"
    "JSON 字符串内反斜杠须写成双反斜杠（`\\\\`）。\n"
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
    "数学公式必须用行内 $...$ 或块级 $$...$$ 包裹（如 `$\\Lambda^n V$`），"
    "禁止输出无定界符的裸 LaTeX（如 `\\Lambda^n V`）或裸 Unicode 数学（如 `Λ^n V`）；"
    "JSON 字符串内反斜杠须写成双反斜杠（`\\\\`）。\n"
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
# 方案 B（map-reduce 分块提炼）：正文超过 RAG_SUMMARY_CHUNK_CHARS 时，
# map 轮逐块提炼 key_points/skills，reduce 轮合并为完整资产（含增量增改）。
CHUNK_SYSTEM_PROMPT = (
    "你是一位知识整理专家。下面是某本书籍的一个片段（可能包含若干章或若干页），"
    "请**只依据这个片段**提炼两类中间结果：\n"
    "1) key_points：该片段内的关键知识点，每条标注出处（格式如『第2章第3段』或『第 X 页』）；\n"
    "2) skills：可从该片段提炼的可复用技能，每项包含技能名 name、适用场景 applicable、"
    "使用步骤 usage、出处章节 sources。\n"
    "不要写全书 summary 与 tags（合并阶段统一生成）。\n"
    "数学公式必须用行内 $...$ 或块级 $$...$$ 包裹（如 `$\\Lambda^n V$`），"
    "禁止输出无定界符的裸 LaTeX（如 `\\Lambda^n V`）或裸 Unicode 数学（如 `Λ^n V`）；"
    "JSON 字符串内反斜杠须写成双反斜杠（`\\\\`）。\n"
    "必须严格输出一个 JSON 对象，不要输出任何其他内容或代码围栏。JSON 结构：\n"
    '{"key_points": ["…（第x章第y段）", …], '
    '"skills": [{"name": "…", "applicable": "…", "usage": "…", "sources": ["第x章", …]}, …]}'
)


MERGE_SYSTEM_PROMPT = (
    "你是一位知识整理专家。用户把一本书切成多个片段分别提炼，下面给出各片段的关键知识点与技能。"
    "请把它们合并为这本书的完整资产：\n"
    "1) summary：全书概述（200 字内）；\n"
    "2) key_points：合并去重，按章节/页顺序排列，保留各自出处；\n"
    "3) skills：合并去重技能；\n"
    "4) tags：本书所属领域（每个为汉字或英文词组，不要带标点）。\n"
    "若提供了【已有 RAG 资产】【已有 Skill 资产】【本轮新增素材】，则在此基础上增改合并，不要丢失已有内容。\n"
    "数学公式必须用行内 $...$ 或块级 $$...$$ 包裹（如 `$\\Lambda^n V$`），"
    "禁止输出无定界符的裸 LaTeX（如 `\\Lambda^n V`）或裸 Unicode 数学（如 `Λ^n V`）；"
    "JSON 字符串内反斜杠须写成双反斜杠（`\\\\`）。\n"
    "必须严格输出一个 JSON 对象，不要输出任何其他内容或代码围栏。JSON 结构：\n"
    '{"summary": "…", "key_points": ["…（第x章第y段）", …], "tags": ["…"], '
    '"skills": [{"name": "…", "applicable": "…", "usage": "…", "sources": ["第x章", …]}, …]}'
)


def build_chunk_user_prompt(book_title: str, block_text: str, block_no: int, total: int) -> str:
    """map 轮：单个片段的用户输入。"""
    return (
        f"书籍：《{book_title}》\n\n"
        f"这是本书第 {block_no}/{total} 个片段，请只依据该片段提炼 key_points 与 skills：\n\n"
        f"{block_text}"
    )


def build_merge_user_prompt(
    book_title: str, blocks_text: str, *, old_rag: dict | None = None, old_skill: dict | None = None, new_material: str = ""
) -> str:
    """reduce 轮：各片段中间结果 → 合并（首次）；或旧资产 + 新素材 + 片段结果 → 增改合并（增量）。"""
    parts = [f"书籍：《{book_title}》", "", "以下是本书各片段的关键知识点与技能总结：", "", blocks_text]
    if old_rag or old_skill:
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
        parts += [
            "",
            "【已有 RAG 资产】",
            f"summary: {old_rag.get('summary', '')}",
            f"key_points:\n{kp_lines or '（无）'}",
            "",
            "【已有 Skill 资产】",
            skill_lines or "（无）",
            "",
            "【本轮新增素材（笔记/划线/不理解/对话）】",
            new_material,
            "",
            "请在已有资产基础上增改合并，输出增改后的完整 JSON 资产。",
        ]
    else:
        parts += ["", "请合并去重（内容重复的只保留一份），输出这本书的完整 JSON 资产。"]
    return "\n".join(parts)

