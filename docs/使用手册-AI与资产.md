# 使用手册 · AI 与资产（分册）

> 本文档是《使用手册》v1.90 大型修订拆分出的功能域分册（LLM 客户端/设置/对话/脑图/RAG/Skill/归档/Prompt/并发实验/流式渲染）。
> 总纲（模块地图 / 快速定位 / 跨模块流程 / 更新约定 / 变更记录）见 [使用手册.md](使用手册.md)。
> 章节标题**沿用原手册编号**（如 2.1），正文交叉引用可按原编号在本分册或总纲定位表中查找。

## 本分册目录

| 原编号 | 标题 |
| --- | --- |
| 1. LLM 简易对话 Demo（第 1 轮任务产出） |
| 1.1 chat_demo.py —— 对话客户端（`demo/chat_demo.py`） |
| 1.2 _mock_llm.py —— 本地模拟 LLM 服务（`demo/_mock_llm.py`） |
| 2.6 AI 客户端（`backend/app/ai/client.py`） |
| 3.2 资产仓储（`backend/app/repositories/assets.py`） |
| 3.3 RAG/Skill 提示词（`backend/app/ai/prompts/rag_skill.py`） |
| 3.4 RAG 服务（`backend/app/services/rag_service.py`） |
| 3.5 资产 API（`backend/app/api/routes/assets.py`） |
| 3.6 前端资料页（`frontend/src/views/RagView.vue` + `src/api/rag.ts`） |
| 4. M4 AI 接入（第 4 轮任务产出） |
| 4.1 设置 API（`backend/app/api/routes/settings.py`） |
| 4.2 对话流式问答（`backend/app/api/routes/chat.py` + `backend/app/services/chat_service.py`） |
| 4.3 设置仓储扩展（`backend/app/repositories/settings.py`） |
| 4.4 前端 AI 配置页（rontend/src/views/SettingsView.vue） |
| 4.5 前端 AI 助手面板（`frontend/src/views/ReaderView.vue`） |
| 4.6 冒烟要点（mock LLM） |
| 6. M5 AI 增强：脑图图像组件 + 划词 AI 操作（第 5 轮任务产出） |
| 6.1 脑图服务（`backend/app/services/mindmap_service.py`） |
| 6.2 脑图 API（`backend/app/api/routes/mindmap.py`） |
| 6.3 脑图组件（`frontend/src/components/MindMapPanel.vue`） |
| 6.4 阅读页集成（`frontend/src/views/ReaderView.vue`） |
| 6.5 冒烟要点 |
| 14.2 输入准备下沉：`services/rag_input.py`（自 `rag_service` 拆出） |
| 14.3 对话编排收敛：`services/chat_service.py` |
| 15. AI 多接口格式支持（第 15 轮任务产出） |
| 16. Prompt 能力补全（第 16 轮任务产出） |
| 16.1 数学表达硬性规则（所有 LLM 输出） |
| 16.2 对话链路：三层画像注入 + 预设模式模板 + Skill 相关性 |
| 16.3 Skill 按任务相关性匹配 |
| 17. 并发大模型实验（demo 验证轮） |
| 17.1 背景与目的 |
| 17.2 产物 |
| 17.3 parallel_llm.py 使用说明 |
| 17.4 实验结论 |
| 17.5 主应用落地方向（按收益排序） |
| 18. 阅读页 AI 流式渲染节流与会话分池（已实现） |
| 18.1 背景与现状 |
| 18.2 流式渲染节流（已实现） |
| 18.3 会话分池与历史注入（已实现） |
| 18.4 落地范围 |
| 19. 决策 34：LLM 自主挑选 RAG/Skill（跨书知识路由，v1.96 新增） |
| 19.1 总体流程与调用链 |
| 19.2 候选目录构建（`build_catalog`） |
| 19.3 LLM 挑选与降级（`_select_llm` / `_select_fallback`） |
| 19.4 会话缓存（session_id + 章节） |
| 19.5 跨书注入与出处（`_selection_payload` / `_cross_book_rag_block`） |
| 19.6 配置项（`.env`） |
| 19.7 前端 session_id 传递 |
| 19.8 修改指引 |

---

## 1. LLM 简易对话 Demo（第 1 轮任务产出）

### 1.1 chat_demo.py —— 对话客户端（`demo/chat_demo.py`）

| 函数 | 说明 |
| --- | --- |
| `load_env_file(path)` | 读取 KEY=VALUE 的 .env 文件，返回 dict；跳过注释与空行 |
| `parse_args()` | 解析命令行参数（base-url/api-key/model/mode/timeout/no-verify-ssl/prompt/mock） |
| `build_payload(mode, model, messages)` | 按接口模式构造请求体：responses（instructions/input）或 chat（messages） |
| `extract_reply(mode, data)` | 从响应 JSON 中提取回复文本（两种模式的兼容解析） |
| `call_llm(base_url, api_key, model, mode, messages, timeout, verify_ssl)` | 发送一次对话请求，返回回复文本；失败抛异常 |
| `mask_key(key)` | 隐藏 API Key 中间部分，避免日志泄露 |
| `main()` | 入口：单轮（--prompt）或交互式多轮对话 |

**如何使用**
```bash
python demo/chat_demo.py --mock --prompt "请生成本书的思维导图"   # 本地 mock 验证
python demo/chat_demo.py --prompt "你好"                          # 使用 demo/.env 的真实配置
python demo/chat_demo.py --mode chat --prompt "1+1=?"             # 切换 chat 模式
python demo/chat_demo.py                                          # 交互式多轮对话（exit 退出）
```
- 配置来源优先级：命令行参数 > 环境变量 > `demo/.env`。
- `demo/.env` 为敏感文件（已加入 `.gitignore`），模板见 `demo/.env.example`。

**如何修改**
- 新增接口模式：在 `build_payload` / `extract_reply` 中按模式分支，并在 `--mode` 的 choices 中注册。
- 调整默认超时/模型：改 `demo/.env` 的 `AI_TIMEOUT` / `AI_MODEL`。
- 注意：`call_llm` 当前为非流式请求；后续接入流式输出（SSE）时保持该函数签名稳定，另加 `stream=True` 分支。

### 1.2 _mock_llm.py —— 本地模拟 LLM 服务（`demo/_mock_llm.py`）

- 功能：OpenAI 兼容 mock，同时支持 `/v1/chat/completions` 与 `/v1/responses`，默认端口 `18999`。
- 回复规则：`pick_reply(sys_text, user_text)`——含「知识整理专家」返回固化知识 JSON；含「阅读辅导专家」返回画像 JSON；否则按关键字命中 `MOCK` 表，未命中返回提示语。
- 如何使用：`python demo/_mock_llm.py` 启动；demo 用 `--mock` 自动指向 `http://127.0.0.1:18999/v1`。
- 如何修改：新增模拟回复在 `MOCK` 字典与 `pick_reply` 中追加；修改端口改 `PORT` 常量（需同步 `chat_demo.py` 的 `DEFAULT_MOCK`）。

---


### 2.6 AI 客户端（`backend/app/ai/client.py`）

