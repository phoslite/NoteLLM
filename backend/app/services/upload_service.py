"""上传流式写盘服务（审查 P0-7）：分块接收 + 大小上限拦截 + sha256 计算从路由下沉。

路由只负责解析 UploadFile 与返回结果；临时文件生命周期与导入调用收敛在本层。
"""
import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.services.import_service import import_book_file

CHUNK_SIZE = 1024 * 1024  # 1MB 分块


async def stream_upload_to_temp(file: UploadFile) -> tuple[Path, str]:
    """把上传文件分块写入临时目录，返回 (临时路径, sha256)；超大文件抛 413（写入中拦截）。"""
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp = upload_dir / f"{uuid.uuid4().hex}.upload"
    hasher = hashlib.sha256()
    try:
        with open(tmp, "wb") as out:
            total = 0
            while chunk := await file.read(CHUNK_SIZE):
                total += len(chunk)
                if total > settings.max_upload_bytes:  # 审查 C-问题13：分块写入时即拦截超大文件
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过大小上限 {settings.max_upload_bytes // CHUNK_SIZE}MB",
                    )
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, hasher.hexdigest()


def import_uploaded_book(
    db, tmp_path: Path, original_name: str, *, title: str | None, author: str | None, content_hash: str
):
    """临时文件入架：调用两段式导入（同步入架秒回 + 后台任务），失败清理临时文件。"""
    try:
        return import_book_file(
            db,
            tmp_path,
            original_name,
            title=title,
            author=author,
            content_hash=content_hash,
        )
    except ValueError as exc:
        raise exc
    finally:
        tmp_path.unlink(missing_ok=True)  # 已 move 进书籍目录则自动忽略
