# 读书阅读助手（LLMnotebook）

![License](https://img.shields.io/badge/license-MIT-blue.svg)

本地单用户、本地优先的读书阅读助手：导入 PDF / Markdown / TXT / EPUB 书籍，提供三栏阅读工作台（左：书架 + 目录；中：正文阅读区；右：AI 助手），持续沉淀三层个性化画像与跨书知识谱系，把读过的书连成一张可检索、可追问的知识网络。


## 文档索引

| 文档 | 版本 | 内容 |
| --- | --- | --- |
| [需求文档.md](需求文档.md) | v1.86 | 需求总纲：概述 / 分册索引 / 变更记录 |
| [需求-功能需求.md](需求-功能需求.md) | 随总纲（当前 v1.86） | 分册：书架 / 导入 / 阅读 / AI 助手 / 图谱需求 |
| [需求-非功能与数据.md](需求-非功能与数据.md) | 随总纲（当前 v1.86） | 分册：非功能 / 数据模型 / 页面交互 |
| [需求-里程碑与验收.md](需求-里程碑与验收.md) | 随总纲（当前 v1.86） | 分册：里程碑 / 验收标准 |
| [需求-决策.md](需求-决策.md) | 随总纲（当前 v1.86） | 分册：决策 1~37 / 开放项 |
| [技术栈规范.md](技术栈规范.md) | v1.88 | 技术选型、工程规范、解耦/重构规则 |
| [重构规范.md](重构规范.md) | v1.49 | 重构记录表与变更记录 |
| [docs/使用手册.md](docs/使用手册.md) | v1.140 | 手册总纲：模块地图 / 快速定位 / 跨模块流程 / 变更记录 |
| [docs/使用手册-后端核心.md](docs/使用手册-后端核心.md) | 随总纲（当前 v1.140） | 分册：配置/数据库/解析/导入/任务/API 基础 |
| [docs/使用手册-阅读与PDF.md](docs/使用手册-阅读与PDF.md) | 随总纲（当前 v1.140） | 分册：阅读闭环/书签/涂鸦/页图/视觉提取 |
| [docs/使用手册-AI与资产.md](docs/使用手册-AI与资产.md) | 随总纲（当前 v1.140） | 分册：LLM/对话/脑图/RAG/Skill/Prompt |
| [docs/使用手册-图谱与画像.md](docs/使用手册-图谱与画像.md) | 随总纲（当前 v1.140） | 分册：图谱/聚类/画像/阈值学习 |
| [docs/使用手册-前端.md](docs/使用手册-前端.md) | 随总纲（当前 v1.140） | 分册：前端组件/组合式函数/工具 |
| [docs/知识图谱聚类算法.md](docs/知识图谱聚类算法.md) | — | 聚类算法（pre/post-classify、阈值、术语命名）说明 |
| docs/异步并行改造计划.md（已移出 git 跟踪与磁盘） | v1.0 | 异步 / 并行改造独立计划（已实施完成；要点并入 使用手册-后端核心 §13，完整历史见 git） |
| docs/性能优化路径.md（已移出 git 跟踪与磁盘） | v1.2 | 性能优化独立路径（已实施完成；要点并入 使用手册-后端核心 §13，完整历史见 git） |
| [docs/待办清单.md](docs/待办清单.md) | v2.27 | 待办 / 缺口 / 备选方案清单（按紧急度排序，含审查记录） |
| [docs/审查报告-20260810-终审.md](docs/审查报告-20260810-终审.md) | — | 终审报告：四域审查发现 / 修复状态 / 第 2 轮复审（§6.7） |
| [docs/审查报告-20260811-四域复审.md](docs/审查报告-20260811-四域复审.md) | — | 2026-08-11 四域复审：问题与解决方案台账 / 修复记录 / 验证证据 |

## 功能总览

- **书架与主页**：左侧「近期阅读」（最近 5 本，按打开时间倒序），右侧「书架」；搜索/标签筛选、手动 tag；**文件夹桌面式布局（D8）**：文件夹与书混排网格、多级嵌套、新建/重命名/删除、拖入文件夹、批量移动、批量设 tag、面包屑导航；书籍卡片拖拽排序；书籍卡片渲染封面（PDF/EPUB 自动提取）；阅读进度（已读章节/总章节 + 进度条，自动与手动标记）。
- **阅读体验**：正文支持 Markdown / LaTeX 渲染（含手写 `<svg>` 内嵌图形，DOMPurify 消毒）；PDF 统一按页处理（含文本型，规避公式乱码），直接以原图分辨率阅读并支持缩放（适配宽度 / 原始大小 / ＋－）；位置书签（全格式，支持分组与跳转）；PDF 页图涂鸦（笔刷 / 高亮 / 橡皮 / 文本、撤销最多 5 步、划线批注与划线区域提问）；笔记支持 Markdown/LaTeX 并可导出 Markdown / PDF。
- **AI 助手**：设置页配置大模型 API（`responses` / `chat` / `anthropic` 三种接口格式，文本与多模态独立配置；`base_url` 支持基础地址自动补全或完整 URL 直填；自动携带浏览器 UA 规避 Cloudflare 拦截）；按章节上下文问答、SSE 流式输出、自动标注出处【第X章 第Y段】；划词菜单（解释选中段 / 该段脑图 / 加入思考清单）；生成解读 / 概论 / 脑图 / 思考逻辑；脑图为 ECharts 三层树图（大纲 / 细节 / 重要定理），支持下载大纲 .md、导出 PNG、插入为本章批注；**主页全局 AI 助手（决策 37）**——右下角浮窗，不绑定书籍，在阅读之外结合全局 Skill / 跨书 RAG 与冷暖画像答疑（LLM 自主挑选知识源，SSE 流式 + Markdown/LaTeX 渲染）。
- **多模态视觉提取（M7 / 决策 36）**：对 PDF 提问时按 `[P-1, P, P+1]` 滑动窗口调用视觉模型提取页面完整信息，缓存到书籍目录 `page_text/`，缓存命中不重复调用；书架/资料页导入 PDF 时自动批量预提取（独立 vision 任务、不阻塞导入、可取消；受「发送书籍内容至模型」隐私开关与多模态配置约束），书籍卡片亦提供手动「提取全书页缓存」（x/y 页进度、可取消）；读完归档时全书批量提取；**未缓存的附件（划线区域裁剪图 / Markdown 正文插图）统一经视觉模型提取为文本**（内容寻址缓存 `data/cache/attachment_text/`，命中不重复调用），主模型只收文本，消除纯文本端点的 `image_url` 400 报错。
- **知识图谱（M8）**：`/graph` 书籍级谱系图，先按用户 tag → 文件夹 → 领域自动聚类分层（优先匹配用户可编辑的专业术语词库）；点击书籍展示书内知识点分布谱系（章节级 + 重要段落 + 用户笔记/不理解段落）；关联强度 = LLM 打分 + 关键词共现 + 笔记加权，边带理论传承方向箭头与关联原因；支持人工反馈、重建与跨书知识检索；图谱更新自动联动 RAG/Skill 增量增改与暖画像。
- **个性化画像（M9）**：三层画像（冷 = 重要但不常调用 / 暖 = 近期 1-2 本书 / 热 = 当前书细节）；归档迁移阈值按跨书节奏自动学习、可手动覆盖；相关度阈值函数已落地。画像维护能力：冷记忆分词修复（jieba 画像术语层，杜绝跨词碎片）、「🔃 重新生成画像」（暖主题重算 + 领域偏好从书库 RAG 资产重建 + 覆盖 ≥2 本的强领域词自动沉淀进可编辑的专业术语词库）、**知识水平校准**（按归档书数 / RAG 资产 / 兴趣深度证据打分，用户确认后应用）、长期兴趣碎片与次泛词自动清理（手动编辑词经快照保护）。
- **RAG / Skill 资产**：资料页（`/rag`）上传 Markdown / PDF / TXT / EPUB → AI 自动总结生成 RAG（摘要 + 关键知识点 + 段落级检索片段，带出处）与 Skill（技能）资产；再次阅读同一本书并结束对话时在原资产上增量增改；按书籍内容 hash 自动合并重复资产（多书共享一份），支持单条删除资产条目、手动合并重复资产；删除书籍级联移除资产（共享时解除引用或自动转移主资产）；结束对话归档为触发方式（优先用户主动归档）。
- **一键启动**：`start.bat` 自动检查依赖与端口占用（已在运行则跳过，避免 10048），找不到 pnpm 时自动回退用 node 直接运行 vite；`start.bat stop` 一键停止前后端、`start.bat restart` 重启，启动完成后按任意键即可停止服务。

## 更新记录

| 日期 | 内容 |
| --- | --- |
| 2026-08-12 | 四域审查修复轮 2（手册 v1.140）：前端 P1×3（滚动 rAF+段落索引 / 笔记高亮增量 / 图谱代际守卫+任务中心关闭竞态）+ P2×3/P3×4；后端复杂度 H1~H3（聚类合并 12.1x、pair 预计算 4.4x、跨书检索倒排索引 10~12x）+ core P1×3（folder_id 哨兵 / 书架列裁剪 / book_relations 唯一约束）；文档 P1/P2×9+（12 个 md）；验证：后端 332 pytest + ruff、前端 137 vitest + vue-tsc + vite build、markdown-it 断言全绿；同步 技术栈 v1.88、重构 v1.49、待办 v2.27 |
| 2026-08-12 | 四域审查 P1 修复轮（手册 v1.139）：后端 5 项（scrub_html `&quot;` 实体注入绕过 on* 过滤修复、图谱懒构建失败冷却防失败风暴、LLMClient.max_tokens 回退 .env、文件夹递归删除、书文件删除布局守卫）+ 前端 1 项（全局 AI 清空二次确认）+ 文档 3 处（README 索引/使用手册 §6 表格断裂与 v1.137 缺行/待办 §9 错序）+ 聚类 A1 倒排预过滤（N=400 约 3.1x）；pytest 超时根因定位（沙盒 CWD 目录创建挂起）→ 测试从仓库根运行；后端 330 pytest + ruff、前端 126 vitest + vue-tsc + vite build 全绿；同步 技术栈 v1.87、重构 v1.48、待办 v2.26 |
| 2026-08-12 | 前端 AI 助手交互修复 + 预设芯片方案 A（手册 v1.138）：解读/概论/思考逻辑芯片仅切池+预填提示词、手动发送（不再一键生成）；Enter 发送 isComposing 守卫（中文输入法不误发送）；流式 error/abort/F2 后气泡 local 复位（闪烁光标不永久显示）；无章节发送提示；切章中断旧章节流式回答；页面隐藏暂停流式轮询、恢复可见续跑；vitest 125 + vue-tsc + build 全绿；同步 待办 v2.25 |
| 2026-08-12 | 联动沉淀优化轮（手册 v1.137）：设置页暴露 `GRAPH_SYNC_CONCURRENCY`（DB 覆盖优先 0~8、0=不限制死代码修复）；真实 API 冒烟 6 书 × 1/4/8 → 甜点=4（3.0x 加速 6/6 成功）、8 约 5.0x 但 2/6 上游限流失败、默认保持 1；新增设置覆盖链路测试，后端 326 pytest + ruff 全绿；同步 待办 v2.24 |
| 2026-08-11 | D8/D9 实现（E2E 实测确认 → 桌面式书架）：① 文件夹桌面式布局（与书混排、多级嵌套、新建/重命名/删除、拖入、批量移动/批量设 tag、面包屑）；② 后端 folder_id=null 哨兵修复（PATCH 可移出文件夹）+ 回归测试；③ MD/EPUB 工具栏「第x/共x章」+ 阅读宽度调节；验证 312 pytest + 124 vitest + build + 浏览器 E2E 全绿；文档同步 使用手册-前端 §3.15、待办 v2.22 |
| 2026-08-11 | 长期兴趣分词修复（手册 v1.136）：手动编辑快照 `manual_interests` 收窄手动词保护——旧二元组碎片（由度/性映/然种，无虚词字、父整词落每本书 top15 外）不再误判为手动词永久保留；长期兴趣重建 top10 与归档沉淀均过滤次泛词（`_PROFILE_SYNC_STOPWORDS`）；碎片抑制 fragments 覆盖每本书 top80 抽取词（聚合口径 top15 不变）；真实库冒烟 29→10（积分/算子/矩阵/质点/Fourier/Banach/角动量…，碎片与次泛词清零）；312 pytest + ruff 全绿；文档同步 分册 图谱 §11.1/§11.7、技术栈 v1.86 |
| 2026-08-11 | 知识水平校准（手册 v1.135，**用户主动触发**，spec: docs/superpowers/specs/2026-08-11-knowledge-level-calibration-design.md）：增强点 2（归档全库重建）与 3（knowledge_level 校准）定稿不自动执行；`GET /api/profile/calibrate` 按归档书数 / RAG 资产书数 / 长期兴趣词数 / 领域偏好最高分证据打分（只建议不写入）+ `PATCH /profile/cold` 支持 `knowledge_level` 枚举归一化；画像页「🎓 知识水平」下拉手选 + 校准建议弹窗（证据明细 → 用户确认应用）；306 pytest + ruff、vue-tsc + vite build 全绿；文档同步 分册 图谱 §11.1/§11.2、技术栈 v1.85 |
| 2026-08-11 | 画像维护四轮（手册 v1.131~v1.134）：① 冷记忆分词修复——`graph/terms.py` 画像术语层（LaTeX 清理/泛化词/虚词碎片/词库整词提权）+ `scripts/clean_profiles.py` 旧数据清洗；② 「重新生成画像」功能——`POST /api/profile/refresh` + 画像页按钮（暖主题重算 + 冷画像清洗，不清空任何层）；③ 领域偏好 jieba 分词 + 从书库 RAG 资产重建（每本 top15 → 聚合 top60，真实库 1126→60 碎片清零）；④ 领域偏好 → 词库沉淀联动（覆盖 ≥2 本书的强领域词自动入 `domain_terms.txt` 系统缓存区，次泛词过滤）；300 pytest + ruff 全绿；文档同步 技术栈 v1.83/v1.84 |
| 2026-08-11 | 四域复审第 7 轮收尾（审查报告 §12）：后端死代码清理（删 repositories/books.py::create_book/add_chapters，B1）+ 挑选会话缓存清空回归测试（B2）+ 缓存键 chapter.id None 防御（B3）；前端 useStreamSession 同步抛错防御（F1）+ /rag/15 双滚动条修复（E2E #1，.rag-detail 改 min-height:100%）；文档 D-01~D-06（五处变更记录首行=最新 / MO3 分册登记 / 技术栈 §5.3 / 分册死引用清零 / 六五处口径 / 超长行拆分）；全量回归：pytest 291 + ruff、vitest 124 + vue-tsc 双模式 0 错误 + build、E2E 193 项 = 190 PASS / 0 FAIL / 3 WARN、markdown-it 断言；文档同步技术栈 v1.82 / 使用手册 v1.130 / 重构 v1.47 / 待办 v2.21 |
| 2026-08-11 | 四域复审第 6 轮收尾（审查报告 §11）：前端 MO3 流式内核抽取（新增 useStreamSession 249 行 + streamCore 34 行，useReaderAi 400→238 / useGlobalAi 330→164，重复 66.2%→31.9%；vitest 123 + vue-tsc 双模式 0 错误 + build + E2E 冒烟 14/14）；后端死代码清理（删 rag_input.build_llm_input / ai_context.page_image_data_uri，clear_session_cache 接线删书删资产；pytest 290 + ruff + health 200）；台账漂移修正（L23 完成 / L24 已实现更正 / L26 部分完成）；文档同步技术栈 v1.81 / 使用手册 v1.129 / 重构 v1.46 / 待办 v2.20 |
| 2026-08-11 | 四域复审第 5 轮收尾（审查报告 §10）：前端 7 项修复（聊天区列表溢出根因 / 点击目标 24px / rag15 KaTeX / --text-secondary 5.35:1 / 常量收口 / 死代码清理）；文档 4 项（待办清单表格分隔行与 form feed 修复 / README 功能总览归位 / 需求文档目录 §5）+ 拖拽排序口径修正（已实现）；后端服务重启；全量回归：前端 103 vitest + vue-tsc 双模式 0 错误 + build + E2E 复验 10/10、后端 291 pytest + ruff；文档同步技术栈 v1.80 / 使用手册 v1.128 / 重构 v1.45 / 待办 v2.19 |
| 2026-08-11 | 四域复审第 4 轮收尾（审查报告 §9）：后端聚类缓存签名含资产版本 / 资产写锁下沉 LRU 有界 / LPA 流行度增量 / 导入单事务原子化 / FK 冲突 404/409 统一 / 碎片合并单趟 / rag_select_mode 注释清洗等 10 项；前端 SSE 空闲超时降级 / 含 KaTeX 划词高亮归一化匹配 / 语义色 token / 高亮防嵌套 / useTaskPoll 信号合并 / 死代码清理等 15 项；m-5 挑选缓存键问题指纹改动回退（与决策 34 §9.3.1-② / F3 冲突，见 §9.4）；文档 4 Major 修复（版本台账 / 重构规范表格 / 需求文档版本行 / 聚类口径）；全量回归：后端 291 pytest + ruff、前端 87 vitest + vue-tsc + vite build、markdown-it 渲染断言全绿；文档同步技术栈 v1.79 / 使用手册 v1.127 / 重构 v1.44 / 待办 v2.18 |
| 2026-08-11 | 四域复审修复轮（docs/审查报告-20260811-四域复审.md）：① 聚类缓存命中修复（写库后状态重算签名，打开谱系图真正命中）+ 词库输入态签名 + persist=False 无副作用 + 增量补边全量人口 + LPA 测试；② 视觉压缩图渲染移出全局锁（4 线程并行生效）+ 防重键统一 VISION_TASK_PREFIX + responses 透传采样参数 + 进度写库容错；③ 前端切模式分池不串台 / 历史合并共享工具 chatMerge.ts（stream_key 去重）/ Rag 失败任务正确报错 / 任务中心最近完成顺序修复 / 空章守卫 / 流式超时兜底；④ 文档：demo 引用改写、导入预提取口径统一、待办 §7 状态、模块地图补齐、变更记录重排；⑤ 验证：后端 286 pytest + ruff、前端 68 vitest + vue-tsc + build 全绿；文档同步技术栈 v1.77 / 使用手册 v1.125 / 重构 v1.42 / 待办 v2.13；⑥ E2E 实测（Playwright 非视觉，9 场景）——阅读 AI「清空」加确认框并恢复误删的 book 12「解读」池 14 条历史、任务中心「最近完成」倒序修正、手动 tag 保留原样；⑦ 后端 287 pytest + ruff、前端 68 vitest + vue-tsc + build 全绿（e2e 报告 .e2e_logs/e2e-report.md 仅本地留存） |
| 2026-08-11 | 三审修复收尾轮（台账 §8.5~8.6）：① useTaskPoll 卸载中止轮询收敛；② 隐私开关 ai_enable_body_send 在 RAG 总结链路生效（rag_input enable_body 透传 + DB 覆盖）；③ SSE 空闲超时重写（收包重置 120s，不再误杀长流）；④ 涂鸦只读零写请求（doodleDirty + 加载抑制 + wasDirty 快照，根因为 deep-watch 异步回调竞态）；⑤ 前端观感（边/节点对比度、字号、导航目标、EP 中文化、搜索命中高亮）；⑥ 验证：后端 288 pytest + ruff、前端 69 vitest + vue-tsc + vite build、浏览器复验 7/7 全绿；文档同步技术栈 v1.78 / 使用手册 v1.126 / 重构 v1.43 / 待办 v2.17 |
| 2026-08-11 | 二轮复审收尾（台账 §8.4）：test_profile.py 语法修复、vision.py rebuild 补 msg 返回、ruff 6 项清零；后端 287 pytest + ruff、前端 68 vitest + vue-tsc + vite build 全绿；浏览器复验 4/4（任务中心左下锚定不遮挡 AI 面板、TOC 白字、chunk-pos KaTeX 渲染）；清理 10048 僵尸 uvicorn 并用 venv python 重启后端 |
| 2026-08-10 | 第 3 轮四域复审修复轮（终审 §6.9）：前端 C1 涂鸦跨书覆盖修复（doodleBookId 书级守卫 + 4 例回归）；后端时区统一（tasks/recommendation 改 UTC）、任务 JSON 防护/嵌套恢复、F7 书籍集合指纹、重建保留人工反馈、资产写锁 + dedupe 锁 + 删除资产 404、导入预提取改独立 vision 任务、notes PATCH 校验、books 路由 require_book 收敛 + folder 404、chat KeyError 防护；前端空气泡移除/画像文案修复/waitForTask not_found 终态/搜索竞态守卫/脑图 tooltip 转义。后端 274 pytest + 前端 61 vitest + vue-tsc + build + ruff 全绿 |
| 2026-08-10 | 终审修复轮（§6.6/§6.8）：F1/F2 流式卡死（终态复位+代际守卫）、F3 缓存重取、F4 RAG/Skill 幂等（related_id）、F5 任务终态兜底、F6 簇合并泛词剔除、F7 VLM purge OCR txt、C-1 responses 多轮历史+thinking 映射、I-1~I-15（图谱原子防重/错误契约/pdf 容错/页缓存快照/脑图切章代际等）、graph 空关系防重提（F7 收尾）；后端 273 + 前端 57 |
| 2026-08-10 | 第 2 轮四域审查修复轮（终审 §6.7）：后端 conftest 路由同步化 / vision 重建防重 / folders+assets 错误契约 400 / 聚类吸收剔除泛词（F6）/ 双页扫描接线 / submit_dedupe_sync 锁外执行 / JSON 解析包装 / reasoning_text / 会话缓存 global 清理 / 文档口径；前端流代际守卫 streamSeq + SSE 活跃期防重放、页缓存快照刷新、doodle 加载在途保护、脑图切章代际；新增回归测试 6 例（后端 272 + 前端 57）。文档同步 技术栈 v1.73 / 使用手册 v1.121 / 重构 v1.41 / 待办 v2.8 / 终审 §6.7 |
| 2026-08-05 | 决策 37 定稿并实现：主页全局 AI 对话（右下角浮窗，不绑定书籍——全局 Skill/跨书 RAG 自主挑选 + 冷暖画像注入 + SSE 流式 + 历史落库）+ 手写 `<svg>` 标签渲染（markdown-it html 透传 + DOMPurify svg profile）。新增 test_global_chat.py 4 项，后端 230 pytest + ruff 全绿，vue-tsc + vite build 通过，浏览器实测 SVG 渲染与真实 API 流式全通；文档同步需求 v1.72 / 需求-决策 决策 37 / 使用手册 v1.110 |
| 2026-08-05 | 决策 36 定稿并实现：附件统一走视觉模型提取为文本（未缓存划线裁剪图/正文插图经多模态提取为文本并内容寻址缓存，主模型只收文本，消除 `unknown variant image_url` HTTP 400；PDF 页模式不再回退直发页图）。相关 25 项 pytest + 全量 226 pytest + ruff 全绿；文档同步需求 v1.71 / 需求-决策 决策 36 / 使用手册 v1.109 |
| 2026-08-05 | 审查 D 组结构性重构实施：图谱域建仓 repositories/graph.py + 六个路由瘦身（annotations/reading/chat/settings/graph/books 抽服务层）+ 前端 GraphView 拆分（components/graph/ 面板 + utils/graphOption.ts 纯函数 + graphEdges.edgeDirLabel 收敛）。后端 224 pytest + ruff 全绿，vue-tsc + vite build 通过；文档同步需求 v1.69 / 技术栈 v1.72 / 重构规范 v1.40 / 使用手册 v1.108 |
| 2026-08-05 | 审查 C 组实施：EPUB 方案 A（保留图文混排——spine 解析 + 图片提取到 images/ 复用媒体端点 + 服务端消毒 + 前端 DOMPurify 渲染分支；AI/RAG/图谱/搜索文本消费点统一 html_to_text）；画像编辑方案 A（仅冷画像可编辑）；决策 31 Markdown 内嵌图片落地；rag_router 会话缓存上限 / 聚类 GET 只读 / 占位符泄漏断言等。后端 223 pytest + ruff 全绿，vue-tsc + vite build 通过；文档同步使用手册 v1.107 / 需求 v1.67 |
| 2026-08-05 | 修复 WinError 10013：后端进程须在非受限网络环境启动（沙盒/受限终端拉起的后端会拦截出站 TCP，导致 LLM API 全部报 10013）；client.py 错误处理同时判断 winerror/errno（原仅判 errno==10013 永不命中，友好提示失效）。沙盒外重启后端后真实 chat SSE 全通；34 项相关 pytest + ruff 全绿；文档同步使用手册 v1.106 |
| 2026-08-05 | 审查 B 组实施（4 项）：图谱全量重建长写事务（本地边先提交再 LLM 打分，SQLite 写锁不横跨 LLM 调用）；导入双倍页图渲染消除（同步段只写全文索引、后台渲染恰一次）；阅读页章节加载竞态守卫（loadChapter 请求序号）；资产页/归档任务轮询收敛（统一 waitForTask）。新增 B 组回归测试 4 项（导入链路 3 + 图谱提交行为 1）。后端 202 pytest + ruff 全绿，vue-tsc 通过；文档同步使用手册 v1.105 |
| 2026-08-05 | 审查 A 组实施（9 项）：summarize 会话泄漏 finally close；FTS/LIKE SQL 下沉 repositories/search.py；RAG 目录批量加载（list_assets_by_books，5N-6N→常数次查询）；跨书笔记预加载（O(N²)→O(N)）；reading_logs/user_profiles 复合索引；GET /books/assets 批量资产摘要（资产页 1 次请求）；MdRender markdown-it 单例；useReaderPageCache 轮询恢复修复；HomeView FTS5 全文搜索下拉入口。后端 198 pytest + ruff 全绿，vue-tsc + vite build 通过；文档同步使用手册 v1.104 |
| 2026-08-05 | 审查报告复测与修复：POST progress 接口复测正常；扫描件 AI 上下文占位文案修复（ody_fallback_text 三分支，chat/脑图共用）；v1.102 流式接口（stream_events）测试基线同步；后端 198 pytest + ruff 全绿；文档同步使用手册 v1.103 |
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

## 无 Key 联调说明

旧版 `demo/chat_demo.py` / `demo/_mock_llm.py` 等本地 mock 实验脚本已于 2026-08-10 移出版本控制（`demo/` 目录仅本地留存、不入库，见 docs/审查报告-20260811-四域复审.md §4 D-C2）。当前全链路联调走真实入口：

1. 运行 `start.bat` 一键启动前后端（或 `start.bat restart`）；
2. 设置页填入真实 API（文本与多模态独立配置），点「测试连接」验证连通性；
3. 打开书籍阅读页右栏 AI 助手或主页右下角全局 AI 浮窗实际对话验证。

## 端口约定

| 服务 | 地址 |
| --- | --- |
| 后端 API | http://127.0.0.1:8321 |
| 前端开发服务器 | http://127.0.0.1:5173 |

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
| 导入书籍会消耗 AI 额度吗？ | 配置 AI 后，导入会触发跨书关联的有界 LLM 打分（每次最多 40 对，失败自动回退关键词分，见使用手册-后端核心 §2.3）；未配置 AI 则导入完全本地零成本 |
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
