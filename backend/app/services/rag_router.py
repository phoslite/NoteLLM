"""决策 34：LLM 自主挑选 RAG/Skill 注入（跨书知识路由，验收 15 / 里程碑 §8.1-1）。

两级混合：
① 书级挑选——候选目录（按领域分组、冷画像偏好领域优先）交 LLM 输出
   {selected_books, selected_skills, reasons}（独立挑选器配置，低 max_tokens、禁思考）；
② 内容注入——对选中书逐个规则关键词检索 chunks（跨书出处【《书名》第X章 第Y段】）
   与 Skill 全文注入；当前书有资产时始终选入。

降级：LLM 未配置 / 调用失败 / 输出无法解析 → 规则化候选（当前书 + 暖画像相关 top3 +
谱系关联 top2 + 关键词检索，即决策 34 定义的降级方案）。
会话缓存：按 session_id + chapter_id 缓存挑选结果（TTL 可配，0=不缓存）。

决策 37（主页全局 AI 对话）：`select_global_knowledge` 无当前书/章节，从全库目录挑选
（LLM 全局提示词 → 规则降级：摘要/内容关键词相关 top3 书 + 全局 Skill 相关性 top N）；
缓存键 `global:{session_id}`。
"""
import json
import re
import threading
import time
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai.factory import build_selector_client
from app.ai.parsing import parse_llm_json
from app.ai.prompts.rag_select import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_GLOBAL,
    build_global_user_prompt,
    build_user_prompt,
)
from app.core.config import settings
from app.models.book import Book, Folder
from app.models.graph import BookRelation
from app.repositories.assets import (
    get_asset,
    list_assets_by_books,
    load_all_skills,
    load_skills,
    read_asset_content,
    retrieve_rag_chunks,
)
from app.services.profile_service import get_all_profiles

# 候选目录与注入控制
CATALOG_SUMMARY_CHARS = 60  # 每书 RAG 摘要截断长度
CATALOG_SKILL_NAMES = 5  # 目录中每书最多列出的技能名
CATALOG_MAX_ENTRIES = 150  # 目录硬上限（防止数百本时 prompt 过大）
INJECT_TOP_K_PER_BOOK = 3  # 每书最多注入的 chunks 数（预算 3 书共 ≤9 段）

_UNCATEGORIZED = "未分类"


@dataclass
class SelectionResult:
    source: str  # llm / fallback / cache
    book_ids: list[int]
    skill_refs: list[dict]  # [{"book_id": int, "name": str}]
    reasons: str = ""


# 会话挑选缓存：{cache_key: (expire_ts, payload)}；进程内（重启后重新挑选，可接受）
_SESSION_CACHE: dict[str, tuple[float, dict]] = {}
_SESSION_CACHE_MAX = 200  # 容量上限（审查问题 10）：写时清扫过期 + 淘汰最旧
_SESSION_LOCK = threading.Lock()


# ---------------------------------------------------------------- 候选目录

def _book_domain(book: Book, folder_names: dict[int, str]) -> str:
    """领域分组：用户 tag 优先（首个 tag），其次文件夹名，其次聚类领域，最后「未分类」。

    审查 A-7：folder 名一次性批量加载传入，消除逐书查询。
    """
    try:
        tags = json.loads(book.tags_json or "[]")
    except (TypeError, ValueError):
        tags = []
    if tags:
        return str(tags[0])
    if book.folder_id:
        name = folder_names.get(book.folder_id)
        if name:
            return name
    return book.cluster_name or _UNCATEGORIZED


def _has_assets(db: Session, book_id: int) -> bool:
    return bool(get_asset(db, book_id, "rag") or get_asset(db, book_id, "skill"))