- `LLMClient(base_url, api_key, model, mode, anthropic_version, timeout, verify_ssl, temperature, max_tokens, top_p, frequency_penalty, presence_penalty, stop, thinking_type, reasoning_effort, enable_thinking, thinking_budget)`——多接口客户端（stdlib urllib 实现，零额外依赖），支持三种接口格式。
- `client.chat(messages) -> str`——messages 为 `[{role, content}]`；mode=responses 走 `/responses`，mode=chat 走 `/chat/completions`，mode=anthropic 走 `/v1/messages`；失败抛 `LLMError`。
- 使用：默认值来自 `settings`（文本 AI 取 `ai_*`，未传参数回退 `.env`）；真实 DeepSeek `deepseek-v4-flash` 已通过。
- **请求体（chat 分支）**：`temperature/max_tokens/top_p/frequency_penalty/presence_penalty/stop` 与 DeepSeek 思考模式 `thinking:{"type":...}`（`thinking_type`）+ `reasoning_effort`（`thinking=disabled` 时不发）仅在设置时写入；`enable_thinking/thinking_budget` 供 SiliconFlow 推理模型。**responses 分支**仅把 `max_tokens` 映射为 `max_output_tokens`（DeepSeek responses 命名，含思考 token），thinking 参数待定稿。
- 修改：新增接口模式在 `_path` / `_headers` / `_build_body` / `_extract_reply` / `_extract_delta` 分支；新增请求参数在 `__init__` 与 `_build_body` 同步。
- **anthropic 分支**：`_build_body` 把 system 消息提取到顶层 `system` 字段、`max_tokens` 必填（未设置默认 4096）、连续同角色消息自动合并（`_anthropic_content`）、图片部件转 base64 source（`_anthropic_image_block`，data URI → `{type:image, source:{type:base64, media_type, data}}`）；`_headers` 用 `x-api-key` + `anthropic-version`（`AI_ANTHROPIC_VERSION`）鉴权；`_extract_reply` 取 content 文本块、`_extract_delta` 取 `content_block_delta` 的 `text_delta`。


### 3.2 资产仓储（`backend/app/repositories/assets.py`）

| 函数 | 说明 |
| --- | --- |
| `get_asset(db, book_id, kind)` | 读取单条资产（rag / skill） |
| `upsert_asset(db, book_id, kind, content)` | 写入/更新资产，已存在则 `version + 1`（符合技术栈规范 AI 接入规范） |
| `list_assets(db, book_id)` | 列出书籍全部资产 |
| `delete_assets(db, book_id)` | 删除书籍全部资产（删除书籍时级联） |
| `delete_asset(db, book_id, kind)` | 删除指定 kind（rag / skill）的整条资产；返回是否存在被删记录（v1.64） |
| `delete_asset_item(db, book_id, kind, section, index)` | 删除资产内第 index 项（0 基，rag.key_points / rag.chunks / skill.skills），`version + 1` 落库并返回新内容；资产缺失/越界抛 `ValueError`（v1.64） |
| `content_hash(obj)` | 规范化 JSON（剔除 `merged_book_ids` 元数据、排序键、紧凑序列化）的 sha256 前 16 位指纹；条目与整条资产去重均用它（v1.65） |
| `_book_file_hash(db, book_id)` | 懒回填/读取书籍内容 hash：优先 `book.content_hash`，旧书缺失时读原文件 sha256 回填（v1.67） |
| `merge_duplicate_assets(db)` | 跨书去重合并：**按书籍内容 hash（原文件 sha256，存于 `book.content_hash`，只与书籍内容相关）** 相同的整条资产合并为一条主资产（保留最新），被合并书 id 记入主资产 `content.merged_book_ids`，其资产行删除；已合并成员书内容 hash 变化后自动解除引用；返回 `{rag, skill}` 合并数（v1.65，v1.67 改判定基准） |
| `list_assets_by_books(db)` | 批量加载全部书籍资产（含共享反查展开）：`{book_id: {kind: content}}`，内容剔除 `merged_book_ids`；供候选目录一次构建（v1.104 审查 A-7） |
| `list_asset_briefs(db)` | 批量资产摘要：`{book_id: {version, has_rag, has_skill, rag_summary, merged_count}}`，供 `GET /api/books/assets` 资产页列表一次请求（v1.104 审查 A-6） |
| `get_asset / read_asset_content / list_assets` | 无独立资产行时反查共享主资产，透明返回；`read_asset_content` 剔除 `merged_book_ids` 元数据（与生成内容可比）（v1.65） |


### 3.3 RAG/Skill 提示词（`backend/app/ai/prompts/rag_skill.py`）

- `SYSTEM_PROMPT`——知识整理专家角色：输出 `summary` / `key_points`（要求标注章节段落出处）/ `skills` 的 JSON。
- `build_user_prompt(book_title, chapters_text)`——书名 + 分章正文。
- 修改：提示词集中存放，新增能力在同一目录分文件；修改走版本记录（技术栈规范 AI 接入规范）。


### 3.4 RAG 服务（`backend/app/services/rag_service.py`）

| 函数 | 说明 |
| --- | --- |
| `chunk_chapter(chapter, chunk_chars=1600)` | 章节按段落切 RAG 片段，记录章节号/段落号出处 |
| `chunk_book(chapters)` | 整本书切块（按章节顺序） |
| `_parse_llm_json(text)` | 容错解析 LLM JSON（去代码围栏、取首个 `{...}`） |
| `_normalize_skills(raw)` | 技能列表归一化（兼容字符串/字典两种返回） |
| `_build_llm_input(chapters, chunks)` | 按章节组织发送正文（chunks 由调用方一次性切好；上限 `RAG_SUMMARY_CHUNK_CHARS=64000` 字；隐私开关关闭时仅章节标题） |
| `page_chunks(page_texts)` | PDF 页缓存 → RAG 片段列表
| `chunk_page_texts_for_summary(page_texts, chunk_chars)` | PDF 页缓存 → 方案 B 总结分块（map 轮输入；隐私开关关闭仅页号标题单块，v1.83） |
| `chunk_chapters_for_summary(chapters, chunks, chunk_chars)` | 章节正文 → 方案 B 总结分块（按章节顺序；隐私开关关闭仅章节标题单块，v1.83） |
| `_split_blocks(blocks, chunk_chars)` | 带标题正文块按 chunk_chars 切块（标题行不拆分；单块超长按行再切；0=单次发送全文，v1.83） |（`chapter_index`=页号、`para_pos`=页），供 PDF 归档资产使用；片段粒度/页标题格式在此调整 |
| `_build_page_input(page_texts)` | PDF 页缓存 → LLM 输入正文（隐私开关关闭仅页标题；超 `RAG_SUMMARY_CHUNK_CHARS` 截断）；页文本拼接格式在此调整 |
| `generate_rag_skill(db, book_id, *, page_texts=None)` | 总结并落库，返回 `{book_id, version, rag, skill}`；未配置 `AI_API_KEY` 或 AI 返回非 JSON 时报错并透出。`page_texts` 传 PDF 页缓存时以页文本为正文与 RAG 片段（出处「第 X 页」）；成功后触发 `post_classify_book`；页输入分支看 `page_chunks`/`_build_page_input`；**长书分块（方案 B v1.83）**：正文 >`RAG_SUMMARY_CHUNK_CHARS`（默认 64K）时 map 逐块提炼后 reduce 合并（增量模式 reduce 注入旧资产+新素材；单块失败跳过、全失败回退单次） |
| `archive_book_task(book_id)` | **M9 读完归档后台任务**：PDF **仅从未建立缓存的页视觉提取**（`rebuild_book_caches` force=False 跳过已缓存页；并发分支完成后重新 attach book 供收尾使用），再以全书缓存总结 RAG/Skill；随后 `set_all_chapters_read_flag(True)` 标记读完；成功后触发三层画像迁移与 post-classify |

- 修改：切块阈值 `CHUNK_CHARS`、总结分块上限 `RAG_SUMMARY_CHUNK_CHARS`（`backend/.env`）；模型/接口切换在 `backend/.env`；提示词调整在 `app/ai/prompts/`（map/reduce 提示词在 `rag_skill.py` 的 `CHUNK_SYSTEM_PROMPT`/`MERGE_SYSTEM_PROMPT`）。


