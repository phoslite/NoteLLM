"""M8 知识图谱：关键词提取、跨书关联、聚类、书内知识图谱、重建与人工反馈。"""


def _import_md(client, name: str, text: str) -> int:
    r = client.post("/api/books", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert r.status_code == 200
    return r.json()["data"]["id"]


def _global_graph(client, wait_task) -> dict:
    """拉取全局图谱；懒构建中时等待后台任务完成再拉取（决策 35 后台化适配）。"""
    data = client.get("/api/graph/books").json()["data"]
    if data.get("building"):
        st = wait_task(client, data["task_id"])
        assert st["status"] == "success", st.get("error")
        data = client.get("/api/graph/books").json()["data"]
    return data


def _intra_graph(client, wait_task, book_id: int) -> dict:
    """拉取书内图谱；构建中时等待后台任务完成再拉取。"""
    data = client.get(f"/api/graph/books/{book_id}").json()["data"]
    if data.get("building"):
        st = wait_task(client, data["task_id"])
        assert st["status"] == "success", st.get("error")
        data = client.get(f"/api/graph/books/{book_id}").json()["data"]
    return data


def _task_result(client, wait_task, task_id: str) -> dict:
    """等待任务完成并返回 result（rebuild/sync 等提交类接口）。"""
    st = wait_task(client, task_id)
    assert st["status"] == "success", st.get("error")
    return st["result"] or {}


def test_extract_keywords():
    from app.services.graph import extract_keywords

    kw = extract_keywords("变分法研究泛函极值问题，泛函分析是基础。Theorem and definition of calculus.")
    assert "泛函" in kw  # 中文二元组
    assert "calculus" in kw  # 英文词
    assert "的" not in kw  # 停用词过滤


def test_global_graph_lazy_build_edges_and_clusters(client, wait_task):
    a = _import_md(client, "书A.md", "# 第一章 变分法基础\n\n变分法研究泛函极值问题。\n\n# 第二章 泛函分析\n\n泛函空间与范数。\n")
    b = _import_md(client, "书B.md", "# 第一章 泛函分析入门\n\n泛函与极值问题在变分法中常见。\n\n# 第二章 变分方法\n\n变分法应用。\n")
    client.patch(f"/api/books/{a}", json={"tags": ["数学"]})
    client.patch(f"/api/books/{b}", json={"tags": ["数学"]})

    data = _global_graph(client, wait_task)
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) >= 1
    edge = data["edges"][0]
    assert edge["strength"] > 0
    assert edge["direction"] == "无"
    assert any(c["name"] == "数学" and c["book_count"] == 2 for c in data["clusters"])
    assert {n["cluster"] for n in data["nodes"]} == {"数学"}


def test_global_graph_folder_cluster_fallback(client, wait_task):
    """无 tag 的书按文件夹名聚类。"""
    a = _import_md(client, "书D.md", "# 第一章 拓扑\n\n拓扑空间与连续映射。\n")
    b = _import_md(client, "书E.md", "# 第一章 拓扑学\n\n拓扑与连续映射应用。\n")
    folder = client.post("/api/folders", json={"name": "数学分析"}).json()["data"]
    for bid in (a, b):
        client.patch(f"/api/books/{bid}", json={"folder_id": folder["id"]})

    data = _global_graph(client, wait_task)
    assert any(c["name"] == "数学分析" and c["book_count"] == 2 for c in data["clusters"])


def test_intra_book_graph_levels_and_dedup(client, wait_task):
    text = (
        "# 第一章 定义与定理\n\n"
        "这里是一个定义：内积空间定义。\n\n"
        "定理 1：完备空间是巴拿赫空间。\n\n"
        "普通段落内容。\n\n"
        "# 第二章 证明方法\n\n"
        "证明：先证明必要性。\n"
    )
    book_id = _import_md(client, "书C.md", text)
    detail = client.get(f"/api/books/{book_id}").json()["data"]
    ch1 = detail["chapters"][0]
    client.post(
        f"/api/books/{book_id}/notes",
        json={
            "chapter_id": ch1["id"],
            "quote_text": "定理 1：完备空间是巴拿赫空间。",
            "note_text": "不理解这条定理",
            "note_type": "不理解",
        },
    )

    data = _intra_graph(client, wait_task, book_id)
    levels = {n["level"] for n in data["nodes"]}
    assert "章节级" in levels
    assert "重要段落" in levels
    assert "用户标记" in levels
    types = {e["relation_type"] for e in data["edges"]}
    assert "前置依赖" in types  # 章节顺序
    assert "承接" in types  # 同章内重要段落

    # 重建幂等：节点与关系数量不变
    rebuilt = _task_result(client, wait_task, client.post(f"/api/graph/books/{book_id}/rebuild").json()["data"]["task_id"])
    after = _intra_graph(client, wait_task, book_id)
    assert len(rebuilt["nodes"]) == len(after["nodes"])
    assert len(rebuilt["edges"]) == len(after["edges"])


