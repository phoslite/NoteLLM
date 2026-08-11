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
    CHUNK_SYSTEM_PROMPT,
    INCREMENTAL_SYSTEM_PROMPT,
    MERGE_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_chunk_user_prompt,
    build_incremental_user_prompt,
    build_merge_user_prompt,
    build_user_prompt,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories import books as book_repo
from app.repositories.assets import delete_asset, get_asset, read_asset_content, upsert_asset
from app.repositories.chat import list_recent_messages
from app.repositories.notes import list_notes
from app.repositories.reading import set_all_chapters_read_flag
from app.repositories.settings import load_ai_overrides
from app.services.graph.clustering import merge_and_rename_clusters, post_classify_book
from app.services.graph.keywords import sanitize_cluster_name
from app.services.profile_service import migrate_profiles_on_archive
from app.services.rag_input import (
    chunk_book,
    chunk_chapters_for_summary,
    chunk_page_texts_for_summary,
    normalize_skills,
    page_chunks,
)
from app.services.vision_extract import missing_page_caches, read_page_cache, rebuild_book_caches
from app.tasks import update_progress


def _collect_new_material(db: Session, book) -> str:
    """再次阅读归档的增量素材：该书全部笔记/划线/「不理解」+ 最近对话（用户与助手）。"""

    parts: list[str] = []
    for n in list_notes(db, book.id):
        quote = (n.quote_text or "").strip()
        text = (n.note_text or "").strip()
        if quote or text:
            parts.append(f"[{n.note_type}] {quote} 备注：{text}")
    for m in list_recent_messages(db, book.id, limit=20):
        role = "用户" if m.role == "user" else "助手"
        parts.append(f"{role}: {(m.content or '')[:300]}")
    return "\n".join(parts) if parts else "（本轮没有新增笔记或对话）"


def _chat_once(client, system_prompt: str, user_prompt: str) -> dict:
    """单次 LLM 调用并解析 JSON；错误统一转 ValueError。"""
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
        return parse_llm_json(reply)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"AI 返回内容无法解析为 JSON：{exc}") from exc


def _format_map_results(results: list[dict]) -> str:
    """map 轮各块中间结果 → reduce 输入文本。"""
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        kp_lines: list[str] = []
        for k in r.get("key_points") or []:
            if isinstance(k, str):
                kp_lines.append(k)
            elif isinstance(k, dict):
                kp_lines.append(str(k.get("title") or k.get("point") or k))
        skill_lines = [
            f"- {s['name']}（适用：{s['applicable']}）用法：{s['usage']}"
            for s in normalize_skills(r.get("skills"))
        ]
        parts.append(
            f"【片段 {i}】\nkey_points:\n"
            + ("\n".join(kp_lines) or "（无）")
            + "\nskills:\n"
            + ("\n".join(skill_lines) or "（无）")
        )
    return "\n\n".join(parts)


