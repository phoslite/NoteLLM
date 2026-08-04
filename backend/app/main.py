"""应用入口：FastAPI + CORS + 启动建表。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    annotations,
    assets,
    bookmarks,
    books,
    chat,
    folders,
    graph,
    health,
    mindmap,
    notes,
    profile,
    reading,
    tasks,
    vision,
)
from app.api.routes import settings as settings_routes
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.media_service import migrate_all_books
from app.tasks import mark_interrupted


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "books").mkdir(parents=True, exist_ok=True)
    init_db()
    migrate_book_media()
    mark_interrupted()  # 重启后清理遗留任务，防止死任务被幂等复用（决策 35）
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(books.router)
app.include_router(folders.router)
app.include_router(assets.router)
app.include_router(reading.router)
app.include_router(tasks.router)
app.include_router(bookmarks.router)
app.include_router(annotations.router)
app.include_router(notes.router)
app.include_router(chat.router)
app.include_router(mindmap.router)
app.include_router(vision.router)
app.include_router(graph.router)
app.include_router(profile.router)
app.include_router(settings_routes.router)


def migrate_book_media() -> None:
    """启动迁移：旧版扁平书籍目录 → 独立子目录 + 封面回填；失败不阻塞启动。"""
    try:

        with SessionLocal() as db:
            migrate_all_books(db)
    except Exception:
        pass