def test_rebuild_all_and_relation_feedback(client, wait_task):
    _import_md(client, "书F.md", "# 第一章 概率\n\n概率空间与随机变量。\n")
    _import_md(client, "书G.md", "# 第一章 概率论\n\n概率与随机变量理论。\n")
    stats = _task_result(client, wait_task, client.post("/api/graph/rebuild").json()["data"]["task_id"])
    assert stats["books"] == 2
    assert stats["relations"] >= 1
    assert stats["knowledge_points"] >= 2

    edge_id = _global_graph(client, wait_task)["edges"][0]["id"]
    r = client.post(f"/api/graph/relations/{edge_id}/feedback", json={"action": "修改", "strength": 95})
    assert r.status_code == 200
    assert r.json()["data"]["user_feedback"] == "修改"
    assert r.json()["data"]["strength"] == 95

    edges = _global_graph(client, wait_task)["edges"]
    updated = next(e for e in edges if e["id"] == edge_id)
    assert updated["strength"] == 95 and updated["user_feedback"] == "修改"

    bad = client.post(f"/api/graph/relations/{edge_id}/feedback", json={"action": "未知"})
    assert bad.status_code == 400
    missing = client.post("/api/graph/relations/999999/feedback", json={"action": "确认"})
    assert missing.status_code == 404
def test_domain_auto_cluster_without_tags(client, wait_task):
    """无 tag/文件夹的书按内容自动聚类，不再全部落入「其他」。"""
    _import_md(client, "书H.md", "# 第一章 泛函\n\n泛函空间与泛函分析基础内容。\n")
    _import_md(client, "书I.md", "# 第一章 泛函分析\n\n泛函分析与变分法的关系。\n")
    data = _global_graph(client, wait_task)
    clusters = {c["name"] for c in data["clusters"]}
    assert "其他" not in clusters
    assert any(c["book_count"] == 2 for c in data["clusters"])

def test_sanitize_cluster_name():
    """聚类名清洗：只保留汉字/英文字母/数字与单词间空格，去除特殊标点符号。"""
    from app.services.graph import sanitize_cluster_name

    assert sanitize_cluster_name("数学分析（第3版）！") == "数学分析第3版"
    assert sanitize_cluster_name("Math, Analysis: Vol.2") == "Math Analysis Vol 2"
    assert sanitize_cluster_name("ＡＢＣ１２３，测试。") == "ABC123 测试"
    assert sanitize_cluster_name("线性代数 Linear Algebra") == "线性代数 Linear Algebra"
    assert sanitize_cluster_name("！！！") == ""
    assert sanitize_cluster_name("") == ""


def test_tags_sanitized_on_save(client):
    """保存书籍 tag 时清洗：特殊标点剔除、空 tag 丢弃、重复项去重。"""
    a = _import_md(client, "标签清洗书.md", "# 第一章\n\n内容。\n")
    r = client.patch(f"/api/books/{a}", json={"tags": ["数学：分析", "Math, Vol.2", "！！！", "数学：分析"]})
    assert r.status_code == 200
    assert r.json()["data"]["tags"] == ["数学分析", "Math Vol 2"]


def test_assign_clusters_sanitizes_tag_and_folder(client):
    """assign_clusters：tag 与文件夹名作为簇名时统一清洗。"""
    from app.core.database import SessionLocal
    from app.services.graph import assign_clusters

    a = _import_md(client, "簇名书A.md", "# 第一章\n\n变分法内容。\n")
    b = _import_md(client, "簇名书B.md", "# 第一章\n\n拓扑内容。\n")
    client.patch(f"/api/books/{a}", json={"tags": ["数学（考研）"]})
    folder = client.post("/api/folders", json={"name": "物理：力学（上）"}).json()["data"]
    client.patch(f"/api/books/{b}", json={"folder_id": folder["id"]})

    db = SessionLocal()
    try:
        result = assign_clusters(db)
    finally:
        db.close()
    assert result[a] == "数学考研"
    assert result[b] == "物理力学上"


