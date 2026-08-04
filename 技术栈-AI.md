# 技术栈规范 · AI 接入规范（分册）

> 本文档是《技术栈规范》拆分出的分册（LLM 客户端 / 接口格式 / 精细参数 / 资产生成 / 多模态 / 并发限流（原 §6））。
> 总纲（概述 / 目录 / 定位表 / 变更记录）见 [技术栈规范.md](技术栈规范.md)。
> 章节标题**沿用原编号**（如 3.1），正文交叉引用可按原编号在本分册或总纲定位表中查找。

## 本分册目录

| 原编号 | 标题 |
| --- | --- |
| 6. AI 接入规范 |

---

## 6. AI 接入规范

- 统一封装 LLM 客户端（`app/ai/client.py`），构造参数：`base_url / api_key / model / mode / anthropic_version / timeout / verify_ssl / temperature / max_tokens / top_p / frequency_penalty / presence_penalty / stop / thinking_type / reasoning_effort / enable_thinking / thinking_budget`，全部来自配置（`.env` + 设置页 DB 覆盖）。
- **接口格式（`AI_MODE`：`responses | chat | anthropic`）**：`chat` 走 `POST {base_url}/chat/completions`（OpenAI 兼容，Bearer 鉴权）；`responses` 走 `POST {base_url}/responses`（DeepSeek 官方，`max_tokens`→`max_output_tokens`）；`anthropic` 走 `POST {base_url}/v1/messages`（Anthropic Messages API，`x-api-key` + `anthropic-version` 鉴权，版本头 `AI_ANTHROPIC_VERSION` 默认 `2023-06-01`），请求体把 system 提取到顶层 `system` 字段、`max_tokens` 必填（未设置默认 4096）、图片部件自动转 base64 source、连续同角色消息自动合并，仅映射 `temperature / top_p / stop→stop_sequences`（thinking / reasoning_effort / frequency_penalty / presence_penalty 等 OpenAI 专用参数自动忽略）。**base_url 两种写法（v1.47）**：① 基础地址（如 `https://api.deepseek.com` 或 `https://host/v1`），按接口模式自动补全（chat→`/v1/chat/completions`、responses→`/v1/responses`、anthropic→`/v1/messages`；base 以 `/v1` 结尾时补相对路径，避免 `/v1/v1`）；② 完整接口 URL（如 `https://host/v1/chat/completions`），直接使用不再补全——由模块级纯函数 `resolve_endpoint(base_url, mode)`（`app/ai/client.py`）统一解析，文本与多模态客户端共用。**请求头（v1.48）**：统一携带浏览器 `User-Agent`（`_USER_AGENT` 常量），规避 opencode.ai 等前置 Cloudflare 服务商对 urllib 默认 UA 的拦截（HTTP 403 error 1010）；anthropic 仍用 `x-api-key` + `anthropic-version`，其余用 `Bearer`。
- **精细参数与思考模式（按 DeepSeek 官方文档，需求 9.1 决策 27）**：文本 AI 的 `thinking`（`AI_THINKING_TYPE`：`enabled/disabled`）与 `reasoning_effort`（`AI_REASONING_EFFORT`：`low/medium/high/max`，`thinking=disabled` 时不发送）**仅 chat 模式**写入请求体；`AI_MAX_TOKENS`（DeepSeek 默认 32K、最大 64K，含思考 token）；`temperature/top_p/frequency_penalty/presence_penalty` 在思考模式下官方说明「设置不报错但不生效」；**responses 模式**仅把 `max_tokens` 映射为 `max_output_tokens`（DeepSeek responses 命名），thinking 参数待定稿。
- **多模态视觉精细参数（SiliconFlow）**：`vision_temperature / vision_top_p / vision_frequency_penalty / vision_presence_penalty` 为通用 OpenAI 兼容参数；`vision_enable_thinking / vision_thinking_budget`（`enable_thinking`/`thinking_budget`）仅 SiliconFlow DeepSeek/Zhipu 系推理模型可用，Qwen 等非推理模型勿开。
- 上下文策略：整本书建索引，回答按「当前章节/选中段落」取上下文；图谱构建按批次处理，控制 token 成本。
- 所有生成结果带引用出处（书名 + 章节 + 段落位置，需求 3.4.8）。
- 超时与限流：设置超时时间，限流时退避重试；失败降级为本地规则式摘要/关键词共现，并提示用户。
- **并发与限流（v1.53 方案 / v1.57 主应用落地定稿）**：LLM 调用统一走「信号量限流 + 指数退避重试」基础设施（`app/ai/` 内，一切并发的前提）；实测（`demo/parallel_llm.py`，真实 API）文本并发默认 **4**（甜点：比 2 快 35%，8 仅再快 12% 且单任务延迟反升），视觉页提取放宽 **4~8**；跨书 LLM 打分（`MAX_LLM_PAIRS`）与视觉页提取并行收益最大，文本总结与多模态提取异构并行互不阻塞。**落地范围（v1.57 定稿，需求 9.1 决策 33）**：`vision_extract.rebuild_book_caches` 并发化（`VISION_CONCURRENCY` 默认 4，页级进度原子回填）；`graph/llm_score.enrich_pairs_with_llm` 并发化（`AI_CONCURRENCY` 默认 4）；设置页测试连接改后台任务轮询。
- **对话会话与上下文（v1.53，需求 3.4.13/决策 30）**：会话键 `book:{book_id}:{mode}`（默认/解读/概论/思考逻辑分池，任务类型隔离）；每次提问注入最近 **6~10 轮**历史并按约 **8k 字符**截断；本地单用户**不引入 user_id**（`session_id` 已预留 `user:{uid}:` 前缀扩展位）；前端历史按 mode 分组展示。
- **流式输出渲染（v1.53，手册 §18）**：后端 SSE 协议不变（`delta/end/error`）；前端 delta **缓冲 50~100ms 批量写入**（渲染节流），`end`/`error` 强制 flush，**公式感知缓冲**（`$`/`$$` 未闭合时推迟到闭合后再刷出，避免 KaTeX 闪错）；不做后端预缓存（后端本就是边生成边发）。
- 隐私开关：关闭时 AI 请求不携带书籍正文，仅用元信息与用户问题。
- 提示词集中存放（`app/ai/prompts/`），按能力分文件，修改走版本记录。
- **提示词输出规范（v1.51）**：全部 LLM 提示词统一——数学符号只能 LaTeX/Markdown（行内 `$...$`、块级 `$$...$$`），**禁止无定界符裸 LaTeX 与 Unicode 数学字符**（如 `Λ`、`∈`、`ℝ`），JSON 输出内反斜杠双写（`chat.py` `MATH_RULE` 常量 + 脑图/跨书关联/跨书联动/PDF 页提取各提示词）；对话链路注入**三层画像**（`chat.py` `build_profile_block`：热全量摘要 + 暖近期书 + 冷领域偏好，**受隐私开关约束**——关闭正文发送时不注入）与「解读/概论/思考逻辑」结构化模板（`MODE_INSTRUCTIONS`，前端预设按钮携带 `mode` 字段经 `POST /api/books/{id}/chat` 透传）；Skill 资产**按任务相关性排序截断注入**（`repositories/assets.py` `load_skills(db, book_id, task_text, top_n=8)`，问答与脑图共用）。
- **RAG/Skill 资产存储与调用约定**：
  - **存储**：统一存 `BookAsset` 表（`book_id` + `kind(rag/skill)` + `content_json` + `version`），以「书」为单位，随书删除；`content_json` 结构由 Pydantic schema 定义并版本化，禁止散落为任意文件。
  - **生成与更新时机**：读完归档（需求 3.4.9）生成——**M9 已实现**：`POST /api/books/{id}/archive` 提交 `rag_service.archive_book_task` 后台任务，PDF 书先经 `vision_extract.rebuild_book_caches` 视觉通读全书补齐页缓存（命中不重复调用），再以缓存全文（`page_chunks`/`_build_page_input`，RAG 片段与出处按「第 X 页」）由文本模型总结（`generate_rag_skill(..., page_texts=...)`），随后章节全部标记已读、状态=读完；非 PDF 按章节正文总结；再次阅读结束、跨书图谱更新（需求 3.4.7 / 3.6.1）时**在原条目上增改**，每次更新 `version + 1`，**保留至少 3 个版本，回滚粒度为整条目**（需求 9.1 决策 19）。**增量增改（M9 已实现）**：再次归档时 `generate_rag_skill` 检测到已有 `rag` 资产即走增量提示词（`rag_skill.py` `INCREMENTAL_SYSTEM_PROMPT` + `build_incremental_user_prompt(book_title, old_rag, old_skill, new_material, body_text)`），素材由 `rag_service._collect_new_material` 收集（该书全部笔记/划线/「不理解」+ 最近 20 条对话），输出仍为同结构 JSON 整体覆盖落库，原条目 id 不变。
  - **RAG 调用约定**：问答前按相关性检索 `kind=rag` 资产（当前书优先；跨书问答可全库检索），命中片段连同出处注入上下文；注入片段必须保留「书名 + 章节 + 段落」出处，符合需求 3.4.8。
  - **Skill 调用约定**：按任务类型/领域匹配 `kind=skill` 资产（结合暖画像与跨书谱系关联度排序），匹配到的技能以指令形式注入系统提示词；未匹配则不注入，避免无关技能污染回答（**AI 自动按任务匹配调用**，需求 9.1 决策 18）。
  - **联动一致性**：图谱更新、相关领域书写入暖画像等事件，必须触发受影响书籍 RAG/Skill 的增量更新（或标记「待重算」），保证资产不过期。**已实现（v1.27）**：`services/graph_sync.py`——跨书谱系重建/懒构建/关联反馈（确认/修改）自动补本地 RAG 存根（`attach_linked_book_stub` 写 `rag.linked_books`、`link_domain_terms` 写 `domain_terms/linked_terms`，无 AI 也可执行，内容未变化不写库不 bump 版本，避免 post-classify 频繁失效）；`POST /api/graph/sync` 显式联动时 `sync_assets_for_relations`对强度 ≥50（`LINK_MIN_STRENGTH`）且未忽略的关联按 `ai/prompts/rag_link.py` 增量提示词执行 LLM 增改（旧资产概要 + 关联描述 + `rag_book_input` 轻量素材 → 合并 JSON 整体覆盖，保留 `chunks/linked_books/domain_terms`，version+1，失败回滚不阻塞，随后 post-classify）；未配置 AI 时仅本地存根不报错。前端谱系图页「💾 联动沉淀」按钮（`api/graph.ts syncGraphAssets`）。
  - **回收与清理**：删除书籍时级联删除其 `BookAsset` 与相关缓存；提供「重建单书 / 重建全部」入口，用于版本损坏或模型升级后的恢复。**手动删除（v1.40 已实现）**：`DELETE /api/books/{id}/asset?kind=rag|skill` 删除整条资产、`DELETE /api/books/{id}/asset/{kind}/{section}/{index}` 删除单条条目（`rag/key_points`、`rag/chunks`、`skill/skills`，0 基索引），单条删除视为资产变更 `version + 1` 并触发 post-classify 失效重算；前端资料页提供整条/单条删除按钮（二次确认）。**去重合并（v1.41 已实现，v1.43 判定基准更新）**：条目级——写入 `upsert_asset` 时对列表字段按 `content_hash`（规范化 JSON 指纹，剔除 `merged_book_ids`）去重；资产级——`POST /api/assets/dedupe` 执行 `merge_duplicate_assets`，判定基准为**书籍内容 hash**（`Book.content_hash` = 原文件 sha256，导入时计算、旧书懒回填，只与书籍本身内容相关、与 LLM 生成内容无关），hash 相同的多本书资产合并为一条主资产（保留最新），被合并书 id 写入主资产 `content.merged_book_ids`，`get_asset`/`list_assets`/RAG 检索/Skill 读取反查透明共享（`read_asset_content` 剔除元数据保持幂等可比）；**「删除资产」语义 = 移除知识库（rag/skill）及其对应书籍**：`DELETE /api/books/{id}` 级联删除资产与文件（`books_service.delete_book` 走仓储 `delete_assets`，共享引用成员解除、主书转移）。