def build_catalog(db: Session, current_book_id: int) -> tuple[str, dict[int, dict]]:
    """构建候选目录：{领域: [书项]} 按冷画像偏好排序；返回 (目录文本, 书项索引)。

    书项 = {book_id, title, domain, summary, skill_names}；仅包含有 RAG/Skill 资产的书。
    """
    books = db.query(Book).order_by(Book.id).all()
    # 审查 A-7：资产与文件夹名一次性批量加载，目录构建从 5N-6N 次查询降为常数次
    assets_map = list_assets_by_books(db)
    folder_names = {f.id: f.name for f in db.query(Folder).all()}
    index: dict[int, dict] = {}
    groups: dict[str, list[dict]] = {}
    for b in books:
        if len(index) >= CATALOG_MAX_ENTRIES:
            break
        assets = assets_map.get(b.id)
        if not assets:
            continue
        rag = assets.get("rag") or {}
        skill = assets.get("skill") or {}
        summary = str(rag.get("summary") or "")[:CATALOG_SUMMARY_CHARS]
        skill_names = [str(s.get("name") or "") for s in (skill.get("skills") or []) if s.get("name")]
        item = {
            "book_id": b.id,
            "title": b.title or "",
            "domain": _book_domain(b, folder_names),
            "summary": summary,
            "skill_names": skill_names[:CATALOG_SKILL_NAMES],
        }
        index[b.id] = item
        groups.setdefault(item["domain"], []).append(item)

    # 冷画像偏好领域优先展开
    cold = (get_all_profiles(db).get("cold") or {}).get("domain_preferences") or {}
    try:
        pref_order = [d for d, _ in sorted(cold.items(), key=lambda kv: -int(kv[1]))]
    except (TypeError, ValueError):
        pref_order = list(cold.keys())
    ordered_domains = [d for d in pref_order if d in groups] + [
        d for d in groups if d not in pref_order
    ]
    if _UNCATEGORIZED in ordered_domains:
        ordered_domains.remove(_UNCATEGORIZED)
        ordered_domains.append(_UNCATEGORIZED)

    lines = []
    for domain in ordered_domains:
        lines.append(f"【{domain}】")
        for item in groups[domain]:
            mark = "（【当前阅读】）" if item["book_id"] == current_book_id else ""
            skills_txt = ("，技能：" + "、".join(item["skill_names"])) if item["skill_names"] else ""
            lines.append(
                f"- id={item['book_id']} 《{item['title']}》{mark}摘要：{item['summary'] or '（无摘要）'}{skills_txt}"
            )
    return "\n".join(lines), index


# ---------------------------------------------------------------- 挑选

def _selection_payload(result: SelectionResult, db: Session, question: str) -> dict:
    """挑选结果 → 注入内容（跨书 chunks + Skill 全文）。"""
    chunks = []
    for book_id in result.book_ids:
        book = db.get(Book, book_id)
        if not book:
            continue
        for c in retrieve_rag_chunks(db, book_id, question, top_k=INJECT_TOP_K_PER_BOOK):
            chunks.append({**c, "book_id": book_id, "book_title": book.title})
    skills = []
    for ref in result.skill_refs[: settings.rag_select_max_skills]:
        book = db.get(Book, ref["book_id"])
        if not book:
            continue
        content = read_asset_content(db, ref["book_id"], "skill") or {}
        for s in content.get("skills") or []:
            if str(s.get("name") or "") == ref["name"]:
                skills.append({**s, "book_id": ref["book_id"], "book_title": book.title})
                break
    return {
        "chunks": chunks,
        "skills": skills,
        "selection": {
            "book_ids": result.book_ids,
            "skill_refs": result.skill_refs,
            "reasons": result.reasons,
        },
        "source": result.source,
    }