### 3.5 资产 API（`backend/app/api/routes/assets.py`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/books/{id}/summarize` | 提交总结任务，返回 `{task_id}`（后台执行） |
| POST | `/api/books/{id}/archive` | 读完归档（M9）：PDF 仅对未缓存页执行视觉提取（已缓存页复用，不重复调用）→ 文本模型总结 RAG/Skill → 标记读完；返回 `{task_id}`（轮询 `/api/tasks/{task_id}`） |
| GET | `/api/tasks/{task_id}` | 轮询任务状态 `{status, result, error}` |
| GET | `/api/books/{id}/asset` | 读取 RAG/Skill 资产（含各自 version 与更新时间） |
| GET | `/api/books/assets` | **批量资产摘要（v1.104 审查 A-6）**：一次返回全部书籍 `{book_id: {version, has_rag, has_skill, rag_summary, merged_count}}`，资产页列表不再逐书请求；定义于 `routes/books.py`（须在 `/{book_id}` 前注册） |
| DELETE | `/api/books/{id}/asset?kind=rag\|skill` | 删除整条资产；返回 `{deleted}`（v1.64） |
| DELETE | `/api/books/{id}/asset/{kind}/{section}/{index}` | 删除资产内第 index 项（0 基）：`rag/key_points`、`rag/chunks`、`skill/skills`；删除后 version + 1，返回新内容（v1.64） |
| POST | `/api/assets/dedupe` | 跨书资产去重合并（**书籍内容 hash** 相同合并为一条共享资产），返回 `{rag, skill}` 合并数（v1.65，v1.67 改基准） |
| DELETE | `/api/books/{id}` | **删除资产 = 移除知识库（rag/skill）及其对应书籍**：级联删除资产与文件，共享资产自动转移/解除引用（v1.67 语义明确） |


### 3.6 前端资料页（`frontend/src/views/RagView.vue` + `src/api/rag.ts`）

- 路由 `/rag`（资产列表页，`RagView.vue`，v1.74 两级结构；v1.104 列表改 `listAssetBriefs` 批量摘要一次请求，总结完成详情单独 `getBookAsset` 拉取）：上传 Markdown/PDF/TXT/EPUB → 导入 → 自动总结（轮询任务）；**上传总结完成后，在页面上侧以固定大小卡片展示该次提交的 RAG 摘要与 Skill 条数**（`.submitted-fixed` 固定高度 + `overflow: hidden`，无滚动条）；资产列表行仅显示**有无**（`RAG/Skill vN` / `未总结`）、**简略摘要**（MdRender 渲染、两行截断）与「查看完整 RAG/Skill」**入口**。
- 路由 `/rag/:bookId`（下级完整内容页，`RagDetailView.vue`，v1.74）：RAG 摘要 / 关键知识点 / 知识分块 / Skill 技能全部用 `MdRender`（markdown-it + KaTeX + DOMPurify）渲染，`el-collapse` **折叠展开**；支持单条删除（`deleteAssetItem`）、整书移除（`deleteBook`）、未总结时一键总结（`summarizeBook`）。
- API 封装：`src/api/rag.ts` 的 `summarizeBook` / `archiveBook` / `getTask` / `getBookAsset` / `deleteAssetItem` / `dedupeAssets`；下级详情页「移除书籍（含 RAG/Skill）」走 `api/books.ts` 的 `deleteBook`；阅读页「📥 归档并总结 RAG/Skill」按钮走 `archiveBook` + `getTask` 轮询；类型见 `src/types.ts`（`RagContent` / `SkillContent` / `BookAssetView` / `TaskStatus`）。
- 修改：新增折叠分区/渲染字段时改 `RagDetailView.vue`（el-collapse 分区 + MdRender 渲染）；「最近提交总结」固定高度在 `.submitted-fixed`（148px + overflow: hidden）；轮询间隔在 `pollTask` 中调整。
- v1.76 排版：列表页 `.rag-page` 限宽 1400px 居中，`.file-pick` 按钮化文件选择，`.asset-row` 行距 12px + 摘要 13px/1.75；详情页 `.detail-card` 限宽 1200px、`.detail-head` sticky（top:-24px + 白底）、`.summary-block` 左侧主题色边条、`.kp-index` 圆形编号、知识分块默认折叠（`.chunk-text` max-height:168px + `.chunk-fade` 渐隐，`expandedChunks` 状态切换「展开/收起」）、`.meta-tag` 技能标签化、`.read-area` 统一 14px/1.95。


## 4. M4 AI 接入（第 4 轮任务产出）

### 4.1 设置 API（`backend/app/api/routes/settings.py`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/settings/ai` | 读取当前 AI 配置（API Key 掩码后返回） |
| PATCH | `/api/settings/ai` | 保存 AI 配置（空值忽略、保留旧值），返回掩码视图 |
| POST | `/api/settings/ai/test` | 用当前（或请求体临时覆盖）配置发起最小对话，验证连通性与鉴权 |
| POST | `/api/settings/ai/test-selector` | **挑选器独立测试连接（v1.113）**：仅 api_key 必填（其余未填项回退主文本模型），复用轮询式测试；返回 `{ok, message}` |
| POST | `/api/settings/ai/reload-env` | **强制载入 .env 配置文件（v1.89）**：以 `backend/.env` 当前内容为准重置全部运行时 AI/视觉配置，立即生效（无需重启） |

- 请求体字段：`base_url / api_key / model / mode / timeout / verify_ssl / enable_body_send / temperature` + 精细参数 `max_tokens / thinking_type / reasoning_effort / top_p / frequency_penalty / presence_penalty / stop` + 多模态 `vision_base_url / vision_api_key / vision_model / vision_timeout / vision_verify_ssl / vision_max_tokens / vision_temperature / vision_top_p / vision_frequency_penalty / vision_presence_penalty / vision_enable_thinking / vision_thinking_budget`；PATCH 时 `api_key` 留空 = 不修改。挑选器独立字段 `rag_select_enabled / rag_select_base_url / rag_select_api_key / rag_select_model / rag_select_mode / rag_select_timeout / rag_select_verify_ssl / rag_select_max_tokens / rag_select_temperature / rag_select_thinking_type / rag_select_reasoning_effort / rag_select_max_books / rag_select_max_skills / rag_select_cache_ttl_minutes`（v1.113，设置页「挑选模型」页签）；**显式清空语义**：`rag_select_mode` / `rag_select_reasoning_effort` 空串 = 跟随主模型（合法值直接写入），其余键空串仍 = 不修改。
- 前端字段名 → 仓储键（`ai_*`）映射由 `FIELD_TO_KEY` 定义；保存与掩码视图复用 `app/repositories/settings.py`。
- 测试连接返回 `{ok, message}`；失败不抛 500，以 `ok=false` 返回友好信息（网络/鉴权错误不泄露 Key）。
- **强制载入 .env（v1.89）**：`POST /api/settings/ai/reload-env` → 仓储 `repositories/settings.py::reload_ai_overrides_from_env(db, env_path=None)`——用 `dotenv_values` 只读解析 .env（路径探测：`./.env` → `backend/.env` → 模块上级 `backend/.env`），对 `AI_OVERRIDE_KEYS` 全量同步：.env 存在的键写入 DB 覆盖、不存在的键删除覆盖（回落默认），返回掩码视图；`.env` 缺失返回 404。前端设置页头部「🔄 强制载入 .env」按钮（`ElMessageBox` 二次确认，丢弃未保存修改与已保存覆盖后按 .env 重置并刷新表单），`api/settings.ts::reloadEnvSettings()` 调用；适用于手工编辑 .env 后立即生效、或误改设置页后一键还原。

### 4.2 对话流式问答（`backend/app/api/routes/chat.py` + `backend/app/services/chat_service.py`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/books/{id}/chat` | 按当前章节上下文问答，返回 SSE 流（start/delta/end/error 事件） |
| GET | `/api/books/{id}/chat/messages` | 本书对话历史（按时间正序） |
| DELETE | `/api/books/{id}/chat/messages` | 清空本书对话历史 |

