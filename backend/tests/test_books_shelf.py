"""书架 UI 配套后端能力：position 排序、拖拽换位 reorder、搜索（书名/作者/标签）。"""


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode(), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _ids(client) -> list[int]:
    return [b["id"] for b in client.get("/api/books").json()["data"]]


def test_books_ordered_by_position_on_import(client):
    """新书按导入顺序获得递增 position，列表按 position 升序返回。"""
    ids = [_import_md(client, f"排位书{i}.md", f"# 排位书{i}\n\n内容{i}。\n") for i in range(3)]
    assert _ids(client) == ids
    data = client.get("/api/books").json()["data"]
    positions = [b["position"] for b in data]
    assert positions == sorted(positions) == [1, 2, 3]


def test_reorder_books_persists(client):
    """POST /api/books/reorder 按 ordered_ids 重排，再次读取顺序持久化。"""
    ids = [_import_md(client, f"换位书{i}.md", f"# 换位书{i}\n\n内容{i}。\n") for i in range(4)]
    reversed_ids = list(reversed(ids))
    r = client.post("/api/books/reorder", json={"ordered_ids": reversed_ids})
    assert r.status_code == 200
    assert r.json()["data"]["reordered"] == 4
    assert _ids(client) == reversed_ids
    data = client.get("/api/books").json()["data"]
    positions = {b["id"]: b["position"] for b in data}
    for pos, book_id in enumerate(reversed_ids, start=1):
        assert positions[book_id] == pos


def test_reorder_ignores_unknown_ids(client):
    """reorder 中不存在的 id 被忽略，其余按给定顺序落位。"""
    ids = [_import_md(client, f"容忍书{i}.md", f"# 容忍书{i}\n\n内容{i}。\n") for i in range(2)]
    r = client.post("/api/books/reorder", json={"ordered_ids": [999999, ids[1], ids[0]]})
    assert r.status_code == 200
    assert _ids(client) == [ids[1], ids[0]]


def test_patch_position_single_book(client):
    """PATCH position 可单本调整排序位。"""
    ids = [_import_md(client, f"单排书{i}.md", f"# 单排书{i}\n\n内容{i}。\n") for i in range(3)]
    r = client.patch(f"/api/books/{ids[2]}", json={"position": 1})
    assert r.status_code == 200
    assert r.json()["data"]["position"] == 1
    assert _ids(client) == [ids[2], ids[0], ids[1]]


def test_search_books_by_title_author_tag(client):
    """q 搜索书名 / 作者 / 标签。"""
    a = _import_md(client, "概率论与数理统计.md", "# 概率论与数理统计\n\n内容。\n")
    _import_md(client, "泛函分析.md", "# 泛函分析\n\n内容。\n")
    r = client.post(
        "/api/books",
        files={"file": ("作者书.md", "# 作者书\n\n内容。\n".encode(), "text/markdown")},
        data={"author": "张某某"},
    )
    c = r.json()["data"]["id"]
    client.patch(f"/api/books/{a}", json={"tags": ["数学", "概率"]})

    assert [x["id"] for x in client.get("/api/books", params={"q": "概率论"}).json()["data"]] == [a]
    assert [x["id"] for x in client.get("/api/books", params={"q": "张某某"}).json()["data"]] == [c]
    assert [x["id"] for x in client.get("/api/books", params={"q": "概率"}).json()["data"]] == [a]
    # 无匹配返回空列表
    assert client.get("/api/books", params={"q": "不存在的书名"}).json()["data"] == []


def test_search_combined_with_folder(client):
    """folder_id 与 q 可组合过滤。"""
    folder = client.post("/api/folders", json={"name": "数学类"}).json()["data"]
    a = _import_md(client, "高等数学.md", "# 高等数学\n\n内容。\n")
    _import_md(client, "线性代数.md", "# 线性代数\n\n内容。\n")
    client.patch(f"/api/books/{a}", json={"folder_id": folder["id"]})
    only_folder = client.get("/api/books", params={"folder_id": folder["id"]}).json()["data"]
    assert [x["id"] for x in only_folder] == [a]
    searched = client.get("/api/books", params={"folder_id": folder["id"], "q": "线性"}).json()["data"]
    assert searched == []


def test_patch_book_folder_id_null_moves_out(client):
    """D8 修复（2026-08-11）：PATCH folder_id=null 把书移出文件夹（哨兵语义区分未传/置空）。"""
    folder = client.post("/api/folders", json={"name": "待移出"}).json()["data"]
    a = _import_md(client, "移出测试.md", "# 移出测试\n\n内容。\n")
    client.patch(f"/api/books/{a}", json={"folder_id": folder["id"]})
    assert client.get(f"/api/books/{a}").json()["data"]["folder_id"] == folder["id"]
    resp = client.patch(f"/api/books/{a}", json={"folder_id": None})
    assert resp.status_code == 200
    assert client.get(f"/api/books/{a}").json()["data"]["folder_id"] is None
    # 未传 folder_id 时保持不变（哨兵不误伤其他字段更新）
    client.patch(f"/api/books/{a}", json={"tags": ["保持"]})
    assert client.get(f"/api/books/{a}").json()["data"]["folder_id"] is None


def test_patch_book_invalid_folder_id_returns_404(client):
    """终审 §6.9：PATCH 无效 folder_id 与全库「资源不存在→404」契约一致。"""
    r = client.post("/api/books", files={"file": ("无效文件夹.md", "# 第一章\n\n正文\n".encode(), "text/markdown")})
    book_id = r.json()["data"]["id"]
    resp = client.patch(f"/api/books/{book_id}", json={"folder_id": 999999})
    assert resp.status_code == 404

def test_clean_tags_keeps_user_punctuation():
    """E2E M-2（2026-08-11）：手动 tag 保留用户输入原样（含连字符等标点），只去空白/空值/重复。"""
    from app.services.books_service import clean_tags

    assert clean_tags(["e2e-tag-msnj2njl"]) == ["e2e-tag-msnj2njl"]
    assert clean_tags(["  ABC-DEF  ", "abc def", "ABC-DEF"]) == ["ABC-DEF", "abc def"]
    assert clean_tags(["", "   ", "有效标签"]) == ["有效标签"]
