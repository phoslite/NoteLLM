# 读书阅读助手（LLMnotebook）

![License](https://img.shields.io/badge/license-MIT-blue.svg)

本地单用户、本地优先的读书阅读助手：导入 PDF / Markdown / TXT / EPUB 书籍，提供三栏阅读工作台（左：书架 + 目录；中：正文阅读区；右：AI 助手），持续沉淀三层个性化画像与跨书知识谱系，把读过的书连成一张可检索、可追问的知识网络。


## 文档索引

| 文档 | 版本 | 内容 |
| --- | --- | --- |
| [需求文档.md](需求文档.md) | v1.66 | 需求总纲：概述 / 分册索引 / 变更记录 |
| [需求-功能需求.md](需求-功能需求.md) | v1.58 | 分册：书架 / 导入 / 阅读 / AI 助手 / 图谱需求 |
| [需求-非功能与数据.md](需求-非功能与数据.md) | v1.58 | 分册：非功能 / 数据模型 / 页面交互 |
| [需求-里程碑与验收.md](需求-里程碑与验收.md) | v1.58 | 分册：里程碑 / 验收标准 |
| [需求-决策.md](需求-决策.md) | v1.58 | 分册：决策 1~33 / 开放项 |
| [技术栈规范.md](技术栈规范.md) | v1.71 | 技术选型、工程规范、解耦/重构规则 |
| [重构规范.md](重构规范.md) | v1.38 | 重构记录表与变更记录 |
| [docs/使用手册.md](docs/使用手册.md) | v1.105 | 手册总纲：模块地图 / 快速定位 / 跨模块流程 / 变更记录 |
| [docs/使用手册-后端核心.md](docs/使用手册-后端核心.md) | v1.90 | 分册：配置/数据库/解析/导入/任务/API 基础 |
| [docs/使用手册-阅读与PDF.md](docs/使用手册-阅读与PDF.md) | v1.90 | 分册：阅读闭环/书签/涂鸦/页图/视觉提取 |
| [docs/使用手册-AI与资产.md](docs/使用手册-AI与资产.md) | v1.90 | 分册：LLM/对话/脑图/RAG/Skill/Prompt |
| [docs/使用手册-图谱与画像.md](docs/使用手册-图谱与画像.md) | v1.90 | 分册：图谱/聚类/画像/阈值学习 |
| [docs/使用手册-前端.md](docs/使用手册-前端.md) | v1.90 | 分册：前端组件/组合式函数/工具 |
| [docs/知识图谱聚类算法.md](docs/知识图谱聚类算法.md) | — | 聚类算法（pre/post-classify、阈值、术语命名）说明 |
| [docs/异步并行改造计划.md](docs/异步并行改造计划.md) | v1.0 | 异步 / 并行改造独立计划（13 落点、Phase 1~3、验收、风险） |
| [docs/性能优化路径.md](docs/性能优化路径.md) | v1.2 | 性能优化独立路径（索引 / 缓存 / 前端 / 检索增强，三梯队；第一/二/三梯队已实施，决策 1~4 定稿） |

## 功能总览

## 更新记录

| 日期 | 内容 |
| --- | --- |
| 2026-08-05 | 审查 B 组实施（4 项）：图谱全量重建长写事务（本地边先提交再 LLM 打分，SQLite 写锁不横跨 LLM 调用）；导入双倍页图渲染消除（同步段只写全文索引、后台渲染恰一次）；阅读页章节加载竞态守卫（loadChapter 请求序号）；资产页/归档任务轮询收敛（统一 waitForTask）。新增 B 组回归测试 4 项（导入链路 3 + 图谱提交行为 1）。后端 202 pytest + ruff 全绿，vue-tsc 通过；文档同步使用手册 v1.105 |
| 2026-08-05 | 审查 A 组实施（9 项）：summarize 会话泄漏 finally close；FTS/LIKE SQL 下沉 repositories/search.py；RAG 目录批量加载（list_assets_by_books，5N-6N→常数次查询）；跨书笔记预加载（O(N²)→O(N)）；reading_logs/user_profiles 复合索引；GET /books/assets 批量资产摘要（资产页 1 次请求）；MdRender markdown-it 单例；useReaderPageCache 轮询恢复修复；HomeView FTS5 全文搜索下拉入口。后端 198 pytest + ruff 全绿，vue-tsc + vite build 通过；文档同步使用手册 v1.104 || 2026-08-05 | 审查报告复测与修复：POST progress 接口复测正常；扫描件 AI 上下文占位文案修复（ody_fallback_text 三分支，chat/脑图共用）；v1.102 流式接口（stream_events）测试基线同步；后端 198 pytest + ruff 全绿；文档同步使用手册 v1.103 |
| 2026-08-05 | AI 输出加粗渲染修复 + 方案2 固定频率刷新（stream_key 滚动落库 + 前端 2s 轮询补增量 + 思考过程实时显示）；阅读页 AI 助手 UI 去重与右侧折叠（v1.100）；代码调研结论入册（v1.101）；文档同步使用手册 v1.102 |
| 2026-08-04 | 资产页上传区优化：外部资料上传卡片改拖拽/点击选择框（虚线边框、hover 高亮、已选文件态）、资产页去页面级滚动条（仅文档级滚动）；修复上传返回结构（后端平铺 `{...book, task_id}`，前端 `UploadResult` 类型与书架页/资产页调用适配）；浏览器实测上传区与提交窗口均无内部滚动条；vue-tsc + vite build 通过；文档版本同步需求 v1.66 / 使用手册 v1.99 |
| 2026-08-04 | 资产页外部资料总结窗口化：RagView 最近提交总结改为固定大小窗口（RAG 摘要 / 关键知识点 / Skill 技能 / 知识分块全文渲染、无内部滚动条、✕ 关闭 + 版本徽标）；vue-tsc + vite build 通过；文档版本同步需求 v1.65 / 使用手册 v1.98 |
| 2026-08-04 | 真实 API 冒烟 + 书架/资产页 UI 重新设计：决策 34 挑选链路端到端冒烟通过（候选目录按领域分组、跨书 chunks 出处【《书名》第X章 第Y段】、会话缓存 source=cache、SSE 流式正常）；前端主题变量体系（theme.css 明暗两套）、HomeView 书架页重设计（近期阅读封面缩略图 + 进度条、状态徽标、统计 chips、渐变占位、hover 效果）、RagView 资产页重设计（统计卡、绿色已总结 rail、AI 总结/查看完整、提交摘要固定卡片）、RagDetailView 折叠面板图标与 sticky 头部；vue-tsc + vite build 通过；文档版本同步需求 v1.64 / 使用手册 v1.97 |
| 2026-08-04 | 性能优化第二/三梯队 + 任务中心 UI：LLM 结果缓存（llm_caches 表，脑图/预设模式共享，命中回放 cached=true）、FTS5 全书搜索（trigram + 触发器 + GET /api/books/search，短词 LIKE 回退）、会话历史裁剪（chat_history_limit 默认 200）；前端封面懒加载、cachedSplitBlocks 正文解析缓存、GraphView 渐进渲染、任务中心重设计；tests/test_perf_tier2.py 8 项，后端 189 pytest + ruff 全绿、vue-tsc + vite build 通过；文档版本同步需求 v1.62 / 使用手册 v1.95 / 性能优化路径 v1.2 |
| 2026-08-04 | 性能优化第一梯队 + 前端并行收尾实施：SQLite PRAGMA 调优（synchronous=NORMAL / cache_size / mmap_size）、外键与热点查询索引幂等补齐（_ensure_indexes）、关键词内容寻址缓存（聚类/相关度/推荐/画像共享）、聚类结果落盘缓存（群体签名失效）、上传分块流式写盘（1MB 分块 + 增量 sha256）；前端 ProfileView / RagDetailView 请求并行化（需求-决策 §9.3.2 #10/#11）；后端 181 pytest + ruff 全绿、vue-tsc + vite build 通过；文档版本同步需求 v1.61 / 使用手册 v1.94 / 性能优化路径 v1.1 |
| 2026-08-04 | 性能优化路径独立成文（docs/性能优化路径.md：索引 / 缓存 / 前端 / 检索增强，三梯队，5 决策项）；文档版本同步需求 v1.58 / 技术栈 v1.70 / 重构规范 v1.38 |
| 2026-08-04 | 异步 / 并行改造计划独立成文（docs/异步并行改造计划.md：13 落点、原则边界、Phase 1~3、验收、风险）；文档版本同步需求 v1.57 / 技术栈 v1.69 / 重构规范 v1.37 |
| 2026-08-04 | 异步 / 并行审查 13 落点清单固化（需求-决策 §9.3.2：图谱路由三处同步阻塞 / 导入同步增量 / 页图渲染 / 测试连接 / 前端串行请求等）；文档版本同步需求 v1.56 / 技术栈 v1.68 / 重构规范 v1.36 |
| 2026-08-04 | 整体异步 / 并行改造登记（需求-决策 §9.3 第 9 行：页图渲染并发 / 测试连接异步 / 图谱后台化等，与任务系统同批次）；文档版本同步需求 v1.55 / 技术栈 v1.67 / 重构规范 v1.35 |
| 2026-08-04 | 备选方案固化：LLM 挑选实现细节（9.3.1）+ 进度条覆盖需求（9.3 第 8 行）；文档版本同步需求 v1.54 / 技术栈 v1.66 / 重构规范 v1.34 |
| 2026-08-04 | 决策 34 修订：RAG/Skill 注入改为 **LLM 自主挑选**（结合冷/暖画像与当前需求，两级混合 + 规则降级）；文档版本同步需求 v1.53 / 技术栈 v1.65 / 重构规范 v1.33 |
| 2026-08-04 | 缺口需求与备选方案固化（需求-决策 §9.3：EPUB 排版 / 画像编辑粒度待定稿，导入 / 并发 / MD 图片 / 跨书复用已定稿待实现）；文档版本同步需求 v1.52 / 技术栈 v1.64 / 重构规范 v1.32 |
| 2026-08-04 | 跨书 RAG/Skill 复用方案定稿（需求决策 34）+ 实现状态审查（需求 §8.1：两段式导入 / 并发 / MD 图片 / EPUB 排版 / 画像编辑等缺口）；文档版本同步需求 v1.51 / 技术栈 v1.63（ADR-011 + ADR-009 更正）/ 重构规范 v1.31 |
| 2026-08-04 | 聚类算法方案选型（词语向量化 vs 文本共现法）登记为待定稿开放项（需求-决策 §9.2 + 知识图谱聚类算法 §10）；文档版本同步需求 v1.50 / 技术栈 v1.62 / 重构规范 v1.30；修正索引中技术栈版本滞后（v1.57 → v1.62） |
| 2026-08-04 | 文档体系重构：需求 / 技术栈 / 使用手册拆分为「总纲 + 分册」；全量锚点修复与版本一致化；决策 31（Markdown 图片）/ 32（导入两段式+进度）/ 33（并发与任务系统）已定稿待实现 |
| 2026-08-03 | 资产去重合并与删除、RAG/Skill 渲染两级结构、谱系图边渲染修复、设置页强制载入 .env、start.bat stop/restart |
| 2026-08-02 | M8 知识图谱（谱系/书内/聚类/LLM 打分）、M9 三层画像与归档沉淀、M10 打磨（笔记导出/性能/验收） |
| 2026-08-01 | 项目初建：M1~M6 需求与实现（阅读闭环 / AI 接入 / 脑图 / 书签涂鸦） |


- **书架与主页**：左侧「近期阅读」（最近 5 本，按打开时间倒序），右侧「书架」；文件夹多级归类（未打 tag 的书默认继承文件夹 tag）、拖拽排序、搜索/标签筛选、手动 tag；书籍卡片渲染封面（PDF/EPUB 自动提取）；阅读进度（已读章节/总章节 + 进度条，自动与手动标记）。
- **阅读体验**：正文支持 Markdown / LaTeX 渲染；PDF 统一按页处理（含文本型，规避公式乱码），直接以原图分辨率阅读并支持缩放（适配宽度 / 原始大小 / ＋－）；位置书签（全格式，支持分组与跳转）；PDF 页图涂鸦（笔刷 / 高亮 / 橡皮 / 文本、撤销最多 5 步、划线批注与划线区域提问）；笔记支持 Markdown/LaTeX 并可导出 Markdown / PDF。
- **AI 助手**：设置页配置大模型 API（`responses` / `chat` / `anthropic` 三种接口格式，文本与多模态独立配置；`base_url` 支持基础地址自动补全或完整 URL 直填；自动携带浏览器 UA 规避 Cloudflare 拦截）；按章节上下文问答、SSE 流式输出、自动标注出处【第X章 第Y段】；划词菜单（解释选中段 / 该段脑图 / 加入思考清单）；生成解读 / 概论 / 脑图 / 思考逻辑；脑图为 ECharts 三层树图（大纲 / 细节 / 重要定理），支持下载大纲 .md、导出 PNG、插入为本章批注。
- **多模态视觉提取（M7）**：对 PDF 提问时按 `[P-1, P, P+1]` 滑动窗口调用视觉模型提取页面完整信息，缓存到书籍目录 `page_text/`，缓存命中不重复调用；书架导入**不再自动预提取**（书籍卡片手动「提取全书页缓存」，x/y 页进度、可取消）；资料页知识库投喂时自动批量预提取；读完归档时全书批量提取。
- **知识图谱（M8）**：`/graph` 书籍级谱系图，先按用户 tag → 文件夹 → 领域自动聚类分层（优先匹配用户可编辑的专业术语词库）；点击书籍展示书内知识点分布谱系（章节级 + 重要段落 + 用户笔记/不理解段落）；关联强度 = LLM 打分 + 关键词共现 + 笔记加权，边带理论传承方向箭头与关联原因；支持人工反馈、重建与跨书知识检索；图谱更新自动联动 RAG/Skill 增量增改与暖画像。
- **个性化画像（M9）**：三层画像（冷 = 重要但不常调用 / 暖 = 近期 1-2 本书 / 热 = 当前书细节）；归档迁移阈值按对话跨越 1 / 3 / >3 本书界定并自动学习；相关度阈值函数已落地。
- **RAG / Skill 资产**：资料页（`/rag`）上传 Markdown / PDF / TXT / EPUB → AI 自动总结生成 RAG（摘要 + 关键知识点 + 段落级检索片段，带出处）与 Skill（技能）资产；再次阅读同一本书并结束对话时在原资产上增量增改；按书籍内容 hash 自动合并重复资产（多书共享一份），支持单条删除资产条目、手动合并重复资产；删除书籍级联移除资产（共享时解除引用或自动转移主资产）；结束对话归档为触发方式（优先用户主动归档）。
- **一键启动**：`start.bat` 自动检查依赖与端口占用（已在运行则跳过，避免 10048），找不到 pnpm 时自动回退用 node 直接运行 vite；`start.bat stop` 一键停止前后端、`start.bat restart` 重启，启动完成后按任意键即可停止服务。

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
2. 双击根目录 `start.bat`：自动启动后端（8321）与前端（5173）并打开浏览器；服务已在运行时自动跳过启动；启动完成后按任意键停止服务，或随时运行 `start.bat stop` / `start.bat restart`。

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
| `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` / `AI_MODE` | 文本大模型（`AI_MODE`：`responses` / `chat` / `anthropic`，默认 DeepSeek responses） |
| `AI_ENABLE_BODY_SEND` | 隐私开关，`false` 时不向模型发送书籍正文 |
| `AI_MAX_TOKENS` / `AI_THINKING_TYPE` / `AI_REASONING_EFFORT` 等 | 文本模型精细参数（`chat` 模式生效，参考 DeepSeek 思考模式文档；`anthropic` 模式仅用 max_tokens/temperature/top_p/stop） |
| `AI_ANTHROPIC_VERSION` | anthropic 模式 Messages API 版本头（默认 `2023-06-01`） |
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
cd backend && .\.venv\Scripts\python.exe -m pytest -q          # 后端 163 项全过
cd backend && .\.venv\Scripts\python.exe -m ruff check app tests
cd frontend && pnpm build                                      # vue-tsc + vite 构建
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `'pnpm' is not recognized...` | 安装 pnpm（`npm install -g pnpm`），或直接用 `start.bat`（自动回退 node 运行 vite） |
| 后端启动 `[Errno 10048] ... address already in use` | 后端已在运行；`start.bat` 会检测端口占用并跳过重复启动，或运行 `start.bat stop` 统一停止前后端 |
| AI 面板 `网络错误: ... WinError 10013` | 防火墙/安全软件拦截出站连接、代理/VPN 抢占端口或受限沙箱；先点设置页「测试连接」排查 |
| AI 返回 `HTTP 403 error 1010` | 服务商前置 Cloudflare 拦截 urllib 默认 UA；已内置浏览器 UA 修复（`LLMClient._headers`），如仍出现请检查 Key/端点是否有效 |
| `git push` 报 `Failed to connect to github.com port 443` | ping 通不代表 443 通；给 git 配置本地代理后重试，例如 `git config --global http.proxy socks5h://127.0.0.1:1080`（端口按代理工具调整） |
| Git 提示 LF/CRLF 换行符警告 | Windows 下正常现象，不影响提交与推送 |

## 开源协议

本项目基于 [MIT License](LICENSE) 开源：

- 可自由使用、修改、分发与商用，但须保留版权声明与许可文本。
- 软件按「现状」提供，不附带任何明示或暗示的担保。
- 第三方依赖（FastAPI / Vue / ECharts / PyMuPDF 等）遵循其各自的开源协议。

## 开发约定

- 提交信息使用 Conventional Commits，主要开发分支 `main`。
- 每轮任务后更新 `docs/使用手册.md`（已实现函数的使用与修改说明），并按要求在 `重构规范.md` 记录审查与解耦重构。