- **PDF 页图的多模态视觉提取与缓存约定**（需求 3.4.11，统一适用于全部 PDF）：
  - **视觉入口**：PDF 页图通过**独立配置的多模态 LLM 客户端**（复用 `app/ai/client.py` 的 `LLMClient`，配置项 `vision_base_url / vision_api_key / vision_model / vision_timeout / vision_verify_ssl / vision_max_tokens` 及精细参数 `vision_temperature / vision_top_p / vision_frequency_penalty / vision_presence_penalty / vision_enable_thinking / vision_thinking_budget`，由 `repositories.settings.vision_client_kwargs/vision_configured` 提供；**独立于文本模型配置、无需额度管理**，需求 9.1 决策 23）逐页提取完整页面信息（Markdown 文本，含公式/表格/图注描述），收敛在 `services/vision_extract.py`。
  - **接口对齐（SiliconFlow）**：视觉客户端**强制 `mode="chat"`**（仅支持 `POST /chat/completions`；`responses` 模式会 404）；请求体按设置携带 `max_tokens`（`vision_max_tokens`，默认 4096）与精细参数（`temperature/top_p/frequency_penalty/presence_penalty`，以及推理模型专用 `enable_thinking/thinking_budget`）；页图与对话附件（页图/划线区域裁剪图）的 `image_url` 统一带 `detail="high"`，部件格式 `{"type":"image_url","image_url":{"url":..., "detail":"high"}}`（`url` 支持 base64 data URI，前端裁剪图统一输出 `image/jpeg`）；`LLMClient` 支持以上构造参数（chat 分支写入请求体，responses 分支不受影响）。
  - **页级缓存**：提取结果写入 `data/books/<书目录>/page_text/page_XXX.md`（UTF-8 Markdown，文件名 = 页号）；**存在且非空即命中，不再调用多模态 API**；提取任务异步执行（`tasks.submit` 后台线程），单页失败可重试、不中断整书重建。
  - **触发时机（v1.56 修订，需求 9.1 决策 22/32）**：**书架导入不再自动全书预提取**（书架书籍提供「提取全书页缓存」手动入口，x/y 页进度、可取消）；**资料页 /rag 知识库投喂时自动批量预提取**（导入服务后台提交）；阅读时不预提取，**用户在当前页对 AI 提问**时按需提取；**读完归档时全书批量提取**（补全缺失页缓存，作为 RAG/Skill 总结的全文输入，命中页不重复调用）；窗口 `[P-1,P,P+1]`（第 1 页/末页裁剪），仅补提取缺失页（增量缓存）。
  - **消费约定**：文本大模型解读 PDF 按页章节时注入页缓存文本（带「第 X 页」出处，符合需求 3.4.8；引用解析支持【第X页】）；缓存缺失时回退当前页原图附件（chat 模式）或提示先提取；禁止把原图直接交给文本模型。
  - **生命周期**：随书删除级联清理；阅读页提供「重提本页 / 重建页缓存 / 缓存 x/y 页」入口（`api/routes/vision.py`）；页缓存文本可作为 RAG 片段来源（复用 3.4.9 资产链路）；受隐私开关约束（关闭不提取、不发送）。
  - **本地抽取文本**：PDF 导入时把 `page.get_text()` 按页写入 `local_text/page_XXX.txt`，仅作全文检索索引，不用于正文展示与 AI 上下文。

---


