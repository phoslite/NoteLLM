"""图谱联动 RAG/Skill 增量增改服务（需求 3.4.7/3.4.9 跨书联动沉淀）。

- 本地联动存根（无 AI 也能执行）：跨书谱系更新后，把受影响书籍的 RAG 资产补
  linked_books / domain_terms / linked_terms 条目（version+1，内容未变化不写库）；
- 显式 LLM 联动（POST /api/graph/sync）：对强度达标且未忽略的关联，按 rag_link
  提示词对受影响书籍做增量增改（RAG 补跨书关联与共同概念、Skill 融合跨书新方法），
  失败回滚不阻塞，成功后触发该书 post-classify。
"""
import json

from sqlalchemy.orm import Session

from app.ai.factory import build_client, is_configured
from app.ai.parsing import parse_llm_json
from app.ai.prompts.rag_link import SYSTEM_PROMPT, build_link_user_prompt
from app.core.time import utcnow
from app.models.book import Book
from app.models.graph import BookRelation
from app.repositories.assets import read_asset_content, save_asset_content, upsert_asset
from app.repositories.graph import list_active_relations, list_books
from app.services.graph.clustering import post_classify_book
from app.services.graph.keywords import extract_keywords
from app.services.graph.lexicon import generic_domain_terms
from app.services.html_util import html_to_text

# 本地联动存根的关联强度下限（与相关度阈值初值对齐）
LINK_MIN_STRENGTH = 50.0
# linked_books 保留最近条目数
MAX_LINKED_BOOKS = 20


def load_reasons(rel: BookRelation) -> list[str]:
    """读取关联原因列表（reasons_json 反序列化，异常返回空）。"""
    try:
        reasons = json.loads(rel.reasons_json or "[]")
    except (ValueError, TypeError):
        return []
    return reasons if isinstance(reasons, list) else []


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
    a = db.get(Book, rel.book_a_id)
    b = db.get(Book, rel.book_b_id)
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


def _llm_link_update(db: Session, book: Book, other: Book, rel: BookRelation, reasons: list[str]) -> None:
    """LLM 增量增改：以旧资产 + 本轮跨书关联为输入，输出合并后的 RAG/Skill 整体覆盖。"""
    old_rag = read_asset_content(db, book.id, "rag")
    old_skill = read_asset_content(db, book.id, "skill")
    relation_desc = f"（{rel.relation_type}，强度 {rel.strength}）"
    user_prompt = build_link_user_prompt(
        book.title, other.title, relation_desc, reasons, old_rag, old_skill, rag_book_input(db, book)
    )
    client = build_client(db)
    reply = client.chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
    )
    parsed = parse_llm_json(reply)
    rag = {
        "title": book.title,
        "summary": parsed.get("summary", old_rag.get("summary", "")),
        "key_points": parsed.get("key_points") or old_rag.get("key_points", []),
        "chunks": old_rag.get("chunks", []),
        "linked_books": old_rag.get("linked_books", []),
        "domain_terms": old_rag.get("domain_terms", []),
        "linked_terms": old_rag.get("linked_terms", []),
    }
    skill = {
        "name": parsed.get("skill_name") or old_skill.get("name") or f"{book.title} 技能包",
        "domains": parsed.get("tags") or old_skill.get("domains", []),
        "skills": parsed.get("skills") or old_skill.get("skills", []),
        "usage": parsed.get("usage", old_skill.get("usage", "")),
    }
    upsert_asset(db, book.id, "rag", rag)
    upsert_asset(db, book.id, "skill", skill)
    try:
        post_classify_book(db, book)
    except Exception:
        db.rollback()


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
    db: Session, relation_ids: list[int] | None = None, *, use_llm: bool | None = None
) -> dict:
    """对受影响书籍执行跨书联动增量增改。

    - 始终补本地 RAG 存根（linked_books）；
    - use_llm 未指定时：已配置 AI 才走 LLM（POST /api/graph/sync 显式调用）；
    - 返回 {"stubs": 新增存根数, "llm_updated": LLM 更新书数}。
    """
    relations = list_active_relations(db, relation_ids)
    llm_enabled = is_configured(db) if use_llm is None else (use_llm and is_configured(db))
    stubs = 0
    llm_updated = 0
    for rel in relations:
        stubs += link_relation_stubs(db, rel)
        if not llm_enabled or rel.strength < LINK_MIN_STRENGTH:
            continue
        a = db.get(Book, rel.book_a_id)
        b = db.get(Book, rel.book_b_id)
        if not a or not b:
            continue
        reasons = load_reasons(rel)
        for book, other in ((a, b), (b, a)):
            try:
                _llm_link_update(db, book, other, rel, reasons)
                llm_updated += 1
            except Exception:
                db.rollback()
    return {"stubs": stubs, "llm_updated": llm_updated}