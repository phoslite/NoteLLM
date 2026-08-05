"""书籍 CRUD 与导入。"""

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.repositories import books as repo
from app.repositories.reading import book_reading_summary, books_reading_summary
from app.schemas.common import fail, ok
from app.schemas.serializers import book_to_dict, chapter_to_dict
from app.services.book_pages import get_or_render_page
from app.services.books_service import clean_tags
from app.services.books_service import delete_book as delete_book_service
from app.services.import_service import import_book_file  # 两段式导入（分块流式写盘 + 后台处理）
from app.services.media_service import book_cover_file
from app.services.search_service import search_books as search_books_service

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
    """上传书籍：分块流式写盘（1MB 块，边写边算 sha256）→ 同步入架（秒回）+ 返回后台任务 task_id（决策 35 两段式）。

    耗时处理（PDF 页渲染/全文索引/跨书图谱增量/视觉预提取）在 import-background
    任务中执行，前端任务中心展示进度；任务失败不阻塞书籍上架。
    """
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp = upload_dir / f"{uuid.uuid4().hex}.upload"
    hasher = hashlib.sha256()
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                hasher.update(chunk)
                out.write(chunk)
        book, task_id = import_book_file(
            db,
            tmp,
            file.filename or "untitled",
            title=title,
            author=author,
            content_hash=hasher.hexdigest(),
        )
    except ValueError as exc:
        return fail(400, str(exc))
    finally:
        tmp.unlink(missing_ok=True)  # 已 move 进书籍目录则自动忽略
    return ok({**_book_out(db, book), "task_id": task_id}, "已提交导入任务")


@router.get("/search")
def search_books_api(q: str = "", limit: int = 30, db: Session = Depends(get_db)):
    """FTS5 全书搜索（性能优化 §7 决策 3）：关键词 → 章节级命中（标题/正文），按相关度排序。"""
    keyword = (q or "").strip()
    if not keyword:
        return ok([])
    return ok(search_books_service(db, keyword, min(limit, 100)))


@router.get("/assets")
def books_assets_brief(db: Session = Depends(get_db)):
    """审查 A-6：批量返回全部书籍资产摘要（资产页列表用，消除逐书请求 N+1）。

    注意：必须定义在 /books/{book_id} 之前，否则会被 int 参数路由截获。
    """
    from app.repositories.assets import list_asset_briefs

    return ok(list_asset_briefs(db))


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
