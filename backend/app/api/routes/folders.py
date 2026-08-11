"""文件夹 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.book import Folder
from app.repositories import books as repo
from app.schemas.common import ok
from app.schemas.serializers import folder_to_dict

router = APIRouter(prefix="/api/folders", tags=["folders"])


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None


class FolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("")
def list_folders(db: Session = Depends(get_db)):
    return ok([folder_to_dict(f) for f in repo.list_folders(db)])


@router.post("")
def create_folder(body: FolderCreate, db: Session = Depends(get_db)):
    if body.parent_id is not None and not db.get(Folder, body.parent_id):
        raise HTTPException(status_code=404, detail="父文件夹不存在")
    try:
        folder = repo.create_folder(db, body.name, body.parent_id)
    except IntegrityError as exc:
        db.rollback()  # 预检与提交间的父文件夹并发删除（FK 冲突）→ 400 而非 500
        raise HTTPException(status_code=400, detail="父文件夹不存在或已被删除") from exc
    return ok(folder_to_dict(folder))


@router.patch("/{folder_id}")
def rename_folder(folder_id: int, body: FolderUpdate, db: Session = Depends(get_db)):
    folder = repo.rename_folder(db, folder_id, body.name)
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return ok(folder_to_dict(folder))


@router.delete("/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    try:
        if not repo.delete_folder(db, folder_id):
            raise HTTPException(status_code=404, detail="文件夹不存在")
    except IntegrityError as exc:
        db.rollback()  # 并发改书引用导致 FK 冲突 → 409（m-7：与 update_book 冲突语义统一）而非 500
        raise HTTPException(status_code=409, detail="文件夹删除失败：书籍引用冲突，请重试") from exc
    return ok(None, "已删除（其中书籍转为未归类）")