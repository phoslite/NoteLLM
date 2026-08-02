"""健康检查与书籍导入链路测试。"""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert r.json()["data"]["status"] == "ok"


def test_books_empty(client):
    r = client.get("/api/books")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_upload_read_delete(client):
    md = "# 第一章 开始\n\n内容一\n\n# 第二章 进阶\n\n内容二\n".encode()
    r = client.post("/api/books", files={"file": ("测试书.md", md, "text/markdown")})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["format"] == "md"
    assert data["total_chapters"] == 2

    detail = client.get(f"/api/books/{data['id']}").json()["data"]
    assert len(detail["chapters"]) == 2
    assert detail["chapters"][0]["title"] == "第一章 开始"

    deleted = client.delete(f"/api/books/{data['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/books/{data['id']}").status_code == 404

def test_book_tags_roundtrip(client):
    md = "# 第一章\n\n内容\n".encode()
    book_id = client.post("/api/books", files={"file": ("书.md", md, "text/markdown")}).json()["data"]["id"]
    r = client.patch(f"/api/books/{book_id}", json={"tags": ["学习方法", "效率"]})
    assert r.status_code == 200
    assert r.json()["data"]["tags"] == ["学习方法", "效率"]
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    assert isinstance(detail["tags"], list)
    listed = client.get("/api/books").json()["data"][0]
    assert listed["tags"] == ["学习方法", "效率"]