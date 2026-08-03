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
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.asset import BookAsset

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
            _save(db, row, content)


def get_asset(db: Session, book_id: int, kind: str) -> BookAsset | None:
    """读取单条资产（rag / skill）；无独立行时返回包含该书共享主资产。"""
    asset = db.query(BookAsset).filter(BookAsset.book_id == book_id, BookAsset.kind == kind).first()
    if asset:
        return asset
    return _find_shared_asset(db, book_id, kind)


def read_asset_content(db: Session, book_id: int, kind: str) -> dict:
    """读取资产内容 dict（剔除 merged_book_ids 元数据，保证与生成内容可比）；不存在返回 {}。"""
    asset = get_asset(db, book_id, kind)
    if not asset:
        return {}
    content = _load(asset)
    content.pop("merged_book_ids", None)
    return content


def upsert_asset(db: Session, book_id: int, kind: str, content: dict) -> BookAsset:
    """写入/更新资产；已存在则 version + 1（保留历史约定，见技术栈规范 AI 接入规范）。

    写入前对列表条目按 hash 去重；若该书原为共享成员（无独立行），先解除共享引用再新建。
    """
    content = _normalize_content(content, kind)
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
            _save(db, asset, content)
        return True
    content = _load(asset)
    merged = content.get("merged_book_ids") or []
    if merged:  # 该书是主资产且有成员：主书转移给第一个成员书
        asset.book_id = merged.pop(0)
        content["merged_book_ids"] = merged
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
    from app.models.book import Book

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
    """
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

def retrieve_rag_chunks(db: Session, book_id: int, question: str, top_k: int = RAG_TOP_K) -> list[dict]:
    """从书籍 RAG 资产中按关键词重叠检索相关片段；无资产/无命中时返回空。"""
    content = read_asset_content(db, book_id, "rag")
    chunks = content.get("chunks") or []
    if not chunks:
        return []
    tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]*", question or ""))
    if not tokens:
        return chunks[:top_k]

    def _score(c: dict) -> int:
        text = str(c.get("text", ""))
        return sum(1 for t in tokens if t in text)

    scored = sorted(chunks, key=_score, reverse=True)
    hits = [c for c in scored if _score(c) > 0][:top_k]
    return hits or chunks[:top_k]


def load_skills(db: Session, book_id: int) -> list[dict]:
    """读取书籍 Skill 资产中的技能列表。"""
    content = read_asset_content(db, book_id, "skill")
    return content.get("skills") or []