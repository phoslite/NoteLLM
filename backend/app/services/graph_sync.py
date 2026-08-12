"""图谱联动 RAG/Skill 增量增改服务（需求 3.4.7/3.4.9 跨书联动沉淀）。

- 本地联动存根（无 AI 也能执行）：跨书谱系更新后，把受影响书籍的 RAG 资产补
  linked_books / domain_terms / linked_terms 条目（version+1，内容未变化不写库）；
- 显式 LLM 联动（POST /api/graph/sync）：对强度达标且未忽略的关联，按 rag_link
  提示词对受影响书籍做增量增改（RAG 补跨书关联与共同概念、Skill 融合跨书新方法），
  失败回滚不阻塞，成功后触发该书 post-classify。
"""
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from app.ai.factory import build_client, is_configured
from app.ai.parsing import parse_llm_json
from app.ai.prompts.rag_link import SYSTEM_PROMPT, build_multi_link_user_prompt
from app.core.config import settings
from app.core.time import utcnow
from app.models.book import Book
from app.models.graph import BookRelation
from app.repositories.assets import read_asset_content, save_asset_content, upsert_asset
from app.repositories.books import get_book
from app.repositories.graph import list_active_relations, list_books
from app.repositories.settings import load_ai_overrides
from app.services.graph.clustering import (
    build_posterior_index,
    merge_and_rename_clusters,
    post_classify_book,
)
from app.services.graph.keywords import extract_keywords
from app.services.graph.lexicon import generic_domain_terms
from app.services.html_util import html_to_text

# 本地联动存根的关联强度下限（与相关度阈值初值对齐）
LINK_MIN_STRENGTH = 50.0
# linked_books 保留最近条目数
MAX_LINKED_BOOKS = 20
# L1：每本书单轮聚合联动边上限（超出部分只补本地存根，不参与 LLM 上下文）
MAX_LINKS_PER_BOOK = 8


def load_reasons(rel: BookRelation) -> list[str]:
    """读取关联原因列表（reasons_json 反序列化，异常返回空）。"""
    try:
        reasons = json.loads(rel.reasons_json or "[]")
    except (ValueError, TypeError):
        return []
    return reasons if isinstance(reasons, list) else []


