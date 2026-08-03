"""书籍 CRUD 与导入。"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories import books as repo
from app.repositories.reading import book_reading_summary, books_reading_summary
from app.schemas.common import fail, ok
from app.schemas.serializers import book_to_dict, chapter_to_dict
from app.services.book_pages import get_or_render_page
from app.services.books_service import clean_tags
from app.services.books_service import delete_book as delete_book_service
from app.services.graph.cross_book import incremental_cross_book_graph
from app.services.import_service import import_book
from app.services.media_service import book_cover_file

router = APIRouter(prefix="/api/books", tags=["books"])


class BookUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    status: str | None = None  # 未读/在读/读完
    progress: float | None = None
    folder_id: int | None = None
    tags: list[str] | None = None
    position: int | None = None  # 书架排序位（拖拽换位）


class BookReorder(BaseModel):
    ordered_ids: list[int]


def _book_out(db: Session, book) -> dict:
    """书籍序列化 + 阅读概况（已读章节数 / 最新章节）。"""
    read_chapters, latest_chapter = book_reading_summary(db, book)
    return book_to_dict(book, read_chapters=read_chapters, latest_chapter=latest_chapter)


@router.get("")
def list_books(folder_id: int | None = None, q: str | None = None, db: Session = Depends(get_db)):
    """书架列表：按 position 排序；q 搜索书名/作者/tag。"""
    books = repo.list_books(db, folder_id, q)
    summaries = books_reading_summary(db, books)
    return ok([book_to_dict(b, *summaries.get(b.id, (0, None))) for b in books])


@router.post("/reorder")
def reorder_books(body: BookReorder, db: Session = Depends(get_db)):
    """批量重排书架：ordered_ids 为期望的完整顺序（position 1..N）。"""
    repo.reorder_books(db, body.ordered_ids)
    return ok({"reordered": len(body.ordered_ids)}, "书架顺序已更新")


@router.post("")
async def upload_book(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    author: str | None = Form(None),
    db: Session = Depends(get_db),
):
    data = await file.read()
    try:
        book = import_book(db, data, file.filename or "untitled", title=title, author=author)
    except ValueError as exc:
        return fail(400, str(exc))
    # 新书导入后增量更新跨书关联（需求 3.6.2：不动既有关联，只补新书与其他书的边；失败不阻塞导入）
    try:
        incremental_cross_book_graph(db, book.id)
    except Exception:
        db.rollback()
    return ok(_book_out(db, book), "导入成功")


@router.get("/{book_id}")
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = repo.get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    data = _book_out(db, book)
    data["chapters"] = [chapter_to_dict(c) for c in repo.list_chapters(db, book_id)]
    return ok(data)


@router.patch("/{book_id}")
def update_book(book_id: int, body: BookUpdate, db: Session = Depends(get_db)):
    tags = clean_tags(body.tags) if body.tags is not None else None
    book = repo.update_book(
        db,
        book_id,
        title=body.title,
        author=body.author,
        status=body.status,
        progress=body.progress,
        folder_id=body.folder_id,
        tags=tags,
        position=body.position,
    )
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return ok(_book_out(db, book))


@router.delete("/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db)):
    if not delete_book_service(db, book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    return ok(None, "已删除")


@router.get("/{book_id}/cover")
def get_book_cover(book_id: int, db: Session = Depends(get_db)):
    """返回书籍封面图片文件；缺封面时按需提取（PDF 渲染第 1 页 / EPUB OPF 封面）。"""
    book = repo.get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    path = book_cover_file(db, book)
    if not path:
        raise HTTPException(status_code=404, detail="该书没有封面")
    return FileResponse(path)


@router.get("/{book_id}/pages/{page_index}")
def get_book_page(book_id: int, page_index: int, db: Session = Depends(get_db)):
    """返回扫描版 PDF 的原始页图片；页图缺失或分辨率低于内嵌原图时按需重渲染（升级低清页）。"""
    book = repo.get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    path = get_or_render_page(book, page_index)
    if not path:
        raise HTTPException(status_code=404, detail="页面图片不存在")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=600"})
