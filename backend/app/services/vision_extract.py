"""PDF 页面的多模态视觉提取与页级缓存（M7）。

- 独立配置的多模态 LLM（vision_base_url / vision_api_key / vision_model）逐页提取完整页面信息
  （Markdown，含公式/表格/图注），落盘 `data/books/<书目录>/page_text/page_XXX.md`；
- 命中（文件存在且非空）不重复调用多模态 API；
- 滑动窗口 `[P-1, P, P+1]`（首/末页裁剪）增量缓存：仅补提取缺失页；
- 受「发送书籍内容至模型」隐私开关约束；随书删除随目录清理。
"""
import base64
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.client import LLMClient
from app.core.config import settings
from app.repositories.settings import load_ai_overrides, vision_client_kwargs
from app.services.media_service import page_image_path

PAGE_TEXT_DIR = "page_text"

EXTRACT_SYSTEM = (
    "你是 PDF 页面信息提取专家。请把用户提供的这一页 PDF 图片完整地转为结构化 Markdown 文本：\n"
    "1) 转录正文内容；公式使用 LaTeX（行内 $...$、块级 $...$），禁止输出 Unicode 数学字符（如 Λ、∈、ℝ、√），一律写成 LaTeX 命令（如 \\Lambda、\\in、\\mathbb{R}、\\sqrt）；表格转为 Markdown 表格；\n"
    "2) 图片/图表用文字描述其内容与作用（图注优先转录）；\n"
    "3) 保留标题层级、列表与页码信息；不要遗漏任何可见文字；\n"
    "4) 只输出该页内容本身，不要任何前言后语。"
)


def page_text_path(book, page_index: int) -> Path:
    """页缓存文件路径：data/books/<书目录>/page_text/page_XXX.md。"""
    return Path(book.file_path).parent / PAGE_TEXT_DIR / f"page_{page_index:03d}.md"


def read_page_cache(book, page_index: int) -> str | None:
    """读取页缓存文本；不存在或为空返回 None。"""
    path = page_text_path(book, page_index)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _extract_page_text(client: LLMClient, book, page_index: int) -> str:
    """调用多模态 LLM 提取单页完整信息，返回 Markdown 文本。"""
    path = page_image_path(book, page_index)
    if not path.exists():
        raise FileNotFoundError(f"页图缺失: {path}")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    uri = f"data:image/jpeg;base64,{b64}"
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"请提取这本书《{getattr(book, 'title', '')}》第 {page_index} 页的完整内容。"},
                {"type": "image_url", "image_url": {"url": uri, "detail": "high"}},
            ],
        },
    ]
    text = client.chat(messages).strip()
    if not text:
        raise RuntimeError(f"第 {page_index} 页提取结果为空")
    return text


def ensure_page_cache(db: Session, book, page_index: int, force: bool = False) -> str:
    """确保指定页有缓存：命中（非空且非 force）直接读取，否则调用多模态 LLM 提取并落盘。

    隐私开关关闭时抛 ValueError（不触发提取）。
    """
    overrides = load_ai_overrides(db)
    enable_body = overrides.get("ai_enable_body_send", settings.ai_enable_body_send)
    if not enable_body:
        raise ValueError("隐私开关已关闭，未触发多模态提取")
    cached = read_page_cache(book, page_index)
    if cached and not force:
        return cached
    client = LLMClient(**vision_client_kwargs(db))
    text = _extract_page_text(client, book, page_index)
    path = page_text_path(book, page_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def ensure_window_caches(db: Session, book, page_index: int, force: bool = False) -> dict[int, str]:
    """按 `[P-1, P, P+1]`（首/末页裁剪）保证窗口内页缓存齐全，返回 {页号: 文本}。

    仅补提取缺失页（增量缓存）；已缓存页直接读取，不重复调用多模态 API。
    """
    total = getattr(book, "page_count", None) or 0
    start = max(1, page_index - 1)
    end = min(total, page_index + 1) if total else page_index + 1
    out: dict[int, str] = {}
    for i in range(start, end + 1):
        out[i] = ensure_page_cache(db, book, i, force=force)
    return out


def rebuild_book_caches(
    db: Session,
    book,
    force: bool = False,
    progress: object | None = None,
) -> dict:
    """重建/补齐全书页缓存：force=False 仅补缺失页，force=True 全部重提取；返回统计。"""
    total = getattr(book, "page_count", 0)
    stats = {"total": total, "extracted": 0, "cached": 0, "failed": 0, "errors": []}
    for i in range(1, total + 1):
        try:
            if not force and read_page_cache(book, i):
                stats["cached"] += 1
                continue
            ensure_page_cache(db, book, i, force=force)
            stats["extracted"] += 1
        except Exception as exc:  # noqa: BLE001 单页失败不中断整体
            stats["failed"] += 1
            stats["errors"].append(f"第 {i} 页: {exc}")
        if progress is not None:
            progress(i, total)
    return stats


def extract_book_pages_task(book_id: int, force: bool = False) -> dict:
    """后台任务入口：打开独立会话，补齐全书页缓存（force=True 全部重提取）。"""
    from app.core.database import SessionLocal
    from app.repositories import books as book_repo

    db = SessionLocal()
    try:
        book = book_repo.get_book(db, book_id)
        if not book:
            return {"error": "书籍不存在"}
        return rebuild_book_caches(db, book, force=force)
    finally:
        db.close()
