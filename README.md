# 读书阅读助手（LLMnotebook）

本地单用户的读书阅读助手：导入 PDF / Markdown / TXT / EPUB 书籍，阅读页左侧为书架 + 目录、中间为正文阅读区、右侧为 AI 助手（解读 / 概论 / 脑图 / 思考逻辑），并持续沉淀个性化画像与跨书知识谱系。

> 详细文档：`需求文档.md`、`技术栈规范.md`、`重构规范.md`、`docs/使用手册.md`

## 环境要求

- Python 3.11+
- Node.js 18+ 与 pnpm（推荐 pnpm 11，配置见 `frontend/pnpm-workspace.yaml`）

## 一键启动

双击根目录的 `start.bat`：自动启动后端（8321）与前端（5173），并打开浏览器。前端命令会自动解析 pnpm（找不到时直接用 node 运行 vite，无需额外安装）。首次使用需先完成下方「首次准备」。

## 启动步骤

### 0. 首次准备

```bash
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env          # 填写 AI_API_KEY（DeepSeek 等 OpenAI 兼容服务）

cd ..\frontend
pnpm install
```

### 1. 启动后端（端口 8321）

```bash
cd backend
python -m venv .venv                              # 首次
.venv\Scripts\python -m pip install -e ".[dev]"   # 首次安装依赖
copy .env.example .env                            # 首次：填写 AI_API_KEY（DeepSeek 等 OpenAI 兼容服务）
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8321
```

- 健康检查：`GET http://127.0.0.1:8321/api/health`，返回 `{"code":0,...}` 即正常。
- 首次启动自动建表（SQLite WAL，数据在 `backend/data/`）。

### 2. 启动前端（端口 5173）

```bash
cd frontend
pnpm install     # 首次
pnpm dev
```

- 浏览器打开 http://127.0.0.1:5173
- Vite 已配置代理：`/api` → `http://127.0.0.1:8321`，无需处理跨域。

### 3. 生产构建（可选）

```bash
cd frontend
pnpm build       # vue-tsc 类型检查 + vite 构建，产物在 frontend/dist/
```

### 4. LLM 对话 Demo（可选）

```bash
python demo/chat_demo.py --mock --prompt "你好"          # 本地 mock，无需 API Key
python demo/chat_demo.py --prompt "你好"                 # 使用 demo/.env 的真实配置
```

## AI 助手对话（M4）

- 设置页（`/settings`）配置 Base URL / API Key / 模型 / 接口模式（`responses` 或 `chat`）/ 超时 / 隐私开关（是否发送书籍正文），支持「测试连接」。
- M5 AI 增强：阅读页「脑图」生成 ECharts 树形脑图（大纲/细节/重要定理三层，节点名自动清洗 LaTeX/Markdown 记号；节点点击跳转原文；支持复制大纲、下载大纲 .md、导出 PNG、插入为本章批注）；划词菜单支持「解释选中段」「该段脑图」「加入思考清单」；笔记正文支持 Markdown/LaTeX 渲染。
- 阅读页右栏 AI 助手：基于当前章节上下文问答，自动附带阅读区划词选区；回复支持 Markdown / LaTeX 并标注 `【第X章 第Y段】` 出处；对话历史按书保存，可清空。
- 无 API Key 联调：`python demo/_mock_llm.py` 启动 mock（18999），设置页填 `http://127.0.0.1:18999/v1` 与任意 Key。
- 相关 API：`POST /api/books/{id}/chat`（SSE 流式）、`GET / DELETE /api/books/{id}/chat/messages`、`GET / PATCH /api/settings/ai`、`POST /api/settings/ai/test`。
- 排查：若 AI 面板报 `网络错误: ... WinError 10013`，通常是系统防火墙/安全软件拦截出站连接、代理/VPN 抢占端口，或程序运行在受限沙箱中（出站 TCP 被禁止）。请用 `start.bat` 或普通终端启动后端后重试；也可先点设置页「测试连接」确认连通性。

## PDF 封面 / 按页阅读（M4 补充）

