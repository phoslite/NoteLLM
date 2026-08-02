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


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)