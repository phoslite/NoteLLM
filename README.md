# 读书阅读助手（LLMnotebook）

![License](https://img.shields.io/badge/license-MIT-blue.svg)

本地单用户、本地优先的读书阅读助手：导入 PDF / Markdown / TXT / EPUB 书籍，提供三栏阅读工作台（左：书架 + 目录；中：正文阅读区；右：AI 助手），持续沉淀三层个性化画像与跨书知识谱系，把读过的书连成一张可检索、可追问的知识网络。


## 文档索引

| 文档 | 版本 | 内容 |
| --- | --- | --- |
| [需求文档.md](需求文档.md) | v1.38 | 需求边界、开放项与验收标准 |
| [技术栈规范.md](技术栈规范.md) | v1.44 | 技术选型、工程规范、解耦/重构规则 |
| [重构规范.md](重构规范.md) | v1.23 | 重构记录表与变更记录 |
| [docs/使用手册.md](docs/使用手册.md) | v1.68 | 已实现函数的使用与修改手册 |

## 功能总览

- **书架与主页**：左侧「近期阅读」（最近 5 本，按打开时间倒序），右侧「书架」；文件夹多级归类（未打 tag 的书默认继承文件夹 tag）、拖拽排序、搜索/标签筛选、手动 tag；书籍卡片渲染封面（PDF/EPUB 自动提取）；阅读进度（已读章节/总章节 + 进度条，自动与手动标记）。
- **阅读体验**：正文支持 Markdown / LaTeX 渲染；PDF 统一按页处理（含文本型，规避公式乱码），直接以原图分辨率阅读并支持缩放（适配宽度 / 原始大小 / ＋－）；位置书签（全格式，支持分组与跳转）；PDF 页图涂鸦（笔刷 / 高亮 / 橡皮 / 文本、撤销最多 5 步、划线批注与划线区域提问）；笔记支持 Markdown/LaTeX 并可导出 Markdown / PDF。
- **AI 助手**：设置页配置 OpenAI 兼容 API（文本与多模态独立配置）；按章节上下文问答、SSE 流式输出、自动标注出处【第X章 第Y段】；划词菜单（解释选中段 / 该段脑图 / 加入思考清单）；生成解读 / 概论 / 脑图 / 思考逻辑；脑图为 ECharts 三层树图（大纲 / 细节 / 重要定理），支持下载大纲 .md、导出 PNG、插入为本章批注。
- **多模态视觉提取（M7）**：对 PDF 提问时按 `[P-1, P, P+1]` 滑动窗口调用视觉模型提取页面完整信息，缓存到书籍目录 `page_text/`，缓存命中不重复调用；导入 PDF 作为知识库时后台批量预提取；读完归档时全书批量提取。
- **知识图谱（M8）**：`/graph` 书籍级谱系图，先按用户 tag → 文件夹 → 领域自动聚类分层（优先匹配用户可编辑的专业术语词库）；点击书籍展示书内知识点分布谱系（章节级 + 重要段落 + 用户笔记/不理解段落）；关联强度 = LLM 打分 + 关键词共现 + 笔记加权，边带理论传承方向箭头与关联原因；支持人工反馈、重建与跨书知识检索；图谱更新自动联动 RAG/Skill 增量增改与暖画像。
- **个性化画像（M9）**：三层画像（冷 = 重要但不常调用 / 暖 = 近期 1-2 本书 / 热 = 当前书细节）；归档迁移阈值按对话跨越 1 / 3 / >3 本书界定并自动学习；相关度阈值函数已落地。
- **RAG / Skill 资产**：资料页（`/rag`）上传 Markdown / PDF / TXT / EPUB → AI 自动总结生成 RAG（摘要 + 关键知识点 + 段落级检索片段，带出处）与 Skill（技能）资产；再次阅读同一本书并结束对话时在原资产上增量增改；按书籍内容 hash 自动合并重复资产（多书共享一份），支持单条删除资产条目、手动合并重复资产；删除书籍级联移除资产（共享时解除引用或自动转移主资产）；结束对话归档为触发方式（优先用户主动归档）。
- **一键启动**：`start.bat` 自动检查依赖与端口占用（已在运行则跳过，避免 10048），找不到 pnpm 时自动回退用 node 直接运行 vite。

## 页面导航

| 路由 | 页面 |
| --- | --- |
| `/` | 主页（近期阅读 + 书架，可切换谱系图视图） |
| `/reader/:bookId` | 三栏阅读工作台 |
| `/graph` | 跨书谱系图 / 书内知识图谱 |
| `/rag` | 资料页（外部资料 → RAG/Skill 资产） |
| `/profile` | 个性化画像 |
| `/settings` | 文本 AI / 多模态 / 隐私配置 |

## 环境要求

- Python 3.11+
- Node.js 18+（pnpm 优先；缺失时 `start.bat` 自动回退 node 直接运行 vite）

## 快速开始（一键启动）

1. 先完成下方「首次准备」。
2. 双击根目录 `start.bat`：自动启动后端（8321）与前端（5173）并打开浏览器；服务已在运行时自动跳过启动。

### 首次准备

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env        # 填写 AI_API_KEY；可选 VISION_API_KEY（多模态）
cd ..\frontend
pnpm install
```

## 手动启动

### 后端（端口 8321）

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8321
```

- 健康检查：`GET http://127.0.0.1:8321/api/health` 返回 `{"code":0,...}` 即正常。
- 数据目录 `backend/data/`（SQLite WAL + 书籍文件与页图缓存），首次启动自动建表。

### 前端（端口 5173）

```powershell
cd frontend
pnpm dev
```

- 打开 http://127.0.0.1:5173；Vite 已配置代理 `/api → http://127.0.0.1:8321`。

### 生产构建（可选）

```powershell
cd frontend
pnpm build      # vue-tsc 类型检查 + vite 构建，产物 frontend/dist/
```

## 配置说明（backend/.env）

| 配置项 | 说明 |
| --- | --- |
| `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` / `AI_MODE` | 文本大模型（OpenAI 兼容，默认 DeepSeek `responses` 模式） |
| `AI_ENABLE_BODY_SEND` | 隐私开关，`false` 时不向模型发送书籍正文 |
| `AI_MAX_TOKENS` / `AI_THINKING_TYPE` / `AI_REASONING_EFFORT` 等 | 文本模型精细参数（`chat` 模式生效，参考 DeepSeek 思考模式文档） |
| `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` / `VISION_MAX_TOKENS` 等 | 多模态视觉 API（默认 SiliconFlow，强制 `chat` 模式，独立于文本 AI） |
| `DOMAIN_TERMS_FILE` | 专业术语词库路径（默认 `domain_terms.txt`，与 `.env` 同级） |

- **专业术语词库** `backend/domain_terms.txt`：每行一个术语（中文词组或英文词组），上方为用户自定义区（最高优先级，修改即时生效），下方为系统缓存区（可编辑/删除）；模板见 `backend/domain_terms.txt.example`。

## LLM 对话 Demo（无 Key 联调）

```powershell
python demo/chat_demo.py --mock --prompt "你好"     # 本地 mock，无需 API Key
python demo/_mock_llm.py                            # 启动 mock 服务（18999）
```

设置页填入 `http://127.0.0.1:18999/v1` 与任意 Key 即可全链路联调。

## 端口约定

| 服务 | 地址 |
| --- | --- |
| 后端 API | http://127.0.0.1:8321 |
| 前端开发服务器 | http://127.0.0.1:5173 |
| Mock LLM（demo） | http://127.0.0.1:18999 |

## 测试与检查

```powershell
cd backend && .\.venv\Scripts\python.exe -m pytest -q          # 后端 151 项全过
cd backend && .\.venv\Scripts\python.exe -m ruff check app tests
cd frontend && pnpm build                                      # vue-tsc + vite 构建
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `'pnpm' is not recognized...` | 安装 pnpm（`npm install -g pnpm`），或直接用 `start.bat`（自动回退 node 运行 vite） |
| 后端启动 `[Errno 10048] ... address already in use` | 后端已在运行；`start.bat` 会检测端口占用并跳过重复启动，或先结束占用 8321 的进程 |
| AI 面板 `网络错误: ... WinError 10013` | 防火墙/安全软件拦截出站连接、代理/VPN 抢占端口或受限沙箱；先点设置页「测试连接」排查 |

## 开源协议

本项目基于 [MIT License](LICENSE) 开源：

- 可自由使用、修改、分发与商用，但须保留版权声明与许可文本。
- 软件按「现状」提供，不附带任何明示或暗示的担保。
- 第三方依赖（FastAPI / Vue / ECharts / PyMuPDF 等）遵循其各自的开源协议。

## 开发约定

- 提交信息使用 Conventional Commits，主要开发分支 `main`。
- 每轮任务后更新 `docs/使用手册.md`（已实现函数的使用与修改说明），并按要求在 `重构规范.md` 记录审查与解耦重构。