- 导入 PDF/EPUB 时自动提取封面，书架卡片渲染封面图（无封面时显示格式徽章）。
- PDF **统一按页处理（含文本型，需求 v1.9）**：不再区分扫描版/文本型——文本型 PDF 直接抽取文本时数学公式/符号会乱码，因此统一按原始页数切章、阅读页直接展示**原图**（按 PDF 内嵌原图分辨率渲染，支持「适配宽度 / 原始大小 / ＋/－」缩放与横向滚动），目录为「第 N 页」；本地文本抽取仅保留为**全文检索索引**，不用于正文展示与 AI 上下文。
- 设置页「发送页面图片」开启后，对 PDF（按页处理）提问会自动把当前页图片作为附件发送给 LLM（chat 模式，需模型支持视觉输入；关闭隐私开关时不发送）。
- PDF（含文本型）AI 解读统一走页图 + 多模态提取（M7 已实现，见需求文档 3.4.11）：配置多模态 API 后，用户在当前页提问时按 `[P-1,P,P+1]` 滑动窗口提取页面完整信息并缓存到书籍目录（`page_text/`），文本大模型基于缓存解读，缓存命中不重复调用多模态 API；导入 PDF 作为知识库时后台批量预提取，设置页可独立配置多模态 API（含视觉推理参数）。
- 阅读增强（M6 已实现）：任意格式支持位置书签并跳转（PDF 整页 / 文本书章节+段落，书签可分组归类）；PDF 按页阅读时支持页图涂鸦划线标注（画板式：笔刷/高亮/橡皮/文本、撤销最多 5 步、划线批注与划线区域提问，随页保存）。
- 相关 API：`GET /api/books/{id}/cover`、`GET /api/books/{id}/pages/{page_index}`；封面缺失的旧书会在启动时自动回填，新书每本独立子目录存储，避免封面串书。
- 书架卡片悬停显示 🗑 删除按钮：删除书籍会一并清理其笔记、对话记录、RAG/Skill 资产与本地文件（`DELETE /api/books/{id}`）。

## 外部资料 → RAG / Skill

- 页面：顶部导航「资料」（`/rag`），上传 Markdown / PDF / TXT / EPUB 文件。
- 流程：导入书籍 → 后台调用 AI 总结 → 生成 RAG 资产（摘要 + 关键知识点 + 段落级检索片段，含章节/段落出处）与 Skill 资产（可复用技能），存入 `BookAsset` 表，重复总结在原资产上 `version + 1`。
- 无 API Key 时可先用本地 mock 验证链路：`python demo/_mock_llm.py`，然后以环境变量启动后端：
  `set AI_BASE_URL=http://127.0.0.1:18999/v1 && set AI_API_KEY=mock && .venv\Scripts\python -m uvicorn app.main:app --port 8321`
- 相关 API：`POST /api/books/{id}/summarize`（提交任务）、`GET /api/tasks/{task_id}`（轮询状态）、`GET /api/books/{id}/asset`（读取资产）。

## M10 打磨（v1.31）

- **笔记导出 Markdown + PDF**：阅读页笔记抽屉「导出 Markdown / 导出 PDF」；API `GET /api/books/{id}/notes/export?fmt=md|pdf`（默认 md）。PDF 由后端 PyMuPDF 内嵌 CJK 字体生成 A4，保留章节定位/引文/正文结构，笔记中的 LaTeX 公式以源码保留（PDF 端不做公式排版）。
- **性能优化**：PDF 页图目标宽度进程内缓存（翻页不再重开 PDF）、页图 `Cache-Control` 10 分钟（翻页走浏览器缓存）、前端预加载相邻页、vite vendor 分包（echarts 按需加载，阅读页主 chunk 189KB→56KB）。
- **验收测试**：新增笔记导出 pytest（MD/PDF/参数校验）；测试环境与真实 `.env` 的 AI/视觉配置隔离，后端全量 **128 通过**、ruff 全绿、vue-tsc + vite build 通过。

## 端口约定

| 服务 | 地址 |
| --- | --- |
| 后端 API | http://127.0.0.1:8321 |
| 前端开发服务器 | http://127.0.0.1:5173 |
| Mock LLM（demo） | http://127.0.0.1:18999 |

## 常用命令

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest -q   # 后端测试
cd backend && .\.venv\Scripts\python.exe -m ruff check app tests   # 后端 lint
```