- SSE 事件序列：`{"type":"start"}` → N 个 `{"type":"delta","text":...}` → `{"type":"end","text":...,"citations":[{chapter,para}]}`；失败发 `{"type":"error","message":...}`。
- 上下文组装：当前章节正文按段落编号【第N段】注入；RAG 资产片段（`retrieve_rag_chunks` 关键词检索、带出处）与 Skill 资产（`load_skills`）自动注入系统提示词；隐私开关（`ai_enable_body_send=false`）时不发送正文与片段。`r`n- 扫描件占位文案（v1.103）：正文为空时按原因分流——隐私关闭「（正文未发送，遵循隐私设置）」；扫描件按页阅读「（本书为扫描版 PDF，正文以页面图片或页缓存文本为准）」；普通书「（当前章节暂无正文）」（`ai/prompts/chat.py::body_fallback_text`，chat 与脑图共用；`build_user_prompt`/`build_messages` 增 `enable_body_send`/`page_mode` 透传）。
- 引用出处：`extract_citations` 解析回答中 `【第X章 第Y段】` 格式标注，`end` 事件携带结构化列表供前端展示。
- 历史落库：`end` 事件后写入 `ChatMessage`（独立会话，避免流式期间请求级会话被关闭）；失败不影响已输出的回答。

**函数清单（chat_service.py）**

| 函数 | 功能 |
| --- | --- |
| `paragraph_numbered(text)` | 章节正文按行编号，每段前加【第N段】 |
| `extract_citations(text)` | 从回答中解析引用出处 → `[{chapter, para}]` |
| `retrieve_rag_chunks(db, book_id, question, top_k=4)` | 按关键词重叠从书籍 RAG 资产检索相关片段（含出处），无命中返回空 |
| `load_skills(db, book_id)` | 读取书籍 Skill 资产技能列表 |
| `build_messages(book, chapter, question, selection, rag_chunks, skills, enable_body_send, crop_text=None, media_texts=None)` | 组装 system/user messages；隐私开关关闭时不发正文；划线裁剪图/正文插图以视觉提取文本（`crop_text`/`media_texts`）注入，不再直发图片（决策 36） |
| `persist_chat(db, book_id, chapter_id, selection, question, answer)` | 写入一条 user + 一条 assistant 历史 |
| `stream_chat(job)` | SSE 事件生成器（start/delta/end/error + 落库兜底） |
| `replay_cached_chat(db, book, chapter, question, selection, mode, cache_key_val)` | LLM 结果缓存命中回放（`cached=true`，审查 P0-4 下沉；chat 路由只做流式包装） |
| `build_client(db)` | 按运行时配置构建 LLMClient（.env + 设置页覆盖） |
| `is_configured(db)` | 是否已配置 API Key |

**如何修改**
- 提示词：`backend/app/ai/prompts/chat.py`（`SYSTEM_PROMPT` / `build_system_prompt` / `build_user_prompt`）；新增 M5 专项能力（解读/概论/脑图/思考逻辑）在此扩展预设。
- LLM 客户端：`backend/app/ai/client.py` —— `chat()` 普通请求、`stream()` SSE 流式，双模式（responses/chat）；新增接口模式在 `_build_body` / `_extract_reply` / `_extract_delta` 分支。

### 4.3 设置仓储扩展（`backend/app/repositories/settings.py`）

- `client_kwargs(db)` —— 把运行时 AI 配置（`ai_*` 键）映射为 `LLMClient` 构造参数（剔除与客户端无关的 `ai_enable_body_send`），供 `build_client` 与设置页测试连接复用；映射表 `CLIENT_KWARG_KEYS`。
- 修改：新增 LLM 参数时同步 `AI_OVERRIDE_KEYS`、`CLIENT_KWARG_KEYS` 与 `.env.example`。

### 4.4 前端 AI 配置页（rontend/src/views/SettingsView.vue）

- 页面布局（v1.7x 重构）：顶部页头（标题 + 保存配置按钮）＋ el-tabs **三 Tab**——「文本模型」「多模态视觉模型」「挑选模型」各自独立；Tab 内按「连接信息 / 采样参数 / 思考模式 / 隐私与附件」分组卡片（视觉模型无隐私组；挑选模型含「总开关 / 预算」组），字段由 `textFields` / `visionFields` / `selectorFields` 声明式驱动（FieldDef：text/password/number/switch/select + section 分组 + tip 提示），字段变化走 getField / setField 统一读写表单。挑选页签（v1.113）：总开关 → 连接信息（base_url/api_key/model/mode/timeout/verify_ssl）→ 采样参数（temperature/max_tokens）→ 思考模式（thinking_type/reasoning_effort）→ 预算（max_books/max_skills/cache_ttl）；**未填项自动跟随文本模型**（mode / reasoning_effort 可显式清空恢复跟随）；「测试挑选连接」调用 `POST /api/settings/ai/test-selector`（仅 api_key 必填）。
- 表单字段与后端一致；**三个页签的 API Key 输入框留空 = 保持不变**（已设置时显示「已设置」绿色徽标 + 占位提示，load/save/reloadEnv 后输入框均清空，避免掩码值回显被误提交）；「测试连接」用当前表单值临时覆盖测试（不保存）。
- API 封装：`src/api/settings.ts` —— `getAiSettings / saveAiSettings / testAiSettings / testSelectorAiSettings`。

### 4.5 前端 AI 助手面板（`frontend/src/views/ReaderView.vue`）

- 右栏 30% 固定宽度；顶部 4 个能力预设按钮（解读/概论/脑图/思考逻辑，M4 为提问模板，M5 升级为专项生成）；中部对话流（Markdown/LaTeX 渲染 + 引用出处 chips）；底部输入框（Enter 发送、流式中可停止）。
- 流式解析：`src/api/chat.ts` 的 `streamChat(bookId, body, onEvent)` 用 fetch + ReadableStream 解析 SSE，返回 `{promise, abort}` 支持中断。
- 上下文：发送时自动附带当前章节 id 与阅读区选中文本（`currentSelection()`）。
- 历史：进入页面 `loadChatHistory()`；「清空」调用 `clearChatMessages`；切书自动 `resetChat()`。
- 类型：`AiSettings / ChatMessageItem / ChatStreamEvent` 定义在 `src/types.ts`。

### 4.6 冒烟要点（mock LLM）

1. `python demo/_mock_llm.py` 启动 mock（18999）。
2. 设置页填 `http://127.0.0.1:18999/v1`、任意 Key、mode=responses，点「测试连接」应提示连接成功。
3. 打开任一书籍阅读页 → 点「解读」预设（输入框出现带章节上下文的提问）→ Enter 发送 → 右栏流式输出、无报错。
4. 刷新页面历史仍在；「清空」后消失。
5. 回归：`pytest`（27 项）+ `pnpm build`。


## 6. M5 AI 增强：脑图图像组件 + 划词 AI 操作（第 5 轮任务产出）

> 升级四类生成中的「脑图」为 ECharts 图像组件（同一张图展示大纲、细节与重要定理三层），并为划词菜单增加 AI 操作。

### 6.1 脑图服务（`backend/app/services/mindmap_service.py`）

