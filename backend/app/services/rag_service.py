"""RAG/Skill 资产生成服务：书籍 → 切块 + LLM 总结 → BookAsset 落库。

- RAG 资产：全书摘要 + 关键知识点（带章节/段落出处）+ 段落级检索片段（chunks）。
- Skill 资产：可复用技能列表（名称/适用场景/用法/出处）。
- 重复总结在原资产上 version + 1（技术栈规范 AI 接入规范）。
- M9 归档链路：PDF 书读完归档时先视觉通读全书并缓存页文本，再以缓存全文总结
  （archive_book_task → page_chunks/build_page_input），成功后触发 post-classify。
"""
import json

from sqlalchemy.orm import Session

from app.ai.client import LLMError
from app.ai.factory import build_client, is_configured
from app.ai.parsing import parse_llm_json
from app.ai.prompts.rag_skill import (
    INCREMENTAL_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_incremental_user_prompt,
    build_user_prompt,
)
from app.repositories import books as book_repo
from app.repositories.assets import delete_asset, get_asset, read_asset_content, upsert_asset
from app.repositories.reading import set_all_chapters_read_flag
from app.services.graph.clustering import post_classify_book
from app.services.graph.keywords import sanitize_cluster_name
from app.services.rag_input import (
    build_llm_input,
    build_page_input,
    chunk_book,
    normalize_skills,
    page_chunks,
)


def _collect_new_material(db: Session, book) -> str:
    """再次阅读归档的增量素材：该书全部笔记/划线/「不理解」+ 最近对话（用户与助手）。"""
    from app.models.activity import ChatMessage, Note

    parts: list[str] = []
    for n in db.query(Note).filter(Note.book_id == book.id).order_by(Note.id).all():
        quote = (n.quote_text or "").strip()
        text = (n.note_text or "").strip()
        if quote or text:
            parts.append(f"[{n.note_type}] {quote} 备注：{text}")
    for m in db.query(ChatMessage).filter(ChatMessage.ref_book_id == book.id).order_by(ChatMessage.id).all()[-20:]:
        role = "用户" if m.role == "user" else "助手"
        parts.append(f"{role}: {(m.content or '')[:300]}")
    return "\n".join(parts) if parts else "（本轮没有新增笔记或对话）"


def archive_book_task(book_id: int) -> dict:
    """M9 读完归档任务：PDF 先视觉通读全书并缓存 → 文本模型总结 RAG/Skill → 标记读完。

    - PDF：隐私开启时调用 rebuild_book_caches 补全缺失页缓存（命中不重复调用），
      再以全书页缓存为输入总结（出处「第 X 页」）；视觉未配置/全部失败时回退章节标题弱总结。
    - 非 PDF：直接按章节正文总结。
    - 成功后章节全部标记已读、书籍状态=读完，并触发 post-classify（两阶段分类 §9）。
    """
    from app.core.database import SessionLocal
    from app.repositories import books as book_repo
    from app.services.vision_extract import read_page_cache, rebuild_book_caches

    db = SessionLocal()
    try:
        book = book_repo.get_book(db, book_id)
        if not book:
            return {"error": "书籍不存在"}
        page_stats: dict | None = None
        page_texts: dict[int, str] | None = None
        if book.format == "pdf" and book.page_count:
            page_stats = rebuild_book_caches(db, book)  # 视觉通读：补全缺失页
            texts = {i: read_page_cache(book, i) for i in range(1, book.page_count + 1)}
            page_texts = {k: v for k, v in texts.items() if v} or None
        result = generate_rag_skill(db, book_id, page_texts=page_texts)
        set_all_chapters_read_flag(db, book, True)  # 标记读完（状态=读完，进度=100%）
        # 三层画像迁移 + 暖记忆联动（失败不阻塞归档）
        try:
            from app.services.profile_service import migrate_profiles_on_archive

            result["profile"] = migrate_profiles_on_archive(db, book, rag=result.get("rag"))
        except Exception:
            db.rollback()
        # post-classify 簇合并/重命名（§9.4.4/9.4.5，失败不阻塞归档）
        try:
            from app.services.graph.clustering import merge_and_rename_clusters

            result["cluster_merge"] = merge_and_rename_clusters(db)
        except Exception:
            db.rollback()
        if page_stats is not None:
            result["page_cache"] = page_stats
        return result
    finally:
        db.close()


