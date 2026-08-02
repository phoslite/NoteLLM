"""书内知识图谱：章节级/重要段落级/用户标记级知识点构建与序列化。"""
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models.activity import Note
from app.models.book import Book, Chapter
from app.models.graph import KnowledgePoint, KpRelation
from app.services.graph.corpus import _chapter_text
from app.services.graph.keywords import _THEOREM_RE


def build_intra_book_graph(db: Session, book: Book) -> dict:
    """重建单书内部知识图谱：章节级 + 重要段落级 + 用户标记级，点间关系按阅读顺序。"""
    old_ids = [k.id for k in db.query(KnowledgePoint.id).filter(KnowledgePoint.book_id == book.id).all()]
    if old_ids:
        db.query(KpRelation).filter(
            KpRelation.from_kp_id.in_(old_ids) | KpRelation.to_kp_id.in_(old_ids)
        ).delete(synchronize_session=False)
    db.query(KnowledgePoint).filter(KnowledgePoint.book_id == book.id).delete(synchronize_session=False)

    chapter_points: list[tuple[Chapter, KnowledgePoint]] = []
    for ch in sorted(book.chapters, key=lambda c: c.index):
        text = _chapter_text(book, ch)
        title = (ch.title or f"第 {ch.index} 章").strip()[:200]
        kp = KnowledgePoint(
            book_id=book.id,
            chapter_id=ch.id,
            para_pos=None,
            title=title,
            summary=text.strip()[:200],
            importance=4 if ch.word_count > 0 else 2,
            level="章节级",
            aliases_json="[]",
        )
        db.add(kp)
        db.flush()
        chapter_points.append((ch, kp))
        # 重要段落：命中定理/定义/引理等模式的行
        for para_pos, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if len(line) > 8 and _THEOREM_RE.search(line):
                db.add(
                    KnowledgePoint(
                        book_id=book.id,
                        chapter_id=ch.id,
                        para_pos=str(para_pos),
                        title=line[:50],
                        summary=line[:300],
                        importance=5,
                        level="重要段落",
                        aliases_json="[]",
                    )
                )
    # 用户标记级：笔记/高亮/批注/思考/不理解 自动纳入
    for note in db.query(Note).filter(Note.book_id == book.id).order_by(Note.id).all():
        title = (note.quote_text or note.note_text or note.note_type or "").strip()[:50]
        if not title:
            continue
        db.add(
            KnowledgePoint(
                book_id=book.id,
                chapter_id=note.chapter_id,
                para_pos=None,
                title=title,
                summary=(note.note_text or note.quote_text or "")[:300],
                importance=5,
                level="用户标记",
                aliases_json="[]",
            )
        )
    db.flush()
    # 关系：章节顺序「前置依赖」
    for (_, kp_a), (_, kp_b) in zip(chapter_points, chapter_points[1:], strict=False):
        db.add(
            KpRelation(
                from_kp_id=kp_a.id, to_kp_id=kp_b.id, relation_type="前置依赖", strength=60.0, note="章节顺序"
            )
        )
    # 关系：同章内重要段落「承接」
    kps = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.book_id == book.id, KnowledgePoint.level == "重要段落")
        .order_by(KnowledgePoint.id)
        .all()
    )
    by_chapter: dict[int, list[KnowledgePoint]] = defaultdict(list)
    for kp in kps:
        by_chapter[kp.chapter_id].append(kp)
    for pts in by_chapter.values():
        for a, b in zip(pts, pts[1:], strict=False):
            db.add(
                KpRelation(
                    from_kp_id=a.id, to_kp_id=b.id, relation_type="承接", strength=50.0, note="同章内重要段落"
                )
            )
    book.graph_built = True
    db.commit()
    return intra_graph_payload(db, book)

def intra_graph_payload(db: Session, book: Book) -> dict:
    """书内知识图谱数据：知识点节点 + 知识点关系 + 章节索引。"""
    kps = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.book_id == book.id)
        .order_by(KnowledgePoint.id)
        .all()
    )
    kp_ids = [k.id for k in kps]
    nodes = [
        {
            "id": k.id,
            "chapter_id": k.chapter_id,
            "title": k.title,
            "summary": k.summary,
            "importance": k.importance,
            "level": k.level,
            "para_pos": k.para_pos,
        }
        for k in kps
    ]
    rels = (
        db.query(KpRelation)
        .filter(KpRelation.from_kp_id.in_(kp_ids))
        .order_by(KpRelation.id)
        .all()
    )
    edges = [
        {
            "from": r.from_kp_id,
            "to": r.to_kp_id,
            "relation_type": r.relation_type,
            "strength": r.strength,
            "note": r.note,
        }
        for r in rels
    ]
    chapters = [
        {"id": c.id, "index": c.index, "title": c.title}
        for c in sorted(book.chapters, key=lambda c: c.index)
    ]
    return {"nodes": nodes, "edges": edges, "chapters": chapters}