- `generate_mindmap(db, book, chapter, selection="", focus="")`：以当前章节（可叠加选中段落/关注重点）为输入生成脑图，返回 `{title, tree, markdown, citations}`。
- 提示词要求 LLM 输出严格 JSON 树（`MINDMAP_SYSTEM`）：节点含 `name / nodeType(大纲|细节|重要定理) / ref({chapter, para}) / children`。
- `parse_mindmap_json(text)`：支持裸 JSON 与 ` ```json ` 代码块；解析失败回退 `markdown_to_tree`（Markdown 列表/纯文本缩进行 → 树，含「定理/公式/定义」关键词自动标记重要定理）。
- `tree_to_markdown(node)`：树 → Markdown 层级列表（复制/导出用）。
- 兼容既有能力：隐私开关关闭时不发正文；扫描版开启「发送页面图片」时自动附带当前页图；RAG 片段与 Skill 技能注入；生成结果以 `persist_chat` 写入对话历史（问题：`生成脑图：<焦点>`）。

### 6.2 脑图 API（`backend/app/api/routes/mindmap.py`）

- `POST /api/books/{book_id}/mindmap`：body `{chapter_id?, selection?, focus?}`，返回 `ok({title, tree, markdown, citations})`；未配置 API Key 返回 400，LLM 调用失败返回 502。

### 6.3 脑图组件（`frontend/src/components/MindMapPanel.vue`）

- 基于 ECharts `tree` 系列渲染：`nodeType` 着色（大纲蓝 / 细节绿 / 重要定理红），图例提示，`tooltip` 显示类型与出处 `【第X章 第Y段】`。
- 节点点击 → 跳转阅读区对应段落（复用 `[data-para]` 锚点，可跨章节）。
- 工具栏：复制大纲（Markdown）、导出图片（`chart.getDataURL` PNG）。

### 6.4 阅读页集成（`frontend/src/views/ReaderView.vue`）

- 「脑图」预设改为弹出脑图对话框（不再填入输入框）；「解读 / 概论 / 思考逻辑」维持文本生成。
- 划词菜单新增 AI 操作：🤖 解释选中段（带选中内容提问）、🧠 该段脑图（以选中段为输入生成）、📌 加入思考清单（创建「思考」类型笔记）。
- 聊天消息新增「复制」按钮；对话历史/引用出处展示不变。

### 6.5 冒烟要点

1. 阅读页点「脑图」→ 弹出对话框 → 生成中提示 → ECharts 树渲染（三层着色 + 图例），无报错。
2. 划词 → 菜单含 3 个 AI 操作；「加入思考清单」落库为思考笔记；「解释选中段」带选中文本发送并流式回复。
3. 脑图节点带出处时可点击跳转原文；「复制大纲」「导出图片」可用。
4. 回归：`pytest`（38 项）+ `ruff check app tests` + `pnpm build`。


### 14.2 输入准备下沉：`services/rag_input.py`（自 `rag_service` 拆出）

| 函数 | 说明 |
| --- | --- |
| `chunk_chapter(chapter, chunk_chars=1600)` | 单章按段落切 RAG 片段（chapter_index/chapter_title/para_pos 出处） |
| `chunk_book(chapters)` | 全书按章节顺序切片 |
| `page_chunks(page_texts)` | PDF 页缓存 → 片段（出处「第 X 页」） |
| `normalize_skills(raw)` | LLM 技能列表归一化（兼容字符串列表） |
| `build_llm_input(chapters, chunks)` | 章节正文 → LLM 输入（隐私开关关闭仅发标题，超 `SEND_BUDGET` 截断） |
| `build_page_input(page_texts)` | PDF 页缓存 → LLM 输入（同上约束） |

- 使用：`rag_service.generate_rag_skill` / `archive_book_task` 调用；测试直接引用本模块（`test_assets`、`test_archive_m9`）。
- 修改：切块策略与输入组装只改这里；`rag_service` 保持「AI 调用 + 资产落库 + 后分类」编排职责。


### 14.3 对话编排收敛：`services/chat_service.py`

| 函数 | 说明 |
| --- | --- |
| `resolve_chat_chapter(db, book_id, chapter_id)` | 解析目标章节，返回 `(chapters, chapter)`；空书返回 `([], None)` |
| `prepare_chat_job(db, book, chapter, question, selection, crop_image, crop_label)` | 组装对话任务：隐私/视觉覆盖、`[P-1,P,P+1]` 页缓存窗口（不再回退直发页图）、附件经 `extract_image_attachment` 视觉提取为文本（命中缓存不重复调用，决策 36）、RAG/Skill 检索、messages、client |
| `list_history(db, book_id)` / `clear_history(db, book_id)` | 对话历史读取 / 清空（薄封装） |

- 使用：`api/routes/chat.py` 只做参数校验与流式返回，不再直连仓储。
- 修改：页缓存窗口大小、附件提取开关（`ai_send_page_image`）、RAG/Skill 注入策略改这里。


### 14.4 全局 AI 对话（`services/chat_service.py` + `services/rag_router.py` + `api/routes/ai_chat.py`，决策 37）

主页右下角全局 AI 助手：不绑定书籍/章节，在阅读之外使用 Skill/RAG 资产辅助用户。

| 函数 | 说明 |
| --- | --- |
| `chat_service.prepare_global_job(db, question, session_id, stream_key)` | 组装全局对话任务：隐私开关（关闭仅注入 Skill）、画像（冷+暖）、`select_global_knowledge`、全局历史、messages、client；`persist.book_id=None`、`session_id=global:{client_id}` |
| `chat_service.build_global_messages(question, rag_block, skills, enable_body_send, history, profiles)` | 全局 system（Skill+画像）+ history + 问题（隐私开启时附加跨书片段块） |
| `chat_service.list_global_history(db, session_id)` / `clear_global_history(db, session_id)` | 按 `global:{session_id}` 读写历史（薄封装） |
| `rag_router.select_global_knowledge(db, question, session_id)` | 全局知识挑选：LLM 全库目录挑选（`SYSTEM_PROMPT_GLOBAL`/`build_global_user_prompt`，无当前书/章）→ 规则降级（摘要关键词 top3 书 + 全局 Skill 相关性）；会话缓存键 `global:{session_id}` |
| `rag_router._select_llm_global` / `_select_fallback_global` / `_global_query_tokens` | 全局挑选 LLM 版 / 规则版 / 中文二元组切词 |
| `assets.load_all_skills(db, task_text, top_n=8)` | 全局 Skill 聚合（含 book_id/book_title，共享主资产展开，按任务相关性排序） |
| `repositories/chat.global_session_id(client_id)` | 全局会话键 `global:{client_id}`；`persist_chat`/`list_messages`/`clear_messages`/`recent_history_texts` 均支持显式 `session_id`（book_id 可空） |

- API：`POST /api/ai/chat`（SSE，body `{question, session_id, stream_key}`）、`GET/DELETE /api/ai/chat/messages?session_id=`。
- 修改：全局挑选提示词改 `ai/prompts/rag_select.py`（`SYSTEM_PROMPT_GLOBAL`）；候选预算沿用 `rag_select_max_books/max_skills`。


## 15. AI 多接口格式支持（第 15 轮任务产出）

文本大模型接口格式由 `AI_MODE` 控制，三选一（`backend/.env` 或设置页「接口模式」）：

| 模式 | 端点 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `responses` | `POST {endpoint}`（基础地址自动补 `/responses`） | Bearer | DeepSeek 官方（instructions/input；`max_tokens`→`max_output_tokens`） |
| `chat` | `POST {endpoint}`（基础地址自动补 `/chat/completions`） | Bearer | OpenAI 兼容（messages；精细参数 + thinking/reasoning_effort） |
| `anthropic` | `POST {endpoint}`（基础地址自动补 `/v1/messages`） | `x-api-key` + `anthropic-version` | Anthropic Messages API（system 顶层化、max_tokens 必填默认 4096、图片转 base64 source、同角色消息合并；仅映射 temperature/top_p/stop） |

- 环境变量：`AI_MODE`（默认 `responses`）、`AI_ANTHROPIC_VERSION`（默认 `2023-06-01`）。
- **base_url 两种写法（v1.71）**：① 基础地址（如 `https://api.deepseek.com` 或 `https://host/v1`），按接口模式自动补全（chat→`/v1/chat/completions`、responses→`/v1/responses`、anthropic→`/v1/messages`；base 以 `/v1` 结尾补相对路径避免 `/v1/v1`）；② 完整接口 URL（如 `https://host/v1/chat/completions`），直接使用不再补全。解析统一在 `app/ai/client.py::resolve_endpoint`，文本与多模态共用；设置页两处 Base URL 已更新提示。
- 设置页「接口模式」下拉已含 anthropic 选项；设置页 DB 覆盖支持 `ai_anthropic_version`。
- **请求头（v1.72）**：`LLMClient._headers` 统一携带浏览器 `User-Agent`（`_USER_AGENT` 常量），修复 opencode.ai 等经 Cloudflare 的服务商拒绝 urllib 默认 UA（HTTP 403 error 1010）导致的「网络错误」；文本与多模态客户端共用。
- 多模态视觉客户端不受影响（仍强制 `chat` 模式）。



