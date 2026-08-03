# LLMnotebook 后端

## 运行

```bash
cd backend
.venv\Scripts\activate        # 或直接使用 .venv\Scripts\python.exe
cp .env.example .env          # 填写 AI_API_KEY
uvicorn app.main:app --host 127.0.0.1 --port 8321
```

- 健康检查：`GET /api/health`；书架/文件夹/阅读/笔记/书签/涂鸦/聊天/脑图/图谱/画像/RAG 资产/视觉提取等 API 见 `docs/使用手册.md`。
- 首次启动自动建表（SQLite WAL）+ `_ensure_columns` 增量列迁移；完整能力与配置见根目录 `README.md` 与 `docs/使用手册.md`。

## 目录结构

见 `技术栈规范.md` §2；分层：api -> services -> repositories -> models。"# NoteLLM" 
