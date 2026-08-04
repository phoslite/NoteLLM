"""M5 脑图生成服务：LLM 结构化 JSON → ECharts 树数据；失败时回退 Markdown 列表解析。"""
import json
import re

from sqlalchemy.orm import Session

from app.ai.factory import build_client
from app.ai.parsing import parse_llm_json
from app.core.config import settings
from app.repositories.assets import load_skills, retrieve_rag_chunks
from app.repositories.chat import persist_chat
from app.repositories.settings import load_ai_overrides, vision_configured
from app.services.ai_context import (
    build_context_block,
    build_page_context_block,
    page_image_data_uri,
)
from app.services.citations import extract_citations
from app.services.llm_cache import cache_key, chapter_fingerprint, get_llm_cache, set_llm_cache
from app.services.vision_extract import ensure_window_caches

MINDMAP_SYSTEM = """你是知识图谱与思维导图专家。根据提供的章节内容，生成三层思维导图数据：
- 大纲层：章节的主题结构与分节（一级/二级结构）；
- 细节层：每个大纲节点下的关键细节与论证；
- 重要定理层：重要定理、公式、定义与结论（nodeType 标记为「重要定理」）。

只输出一个 JSON 对象，不要 Markdown 代码块、不要多余解释。结构：
{"title": "章节标题", "children": [{"name": "节点名", "nodeType": "大纲|细节|重要定理", "ref": {"chapter": 1, "para": "3"}, "children": []}]}
规则：nodeType 省略时视为「大纲」；ref 引用正文出处【第X章 第Y段】，无法确定时可为 null；children 为数组，叶节点可为空数组。
数学表达：节点名中的公式必须用 $...$ 包裹（如 $\\Lambda^n V$），禁止输出无定界符的裸 LaTeX 或 Unicode 数学字符（如 Λ^n V、∈、ℝ）。JSON 字符串内反斜杠须写成双反斜杠（\\）。"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+")
_NUM_RE = re.compile(r"^\s*\d+[.、)]\s+")
_HEAD_RE = re.compile(r"^\s*(#+)\s+")


def parse_mindmap_json(text: str) -> dict | None:
    """从 LLM 回复中提取思维导图 JSON；支持裸 JSON 与 ```json 代码块。"""
    if not text:
        return None
    candidates = [text]
    for m in _JSON_FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    for cand in candidates:
        try:
            data = parse_llm_json(cand)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and ("children" in data or "title" in data):
            return data
    return None



def _clean_node(node: dict) -> dict:
    name = str(node.get("name") or node.get("title") or "").strip()
    node_type = node.get("nodeType") if node.get("nodeType") in ("大纲", "细节", "重要定理") else "大纲"
    ref = node.get("ref")
    if isinstance(ref, dict) and ref.get("chapter"):
        ref = {"chapter": int(ref["chapter"]), "para": str(ref.get("para") or "-")}
    else:
        ref = None
    children = [_clean_node(c) for c in (node.get("children") or []) if isinstance(c, dict)]
    return {"name": name, "nodeType": node_type, "ref": ref, "children": children}


def _md_depth(raw: str) -> int | None:
    if _HEAD_RE.match(raw):
        return len(_HEAD_RE.match(raw).group(1))
    m = _BULLET_RE.match(raw) or _NUM_RE.match(raw)
    if m:
        # 层级 = 1 + 前导空格缩进层级（2 空格一级）
        return 1 + (len(m.group(0)) - len(m.group(0).lstrip())) // 2
    stripped = raw.lstrip()
    if not stripped:
        return None
    # 纯文本行（如制表符缩进的脑图文本）：按前导空白推断层级
    leading = raw[: len(raw) - len(stripped)].replace("\t", "    ")
    return 1 + len(leading) // 2


def markdown_to_tree(md: str, title: str = "思维导图") -> dict:
    """Markdown 层级列表 → 树（LLM 未输出 JSON 时的回退）。"""
    root = {"name": title, "nodeType": "大纲", "ref": None, "children": []}
    stack: list[tuple[int, dict]] = [(0, root)]
    for raw in (md or "").splitlines():
        depth = _md_depth(raw)
        if depth is None:
            continue
        name = _HEAD_RE.sub("", _BULLET_RE.sub("", _NUM_RE.sub("", raw))).strip()
        if not name:
            continue
        if not (raw.lstrip().startswith(("-", "*", "+")) or raw.lstrip()[0].isdigit() or raw.lstrip().startswith("#")):
            name = raw.strip()
        node = {"name": name, "nodeType": "大纲", "ref": None, "children": []}
        if re.search(r"定理|公式|定义|结论|推论|命题|定律|公理", name):
            node["nodeType"] = "重要定理"
        elif depth >= 2:
            node["nodeType"] = "细节"
        while stack and depth <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(0, root)]
        stack[-1][1]["children"].append(node)
        stack.append((depth, node))
    return root


def tree_to_markdown(node: dict, depth: int = 0) -> str:
    """树 → Markdown 层级列表（供复制/导出）。"""
    tag = "" if node.get("nodeType", "大纲") == "大纲" else f"（{node['nodeType']}）"
    lines = ["  " * depth + f"- {node['name']}{tag}"]
    for c in node.get("children", []):
        lines.append(tree_to_markdown(c, depth + 1))
    return "\n".join(lines)


def build_mindmap_messages(
    book,
    chapter,
    selection: str,
    focus: str,
    rag_chunks: list[dict],
    skills: list[dict],
    enable_body_send: bool,
    page_image: str | None,
    page_context: str | None = None,
) -> list[dict]:
    """构建脑图生成 messages；隐私开关关闭时不发送正文与 RAG 片段；PDF 按页阅读优先注入页缓存。"""
    context_text, rag_block = build_context_block(chapter, rag_chunks, enable_body_send)
    if page_context:
        rag_block = ""
    user = f"书籍：《{book.title}》\n当前章节：第{chapter.index}章 {chapter.title}\n"
    if selection:
        user += f"\n用户选中内容：\n{selection}\n"
    if focus:
        user += f"\n关注重点：{focus}\n"
    if page_context:
        user += f"\n【当前页及相邻页内容（页缓存）】\n{page_context}\n"
    else:
        user += f"\n【当前章节正文】\n{context_text or '（正文未发送，遵循隐私设置）'}\n"
    if rag_block and not page_context:
        user += f"\n【相关背景（RAG）】\n{rag_block}\n"
    user += "\n请按系统要求输出思维导图 JSON。"
    system = MINDMAP_SYSTEM
    if skills:
        system += "\n\n本书已沉淀可复用技能：" + "；".join(
            s.get("name") or s.get("description") or "" for s in skills
        )
    messages: list[dict] = [{"role": "system", "content": system}]
    if page_image and enable_body_send:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": page_image}},
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": user})
    return messages


def generate_mindmap(
    db: Session,
    book,
    chapter,
    selection: str = "",
    focus: str = "",
) -> dict:
    """生成章节/选中段的层级化脑图；返回 {title, tree, markdown, citations}。"""
    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    send_page = overrides.get("ai_send_page_image", settings.ai_send_page_image)
    page_mode = chapter.page_index is not None
    page_context = None
    if page_mode and enable_body and vision_configured(db):
        try:
            window = ensure_window_caches(db, book, chapter.page_index)
            page_context = build_page_context_block(window, enable_body)
        except Exception:  # noqa: BLE001 提取失败回退页图附件
            page_context = None
    page_image = (
        None
        if page_context
        else page_image_data_uri(book, chapter, enable_body and send_page)
    )
    rag_chunks = retrieve_rag_chunks(db, book.id, "思维导图 " + (focus or selection or ""))
    # 缓存命中检查（性能优化 §7 决策 5）：同书同章同选区/焦点直接回放，不重复调用 LLM
    cache_key_input = cache_key({
        "chapter": chapter.id,
        "content": chapter_fingerprint(chapter),
        "selection": selection,
        "focus": focus,
        "body": enable_body,
        "send_page": send_page,
        "page_index": chapter.page_index,
    })
    hit = get_llm_cache(db, book.id, "mindmap", cache_key_input)
    if hit is not None and hit.get("tree"):
        return {**hit, "cached": True}
    skills = load_skills(db, book.id, task_text=f"思维导图 {focus or selection or ''}")
    messages = build_mindmap_messages(
        book, chapter, selection, focus, rag_chunks, skills, enable_body, page_image, page_context
    )
    client = build_client(db)
    reply = client.chat(messages)
    tree = parse_mindmap_json(reply)
    if tree is None:
        tree = markdown_to_tree(reply, title=f"第{chapter.index}章 {chapter.title}")
    else:
        tree = _clean_node(tree)
    if not tree.get("name"):
        tree["name"] = f"第{chapter.index}章 {chapter.title}"
    markdown = tree_to_markdown(tree)
    citations = extract_citations(reply)
    try:
        persist_chat(
            db, book.id, chapter.id, selection, f"生成脑图：{focus or chapter.title}", markdown
        )
    except Exception:  # noqa: BLE001 历史落库失败不影响返回结果
        pass
    data = {"title": tree["name"], "tree": tree, "markdown": markdown, "citations": citations}
    try:
        set_llm_cache(db, book.id, "mindmap", cache_key_input, data)
    except Exception:  # noqa: BLE001 缓存写入失败不影响本次结果
        pass
    return {**data, "cached": False}