## 16. Prompt 能力补全（第 16 轮任务产出）

需求 3.4.1/3.4.10/决策 18、29（需求 v1.41）。本轮让 LLM Prompt 跟上已定需求：对话注入三层画像、预设能力结构化、Skill 按任务匹配、数学输出硬性规范。

### 16.1 数学表达硬性规则（所有 LLM 输出）

| 位置 | 说明 |
| --- | --- |
| `backend/app/ai/prompts/chat.py` `MATH_RULE` | 对话系统提示词公共常量：数学只能用 LaTeX/Markdown（行内 `$...$`、块级 `$$...$$`），禁无定界符裸 LaTeX 与 Unicode 数学字符（`Λ`、`∈`、`ℝ`、`√`、`≥` 等），JSON 内反斜杠双写 |
| `mindmap_service.py` `MINDMAP_SYSTEM` | 脑图节点名公式 `$...$` 包裹、禁 Unicode（JSON 内 `\` 双写） |
| `backend/app/ai/prompts/graph_edge.py` | 跨书关联 `reasons` 数学符号 LaTeX 化、禁 Unicode |
| `backend/app/ai/prompts/rag_link.py` | 跨书联动 RAG/Skill 增改同数学规则 |
| `backend/app/services/vision_extract.py` `EXTRACT_SYSTEM` | PDF 页提取公式 LaTeX 化、禁 Unicode 数学字符 |
| `backend/app/ai/prompts/rag_skill.py` | 归档总结/增量增改（v1.75 已含） |

### 16.2 对话链路：三层画像注入 + 预设模式模板 + Skill 相关性

| 函数/字段 | 说明 |
| --- | --- |
| `chat.py` `build_profile_block(profiles)` | 热（当前书进度/章节脉络/近期划线/问题）+ 暖（近 2 本摘要 + 相关领域书）+ 冷（领域偏好/知识水平/语言风格/长期兴趣）→ 系统提示词片段；空画像返回空串 |
| `chat.py` `MODE_INSTRUCTIONS` | 「解读 / 概论 / 思考逻辑」结构化输出模板（结论 → 逐层展开 → 意义应用） |
| `chat.py` `build_system_prompt(skills, page_mode, mode, profiles)` | 新增 `mode`（附加任务模板）与 `profiles`（注入画像）参数 |
| `chat_service.build_messages(..., mode, profiles)` | 透传模式与画像（画像在 `prepare_chat_job` 按隐私开关加载） |
| `chat_service.prepare_chat_job(..., mode)` | 新增 `mode` 参数；`ai_enable_body_send` 关闭时不加载画像；Skill 改 `load_skills(db, book.id, task_text=question)` |
| `api/routes/chat.py` `ChatIn.mode` | 请求体新增 `mode`（解读/概论/思考逻辑，可选） |
| `frontend/src/api/chat.ts` `streamChat` | 请求体新增 `mode?: string \| null` |
| `frontend/src/composables/useReaderAi.ts` | 新增 `pendingMode`：预设按钮点击记录模式，`sendChat` 随消息发送、发送后清空（脑图按钮仍走 `openMindmap`）；划词追问清除模式 |

### 16.3 Skill 按任务相关性匹配

| 函数 | 说明 |
| --- | --- |
| `repositories/assets.py` `_query_tokens(text)` | 公共分词（中文二元组 + 英文词），RAG 检索与 Skill 相关性共用 |
| `repositories/assets.py` `load_skills(db, book_id, task_text=None, top_n=8)` | 给出任务文本时按「技能名/适用场景/使用步骤/出处」关键词重叠打分排序，命中不足时取高分兜底，截断 `top_n` 条；无任务文本返回全部（兼容旧调用） |
| `repositories/assets.py` `retrieve_rag_chunks` | 复用 `_query_tokens`（行为不变） |
| `mindmap_service.py` | 脑图任务同步改 `load_skills(db, book.id, task_text=f"思维导图 {focus or selection or ''}")` |

**如何修改**
- 调整画像注入内容/截断：改 `build_profile_block` 内的字段选择与截断长度（热 5 条划线 / 3 条问题、暖 2 本、冷 10 个领域）；画像数据来自 `services/profile_service.py`（get_hot/get_warm/get_cold）。
- 调整预设模板：改 `MODE_INSTRUCTIONS` 对应文案；新增预设模式需同步前端 `useReaderAi.ts` 的 `presetPrompt` 白名单与 `ReaderChatPanel.vue` 按钮。
- 调整 Skill 匹配：改 `load_skills` 的 `top_n` 与打分字段；新增相关性信号（如来源章节、笔记命中）在 `_score` 内扩展。
- 数学硬规则改动：以 `chat.py MATH_RULE` 为基准文案，同步各提示词文件与 `docs/使用手册.md` v1.77 变更记录。


## 17. 并发大模型实验（demo 验证轮）

### 17.1 背景与目的

主应用存在多处可并行的 LLM 密集任务（扫描件逐页视觉提取、跨书关联打分、RAG/Skill 总结等），但 `ai/client.py` 尚无重试 / 限流 / 并发基础设施。本轮先在 `demo/` 内做可行性验证，不进入主应用。

### 17.2 产物

| 文件 | 说明 |
| --- | --- |
| `demo/parallel_llm.py` | 并发实验脚本（新增） |
| `demo/_mock_llm.py` | 新增 `--delay` / `--port` 参数（修改，并修复 `global _DELAY` 语法错误） |

### 17.3 parallel_llm.py 使用说明

```bash
# 0) 启动本地 mock（模拟每请求 1s 延迟）
python demo/_mock_llm.py --delay 1

# 场景 1+2：mock 并发验证（推荐）
python demo/parallel_llm.py --mock --tasks 8 --workers 4

# 真实 API（读 demo/.env），跳过 worker 扫描省额度
python demo/parallel_llm.py --tasks 3 --workers 3 --skip-scan