def _map_reduce_summarize(
    client,
    book_title: str,
    blocks: list[str],
    *,
    is_incremental: bool,
    old_rag: dict | None,
    old_skill: dict | None,
    new_material: str,
) -> dict:
    """方案 B：map 逐块提炼 key_points/skills → reduce 合并为完整资产。

    - 单块失败（LLMError/解析错误）跳过，其余块照常合并；
    - 全部失败回退单次调用（仅发第一块），保证至少有一次总结机会。
    """
    results: list[dict] = []
    total = len(blocks)
    for i, block in enumerate(blocks, 1):
        # 文本块处理可视化进度（决策 35 权重：文本总结区间 65→95，map 占 25 点）
        update_progress(65 + 25 * (i - 1) // max(1, total), f"文本总结 块 {i}/{total}（处理中）")
        try:
            reply = client.chat(
                [
                    {"role": "system", "content": CHUNK_SYSTEM_PROMPT},
                    {"role": "user", "content": build_chunk_user_prompt(book_title, block, i, len(blocks))},
                ]
            )
            results.append(parse_llm_json(reply))
            update_progress(65 + 25 * i // max(1, total), f"文本总结 块 {i}/{total} 完成")
        except (LLMError, ValueError, json.JSONDecodeError):
            continue
    if not results:
        update_progress(92, "文本总结回退单次调用")
        if is_incremental:
            system_prompt = INCREMENTAL_SYSTEM_PROMPT
            user_prompt = build_incremental_user_prompt(book_title, old_rag, old_skill, new_material, blocks[0])
        else:
            system_prompt = SYSTEM_PROMPT
            user_prompt = build_user_prompt(book_title, blocks[0])
        return _chat_once(client, system_prompt, user_prompt)
    blocks_text = _format_map_results(results)
    update_progress(92, "文本模型合并总结")
    return _chat_once(
        client,
        MERGE_SYSTEM_PROMPT,
        build_merge_user_prompt(
            book_title,
            blocks_text,
            old_rag=old_rag if is_incremental else None,
            old_skill=old_skill if is_incremental else None,
            new_material=new_material if is_incremental else "",
        ),
    )


def archive_book_task(book_id: int) -> dict:
    """M9 读完归档任务：PDF 先视觉通读全书并缓存 → 文本模型总结 RAG/Skill → 标记读完。

    - PDF：**仅从未建立缓存的页开始视觉提取**（已缓存页直接复用，不重复调用多模态 API；
      force=False 由 _cache_one 命中跳过）；页缓存无缺失时整段跳过视觉提取，
      进度条不显示视觉提取阶段；再以全书页缓存为输入总结（出处「第 X 页」）；
      视觉未配置/全部失败时回退章节标题弱总结。
    - 非 PDF：直接按章节正文总结。
    - 成功后章节全部标记已读、书籍状态=读完，并触发 post-classify（两阶段分类 §9）。
    """

    db = SessionLocal()
    try:
        book = book_repo.get_book(db, book_id)
        if not book:
            return {"error": "书籍不存在"}
        page_stats: dict | None = None
        page_texts: dict[int, str] | None = None
        if book.format == "pdf" and book.page_count:
            # 权重（决策 35）：视觉通读 60 / 文本总结 40；先预检缺失页，无缺失直接跳过视觉提取
            missing = missing_page_caches(book)
            if not missing:
                # 页缓存已完整：不进入视觉提取（无视觉 API 调用、无压缩页图预生成、进度条不显示该阶段）
                page_stats = {
                    "total": book.page_count,
                    "extracted": 0,
                    "cached": book.page_count,
                    "failed": 0,
                    "errors": [],
                }
                texts = {i: read_page_cache(book, i) for i in range(1, book.page_count + 1)}
                page_texts = {k: v for k, v in texts.items() if v} or None
                update_progress(60, f"页缓存已完整（{book.page_count}/{book.page_count}），跳过视觉提取")
            else:
                update_progress(5, f"补齐缺失页缓存（缺失 {len(missing)}/{book.page_count} 页）")

                def _on_page_progress(done: int, total: int) -> None:
                    update_progress(5 + 55 * max(0, min(total, done)) // max(1, total), f"视觉提取 {done}/{total} 页")

                page_stats = rebuild_book_caches(db, book, progress=_on_page_progress)  # force=False：跳过已缓存页
                texts = {i: read_page_cache(book, i) for i in range(1, book.page_count + 1)}
                page_texts = {k: v for k, v in texts.items() if v} or None
                update_progress(
                    60,
                    f"视觉通读完成：提取 {page_stats['extracted']} · 复用缓存 {page_stats['cached']} · 失败 {page_stats['failed']}",
                )
        update_progress(65, "文本模型总结 RAG/Skill")
        result = generate_rag_skill(db, book_id, page_texts=page_texts)
        update_progress(95, "归档收尾")
        set_all_chapters_read_flag(db, book, True)  # 标记读完（状态=读完，进度=100%）
        # 三层画像迁移 + 暖记忆联动（失败不阻塞归档）
        try:
            result["profile"] = migrate_profiles_on_archive(db, book, rag=result.get("rag"))
        except Exception:
            db.rollback()
        # post-classify 簇合并/重命名（§9.4.4/9.4.5，失败不阻塞归档）
        try:
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

    chunk_chars = settings.rag_summary_chunk_chars
    # 三审 Major-2：隐私开关以设置页 DB 覆盖为准（与 chat/vision/mindmap 一致），纯函数侧通过 enable_body 透传
    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    if page_texts:
        chunks = page_chunks(page_texts)
        blocks = chunk_page_texts_for_summary(page_texts, chunk_chars, enable_body=enable_body)
    else:
        chunks = chunk_book(chapters, is_html=book.format == "epub")
        blocks = chunk_chapters_for_summary(chapters, chunks, chunk_chars, enable_body=enable_body)

    # 再次阅读归档：已有**实质**资产 → 增量增改模式（旧资产概要 + 新笔记/对话 + 正文）。
    # 图谱联动可能留下空存根（summary/key_points 为空，v1.68 起不 bump 版本）——
    # 空存根视为无资产：先删除存根再全量生成，保证新书首次总结 version=1 且不走增量提示词。
    old_rag_asset = get_asset(db, book_id, "rag")
    old_rag = read_asset_content(db, book_id, "rag") if old_rag_asset else {}
    is_incremental = bool(old_rag_asset and (old_rag.get("summary") or old_rag.get("key_points")))
    if not is_incremental and old_rag_asset:
        delete_asset(db, book_id, "rag")  # 清除空存根，版本归 1
    old_skill = read_asset_content(db, book_id, "skill") if is_incremental else None
    new_material = _collect_new_material(db, book) if is_incremental else ""

    client = build_client(db)
    if len(blocks) <= 1:
        # 短书/隐私关闭：单次调用（正文上限取配置 64K，不再 8K 截断只覆盖前几章）
        llm_input = blocks[0]
        if is_incremental:
            system_prompt = INCREMENTAL_SYSTEM_PROMPT
            user_prompt = build_incremental_user_prompt(book.title, old_rag, old_skill, new_material, llm_input)
        else:
            system_prompt = SYSTEM_PROMPT
            user_prompt = build_user_prompt(book.title, llm_input)
        update_progress(90, "文本模型总结（单块）")
        parsed = _chat_once(client, system_prompt, user_prompt)
    else:
        # 长书（>64K 字符）：方案 B map-reduce 分块提炼
        # （单块失败跳过；全部失败回退单次调用，与旧行为一致）
        parsed = _map_reduce_summarize(
            client,
            book.title,
            blocks,
            is_incremental=is_incremental,
            old_rag=old_rag,
            old_skill=old_skill,
            new_material=new_material,
        )

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
