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
    vision,
)
from app.api.routes import settings as settings_routes
from app.core.config import settings
from app.core.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "books").mkdir(parents=True, exist_ok=True)
    init_db()
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
app.include_router(bookmarks.router)
app.include_router(annotations.router)
app.include_router(notes.router)
app.include_router(chat.router)
app.include_router(mindmap.router)
app.include_router(vision.router)
app.include_router(graph.router)
app.include_router(profile.router)
app.include_router(settings_routes.router)