# 场景 3：文本 + 多模态异构并行（读 backend/.env 的 VISION_*）
python demo/parallel_llm.py --tasks 3 --workers 3 --skip-scan --vision-env backend/.env
```

参数：`--mock`（本地 mock）、`--env`（文本 .env 路径，默认 demo/.env）、`--vision-env`（多模态 .env 路径，提供后启用场景 3）、`--tasks`（任务数，默认 8）、`--workers`（场景 1 并发数，默认 4）、`--retries`（失败重试，默认 1）、`--skip-scan`（跳过场景 2）。

三个场景：场景 1 串行 vs 并发加速比；场景 2 worker 数量扫描（1/2/4/8）；场景 3 文本 + 视觉（图片附件，OpenAI 兼容 chat.completions 多模态格式）异构并行。

**如何修改**
- 任务 prompt：改 `build_specs`；单任务逻辑：改 `call_once`；并发编排：改 `run_batch`（ThreadPoolExecutor）。
- 多模态请求体：改 `call_vision` / `build_vision_payload`（当前为 SiliconFlow image_url 格式）。
- 新增场景：在 `main` 中按 `scene1/2/3` 模式追加即可。

### 17.4 实验结论

| 实验 | 结果 |
| --- | --- |
| mock（每请求 1s，8 任务） | 串行 8.5s → 并发 4 workers 2.4s，加速比 3.5x；worker 1→8 线性扩展（8.5s→1.4s，6x） |
| 真实 API（deepseek-v4-flash，3 任务） | 串行 16.9s → 并发 3 workers 5.0s，加速比 3.4x，3/3 成功 |
| 异构并行（文本 3 + 视觉 3） | 12.5s，6/6 成功；SiliconFlow 多模态图片附件格式验证通过 |
| 真实 API 二次实测（6 任务） | 串行 25.9s → 并发 4 workers 11.1s，加速 2.33x，6/6 成功；单次延迟波动大（平均 4.7~8.9s、最大 18.8s），并发可摊平波动 |
| worker 扫描实测（6 任务，真实 API） | 1/2/4/8 workers = 53.2/19.9/13.1/11.7s；**4 workers 为甜点**（比 2 快 35%），8 workers 仅再快 12% 且单任务平均延迟反升（服务端排队），说明有并发上限 |
| 异构并行二次实测 | 文本 3 + 视觉 3 = 5.98s，6/6 成功 |
| WinError 10013 | 本机沙箱限制并发出站套接字所致（`errno=13`/EACCES，真实错误码在 `winerror=10013`），真实环境不存在；与 v1.14 结论一致（运行环境出站 TCP 被拦截，非代码缺陷）。v1.106 修复 client.py 误判：原只判 `reason.errno == 10013` 永不命中（Windows errno 映射为 13），现同时判断 `winerror` 与 `errno`，友好提示新增「沙盒环境启动请改用普通终端/start.bat」排查项 |

结论：并发在真实 API 下可稳定获得 3~4x 加速，worker 数与任务数匹配时接近线性扩展；文本与多模态异构并行互不阻塞。

### 17.5 主应用落地方向（按收益排序）

1. 扫描件逐页视觉提取并发收益最大（单页约 4~5s，数百页可在分钟级完成）；
2. 跨书关联 LLM 打分（N×M 对书籍）天然可并行；
3. RAG/Skill 总结与视觉提取异构并行。

前提：先给 `ai/client.py` 补「信号量限流 + 指数退避重试」基础设施，再接入并发；实测（真实 API 6 任务）文本并发**默认 4**（甜点：比 2 快 35%，8 仅再快 12%），视觉页提取可放宽 4~8，按任务类型配置。


## 18. 阅读页 AI 流式渲染节流与会话分池（已实现）

### 18.1 背景与现状

- 后端 `chat_service.stream_chat()` 已是 SSE 流式（`client.stream` 逐 chunk yield），传输层无问题。
- 瓶颈在前端 `useReaderAi.ts`：每个 delta 事件都直接 `assistant.content += ev.text` 并调 `scrollChat()`——即**每个 token 触发一次** Vue 重渲染 + MdRender 全量 Markdown/KaTeX 渲染 + 滚动；KaTeX 渲染昂贵，服务端 chunk 较小时为阅读页卡顿主因。

### 18.2 流式渲染节流（已实现）

`useReaderAi.ts` 已按方案落地，后端 SSE 协议不变（`delta/end/error` 事件结构保持）：

- delta 先累积到 `pendingText` 缓冲，`scheduleFlush()` 以 **80ms 定时器批量写入** `assistant.content`，一次只渲染一批，避免每个 token 触发一次 Vue 重渲染 + MdRender 全量 KaTeX；
- 公式感知：`hasUnclosedMath()` 检测缓冲末尾 `` / `$` 未闭合时**最多再等 500ms**，闭合后立即刷出，避免流式过程中 KaTeX 闪错；
- 强制 flush：`end` / `error` / 用户中断（`stopStream`）时 `flushDelta()` 立即刷出剩余缓冲，不丢内容；
- `scrollChat()` 随批量调用，避免高频滚动。

### 18.3 会话分池与历史注入（已实现）

- 后端 `repositories/chat.py::chat_session_id(book_id, mode)`：会话键 `book:{id}:{mode}`（默认 / 解读 / 概论 / 思考逻辑分池），任务类型互相隔离，避免「概论」历史污染「解读」上下文；
- `repositories/chat.py::recent_history_texts(db, book_id, mode)`：窗口化历史注入——取该会话最近 **10 轮**、按 **8k 字符预算**截断（新→旧选、时间正序返回），`chat_service.build_messages(..., history=...)` 以 `user/assistant` 消息对注入到 system 之后、当前提问之前；
- `chat_service.prepare_chat_job`：隐私开关开启时加载历史（关闭正文发送时不注入，与三层画像同规则）；
- 历史 API 支持按模式：`GET/DELETE /api/books/{id}/chat/messages?mode=`（`list_messages` / `clear_messages` 均带 mode），前端 `api/chat.ts` 透传；
- 前端 `useReaderAi.ts`：新增 `chatMode` 状态 + `switchMode()`（中断当前流 → 按模式加载历史 → 防竞态 seq 递增），阅读页 AI 面板顶部新增「默认 / 解读 / 概论 / 思考逻辑」模式 tab（`ReaderChatPanel.vue`，`@mode-change` 接线到 ReaderView）。

### 18.4 落地范围

| 位置 | 改动 |
| --- | --- |
| `backend/app/repositories/chat.py` | `chat_session_id`（mode 分池）/ `recent_history_texts`（10 轮、8k 截断窗口注入）/ `list_messages`、`clear_messages`、`persist_chat` 支持 mode |
| `backend/app/services/chat_service.py` | `build_messages` 增 `history` 参数、`prepare_chat_job` 隐私开启时加载历史、历史 API 透传 mode |
| `backend/app/api/routes/chat.py` | `GET/DELETE /api/books/{id}/chat/messages?mode=` 分池支持 |
| `frontend/src/composables/useReaderAi.ts` | `chatMode` + `switchMode()`（中断/加载历史/防竞态）+ 80ms 缓冲节流 + 公式感知 + 强制 flush |
| `frontend/src/components/ReaderChatPanel.vue` | 顶部模式 tab（默认/解读/概论/思考逻辑） |
| `frontend/src/api/chat.ts` | 历史 API 带 `?mode=` 参数 |


---

## 19. 决策 34：LLM 自主挑选 RAG/Skill（跨书知识路由，v1.96 新增）

> 验收 15 / 里程碑 §8.1-1。阅读页提问时，由 LLM（独立挑选器配置）结合冷/暖画像与当前需求，从全库候选目录中挑选本次对话需要的书与 Skill，再对选中书逐个做规则关键词检索注入（跨书出处【《书名》第X章 第Y段】）。实现细节（§9.3.1 四项）已在 需求-决策.md 9.1 决策 34 定稿。

### 19.1 总体流程与调用链

```
ReaderChatPanel 提问（携带 session_id）
  → POST /api/books/{id}/chat（ChatIn.session_id）
  → chat_service.prepare_chat_job(db, book, chapter, question, selection, mode, session_id)
      → rag_router.select_knowledge(...)
          1) 会话缓存命中（session_id + chapter.id，TTL 内）→ 直接复用（source="cache"）
          2) 未命中 → _select_llm：build_catalog（领域分组目录）→ 挑选器 LLM（chat 非流式）→ parse_llm_json → 预算裁剪/当前书兜底
          3) LLM 失败/未配置/关闭开关 → _select_fallback（当前书 + 暖画像 related_books top3 + 谱系关联 top2 + 关键词）
          4) _selection_payload：对选中书 retrieve_rag_chunks(每书 ≤3 段) + Skill 全文注入 → 写会话缓存
      → _cross_book_rag_block(chunks)：组装【《书名》第X章 第Y段】块
      → build_messages（页模式同样注入 rag 块；隐私关闭只注入 Skill 不注入 chunks）
  → stream_chat SSE 流式返回
