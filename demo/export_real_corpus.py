"""从真实库导出聚类 demo 语料（demo/clustering_demo.py --input 使用）。

用法（任意目录）：
  backend/.venv/Scripts/python.exe demo/export_real_corpus.py
产出：demo/real_corpus.json —— [{"title", "keywords": {词: 频}}]，
关键词复用正式版 extract_keywords/book_keywords（内容寻址缓存）。
"""
import json
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
os.chdir(_BACKEND)  # settings.data_dir 相对 backend 运行目录
sys.path.insert(0, str(_BACKEND))

from app.core.database import SessionLocal
from app.repositories.graph import list_books
from app.services.graph.keywords import book_keywords


def main() -> None:
    db = SessionLocal()
    try:
        books = list_books(db)
        out: list[dict] = []
        for b in books:
            kw = book_keywords(b, 80)
            out.append({"title": b.title, "keywords": kw})
            print(f"  {b.id:>2} kw={len(kw):>3}  {b.title[:44]}")
        path = Path(__file__).resolve().parent / "real_corpus.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"导出 {len(out)} 本 -> {path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