def _link_fingerprint(edges: list[dict]) -> str:
    """本轮联动边集合的稳定指纹（L1 幂等）：rel_id + 强度 + 方向排序哈希。

    任一边增删/强度/方向变化 → 指纹变化 → 重新联动；重跑一致 → 跳过 LLM。
    """
    payload = json.dumps(
        sorted((e["rel_id"], round(float(e["strength"]), 1), e["direction"]) for e in edges),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _upsert_if_changed(db: Session, book_id: int, kind: str, content: dict) -> bool:
    """内容未变化不写库；变化时用 save_asset_content 写入且**不递增版本**——联动存根
    （linked_books/domain_terms）是辅助元数据，不应 bump 版本导致 post-classify 频繁失效
    或污染资产版本语义（v1.68 修复：新书存根曾被每条关联边连续 +1）。"""
    if read_asset_content(db, book_id, kind) == content:
        return False
    save_asset_content(db, book_id, kind, content)
    return True


def rag_book_input(db: Session, book: Book, budget: int = 3000) -> str:
    """轻量 RAG 素材：章节标题 + 正文（截断），供联动上下文与本地存根使用（无 AI 能力也可用）。"""
    parts: list[str] = []
    for ch in book.chapters:
        body = (ch.content_text or "").strip()
        if book.format == "epub" and body:
            body = html_to_text(body).strip()
        head = f"第{ch.index}章 {ch.title}"
        if body:
            head += "：" + body
        parts.append(head)
    text = "\n".join(parts) or book.title
    return text[:budget]


def link_domain_terms(db: Session) -> int:
    """RAG 术语补水：为有 RAG 资产的书籍补 domain_terms（书名 + key_points 术语，跳过泛化词）。"""
    updated = 0
    for book in list_books(db):
        rag = read_asset_content(db, book.id, "rag")
        if not rag:
            continue
        texts = [book.title or ""]
        for kp in rag.get("key_points") or []:
            texts.append(kp if isinstance(kp, str) else str(kp.get("title") or kp.get("point") or ""))
        terms = [t for t in extract_keywords(" ".join(texts), 40) if t not in generic_domain_terms()]
        existing = set(rag.get("domain_terms") or [])
        fresh = [t for t in terms if t not in existing]
        if not fresh:
            continue
        rag["domain_terms"] = list(existing | set(terms))[:40]
        rag["linked_terms"] = list(dict.fromkeys((rag.get("linked_terms") or []) + fresh))[:40]
        if _upsert_if_changed(db, book.id, "rag", rag):
            updated += 1
    return updated


def attach_linked_book_stub(
    db: Session, book: Book, other: Book, strength: float, reasons: list[str], direction: str = "无"
) -> bool:
    """本地联动存根：RAG 资产补 linked_books 条目（无 AI 也可执行；内容未变化不写库）。"""
    direction = direction if direction in ("承接", "发展", "批判") else "无"
    rag = read_asset_content(db, book.id, "rag")
    if not rag:
        rag = {"title": book.title, "summary": "", "key_points": [], "chunks": []}
    existing = rag.get("linked_books") or []
    if any(x.get("book_id") == other.id and x.get("strength") == round(float(strength), 1) for x in existing):
        return False
    linked = [x for x in existing if x.get("book_id") != other.id]
    linked.append(
        {
            "book_id": other.id,
            "title": other.title,
            "strength": round(float(strength), 1),
            "direction": direction,
            "reasons": reasons,
            "linked_at": utcnow().isoformat(),
        }
    )
    rag["linked_books"] = linked[-MAX_LINKED_BOOKS:]
    return _upsert_if_changed(db, book.id, "rag", rag)


def link_relation_stubs(db: Session, rel: BookRelation) -> int:
    """为单条关联的两本书补本地 RAG 存根，返回新增条目数。"""
    if not rel or rel.user_feedback == "忽略" or rel.strength < LINK_MIN_STRENGTH:
        return 0
    a = get_book(db, rel.book_a_id)
    b = get_book(db, rel.book_b_id)
    if not a or not b:
        return 0
    reasons = load_reasons(rel)
    n = 0
    for book, other in ((a, b), (b, a)):
        if attach_linked_book_stub(db, book, other, rel.strength, reasons, rel.direction or "无"):
            n += 1
    return n


def link_graph_assets(db: Session) -> dict:
    """本地联动（自动执行，无需 AI）：强度达标且未忽略的关联补存根 + RAG 术语补水。"""
    stubs = 0
    for rel in list_active_relations(db):
        stubs += link_relation_stubs(db, rel)
    return {"stubs": stubs, "domain_terms": link_domain_terms(db)}



def _prepare_link_update(
    db: Session, book: Book, links: list[dict], *, force: bool = False
) -> tuple[Book, dict, dict, str, list[dict]] | None:
    """L2 准备阶段（主线程）：指纹判定 + 读旧资产 + 构造 multi-link 提示词。

    links 为该书本轮参与 LLM 的关联边（按强度降序、≤ MAX_LINKS_PER_BOOK）。
    返回 (book, old_rag, old_skill, fingerprint, messages)；指纹命中返回 None（跳过 LLM、不 bump 版本）。
    """
    fingerprint = _link_fingerprint(links)
    old_rag = read_asset_content(db, book.id, "rag")
    if not force and old_rag.get("linked_sync_fingerprint") == fingerprint:
        return None
    old_skill = read_asset_content(db, book.id, "skill")
    link_parts = [
        {
            "other_title": link["other_title"],
            "relation_desc": link["relation_desc"],
            "reasons": link["reasons"],
        }
        for link in links
    ]
    user_prompt = build_multi_link_user_prompt(
        book.title, link_parts, old_rag, old_skill, rag_book_input(db, book)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return book, old_rag, old_skill, fingerprint, messages


def _apply_link_update(
    db: Session, book: Book, old_rag: dict, old_skill: dict, fingerprint: str, reply: str
) -> None:
    """L2 落盘阶段（主线程）：解析 LLM 回复并整体覆盖 RAG/Skill（短事务，commit 由 upsert_asset 承担）。

    解析或落盘失败抛异常，由调用方按书回滚并继续，不中断其它书。
    """
    parsed = parse_llm_json(reply)
    rag = {
        "title": book.title,
        "summary": parsed.get("summary", old_rag.get("summary", "")),
        "key_points": parsed.get("key_points") or old_rag.get("key_points", []),
        "chunks": old_rag.get("chunks", []),
        "linked_books": old_rag.get("linked_books", []),
        "domain_terms": old_rag.get("domain_terms", []),
        "linked_terms": old_rag.get("linked_terms", []),
        "linked_sync_fingerprint": fingerprint,
    }
    skill = {
        "name": parsed.get("skill_name") or old_skill.get("name") or f"{book.title} 技能包",
        "domains": parsed.get("tags") or old_skill.get("domains", []),
        "skills": parsed.get("skills") or old_skill.get("skills", []),
        "usage": parsed.get("usage", old_skill.get("usage", "")),
    }
    upsert_asset(db, book.id, "rag", rag)
    upsert_asset(db, book.id, "skill", skill)


def _chat_safe(client, messages: list[dict]) -> str | BaseException:
    """L2 并发 chat 包装：子线程只做网络 IO（红线 1）；单书失败返回异常对象，不中断其它书。"""
    try:
        return client.chat(messages)
    except Exception as exc:  # noqa: BLE001
        return exc


def _sync_llm_workers(db: Session, total: int) -> int:
    """L2 worker 数：设置页/GRAPH_SYNC_CONCURRENCY 默认 1=串行；0=不限制（min(书数, 8)）；N=上限（cap 8）。

    运行时覆盖（设置页保存）优先，未覆盖取 .env；并发仍受 ai_concurrency 信号量约束
    （client.chat 内部统一限流，决策 35 红线 3）。
    """
    n = load_ai_overrides(db).get("graph_sync_concurrency", settings.graph_sync_concurrency)
    if n == 0:
        return min(max(total, 1), 8)  # 0=不限制（min(书数, 8)）
    if n <= 1:
        return 1  # 默认串行
    return min(n, 8)


def apply_relation_feedback(
    db: Session, rel, action: str, strength: float | None = None
) -> None:
    """人工反馈业务（审查 P0-2）：确认/忽略/修改强度回写；确认/修改联动补 RAG 存根。

    action 非法抛 ValueError（路由转 400）；成功提交后补联动存根（失败回滚不阻塞反馈）。
    """
    if action == "确认":
        rel.user_feedback = "确认"
    elif action == "忽略":
        rel.user_feedback = "忽略"
    elif action == "修改":
        if strength is None:
            raise ValueError("修改强度需传入 strength")
        rel.user_feedback = "修改"
        rel.strength = max(0.0, min(100.0, float(strength)))
    else:
        raise ValueError("action 仅支持 确认/忽略/修改")
    db.commit()
    if action in ("确认", "修改"):
        try:
            link_relation_stubs(db, rel)
        except Exception:
            db.rollback()


def sync_assets_for_relations(
    db: Session,
    relation_ids: list[int] | None = None,
    *,
    use_llm: bool | None = None,
    force: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """对受影响书籍执行跨书联动增量增改。

    - 始终补本地 RAG 存根（linked_books）；
    - use_llm 未指定时：已配置 AI 才走 LLM（POST /api/graph/sync 显式调用）；
    - force=True 忽略幂等指纹强制联动（L1，预留参数；任务/路由层暂不暴露）；
    - on_progress(done, total) 在 LLM 落盘阶段每完成一本书回调一次（L2，total=落盘书数，
      指纹跳过瞬时完成不计入；任务层映射进度条）；
    - LLM 阶段三段式执行（L2）：主线程准备 → 并发 chat（仅网络 IO，GRAPH_SYNC_CONCURRENCY
      控制 worker 数，默认 1=串行）→ 主线程落盘（每书独立事务，失败回滚不阻塞）；
    - 返回 {"stubs": 新增存根数, "llm_updated": LLM 更新书数, "llm_skipped": 指纹命中跳过书数}。
    """
    relations = list_active_relations(db, relation_ids)
    llm_enabled = is_configured(db) if use_llm is None else (use_llm and is_configured(db))
    stubs = 0
    by_book: dict[int, list[dict]] = defaultdict(list)  # L1：按书聚合本轮关联边
    for rel in relations:
        stubs += link_relation_stubs(db, rel)
        if not llm_enabled or rel.strength < LINK_MIN_STRENGTH:
            continue
        a = db.get(Book, rel.book_a_id)
        b = db.get(Book, rel.book_b_id)
        if not a or not b:
            continue
        reasons = load_reasons(rel)
        relation_desc = f"（{rel.relation_type}，强度 {rel.strength}）"
        direction = rel.direction or "无"
        for book, other in ((a, b), (b, a)):
            by_book[book.id].append(
                {
                    "rel_id": rel.id,
                    "strength": rel.strength,
                    "direction": direction,
                    "other_title": other.title,
                    "relation_desc": relation_desc,
                    "reasons": reasons,
                }
            )
    llm_updated = 0
    llm_skipped = 0  # L1：指纹命中跳过数
    affected: set[int] = set()  # L0：LLM 更新受影响书，循环后统一 post-classify（每本一次）
    # L2 准备阶段（主线程，只读）：指纹判定 + 构造提示词，id 升序保证确定性
    pending: list[tuple[Book, dict, dict, str, list[dict]]] = []
    for book_id in sorted(by_book):
        edges = by_book[book_id]
        edges.sort(key=lambda edge: -float(edge["strength"]))
        book = db.get(Book, book_id)
        if book is None:
            continue
        prep = _prepare_link_update(db, book, edges[:MAX_LINKS_PER_BOOK], force=force)
        if prep is None:
            llm_skipped += 1
        else:
            pending.append(prep)
    # L2 并发 chat（仅网络 IO，不触碰 Session/ORM；client 线程安全可共享；失败按书隔离）
    if pending:
        client = build_client(db)
        workers = _sync_llm_workers(db, len(pending))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="graph-sync") as pool:
                replies = list(pool.map(lambda m: _chat_safe(client, m), [p[4] for p in pending]))
        else:
            replies = [_chat_safe(client, p[4]) for p in pending]
        # L2 落盘阶段（主线程串行）：解析 + upsert，每书独立事务边界
        done = 0
        total = len(pending)
        for (book, old_rag, old_skill, fingerprint, _messages), reply in zip(pending, replies, strict=True):
            try:
                if isinstance(reply, BaseException):
                    raise reply
                _apply_link_update(db, book, old_rag, old_skill, fingerprint, reply)
                affected.add(book.id)
                llm_updated += 1
            except Exception:
                db.rollback()
            done += 1
            if on_progress is not None:
                on_progress(done, total)
    # L0：LLM 更新落库完成后统一后验分类——复用簇代表特征索引（O(M·C) → O(C)），
    # 每本独立 try/except，post-classify 失败只回滚分类、不丢已成功更新的资产。
    if affected:
        index = build_posterior_index(db)
        for book_id in sorted(affected):
            book = db.get(Book, book_id)
            if book is None:
                continue
            try:
                post_classify_book(db, book, index=index)
            except Exception:
                db.rollback()
        try:
            merge_and_rename_clusters(db)
        except Exception:
            db.rollback()
    return {"stubs": stubs, "llm_updated": llm_updated, "llm_skipped": llm_skipped}