"""BookAsset 仓储：RAG / Skill 资产读写、内容解析、检索与去重合并（按书存储，版本递增）。

去重合并约定（v1.67）：
- 条目级：写入（upsert_asset）时对 rag.key_points / rag.chunks / skill.skills /
  skill.domains 按规范化内容 hash 去重（保留首次出现），「hash 相同合并成一个条目」。
- 资产级：合并判定使用**书籍内容 hash**（原文件 sha256，存于 book.content_hash，与书籍本身内容一一对应）
  hash 相同的多本书资产合并为一条主资产，content.merged_book_ids 记录共享书；被合并书无独立行，通过反查
  透明读取同一资产（get_asset / read_asset_content / list_assets / 检索均兼容）。「删除资产」= 移除知识库（rag/skill）及其对应书籍：DELETE /api/books/{id} 级联删除资产与文件（共享资产自动转移/解除引用）。
"""
import hashlib
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.asset import BookAsset
from app.models.book import Book

RAG_TOP_K = 4
# 合并时忽略的元数据字段（不参与内容指纹，避免合并后 hash 漂移）
_META_KEYS = {"merged_book_ids"}


def content_hash(obj) -> str:
    """规范化 JSON（剔除元数据键、排序键、紧凑序列化）后的 sha256 前 16 位，作为内容指纹。"""
    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items() if k not in _META_KEYS}
        if isinstance(o, list):
            return [_clean(v) for v in o]
        return o
    payload = json.dumps(_clean(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _dedupe_items(items: list) -> list:
    """按条目内容 hash 去重（保序，保留首次出现）。"""
    out: list = []
    seen: set[str] = set()
    for item in items:
        fp = content_hash(item)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(item)
    return out


def _normalize_content(content: dict, kind: str) -> dict:
    """写入前对列表字段按 hash 去重（条目级合并）。"""
    content = dict(content)
    if kind == "rag":
        for key in ("key_points", "chunks"):
            if isinstance(content.get(key), list):
                content[key] = _dedupe_items(content[key])
    elif kind == "skill":
        for key in ("skills", "domains"):
            if isinstance(content.get(key), list):
                content[key] = _dedupe_items(content[key])
    return content


def _load(asset: BookAsset) -> dict:
    try:
        content = json.loads(asset.content_json or "{}")
    except (ValueError, TypeError):
        return {}
    return content if isinstance(content, dict) else {}


def _save(db: Session, asset: BookAsset, content: dict) -> None:
    asset.content_json = json.dumps(content, ensure_ascii=False)
    db.commit()
    db.refresh(asset)


def _asset_links_book(asset: BookAsset, book_id: int) -> bool:
    """资产是否为共享主资产且包含 book_id 为成员书。"""
    merged = _load(asset).get("merged_book_ids")
    return isinstance(merged, list) and book_id in merged


def _find_shared_asset(db: Session, book_id: int, kind: str) -> BookAsset | None:
    """反查包含 book_id 的共享主资产（该书无独立行时透明返回）。"""
    for row in db.query(BookAsset).filter(BookAsset.kind == kind).all():
        if _asset_links_book(row, book_id):
            return row
    return None


def _detach_shared(db: Session, book_id: int, kind: str) -> None:
    """把 book_id 从共享主资产的 merged_book_ids 中解除（该书独立生成资产前调用）。"""
    for row in db.query(BookAsset).filter(BookAsset.kind == kind).all():
        content = _load(row)
        merged = content.get("merged_book_ids")
        if isinstance(merged, list) and book_id in merged:
            merged.remove(book_id)
            content["merged_book_ids"] = merged
            row.version += 1  # 审查 P2-1：成员引用变化同样失效资产指纹（H3 索引/挑选缓存）
            _save(db, row, content)


def get_asset(db: Session, book_id: int, kind: str) -> BookAsset | None:
    """读取单条资产（rag / skill）；无独立行时返回包含该书共享主资产。"""
    asset = db.query(BookAsset).filter(BookAsset.book_id == book_id, BookAsset.kind == kind).first()
    if asset:
        return asset
    return _find_shared_asset(db, book_id, kind)


def list_assets_by_books(db: Session) -> dict[int, dict[str, dict]]:
    """批量加载全部书籍资产（含共享反查展开）：{book_id: {kind: content}}。

    审查 A-7：消除 build_catalog 等场景的 5N-6N 次单书查询；共享主资产
    （merged_book_ids）展开到每个成员书，内容剔除 merged_book_ids 元数据。
    """
    out: dict[int, dict[str, dict]] = {}
    for row in db.query(BookAsset).all():
        content = _load(row)
        members = content.get("merged_book_ids")
        content.pop("merged_book_ids", None)
        book_ids = members if isinstance(members, list) and members else [row.book_id]
        for book_id in book_ids:
            out.setdefault(book_id, {})[row.kind] = content
    return out


def list_asset_briefs(db: Session) -> dict[int, dict]:
    """批量资产摘要（审查 A-6）：{book_id: {version, has_rag, has_skill, rag_summary, merged_count}}。

    供资产页列表一次请求展示全部书籍的资产状态，消除逐书 GET /books/{id}/asset 的 N+1。
    """
    brief: dict[int, dict] = {}
    for row in db.query(BookAsset).all():
        content = _load(row)
        members = content.get("merged_book_ids")
        book_ids = members if isinstance(members, list) and members else [row.book_id]
        for book_id in book_ids:
            entry = brief.setdefault(
                book_id,
                {"version": 0, "has_rag": False, "has_skill": False, "rag_summary": "", "merged_count": 0},
            )
            entry["version"] = max(entry["version"], row.version)
            if row.kind == "rag":
                entry["has_rag"] = True
                entry["rag_summary"] = str(content.get("summary") or "")[:200]
                entry["merged_count"] = len(members) if isinstance(members, list) else 0
            else:
                entry["has_skill"] = True
    return brief


def read_asset_content(db: Session, book_id: int, kind: str) -> dict:
    """读取资产内容 dict（剔除 merged_book_ids 元数据，保证与生成内容可比）；不存在返回 {}。"""
    asset = get_asset(db, book_id, kind)
    if not asset:
        return {}
    content = _load(asset)
    content.pop("merged_book_ids", None)
    return content


_asset_write_locks: "OrderedDict[int, threading.Lock]" = OrderedDict()
_asset_write_locks_guard = threading.Lock()
# M-2 修复：per-book 锁表有界（LRU 上限），超限淘汰**未被持有**的锁（持锁中跳过，
# 避免同书并发互斥失效）；长运行服务随书量不再无界增长。
_ASSET_WRITE_LOCK_MAX = 128


def _asset_write_lock(book_id: int) -> threading.Lock:
    """同书资产写互斥（终审 §6.9 + M-2）：归档 vs 手动总结并发时防「读-改-写」丢失更新。

    锁序约定：**永远单锁、不嵌套**——持锁期间不得再获取其他 _asset_write_lock 或外部锁；
    唯一例外是 merge_duplicate_assets 的跨书批量合并（按 book_id 升序取锁，见其 docstring）。
    """
    with _asset_write_locks_guard:
        lock = _asset_write_locks.get(book_id)
        if lock is None:
            lock = threading.Lock()
            _asset_write_locks[book_id] = lock
        else:
            _asset_write_locks.move_to_end(book_id)
        if len(_asset_write_locks) > _ASSET_WRITE_LOCK_MAX:
            for victim_id, victim in list(_asset_write_locks.items()):
                if len(_asset_write_locks) <= _ASSET_WRITE_LOCK_MAX:
                    break
                if victim.acquire(blocking=False):
                    victim.release()
                    del _asset_write_locks[victim_id]
        return lock


def upsert_asset(db: Session, book_id: int, kind: str, content: dict) -> BookAsset:
    """写入/更新资产；已存在则 version + 1（保留历史约定，见技术栈规范 AI 接入规范）。

    写入前对列表条目按 hash 去重；若该书原为共享成员（无独立行），先解除共享引用再新建。
    """
    content = _normalize_content(content, kind)
    with _asset_write_lock(book_id):  # 终审 §6.9：同书并发写（归档 vs 手动总结）防 version/内容丢失
        asset = db.query(BookAsset).filter(BookAsset.book_id == book_id, BookAsset.kind == kind).first()
        if asset:
            asset.version += 1
        else:
            _detach_shared(db, book_id, kind)
            asset = BookAsset(book_id=book_id, kind=kind, version=1)
            db.add(asset)
        asset.content_json = json.dumps(content, ensure_ascii=False)
        db.commit()
        db.refresh(asset)
    return asset


def list_assets(db: Session, book_id: int) -> list[BookAsset]:
    """列出书籍全部资产（共享资产只返回一条主资产）。"""
    own = db.query(BookAsset).filter(BookAsset.book_id == book_id).order_by(BookAsset.kind).all()
    kinds = {a.kind for a in own}
    for kind in ("rag", "skill"):
        if kind not in kinds:
            shared = _find_shared_asset(db, book_id, kind)
            if shared:
                own.append(shared)
    return own


def save_asset_content(db: Session, book_id: int, kind: str, content: dict) -> BookAsset:
    """写入资产内容但**不递增版本**（图谱联动存根等元数据更新专用：linked_books /
    domain_terms 等不应触发 post-classify 失效）。资产不存在时按 version=1 创建。"""
    content = _normalize_content(content, kind)
    asset = db.query(BookAsset).filter(BookAsset.book_id == book_id, BookAsset.kind == kind).first()
    if not asset:
        asset = BookAsset(book_id=book_id, kind=kind, version=1)
        db.add(asset)
    asset.content_json = json.dumps(content, ensure_ascii=False)
    db.commit()
    db.refresh(asset)
    return asset


def delete_assets(db: Session, book_id: int) -> None:
    """删除书籍全部资产（删除书籍时级联）：主资产转移给成员书，成员书解除引用。"""
    for row in db.query(BookAsset).filter(BookAsset.book_id == book_id).all():
        content = _load(row)
        merged = content.get("merged_book_ids") or []
        if merged:
            row.book_id = merged.pop(0)
            content["merged_book_ids"] = merged
            row.version += 1  # 审查 P2-1：删书转移主书身份（book_id 变化）同样失效资产指纹
            _save(db, row, content)
    db.query(BookAsset).filter(BookAsset.book_id == book_id).delete()
    for row in db.query(BookAsset).all():
        if _asset_links_book(row, book_id):
            _detach_shared(db, book_id, row.kind)
    db.commit()


def delete_asset(db: Session, book_id: int, kind: str) -> bool:
    """删除指定 kind（rag / skill）的整条资产；共享资产按书解除/转移引用。"""
    asset = get_asset(db, book_id, kind)
    if not asset:
        return False
    if asset.book_id != book_id:  # 该书是共享成员：仅解除引用
        content = _load(asset)
        merged = content.get("merged_book_ids") or []
        if book_id in merged:
            merged.remove(book_id)
            content["merged_book_ids"] = merged
            asset.version += 1  # 审查 P2-1：成员引用变化同样失效资产指纹
            _save(db, asset, content)
        return True
    content = _load(asset)
    merged = content.get("merged_book_ids") or []
    if merged:  # 该书是主资产且有成员：主书转移给第一个成员书
        asset.book_id = merged.pop(0)
        content["merged_book_ids"] = merged
        asset.version += 1  # 审查 P2-1：主书身份转移（book_id 变化）同样失效资产指纹
        _save(db, asset, content)
        return True
    db.delete(asset)
    db.commit()
    return True


def delete_asset_item(db: Session, book_id: int, kind: str, section: str, index: int) -> dict:
    """删除资产内第 index 项（0 基），version + 1 并落库；返回删除后的新内容。

    section 取值：rag → key_points（关键知识点）/ chunks（检索片段）；
    skill → skills（技能条目）。资产不存在或索引越界抛 ValueError。
    """
    asset = get_asset(db, book_id, kind)
    if not asset:
        raise ValueError(f"书籍没有 {kind} 资产")
    content = _load(asset)
    items = content.get(section)
    if not isinstance(items, list) or not 0 <= index < len(items):
        raise ValueError(f"资产项不存在：{kind}/{section}/{index}")
    del items[index]
    content = _normalize_content(content, kind)
    asset.version += 1
    _save(db, asset, content)
    return content


def _book_file_hash(db: Session, book_id: int) -> str | None:
    """懒回填/读取书籍内容 hash：优先用 book.content_hash，缺失时读原文件计算并回填。"""

    book = db.get(Book, book_id)
    if not book:
        return None
    if book.content_hash:
        return book.content_hash
    try:
        data = Path(book.file_path).read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256(data).hexdigest()
    book.content_hash = digest
    db.commit()
    return digest


def merge_duplicate_assets(db: Session) -> dict:
    """跨书合并：kind + 书籍内容 hash（原文件 sha256）相同的资产合并为一条主资产（保留最新一条）。

    hash 只与书籍本身内容相关（同一文件重复导入/多本书内容相同即共享一个资产）；
    旧书缺失 content_hash 时读原文件懒回填。被合并书的资产行删除，其 book_id
    （及原主资产的成员书）并入主资产 merged_book_ids；已合并成员书内容 hash 与主书
    不一致时自动解除引用（内容更新后不再共享）。返回 {kind: 合并条数}。
    删除书籍时主资产自动转移（delete_assets）。

    M-2 修复：并发互斥下沉到仓储内部——先收集全部资产行涉及的 book_id，按升序获取
    per-book 写锁（与 upsert_asset 共用 _asset_write_lock）后整体执行，路由层不再需要
    外部锁；并发 merge/upsert 同书时互斥。锁序：跨书批量合并是唯一「多锁」例外，
    按 book_id 升序获取保证并发 merge 锁序一致无死锁；其余路径遵循「永远单锁、不嵌套」。
    """
    lock_ids = {
        row.book_id
        for row in db.query(BookAsset.book_id).filter(BookAsset.kind.in_(("rag", "skill"))).all()
    }
    locks = [_asset_write_lock(bid) for bid in sorted(lock_ids)]
    for lock in locks:
        lock.acquire()
    try:
        return _merge_duplicate_assets_locked(db)
    finally:
        for lock in reversed(locks):
            lock.release()


def _merge_duplicate_assets_locked(db: Session) -> dict:
    """merge_duplicate_assets 执行体（M-2：由外层获取 per-book 写锁后调用）。"""
    stats: dict[str, int] = {"rag": 0, "skill": 0}
    for kind in ("rag", "skill"):
        rows = (
            db.query(BookAsset)
            .filter(BookAsset.kind == kind)
            .order_by(BookAsset.version.asc(), BookAsset.updated_at.asc())
            .all()
        )
        # book_id -> 内容 hash；行主书与已合并成员书都参与判定
        hash_of: dict[int, str | None] = {}
        for row in rows:
            content = _load(row)
            hash_of.setdefault(row.book_id, _book_file_hash(db, row.book_id))
            for mid in content.get("merged_book_ids") or []:
                hash_of.setdefault(mid, _book_file_hash(db, mid))

        groups: dict[str, list[BookAsset]] = {}
        for row in rows:
            key = hash_of.get(row.book_id)
            if key:
                groups.setdefault(key, []).append(row)
        for group in groups.values():
            if len(group) < 2:
                continue
            main = group[-1]  # version/updated_at 升序 → 最新一条为主资产
            main_content = _load(main)
            merged = set(main_content.get("merged_book_ids") or [])
            for member in group:
                if member.id == main.id:
                    continue
                merged.update(_load(member).get("merged_book_ids") or [])
                merged.add(member.book_id)
                db.delete(member)
            merged.discard(main.book_id)
            # 内容 hash 与主书不一致的成员书解除引用（各自独立资产）
            merged = {mid for mid in merged if hash_of.get(mid) == hash_of.get(main.book_id)}
            main_content["merged_book_ids"] = sorted(merged)
            main.content_json = json.dumps(main_content, ensure_ascii=False)
            stats[kind] += len(group) - 1
    db.commit()
    return stats

def _query_tokens(text: str) -> set[str]:
    """把查询文本切分为检索 token：中文二元组 + 英文词（RAG 检索与 Skill 相关性共用）。"""
    return set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]*", text or ""))


def retrieve_rag_chunks(db: Session, book_id: int, question: str, top_k: int = RAG_TOP_K) -> list[dict]:
    """从书籍 RAG 资产中按关键词重叠检索相关片段；无资产/无命中时返回空。"""
    content = read_asset_content(db, book_id, "rag")
    chunks = content.get("chunks") or []
    if not chunks:
        return []
    tokens = _query_tokens(question)
    if not tokens:
        return chunks[:top_k]

    def _score(c: dict) -> int:
        text = str(c.get("text", ""))
        return sum(1 for t in tokens if t in text)

    scored = sorted(chunks, key=_score, reverse=True)
    hits = [c for c in scored if _score(c) > 0][:top_k]
    return hits or chunks[:top_k]


def load_skills(db: Session, book_id: int, task_text: str | None = None, top_n: int = 8) -> list[dict]:
    """读取书籍 Skill 资产中的技能列表；给出任务文本时按相关性排序并截断（避免全量注入）。"""
    content = read_asset_content(db, book_id, "skill")
    skills = content.get("skills") or []
    if not skills or not task_text:
        return skills
    tokens = _query_tokens(task_text)
    if not tokens:
        return skills[:top_n]

    def _score(s: dict) -> int:
        hay = " ".join(str(s.get(k, "")) for k in ("name", "applicable", "usage", "sources"))
        return sum(1 for t in tokens if t in hay)

    scored = sorted(skills, key=_score, reverse=True)
    hits = [s for s in scored if _score(s) > 0]
    return (hits or scored)[:top_n]


def load_all_skills(db: Session, task_text: str | None = None, top_n: int = 8) -> list[dict]:
    """全局 Skill 聚合（决策 37 主页全局 AI 对话）：全部书籍 skill 资产按任务文本相关性排序。

    返回技能列表，每项追加 `book_id`/`book_title` 供跨书出处标注；无任务文本时按
    最近资产顺序返回。共享主资产（merged_book_ids）经 list_assets_by_books 展开。
    """
    skills: list[dict] = []
    books = {b.id: b for b in db.query(Book).all()}  # noqa: F401 仅供标题映射
    assets_map = list_assets_by_books(db)
    for book_id, kinds in assets_map.items():
        content = kinds.get("skill") or {}
        for s in content.get("skills") or []:
            item = dict(s)
            item["book_id"] = book_id
            book = books.get(book_id)
            item["book_title"] = book.title if book else ""
            skills.append(item)
    if not skills or not task_text:
        return skills[:top_n]
    tokens = _query_tokens(task_text)
    if not tokens:
        return skills[:top_n]

    def _score(s: dict) -> int:
        hay = " ".join(str(s.get(k, "")) for k in ("name", "applicable", "usage", "sources"))
        return sum(1 for t in tokens if t in hay)

    scored = sorted(skills, key=_score, reverse=True)
    hits = [s for s in scored if _score(s) > 0]
    return (hits or scored)[:top_n]