```

### 19.2 候选目录构建（`build_catalog`）

| 函数 | 说明 |
| --- | --- |
| `build_catalog(db, current_book_id) -> (text, index)` | 遍历全部书，仅收录有 RAG/Skill 资产的书（v1.104：资产与文件夹名一次性批量加载 `list_assets_by_books`，构建从 5N-6N 次查询降为常数次）；按领域分组（用户 tag 首个 → 文件夹名 → 聚类领域 → 「未分类」），冷画像 `domain_preferences` 偏好领域排前；每书一行 = `id=.. 《书名》（【当前阅读】）摘要：前 60 字，技能：≤5 个技能名`；目录硬上限 150 条 |

- 使用：仅 `rag_router._select_llm` 内部调用。
- 修改：分组优先级、摘要/技能名截断长度（`CATALOG_SUMMARY_CHARS` / `CATALOG_SKILL_NAMES` / `CATALOG_MAX_ENTRIES`）、目录行格式改这里。

### 19.3 LLM 挑选与降级（`_select_llm` / `_select_fallback`）

| 函数 | 说明 |
| --- | --- |
| `_select_llm(db, book, chapter, question, selection, mode, profiles) -> SelectionResult \| None` | 构建画像摘要 + 目录文本，调用挑选器 `client.chat`（提示词 `ai/prompts/rag_select.py`），`parse_llm_json` 解析；校验 book_id 必须在目录内、去重、预算裁剪（`RAG_SELECT_MAX_BOOKS` / `RAG_SELECT_MAX_SKILLS`）；**当前书有资产时始终选入**；任何异常/坏 JSON → 返回 None |
| `_select_fallback(db, book, question) -> SelectionResult` | 规则降级：当前书（有资产）→ 暖画像 `related_books` 前 3 → 谱系 `BookRelation`（非忽略）按 strength 降序补齐预算；Skill 取选中书按问题相关度排序的前 N 个（N=预算） |

- 使用：`select_knowledge` 内部编排；`SelectionResult(source="llm"|"fallback", book_ids, skill_refs, reasons)`。
- 修改：挑选提示词（角色/预算/输出 JSON 结构）改 `ai/prompts/rag_select.py`；降级排序规则改 `_select_fallback`。注意 `SYSTEM_PROMPT` 用 `.format()`，JSON 示例中的字面花括号必须写成 `{{`/`}}`。

### 19.4 会话缓存（session_id + 章节）

| 函数 | 说明 |
| --- | --- |
| `select_knowledge(..., session_id)` | 键 = `session_id:chapter_id`；TTL = `RAG_SELECT_CACHE_TTL_MINUTES`（默认 60，0=不缓存）；命中返回 `source="cache"` 并跳过挑选 |
| `clear_session_cache(session_id=None)` | 清空指定会话缓存（空=全清），测试用 |

- 缓存为**进程内 dict + 锁**，重启后丢失（重新挑选一次，可接受）；键含章节，同会话切章会重新挑选。
- 使用：前端进入对话会话生成 `session_id`（换书/换模式/清空对话后重新生成），随每次提问传递。

### 19.5 跨书注入与出处（`_selection_payload` / `_cross_book_rag_block`）

| 函数 | 说明 |
| --- | --- |
| `_selection_payload(result, db, question)` | 对选中书逐个 `retrieve_rag_chunks(top_k=INJECT_TOP_K_PER_BOOK=3)`，chunk 附加 `book_id`/`book_title`；Skill 按 ref（book_id+name）从资产取全文 |
| `_cross_book_rag_block(chunks)`（chat_service） | 组装【《书名》第X章 第Y段】片段块；页模式（`page_context`）下同样注入（决策 34 敲定） |

- 出处解析：`services/citations.py::CITATION_RE` 已支持 `《书名》` 前缀，`extract_citations` 对跨书引用仍返回 `{chapter, para}`。
- 修改：每书注入段数上限、chunk 块格式改 `chat_service._cross_book_rag_block` 与 `INJECT_TOP_K_PER_BOOK`。

### 19.6 配置项（`.env`）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `AI_RAG_SELECT_ENABLED` | `true` | 总开关；false=跳过 LLM 挑选，直接规则降级 |
| `RAG_SELECT_BASE_URL/API_KEY/MODEL/MODE` | 空 | 挑选器独立模型配置；未填项回退主文本模型（AI_*） |
| `RAG_SELECT_TIMEOUT` / `RAG_SELECT_VERIFY_SSL` | `60` / `true` | 挑选调用超时与 SSL |
| `RAG_SELECT_MAX_TOKENS` | `512` | 挑选输出上限（轻量调用） |
| `RAG_SELECT_TEMPERATURE` | `0.0` | 挑选要确定性，默认低温 |
| `RAG_SELECT_THINKING_TYPE` | `disabled` | 挑选思考模式（chat 模式 `enabled`/`disabled`；DeepSeek 建议 `enabled` + reasoning_effort） |
| `RAG_SELECT_REASONING_EFFORT` | 空 | 挑选思考强度（`low/medium/high`，**DeepSeek 适配 v1.113**）；空 = 跟随主文本模型 `AI_REASONING_EFFORT` |
| `RAG_SELECT_MAX_BOOKS` | `3` | 预算：最多注入书数（含当前书） |
| `RAG_SELECT_MAX_SKILLS` | `2` | 预算：最多注入 Skill 数 |
| `RAG_SELECT_CACHE_TTL_MINUTES` | `60` | 会话挑选缓存 TTL（0=不缓存） |

- **设置页「挑选模型」页签可配置（v1.113）**：全部 `rag_select_*` 字段（总开关/连接信息/采样/思考/预算）均可在设置页填写，未填项自动跟随文本模型；`.env` 仍可配置 + 强制载入 env 覆盖；`AI_OVERRIDE_KEYS` 已登记 `rag_select_*`。测试连接用 `POST /api/settings/ai/test-selector`。

### 19.7 前端 session_id 传递

| 位置 | 改动 |
| --- | --- |
| `frontend/src/composables/useReaderAi.ts` | `sessionId` 生成（`crypto.randomUUID`）；换书（watch bookId）/ `switchMode` / `clearChat` 后重新生成；`sendChat` 携带 `session_id` |
| `frontend/src/api/chat.ts` | `streamChat` body 类型增加 `session_id` |
| `frontend/src/types.ts` | （无改动；ChatStreamEvent 不变） |

- 说明：预设模式问答缓存（llm_cache）键已加入 `session` 分量，避免跨会话挑选结果不同时误回放缓存回答。

### 19.8 修改指引

- 想调整「挑哪些书」：改挑选提示词（预算/规则/画像提示）或目录构建（分组/摘要截断）。
- 想调整「注入多少」：`RAG_SELECT_MAX_BOOKS` / `RAG_SELECT_MAX_SKILLS` / `INJECT_TOP_K_PER_BOOK`。
- 想换独立挑选模型：设置页「挑选模型」页签填写（或 `.env` 填 `RAG_SELECT_*`：base_url/api_key/model/mode/reasoning_effort），留空即用主模型。
- 想关闭该功能：`AI_RAG_SELECT_ENABLED=false`（退回规则降级，行为与决策 34 落地前一致）。
- 回归验证：`backend/tests/test_rag_router.py` 7 项（目录/预算/降级/会话缓存/页模式/隐私/跨书引用）。
