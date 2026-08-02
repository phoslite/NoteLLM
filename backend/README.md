# LLMnotebook 后端（M2 骨架）

## 运行

```bash
cd backend
.venv\Scripts\activate        # 或直接使用 .venv\Scripts\python.exe
cp .env.example .env          # 填写 AI_API_KEY
uvicorn app.main:app --host 127.0.0.1 --port 8321
```

- 健康检查：`GET /api/health`
- 书架：`GET/POST/DELETE /api/books`、文件夹 `GET/POST/PATCH/DELETE /api/folders`
- 首次启动自动建表（SQLite WAL）；后续模型变更走 Alembic 迁移。

## 目录结构

见 `技术栈规范.md` §2；分层：api -> services -> repositories -> models。"# NoteLLM" 