def generate_rag_skill(
    db: Session,
    book_id: int,
    *,
    page_texts: dict[int, str] | None = None,
) -> dict:
    """总结书籍为 RAG + Skill 资产并落库；返回资产内容与版本号。

    page_texts：PDF 归档场景传入全书页缓存（见 archive_book_task），此时 RAG 片段与
    LLM 输入正文以页缓存为准（出处「第 X 页」）；否则按章节正文。
    成功后触发该书 post-classify（两阶段分类 §9）。
    """
    book = book_repo.get_book(db, book_id)
    if not book:
        raise ValueError("书籍不存在")
    chapters = book_repo.list_chapters(db, book_id)
    if not chapters:
        raise ValueError("书籍没有可解析的章节")
    if not is_configured(db):
        raise ValueError("未配置 AI_API_KEY：请在设置页或 backend/.env 填写后重试")

    if page_texts:
        chunks = page_chunks(page_texts)
        llm_input = build_page_input(page_texts)
    else:
        chunks = chunk_book(chapters)
        llm_input = build_llm_input(chapters, chunks)

    # 再次阅读归档：已有**实质**资产 → 增量增改模式（旧资产概要 + 新笔记/对话 + 正文）。
    # 图谱联动可能留下空存根（summary/key_points 为空，v1.68 起不 bump 版本）——
    # 空存根视为无资产：先删除存根再全量生成，保证新书首次总结 version=1 且不走增量提示词。
    old_rag_asset = get_asset(db, book_id, "rag")
    old_rag = read_asset_content(db, book_id, "rag") if old_rag_asset else {}
    if old_rag_asset and (old_rag.get("summary") or old_rag.get("key_points")):
        old_skill = read_asset_content(db, book_id, "skill")
        system_prompt = INCREMENTAL_SYSTEM_PROMPT
        user_prompt = build_incremental_user_prompt(
            book.title, old_rag, old_skill, _collect_new_material(db, book), llm_input
        )
    else:
        if old_rag_asset:
            delete_asset(db, book_id, "rag")  # 清除空存根，版本归 1
        system_prompt = SYSTEM_PROMPT
        user_prompt = build_user_prompt(book.title, llm_input)
    client = build_client(db)
    try:
        reply = client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
    except LLMError as exc:
        raise ValueError(f"AI 调用失败：{exc}") from exc

    try:
        parsed = parse_llm_json(reply)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"AI 返回内容无法解析为 JSON：{exc}") from exc

    rag = {
        "title": book.title,
        "summary": parsed.get("summary", ""),
        "key_points": parsed.get("key_points") or parsed.get("concepts") or [],
        "chunks": chunks,
    }
    domains: list[str] = []
    seen_domains: set[str] = set()
    for raw in parsed.get("tags") or []:
        clean = sanitize_cluster_name(raw)
        if clean and clean not in seen_domains:
            seen_domains.add(clean)
            domains.append(clean)
    skill = {
        "name": parsed.get("skill_name") or f"{book.title} 技能包",
        "domains": domains,
        "skills": normalize_skills(parsed.get("skills")),
        "usage": parsed.get("usage", ""),
    }

    rag_asset = upsert_asset(db, book_id, "rag", rag)
    skill_asset = upsert_asset(db, book_id, "skill", skill)
    # 两阶段分类：资产就绪后按后验信息重算该书聚类归属（失败不阻塞资产生成）
    try:
        post_classify_book(db, book)
    except Exception:
        db.rollback()
    return {
        "book_id": book_id,
        "version": max(rag_asset.version, skill_asset.version),
        "rag": rag,
        "skill": skill,
    }
