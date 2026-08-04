"""ORM 模型注册：import 即注册到 Base.metadata。"""
from app.models.activity import Bookmark, ChatMessage, Note, ReadingLog  # noqa: F401
from app.models.asset import BookAsset  # noqa: F401
from app.models.book import Book, Chapter, Folder  # noqa: F401
from app.models.graph import BookRelation, KnowledgePoint, KpRelation  # noqa: F401
from app.models.llm_cache import LlmCache  # noqa: F401
from app.models.profile import Setting, UserProfile  # noqa: F401
from app.models.task import Task  # noqa: F401