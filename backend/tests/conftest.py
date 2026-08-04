"""pytest 公共夹具：独立临时数据目录与测试库。"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="llmnotebook_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["DB_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db").replace("\\", "/")
os.environ["DOMAIN_TERMS_FILE"] = os.path.join(_TMP, "domain_terms.txt")  # 专业术语词库隔离到临时目录

# M10 验收测试隔离：屏蔽真实 .env 中的 AI / 多模态配置，保证测试确定性——
# 「未配置 API → 400」类断言生效，且导入 PDF 时后台视觉预提取任务（依赖 vision 配置）不会与测试竞争。
for _k in (
    "AI_API_KEY", "AI_BASE_URL", "AI_MODEL", "AI_MODE", "AI_THINKING_TYPE", "AI_REASONING_EFFORT",
    "VISION_API_KEY", "VISION_BASE_URL", "VISION_MODEL",
):
    os.environ[_k] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _sync_tasks(monkeypatch):
    """后台任务同步化（决策 35 改造适配）：测试内 submit 立即执行。

    导入/图谱/测试连接已后台化，异步线程会跨测试产生竞态；
    统一替换为 tasks.submit_sync（同一套落库/配额/进度逻辑），
    保证任务立即可见且不污染后续测试。
    """
    # 注：books.py 不直接引用 submit（两段式经 import_service 提交），无需 patch。
    from app.api.routes import graph as graph_route
    from app.api.routes import settings as settings_route
    from app.services import import_service
    from app.tasks import submit_sync

    for _mod in (graph_route, settings_route, import_service):
        monkeypatch.setattr(_mod, "submit", submit_sync)


@pytest.fixture()
def wait_task():
    """轮询等待后台任务完成（适配 building/task_id 语义），返回任务状态 dict。"""

    def _wait(client, task_id: str, timeout: float = 30.0) -> dict:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = client.get(f"/api/tasks/{task_id}").json()["data"]
            if st["status"] in ("success", "failed"):
                return st
            time.sleep(0.02)
        raise AssertionError(f"task {task_id} 等待超时")

    return _wait


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)