def _select_llm(
    db: Session,
    book: Book,
    chapter,
    question: str,
    selection: str,
    mode: str | None,
    profiles: dict,
) -> SelectionResult | None:
    """LLM 书级挑选；失败返回 None（调用方回退规则方案）。"""
    catalog_text, index = build_catalog(db, book.id)
    if not index:
        return None
    try:
        client = build_selector_client(db)
        if not (client.api_key or "").strip():
            return None
        cold = profiles.get("cold") or {}
        warm = profiles.get("warm") or {}
        profile_lines = []
        if cold.get("domain_preferences"):
            profile_lines.append("冷画像·领域偏好：" + str(dict(cold["domain_preferences"]))[:200])
        if cold.get("knowledge_level"):
            profile_lines.append(f"冷画像·知识水平：{cold.get('knowledge_level')}")
        if cold.get("language_style"):
            profile_lines.append(f"冷画像·语言风格：{cold.get('language_style')}")
        if cold.get("long_term_interests"):
            profile_lines.append("冷画像·长期兴趣：" + "、".join(str(i) for i in cold["long_term_interests"][:10]))
        recent = warm.get("recent_books") or []
        if recent:
            profile_lines.append(
                "暖画像·近期书：" + "；".join(f"《{r.get('title')}》{str(r.get('summary') or '')[:80]}" for r in recent[-3:])
            )
        related = warm.get("related_books") or []
        if related:
            profile_lines.append("暖画像·相关领域书：" + "、".join(str(r.get("title")) for r in related[:5]))
        chapter_label = f"第{chapter.index}章 {chapter.title}" if chapter is not None else "（未定位章节）"
        user = build_user_prompt(
            book.title or "",
            chapter_label,
            question,
            selection or "",
            mode or "",
            catalog_text,
            "\n".join(profile_lines),
        )
        system = SYSTEM_PROMPT.format(max_books=settings.rag_select_max_books, max_skills=settings.rag_select_max_skills)
        reply = client.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        data = parse_llm_json(reply)
    except Exception:  # noqa: BLE001 挑选失败/超时/解析失败 → 降级规则方案
        return None

    # 校验与预算裁剪
    book_ids: list[int] = []
    for b in data.get("selected_books") or []:
        if not isinstance(b, dict):
            continue
        bid = b.get("book_id")
        if isinstance(bid, int) and bid in index and bid not in book_ids:
            book_ids.append(bid)
    if book.id in index and book.id not in book_ids:
        book_ids.insert(0, book.id)  # 当前书有资产时始终选入
    book_ids = book_ids[: settings.rag_select_max_books]
    skill_refs: list[dict] = []
    for s in data.get("selected_skills") or []:
        if not isinstance(s, dict):
            continue
        bid, name = s.get("book_id"), s.get("name")
        if isinstance(bid, int) and bid in index and name and {"book_id": bid, "name": str(name)} not in skill_refs:
            skill_refs.append({"book_id": bid, "name": str(name)})
    reasons = str(data.get("reasons") or "")
    return SelectionResult(source="llm", book_ids=book_ids, skill_refs=skill_refs[: settings.rag_select_max_skills], reasons=reasons)


def _select_fallback(db: Session, book: Book, question: str) -> SelectionResult:
    """规则降级（决策 34）：当前书 + 暖画像相关 top3 + 谱系关联 top2 + 关键词检索。"""
    book_ids: list[int] = []
    if _has_assets(db, book.id):
        book_ids.append(book.id)
    warm = get_all_profiles(db).get("warm") or {}
    for r in (warm.get("related_books") or [])[:3]:
        bid = r.get("book_id")
        if isinstance(bid, int) and bid not in book_ids and _has_assets(db, bid):
            book_ids.append(bid)
    if len(book_ids) < settings.rag_select_max_books:
        rels = (
            db.query(BookRelation)
            .filter(
                or_(BookRelation.book_a_id == book.id, BookRelation.book_b_id == book.id),
                BookRelation.user_feedback != "忽略",
            )
            .order_by(BookRelation.strength.desc())
            .limit(settings.rag_select_max_books - len(book_ids))
            .all()
        )
        for rel in rels:
            other = rel.book_b_id if rel.book_a_id == book.id else rel.book_a_id
            if other not in book_ids and _has_assets(db, other):
                book_ids.append(other)
    skill_refs: list[dict] = []
    for bid in book_ids[: settings.rag_select_max_books]:
        if len(skill_refs) >= settings.rag_select_max_skills:
            break
        for s in load_skills(db, bid, task_text=question, top_n=settings.rag_select_max_skills):
            if len(skill_refs) >= settings.rag_select_max_skills:
                break
            ref = {"book_id": bid, "name": str(s.get("name") or "")}
            if ref["name"] and ref not in skill_refs:
                skill_refs.append(ref)
    return SelectionResult(source="fallback", book_ids=book_ids, skill_refs=skill_refs)


# ---------------------------------------------------------------- 会话缓存

def _cache_key(session_id: str, chapter_id: int) -> str:
    return f"{session_id}:{chapter_id}"