def test_merge_rename_cleans_legacy_dirty_cluster(client):
    """merge_and_rename_clusters 兜底清洗历史遗留含标点的 post 簇名（无资产时只清洗不重命名）。"""
    from app.core.database import SessionLocal
    from app.models.book import Book
    from app.services.graph import merge_and_rename_clusters

    a = _import_md(client, "旧簇书.md", "# 第一章\n\n变分法内容。\n")
    db = SessionLocal()
    try:
        book = db.get(Book, a)
        book.classify_source = "post"
        book.cluster_name = "分析学：变分（旧）"
        db.commit()
        result = merge_and_rename_clusters(db)
        db.refresh(book)
        assert book.cluster_name == "分析学变分旧"
        assert result["renamed"] >= 1
    finally:
        db.close()

def test_auto_cluster_domain_no_punctuation(client):
    """领域自动聚类：领域名只取关键词，无「#id」标点后缀，同名关键词归入同一领域。"""
    from app.core.database import SessionLocal
    from app.services.graph import assign_clusters

    a = _import_md(client, "领域书A.md", "# 第一章 概率空间\n\n概率空间与随机变量。\n")
    b = _import_md(client, "领域书B.md", "# 第一章 概率论\n\n概率与随机变量理论。\n")
    db = SessionLocal()
    try:
        result = assign_clusters(db)
    finally:
        db.close()
    assert result[a] and result[b]
    assert "#" not in result[a] and "#" not in result[b]
    assert result[a] == result[b] == "概率"

def test_auto_cluster_domain_is_professional_term(client):
    """领域自动聚类：领域名应为专业术语，而非泛化词（定理/阅读/作者名/元数据等）。"""
    from app.core.database import SessionLocal
    from app.services.graph import assign_clusters

    a = _import_md(client, "泛函书.md", "# 第一章 泛函分析\n\n定理：泛函空间中的算子有界性。\n\n泛函分析研究算子与空间。\n")
    b = _import_md(client, "概率书.md", "# 第一章 概率论与数理统计\n\n概率论与数理统计教程内容。\n")
    db = SessionLocal()
    try:
        result = assign_clusters(db)
    finally:
        db.close()
    assert result[a] != "定理"
    assert result[a] in {"泛函", "算子", "空间", "有界", "分析"}
    assert result[b] != "教程"
    assert result[b] in {"概率", "率论", "数理", "统计"}


def test_assign_clusters_persist_false_readonly(client):
    """审查问题 7：assign_clusters(persist=False) 只读链路不写库。"""
    from app.core.database import SessionLocal
    from app.models.book import Book
    from app.services.graph import assign_clusters

    a = _import_md(client, "只读聚类书.md", "# 第一章 概率论\n\n概率与随机变量内容。\n")
    db = SessionLocal()
    try:
        book = db.get(Book, a)
        book.classify_source = None
        book.cluster_name = None
        db.commit()
        result = assign_clusters(db, persist=False)
        db.refresh(book)
        assert result.get(a)
        assert book.classify_source is None  # 只读不落盘
        assign_clusters(db)  # 默认 persist=True 才写库
        db.refresh(book)
        assert book.classify_source in ("tag", "folder", "pre", "post")
    finally:
        db.close()


