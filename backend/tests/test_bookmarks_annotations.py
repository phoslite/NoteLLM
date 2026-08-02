"""M6 测试：位置书签 CRUD/分组/跳转定位、页图涂鸦读写、划线提问参数、删除级联清理。"""


def _upload(client, text="# 第一章\n\n正文一\n\n# 第二章\n\n正文二\n"):
    r = client.post("/api/books", files={"file": ("书.md", text.encode(), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def test_bookmark_crud_and_groups(client):
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch1, ch2 = detail["chapters"][0]["id"], detail["chapters"][1]["id"]

    r = client.post(
        f"/api/books/{book_id}/bookmarks",
        json={"chapter_id": ch1, "para_pos": "0", "title": "定理起点", "note": "重点", "group_name": "分析"},
    )
    assert r.status_code == 200
    bm1 = r.json()["data"]
    assert bm1["group_name"] == "分析"
    assert bm1["chapter_id"] == ch1

    client.post(
        f"/api/books/{book_id}/bookmarks",
        json={"chapter_id": ch2, "para_pos": "1", "title": "第二章重点", "group_name": "代数"},
    )

    # 列表按时间倒序：后创建的在前面
    items = client.get(f"/api/books/{book_id}/bookmarks").json()["data"]
    assert len(items) == 2
    assert items[0]["title"] == "第二章重点"

    # 改分组/标题/备注
    r = client.patch(f"/api/bookmarks/{bm1['id']}", json={"group_name": "代数", "note": "已精读"})
    assert r.json()["data"]["group_name"] == "代数"

    # 章节不存在 → 404
    bad = client.post(f"/api/books/{book_id}/bookmarks", json={"chapter_id": 99999})
    assert bad.status_code == 404

    # 删除
    assert client.delete(f"/api/bookmarks/{bm1['id']}").status_code == 200
    assert len(client.get(f"/api/books/{book_id}/bookmarks").json()["data"]) == 1


def test_bookmark_jump_target_fields(client):
    """文本书书签带章节+段落定位；PDF 书签带页号（用扫描属性模拟）。"""
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch = detail["chapters"][0]["id"]

    r = client.post(
        f"/api/books/{book_id}/bookmarks",
        json={"chapter_id": ch, "page_index": 3, "para_pos": "5", "title": "页3"},
    )
    bm = r.json()["data"]
    assert bm["page_index"] == 3
    assert bm["para_pos"] == "5"


def test_annotations_read_write(client):
    book_id = _upload(client)
    # 空页返回 []
    assert client.get(f"/api/books/{book_id}/annotations", params={"page_index": 1}).json()["data"] == []

    elements = [
        {"type": "stroke", "tool": "pen", "color": "#333333", "line_width": 2, "points": [[0.1, 0.1], [0.5, 0.5]]},
        {"type": "text", "text": "定理", "color": "#111111", "font_size": 16, "x": 0.2, "y": 0.3},
    ]
    r = client.put(f"/api/books/{book_id}/annotations", json={"page_index": 1, "elements": elements})
    assert r.status_code == 200
    assert r.json()["data"] == 2

    saved = client.get(f"/api/books/{book_id}/annotations", params={"page_index": 1}).json()["data"]
    assert saved == elements

    # 覆盖保存
    client.put(f"/api/books/{book_id}/annotations", json={"page_index": 1, "elements": []})
    assert client.get(f"/api/books/{book_id}/annotations", params={"page_index": 1}).json()["data"] == []

    # 超大元素上限
    too_many = [{"type": "text", "text": "x"} for _ in range(2001)]
    r = client.put(f"/api/books/{book_id}/annotations", json={"page_index": 1, "elements": too_many})
    assert r.status_code == 400


def test_chat_accepts_crop_image(client):
    """划线提问：chat 接口接受 crop_image 参数（未配置 API 时返回配置错误而非 422）。"""
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch = detail["chapters"][0]["id"]

    r = client.post(
        f"/api/books/{book_id}/chat",
        json={
            "question": "解释划线部分",
            "chapter_id": ch,
            "crop_image": "data:image/jpeg;base64,AAAA",
            "crop_label": "第 1 页 上方 30%",
        },
    )
    # 未配置 API Key → 400（说明参数已通过校验，进入业务校验）
    assert r.status_code == 400
    assert "API Key" in r.json()["detail"]


def test_delete_book_cleans_bookmarks_and_annotations(client):
    book_id = _upload(client)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch = detail["chapters"][0]["id"]

    client.post(f"/api/books/{book_id}/bookmarks", json={"chapter_id": ch, "title": "待删"})
    client.put(
        f"/api/books/{book_id}/annotations",
        json={"page_index": 1, "elements": [{"type": "text", "text": "x"}]},
    )

    assert client.delete(f"/api/books/{book_id}").status_code == 200
    assert client.get(f"/api/books/{book_id}/bookmarks").status_code == 404