def _cache_get(key: str) -> dict | None:
    ttl_min = settings.rag_select_cache_ttl_minutes
    if ttl_min <= 0:
        return None
    with _SESSION_LOCK:
        hit = _SESSION_CACHE.get(key)
    if hit is None:
        return None
    expire_ts, payload = hit
    if time.time() >= expire_ts:
        with _SESSION_LOCK:
            _SESSION_CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: dict) -> None:
    ttl_min = settings.rag_select_cache_ttl_minutes
    if ttl_min <= 0:
        return
    with _SESSION_LOCK:
        _SESSION_CACHE[key] = (time.time() + ttl_min * 60, payload)
        if len(_SESSION_CACHE) > _SESSION_CACHE_MAX:
            # 写时清扫：先删过期，仍超限则淘汰最旧条目（字典保持插入序）
            now = time.time()
            for k in [k for k, (exp, _) in _SESSION_CACHE.items() if exp <= now]:
                del _SESSION_CACHE[k]
            overflow = len(_SESSION_CACHE) - _SESSION_CACHE_MAX
            if overflow > 0:
                for k in list(_SESSION_CACHE)[:overflow]:
                    del _SESSION_CACHE[k]


def clear_session_cache(session_id: str | None = None) -> int:
    """清空会话挑选缓存（session_id 为空=全清）；返回清除条数。"""
    removed = 0
    with _SESSION_LOCK:
        if session_id:
            for k in [k for k in _SESSION_CACHE if k.startswith(f"{session_id}:")]:
                del _SESSION_CACHE[k]
                removed += 1
        else:
            removed = len(_SESSION_CACHE)
            _SESSION_CACHE.clear()
    return removed


def clear_global_selection_cache(client_session_id: str) -> int:
    """删除主页全局会话的挑选缓存（决策 37，键 `global:{client_session_id}`）。"""
    key = f"global:{client_session_id}"
    with _SESSION_LOCK:
        if key in _SESSION_CACHE:
            del _SESSION_CACHE[key]
            return 1
    return 0


# ---------------------------------------------------------------- 全局对话挑选（决策 37）

def _profile_lines(profiles: dict) -> list[str]:
    """画像 → 挑选器可读文本行（冷画像偏好/水平/风格 + 暖画像近期书/相关领域）。"""
    cold = profiles.get("cold") or {}
    warm = profiles.get("warm") or {}
    lines = []
    if cold.get("domain_preferences"):
        lines.append("冷画像·领域偏好：" + str(dict(cold["domain_preferences"]))[:200])
    if cold.get("knowledge_level"):
        lines.append(f"冷画像·知识水平：{cold.get('knowledge_level')}")
    if cold.get("language_style"):
        lines.append(f"冷画像·语言风格：{cold.get('language_style')}")
    if cold.get("long_term_interests"):
        lines.append("冷画像·长期兴趣：" + "、".join(str(i) for i in cold["long_term_interests"][:10]))
    recent = warm.get("recent_books") or []
    if recent:
        lines.append(
            "暖画像·近期书：" + "；".join(f"《{r.get('title')}》{str(r.get('summary') or '')[:80]}" for r in recent[-3:])
        )
    related = warm.get("related_books") or []
    if related:
        lines.append("暖画像·相关领域书：" + "、".join(str(r.get("title")) for r in related[:5]))
    return lines


