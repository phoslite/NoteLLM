"""页图涂鸦标注服务（审查 P0-6）：文件持久化从路由下沉，路由只做参数校验与响应包装。

涂鸦元素 JSON 约定（需求 3.5 / 技术栈规范 §4.7）：
- stroke：{type:'stroke', tool:'pen'|'highlight', color, line_width, points:[[x,y],...], note?, note_meta?}
- text：{type:'text', text, color, font_size, x, y}
撤销栈仅前端会话内维护，本服务只保存最终元素列表，不保存历史版本。
"""
import json
from pathlib import Path

MAX_ELEMENTS = 2000


def annotations_dir(book) -> Path:
    """按书目录定位标注文件夹（book.file_path 同级 annotations/）。"""
    return Path(book.file_path).parent / "annotations"


def annotations_path(book, page_index: int) -> Path:
    """单页标注文件路径（page_XXX.json）。"""
    return annotations_dir(book) / f"page_{page_index:03d}.json"


def read_page_annotations(book, page_index: int) -> list[dict]:
    """读取指定页涂鸦元素；文件缺失或损坏返回空数组。"""
    path = annotations_path(book, page_index)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        return []
    return []


def save_page_annotations(book, page_index: int, elements: list[dict]) -> int:
    """整页覆盖式保存涂鸦元素；返回元素数。超出上限抛 ValueError（由路由转 400）。"""
    if len(elements) > MAX_ELEMENTS:
        raise ValueError(f"单页涂鸦元素过多（上限 {MAX_ELEMENTS}）")
    path = annotations_path(book, page_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
    return len(elements)