def _write_lexicon(path, user_lines=(), cached_lines=()):
    """写入专业术语词库（用户区 + 系统缓存区），并让 graph_service 指向该文件。"""
    from app.services.graph import lexicon as graph_service

    original = graph_service.settings.domain_terms_file
    lines = list(user_lines)
    lines.append("")
    lines.append(graph_service._LEXICON_CACHE_MARKER)
    lines.extend(cached_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    graph_service.settings.domain_terms_file = path
    graph_service._DOMAIN_LEXICON_CACHE = None
    return original


def _restore_lexicon(original):
    from app.services.graph import lexicon as graph_service

    graph_service.settings.domain_terms_file = original
    graph_service._DOMAIN_LEXICON_CACHE = None


def test_pick_domain_name_prefers_user_lexicon(tmp_path):
    """领域命名：用户词库术语优先于覆盖书数更高的自动候选。"""
    from types import SimpleNamespace

    from app.services.graph import lexicon as graph_service

    path = tmp_path / "lexicon.txt"
    original = _write_lexicon(path, user_lines=["泛函分析"])
    try:
        cands = {1: {"泛函分析": 10.0, "空间": 50.0}, 2: {"空间": 60.0, "算子": 40.0}}
        members = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        assert graph_service._pick_domain_name(cands, members) == "泛函分析"
    finally:
        _restore_lexicon(original)


def test_pick_domain_name_cached_joins_candidates(tmp_path):
    """领域命名：系统缓存词库作为备选候选（覆盖书数优先，不覆盖更强的自动候选）。"""
    from types import SimpleNamespace

    from app.services.graph import lexicon as graph_service

    path = tmp_path / "lexicon.txt"
    original = _write_lexicon(path, cached_lines=["测度论"])
    try:
        members = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        # 缓存词仅命中 1 本书，自动候选覆盖 2 本 → 自动候选胜
        cands = {1: {"测度论": 100.0, "空间": 60.0}, 2: {"空间": 60.0, "算子": 40.0}}
        assert graph_service._pick_domain_name(cands, members) == "空间"
        # 覆盖书数相同时，词库词（权重 100）胜出
        cands2 = {1: {"测度论": 100.0, "空间": 10.0}}
        assert graph_service._pick_domain_name(cands2, members) == "测度论"
    finally:
        _restore_lexicon(original)


def test_first_meaningful_term_prefers_lexicon(tmp_path):
    """post-classify 自动命名：词库术语优先于首个非泛化关键词。"""
    from app.services.graph import lexicon as graph_service

    path = tmp_path / "lexicon.txt"
    original = _write_lexicon(path, user_lines=["泛函分析"])
    try:
        keywords = {"空间": 5.0, "泛函分析": 3.0}
        assert graph_service._first_meaningful_term(keywords) == "泛函分析"
    finally:
        _restore_lexicon(original)


def test_domain_candidates_include_lexicon_hits(tmp_path):
    """领域候选词：词库中的多字术语命中文本时进入候选（高权重）。"""
    from types import SimpleNamespace

    from app.services.graph import lexicon as graph_service

    path = tmp_path / "lexicon.txt"
    original = _write_lexicon(path, user_lines=["泛函分析"])
    try:
        book = SimpleNamespace(
            title="泛函分析教程",
            chapters=[SimpleNamespace(title="第一章 泛函分析", content_text="泛函分析研究函数空间与算子。")],
        )
        cands = graph_service._domain_candidates(book)
        assert "泛函分析" in cands
        assert cands["泛函分析"] >= 100.0
    finally:
        _restore_lexicon(original)


def test_cache_domain_term_appends_dedup_and_skips_generic(tmp_path):
    """系统缓存：自动术语写入缓存区、去重、泛化词不缓存、缺失文件自动创建。"""
    from app.services.graph import lexicon as graph_service

    path = tmp_path / "lexicon.txt"
    original = _write_lexicon(path, user_lines=["泛函分析"], cached_lines=["概率"])
    try:
        assert graph_service.cache_domain_term("变分法") is True
        text = path.read_text(encoding="utf-8")
        assert "变分法" in text
        assert text.index("变分法") > text.index(graph_service._LEXICON_CACHE_MARKER)
        assert graph_service.cache_domain_term("变分法") is False  # 去重
        assert graph_service.cache_domain_term("泛函分析") is False  # 用户区已有
        assert graph_service.cache_domain_term("定理") is False  # 泛化词不缓存

        missing = tmp_path / "new_lexicon.txt"
        graph_service.settings.domain_terms_file = missing
        graph_service._DOMAIN_LEXICON_CACHE = None
        assert graph_service.cache_domain_term("测度论") is True
        content = missing.read_text(encoding="utf-8")
        assert "测度论" in content
    finally:
        _restore_lexicon(original)

def test_cache_domain_term_atomic_write_no_tmp_residue(tmp_path):
    """审查 C-问题8：词库写入走临时文件原子替换，不残留 .tmp。"""
    from app.services.graph import lexicon as graph_service

    path = tmp_path / "lexicon_atomic.txt"
    original = _write_lexicon(path, user_lines=[], cached_lines=[])
    try:
        assert graph_service.cache_domain_term("测度论") is True
        text = path.read_text(encoding="utf-8")
        assert "测度论" in text
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], "原子替换不应残留 .tmp 临时文件"
    finally:
        _restore_lexicon(original)