def _select_llm_global(db: Session, question: str, profiles: dict) -> SelectionResult | None:
    """全局对话 LLM 挑选（决策 37）：无当前书/章节，从全库目录挑选；失败返回 None。"""
    catalog_text, index = build_catalog(db, 0)
    if not index:
        return None
    try:
        client = build_selector_client(db)
        if not (client.api_key or "").strip():
            return None
        user = build_global_user_prompt(question, catalog_text, "\n".join(_profile_lines(profiles)))
        system = SYSTEM_PROMPT_GLOBAL.format(
            max_books=settings.rag_select_max_books, max_skills=settings.rag_select_max_skills
        )
        reply = client.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        data = parse_llm_json(reply)
    except Exception:  # noqa: BLE001 挑选失败/超时/解析失败 → 降级规则方案
        return None
    book_ids: list[int] = []
    for b in data.get("selected_books") or []:
        if not isinstance(b, dict):
            continue
        bid = b.get("book_id")
        if isinstance(bid, int) and bid in index and bid not in book_ids:
            book_ids.append(bid)
    book_ids = book_ids[: settings.rag_select_max_books]
    skill_refs: list[dict] = []
    for st in data.get("selected_skills") or []:
        if not isinstance(st, dict):
            continue
        bid, name = st.get("book_id"), st.get("name")
        if isinstance(bid, int) and bid in index and name and {"book_id": bid, "name": str(name)} not in skill_refs:
            skill_refs.append({"book_id": bid, "name": str(name)})
    reasons = str(data.get("reasons") or "")
    return SelectionResult(
        source="llm", book_ids=book_ids, skill_refs=skill_refs[: settings.rag_select_max_skills], reasons=reasons
    )


def _global_query_tokens(text: str) -> set[str]:
    """全局降级检索 token：中文二元组 + 英文词（与 assets.retrieve_rag_chunks 同款切分）。"""
    return set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]*", text or ""))


def _select_fallback_global(db: Session, question: str) -> SelectionResult:
    """全局对话规则降级（决策 37）：摘要/内容关键词相关 top3 书 + 全局 Skill 相关性 top N。"""
    assets_map = list_assets_by_books(db)
    tokens = _global_query_tokens(question)
    scored: list[tuple[int, int]] = []
    for bid, kinds in assets_map.items():
        content = kinds.get("rag") or {}
        summary = str(content.get("summary") or "")
        if not summary and not content.get("chunks"):
            continue
        score = sum(1 for t in tokens if t in summary)
        scored.append((score, bid))
    scored.sort(key=lambda x: -x[0])
    book_ids = [bid for _, bid in scored[: settings.rag_select_max_books]]
    skill_refs: list[dict] = []
    for st in load_all_skills(db, task_text=question, top_n=settings.rag_select_max_skills):
        if len(skill_refs) >= settings.rag_select_max_skills:
            break
        ref = {"book_id": st.get("book_id"), "name": str(st.get("name") or "")}
        if ref["name"] and ref not in skill_refs:
            skill_refs.append(ref)
    return SelectionResult(source="fallback", book_ids=book_ids, skill_refs=skill_refs)


def select_global_knowledge(
    db: Session,
    question: str,
    session_id: str | None = None,
) -> dict:
    """决策 37 主入口：全局对话知识挑选 → 返回注入内容 dict（同 select_knowledge 结构）。

    缓存键 `global:{session_id}`（无 chapter 维度）；LLM 挑选失败/未开启 → 规则降级。
    """
    key = None
    if session_id:
        key = f"global:{session_id}"
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "source": "cache"}
    profiles = get_all_profiles(db)
    result: SelectionResult | None = None
    if settings.ai_rag_select_enabled:
        result = _select_llm_global(db, question, profiles)
    if result is None:
        result = _select_fallback_global(db, question)
    payload = _selection_payload(result, db, question)
    if key:
        _cache_put(key, payload)
    return payload


# ---------------------------------------------------------------- 主入口

def select_knowledge(
    db: Session,
    book: Book,
    chapter,
    question: str,
    selection: str = "",
    mode: str | None = None,
    session_id: str | None = None,
) -> dict:
    """决策 34 主入口：LLM 自主挑选 → 跨书注入；返回注入内容 dict。

    返回 {"chunks": [...], "skills": [...], "selection": {...}, "source": "llm"|"fallback"|"cache"}。
    chunks 每项含 book_id/book_title，出处格式【《书名》第X章 第Y段】由 chat_service 组装。
    """
    key = _cache_key(session_id, chapter.id) if session_id else None
    if key:
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "source": "cache"}
    profiles = get_all_profiles(db)
    result: SelectionResult | None = None
    if settings.ai_rag_select_enabled:
        result = _select_llm(db, book, chapter, question, selection, mode, profiles)
    if result is None:
        result = _select_fallback(db, book, question)
    payload = _selection_payload(result, db, question)
    if key:
        _cache_put(key, payload)
    return payload
