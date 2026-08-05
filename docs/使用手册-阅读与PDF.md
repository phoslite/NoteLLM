# 使用手册 · 阅读与 PDF（分册）

> 本文档是《使用手册》v1.90 大型修订拆分出的功能域分册（阅读闭环/进度/书签/涂鸦/页图/视觉提取/笔记导出）。
> 总纲（模块地图 / 快速定位 / 跨模块流程 / 更新约定 / 变更记录）见 [使用手册.md](使用手册.md)。
> 章节标题**沿用原手册编号**（如 2.1），正文交叉引用可按原编号在本分册或总纲定位表中查找。

## 本分册目录

| 原编号 | 标题 |
| --- | --- |
| 3.8 阅读闭环 M3（第 3 轮任务产出） |
| 3.8.1 阅读进度（`backend/app/repositories/reading.py` + `backend/app/api/routes/reading.py`） |
| 3.8.2 笔记（`backend/app/repositories/notes.py` + `backend/app/api/routes/notes.py`） |
| 3.8.3 前端阅读页（`frontend/src/views/ReaderView.vue`） |
| 3.8.4 Markdown/LaTeX 渲染组件（`frontend/src/components/MdRender.vue`） |
| 3.8.5 API 公共依赖（`backend/app/api/deps.py`） |
| 3.8.6 冒烟要点 |
| 3.9 正文精确高亮与书架进度修复（第 3 轮补充迭代） |
| 3.9.1 正文精确高亮（`frontend/src/views/ReaderView.vue`） |
| 3.9.2 书架进度显示修复（`frontend/src/views/HomeView.vue`） |
| 3.10 读完判定与书架进度展示（第 3 轮补充迭代 2） |
| 3.10.1 章节读完判定（自动 + 手动） |
| 3.10.2 书架进度展示（`frontend/src/views/HomeView.vue`） |
| 3.10.3 窗口最小化/还原显示修复（`frontend/src/App.vue` + `styles/theme.css`） |
| 3.10.4 冒烟要点 |
| 3.11 章节标题数学公式渲染（第 3 轮补充迭代 3） |
| 3.11.1 问题与根因 |
| 3.11.2 修复方案 |
| 3.11.3 已知限制 |
| 3.11.4 冒烟要点 |
| 3.12 章节已读手动开关 + 书架三段式进度（第 3 轮补充迭代 4） |
| 3.12.1 章节已读手动开关 |
| 3.12.2 书架进度显示（三段式） |
| 3.12.3 冒烟要点 |
| 5. PDF 封面 / 扫描版按页阅读 / LLM 页图附件（M4 补充） |
| 5.1 解析器：扫描判定与页级章节（`backend/app/parsers/pdf.py`） |
| 5.2 数据模型与旧库迁移（`backend/app/models/` + `backend/app/core/database.py`） |
| 5.3 导入流程（`backend/app/services/import_service.py`） |
| 5.4 新增 API（`backend/app/api/routes/books.py`） |
| 5.5 聊天页图附件（`backend/app/api/routes/chat.py` + `backend/app/services/chat_service.py`） |
| 5.6 前端（`frontend/src/`） |
| 5.7 冒烟要点（mock LLM） |
| 5.8 封面回填、旧布局迁移与书架删除（补充修复） |
| 5.9 扫描版页图高清化与阅读缩放（v1.22） |
| 5.10 PDF 页图多模态视觉提取与页级缓存（统一适用于全部 PDF） |
| 5.11 位置书签与 PDF 页图涂鸦（M6 已实现） |
| 8. M6 阅读体验补全：位置书签 + PDF 页图涂鸦（第 8 轮任务产出） |
| 8.1 位置书签（全格式 + 分组） |
| 8.2 PDF 页图涂鸦（画板 + 撤销/擦除/文本 + 划线批注/提问） |
| 8.3 冒烟要点 |
| 8.4 涂鸦修复轮：渲染与工具栏重排（第 8 轮补充迭代） |
| 8.5 阅读区单一滚动条（第 8 轮补充迭代） |
| 9. M7 PDF 统一处理与多模态视觉提取（第 9 轮任务产出） |
| 9.1 PDF 解析统一按页（`backend/app/parsers/pdf.py`） |
| 9.2 多模态视觉配置 |
| 9.3 视觉提取服务（`backend/app/services/vision_extract.py`） |
| 9.4 页缓存 API（`backend/app/api/routes/vision.py`，prefix `/api/books`） |
| 9.5 提问链路（对话 + 脑图） |
| 9.6 前端入口（`frontend/src/api/vision.ts` + `ReaderView.vue`） |
| 9.7 冒烟要点 |
| 13.1 笔记导出服务（`backend/app/services/note_export.py`，M10） |

---

### 3.8 阅读闭环 M3（第 3 轮任务产出）

#### 3.8.1 阅读进度（`backend/app/repositories/reading.py` + `backend/app/api/routes/reading.py`）

| 函数/端点 | 说明 |
| --- | --- |
| `get_latest_log(db, book_id)` | 取该书最近一条 ReadingLog（按 updated_at 倒序），用于重开恢复位置 |
| `upsert_log(db, book_id, chapter_id, position)` | 记录阅读位置；同一章节内重复记录只更新 position |
| `update_book_reading(db, book, progress, chapter_id)` | 更新书籍整体 progress 与 last_opened_at；chapter_id 对应章节置 read_flag=True |
| GET `/api/books/{id}/chapters/{cid}` | 章节正文（Markdown 原文 + word_count + read_flag），供前端渲染 |
| GET/POST `/api/books/{id}/progress` | 读取/保存阅读位置；POST 未传 progress 时按 `(章节序号 + position) / 总章节` 计算整体进度 |

- 修改：进度计算公式、已读阈值等都在 `routes/reading.py` 的 `save_progress` 与 `repositories/reading.py`。
- 数据结构：`ReadingLog`（book_id/chapter_id/position/updated_at）在 `app/models/activity.py`；`Chapter.read_flag` 在 `app/models/book.py`。

#### 3.8.2 笔记（`backend/app/repositories/notes.py` + `backend/app/api/routes/notes.py`）

| 函数/端点 | 说明 |
| --- | --- |
| `list_notes / get_note / create_note / update_note / delete_note` | 笔记 CRUD；类型固定为 `高亮 \| 批注 \| 思考 \| 不理解`（Pydantic pattern 校验） |
| GET/POST `/api/books/{id}/notes` | 列表/新建笔记 |
| PATCH/DELETE `/api/notes/{id}` | 修改内容或类型 / 删除 |
| GET `/api/books/{id}/notes/export?fmt=md\|pdf` | 导出全书笔记（默认 md；pdf 为 M10 新增，含章节定位与引用原文，LaTeX 源码保留，见 §13.1） |

- 修改：新增笔记类型需同步 `NoteIn.note_type` pattern、前端 `NoteType` 类型与 `typeTag` 颜色映射。
- 注意：`update_note` 只允许改 `note_text` / `note_type`，章节与引用不可变（保持出处可追溯）。

#### 3.8.3 前端阅读页（`frontend/src/views/ReaderView.vue`）

- 布局：左栏 25%（竖向书架 + 目录）、中栏 45%（阅读主体）、右栏 30%（AI 助手，M4/M5 接入）。
- 左栏内部：书架固定在左上角（`shelf-section`，`flex:none; max-height:40%`），目录占左下剩余空间（`toc-section`，`flex:1`），两者各自独立滚动条，互不共享、互不覆盖。
- 正文：按空行分段渲染（`splitBlocks`，保留 ``` 代码块合并）；滚动防抖 600ms 保存进度；重开自动恢复上次章节与滚动位置。
- 交互：
  - 段落 hover 出现侧边按钮：❓ 不理解 / ✍ 高亮 / 批注 / 思考（前两者即时建笔记，后两者弹对话框补充内容）。
  - 划词弹出浮动菜单（同一组操作）；点击菜单按钮后清除选区。
  - 右抽屉「笔记」：列表（类型/章节/定位/编辑/删除）+「⬇ 导出 Markdown / ⬇ 导出 PDF」链接（`exportNotesUrl` / `exportNotesPdfUrl`，PDF 为 M10 新增）。
  - 工具栏「标记读完」：PATCH `status=读完, progress=1`（归档与 RAG/Skill 沉淀在 M9 接入）。
- API 封装：`frontend/src/api/reading.ts`（`getChapterContent/getProgress/saveProgress/listNotes/createNote/updateNote/deleteNote/exportNotesUrl/exportNotesPdfUrl`）；类型在 `src/types.ts`（`ChapterContent/ReadingProgress/NoteType/NoteItem`）。

#### 3.8.4 Markdown/LaTeX 渲染组件（`frontend/src/components/MdRender.vue`）

- 渲染链：`markdown-it(html:false)` → DOMPurify 消毒 → KaTeX auto-render（`katex/dist/contrib/auto-render.mjs` 动态 import）。
- 支持：`$…$` `$$…$$` `\(…\)` `\[…\]`；表格/代码/引用样式已内置。
- 已知坑与修复：`breaks:true` 会把块级公式内的换行变成 `<br>`，导致 KaTeX 无法跨文本节点匹配；`preprocessMath` 在渲染前将 `$$…$$` 内部换行压缩为空格。
- 修改：新增公式语法在 `renderMath` 的 `delimiters` 中追加；markdown-it 选项在组件顶部 `new MarkdownIt({...})` 调整；类型声明在 `src/env.d.ts`（markdown-it / auto-render.mjs）。

#### 3.8.5 API 公共依赖（`backend/app/api/deps.py`）

- `require_book(db, book_id)`——按 ID 取书并抛 404，`routes/reading.py` / `routes/notes.py` / `routes/assets.py` 复用（消除三处重复实现）。新增接口若需"书不存在"校验，直接复用该依赖。

#### 3.8.6 冒烟要点

1. `cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8321` 启动后端。
2. `cd frontend && pnpm dev --host 127.0.0.1` 启动前端（无 pnpm 时用 `node node_modules\vite\bin\vite.js --host 127.0.0.1`）。
3. 打开 `/reader/1`：验证三栏布局、章节切换、滚动保存进度、刷新恢复、hover/划词建笔记、抽屉编辑删除导出、「标记读完」。
4. 回归：`cd backend && .venv\Scripts\python.exe -m pytest`（16 项）+ `cd frontend && pnpm build`（vue-tsc + vite）。


### 3.9 正文精确高亮与书架进度修复（第 3 轮补充迭代）

#### 3.9.1 正文精确高亮（`frontend/src/views/ReaderView.vue`）

- 需求：划词「高亮 / 不理解」不再整段，而是**精细到所划线的部分**，并在正文可视化标记。
- `wrapQuoteInElement(el, quote, cls)`：在段落渲染 DOM 中按文本精确匹配 quote 并包裹 `<mark class="note-hl ...">`；支持跨文本节点、合并命中为单个 mark、嵌套（整段标记内再高亮精确片段）。
- `applyHighlights()`：章节加载与笔记增删改后调用；先循环展开全部旧 `.note-hl` 再按 **quote 长度降序**重新包裹（长整段先包裹、短划词嵌套在内），保持幂等。
- `NOTE_HL_CLASS`：类型→样式类映射（高亮=黄底、不理解=红波浪、批注=绿线、思考=蓝线）；样式见 `.reading-scroll :deep(.note-hl-*)`。
- `quickNote` 改进：hover 侧边按钮的 quote 改用段落渲染后文本（`textContent`），保证与正文 DOM 可匹配。
- 注意：quote 为渲染后文本（划词 `selMenu.text` / 段落 `textContent`），与 markdown 源文本（`blocks[i]`）不同；公式等特殊渲染元素可能无法精确匹配（自动跳过，不影响其他高亮）。

#### 3.9.2 书架进度显示修复（`frontend/src/views/HomeView.vue`）

- 近期阅读：`Math.round(b.progress)` 漏乘 100（0.33 显示为 0%）→ 改为 `Math.round((b.progress ?? 0) * 100)`。
- 书架卡片：新增进度条 `el-progress` 与百分比文本（`progress > 0` 时显示），满足需求 3.1「书格显示阅读进度」。
- 阅读页左侧书架进度依赖 `saveNow → store.fetchBooks()` 实时刷新（已有逻辑，未改动）。



### 3.10 读完判定与书架进度展示（第 3 轮补充迭代 2）

#### 3.10.1 章节读完判定（自动 + 手动）

- 自动判定（前端 `frontend/src/views/ReaderView.vue` + `composables/useReaderProgress.ts`）：`AUTO_READ_MS = 10_000`，每 1s 定时器 `checkAutoRead()` + 滚动事件触发；条件为 **当前章节可见停留时长 ≥10s 且该页滚动到底**（`scrollHeight - scrollTop - clientHeight <= 4`）时，调用 `saveProgress(..., { mark_read: true })` 将本章标记已读；`autoMarkedChapter` 集合保证每章只自动标记一次。
  - **页面可见性感知（v1.91）**：阅读时长按「页面可见」累计（`visibleAccumMs` + `visibleSinceAt`，`visibilitychange` 结算），切换标签页/最小化期间不计入；`ReaderView` 的 1s 定时器在页面隐藏时暂停（`stopReadCheck`）、恢复可见时立即补查并重启（`startReadCheck`）——后台零轮询、零网络请求，省电且不误判已读。
- 后端（`backend/app/api/routes/reading.py`）：`ProgressIn` 新增 `mark_read: bool = False`；`repositories/reading.py` 的 `update_book_reading(..., mark_read=False)` 仅当 `mark_read=True` 时才置 `Chapter.read_flag`（修复旧逻辑"打开章节即标记已读"的问题）；当某书**全部章节已读**时自动将 `Book.status` 置为 `读完`。
- 手动标记（阅读页工具栏按钮）：书未读完显示「标记读完」（`status=读完, progress=1`），书已读完显示「标记为在读」（`status=在读`），由 `toggleFinished()` 切换，本地 `book` 与书架 store 同步刷新。
- 章节列表 `✓`、阅读页工具栏「已读 x/y 章 · 进度 z%」与书架进度均基于 `read_flag` 实时计算。

#### 3.10.2 书架进度展示（`frontend/src/views/HomeView.vue`）

- 书架卡片进度区改为三段式：**上方**「已阅读 xx/yy 章」，**中间**「最新章节：第n章 标题」，**下方**放置 `el-progress` 阅读进度条（始终显示）。
- 进度百分比由 `read_chapters / chapter_count` 计算（`chapterPercent(b)`），不再使用滚动位置进度；阅读页工具栏与左侧书架同步按章节数计算。
- 近期阅读面板同步显示「已阅读 x/y 章」信息行与进度条。
- 数据来源：后端 `book_to_dict` 新增 `read_chapters`（已读章节数）与 `latest_chapter`（`{index, title}`，取最近阅读日志章节，兜底已读最高章节）；`api/routes/books.py` 通过 `book_reading_summary(db, book)`（`repositories/reading.py`）统一注入，列表/详情/上传/更新接口均返回。

#### 3.10.3 窗口最小化/还原显示修复（`frontend/src/App.vue` + `styles/theme.css`）

- 视口高度由 `100vh` 改为百分比链（`html/body/#app` 高度 100%）+ `100dvh` 兜底（`min-height: 100vh; min-height: 100dvh`），避免浏览器 UI 高度变化/窗口缩放时 `100vh` 超出可视区导致页面底部被裁切、还原后布局错乱。
- 已用 Playwright（Edge）在 1440×900 / 1280×720 / 1024×640 / 800×600 下验证：`documentElement.scrollHeight == clientHeight`、`body.scrollWidth == innerWidth`，无页面级滚动条。

#### 3.10.4 冒烟要点

1. 打开长章节，停在顶部停留 11s：章节不应被标记已读。
2. 停留 10s 后滚动到底：出现「第n章…已读完」提示，书架已读章节数 +1；全书章节读完时书籍自动变为「读完」。
3. 可见性感知：停留 4s → 切后台/最小化 15s → 回来，不应标记已读；继续可见阅读累计满 10s 并滚到底才标记；后台期间 DevTools Network 面板应无任何请求。
3. 工具栏按钮在「标记读完 / 标记为在读」间切换，切换后书架状态同步。
4. 书架卡片显示「已阅读 x/y 章 · 最新章节：第n章 …」与底部进度条。
5. 窗口缩放到 800×600 再还原，页面无裁切/滚动条。
6. 回归：`cd backend && .venv\Scripts\python.exe -m pytest`（16 项）+ `cd frontend && pnpm build`。


### 3.11 章节标题数学公式渲染（第 3 轮补充迭代 3）

#### 3.11.1 问题与根因

- 现象：章节标题含 LaTeX 公式（如 `$-\Delta u = f$`）时，目录与工具栏标题显示原始 `$...$` 源码而非渲染后的公式。
- 根因：`ReaderView.vue` 的目录项 `.chapter-title` 与工具栏 `.chapter-heading` 使用纯文本插值 `{{ c.title }}`，未经过数学渲染管线。

#### 3.11.2 修复方案

- `components/MdRender.vue` 新增 `inline?: boolean` 属性：`inline=true` 时改用 `md.renderInline()` 渲染并以 `<span class="md-render-inline">` 输出，其余复用同一管线（`preprocessMath` → markdown-it → DOMPurify → KaTeX auto-render），保证块级/行内数学渲染行为一致。
- 新增样式 `.md-render-inline`（`display:inline; line-height:inherit`）与 `.md-render-inline :deep(.katex) { font-size: 1em }`，避免 KaTeX 默认 1.21em 放大标题字号。
- `ReaderView.vue` 三处改为 `<MdRender :source="..." inline />`：目录章节标题、工具栏章节标题、笔记抽屉定位行（`第n章 标题`）。
- `env.d.ts` 的 markdown-it 类型补丁补充 `renderInline(src: string): string`。
- 顺带修复：`C\*` 这类 markdown 转义（`\*` → `*`）在标题中也会被正确还原（由 markdown-it 内联规则处理）。

#### 3.11.3 已知限制

- 与正文同一限制：若公式内部出现会被 markdown-it 解析为强调的 `_`/`*`（如 `$x _1$` 中 `_` 两侧均为空格），`$...$` 会被拆到不同文本节点导致 KaTeX 无法匹配；常见的 `$a_i$`（下划线两侧为字母，CommonMark 视为单词内下划线，不触发强调）不受影响。极端情况可在标题中改用 `\(...\)` 分隔符。

#### 3.11.4 冒烟要点

1. 打开含公式标题的章节（如书 2 第 9.2 章 `9.2 全流程演示：$-\Delta u = f$，$u|_{\partial\Omega} = 0$`）。
2. 检查目录项与工具栏标题：可见文本无残留 `$`，公式渲染为 KaTeX（DOM 中 `.katex` 数量与公式数一致，含 MathML）。
3. 回归：正文块级公式仍正常（`pnpm build` + 阅读页冒烟）。


### 3.12 章节已读手动开关 + 书架三段式进度（第 3 轮补充迭代 4）

#### 3.12.1 章节已读手动开关

- 目录每行右侧新增开关按钮：`✓`（已读，点击取消）/ `○`（未读，点击标记），`@click.stop` 不影响行点击跳转。
- 后端新增 `PATCH /api/books/{book_id}/chapters/{chapter_id}/read`，body `{ read: bool }`（`app/api/routes/reading.py` + `repositories/reading.py#set_chapter_read_flag`）。
- 书籍状态同步规则统一为共享助手 `_refresh_status`：全部章节已读→`读完`；部分已读→`在读`；全部未读→`未读`。仅当章节标记实际变化时同步（位置保存不改变 status，保留手动「标记读完」覆盖）；自动读完路径（`mark_read=True`）同样走该规则。

#### 3.12.2 书架进度显示（三段式）

- 上方：`已阅读 xx/yy 章`；中间：`最新章节：第n章 标题`（无日志时显示「最新章节：暂无」）；下方：`el-progress` 进度条。
- 进度 = `已读章节数 / 总章节数`：`HomeView.chapterPercent(b)` 与 `ReaderView.percent(b)` 统一按此计算，主页卡片、近期阅读、阅读页左侧书架与工具栏百分比一致。

#### 3.12.3 冒烟要点

1. 目录点击 `○` → 变为 `✓`，书架已读章节 +1，书籍状态 未读→在读；再点 `✓` → 取消，状态回退。
2. 全部章节标记已读 → 状态自动变「读完」；取消其中一章 → 回退「在读」。
3. 书架卡片三段式（已阅读 x/y 章 / 最新章节 / 进度条），百分比 = x/y×100。
4. 回归：`pytest`（17 项）+ `pnpm build` + 阅读页冒烟。

### 3.13 路由瘦身服务（审查 D 组，2026-08-05）

- `backend/app/services/reading_service.py`：`save_book_progress(db, book_id, chapter_id, ...)`——进度保存编排（章节不存在抛 `LookupError`，路由映射 404；原 reading 路由内联逻辑下沉）。
- `backend/app/services/annotation_service.py`：`read_page_annotations(book, page_index)` / `save_page_annotations(book, page_index, elements)`（元素上限 `MAX_ELEMENTS=2000`）——页批注（划线/涂鸦/文本）读写收敛；`annotations_path(book, page_index)` 定位批注 JSON 文件。修改：文件格式/上限调整在此层，annotations 路由只做参数校验与序列化。

## 5. PDF 封面 / 扫描版按页阅读 / LLM 页图附件（M4 补充）

> 需求 v1.9 起已改为「**PDF 统一按页处理（含文本型）**」：文本型 PDF 不再直接抽取正文（数学符号会乱码），统一按页切章、原图阅读、多模态视觉提取（见需求 3.2/3.4.11）。本节描述当前代码实现（扫描版识别 + 按页读图），待统一处理实现后更新。
>
> 本轮补全三类能力：PDF/EPUB 封面提取并在书架渲染；扫描版 PDF 按原始页数切章、直接阅读页图；对扫描版提问时自动把当前页图片作为附件发送给 LLM（chat 模式，需模型支持视觉输入）。

### 5.1 解析器：扫描判定与页级章节（`backend/app/parsers/pdf.py`）

- 解析改用 PyMuPDF（`pymupdf>=1.28`，已同步 `pyproject.toml` 依赖）。
- 全文提取文本长度 < `SCANNED_TEXT_THRESHOLD = 30` 字符 → 判定为扫描版：
  - 每页生成一个章节（`ParsedChapter(page_index=i, title="第 N 页", content="", is_scanned=True)`），`page_count` 为总页数；
  - 文本 PDF 维持原有章节切分逻辑不变。
- 辅助函数：
  - `render_pdf_page(path, page_index, out_path)`：把指定页渲染为 `page_XXX.jpg`（默认 1000px 宽、quality 88）；
  - `extract_pdf_cover(path, out_path)`：渲染第 1 页为封面图（无元数据封面时兜底）；
  - `render_pdf_pages(path, out_dir)`：渲染全部页到 `pages/page_001.jpg`…。
- `backend/app/parsers/epub.py` 新增 `extract_epub_cover`：优先取 OPF `<meta name="cover">` / `<meta name="cover-image">` 指向的资源，写入 `cover.{ext}`。

### 5.2 数据模型与旧库迁移（`backend/app/models/` + `backend/app/core/database.py`）

- `ParsedBook` 新增 `is_scanned` / `page_count`；`ParsedChapter` 与 `Chapter` 新增 `page_index`；`Book` 新增 `is_scanned` / `page_count`。
- `database.py` 新增 `_ensure_columns()`：`init_db` 建表后执行轻量 `ALTER TABLE`（`books.is_scanned`、`books.page_count`、`chapters.page_index`），旧数据库无需重建即可升级，缺列自动补默认值。

### 5.3 导入流程（`backend/app/services/import_service.py`）

- 导入 PDF/EPUB 时提取封面并写入 `book.cover`（书架展示用 `cover_url`）。
- 每本书使用独立子目录 `data/books/<file_id>/`（书文件 + `cover.jpg` + `pages/`），避免封面/页图跨书共享覆盖。
- 扫描版 PDF 渲染 `pages/` 目录；章节按页写入，`add_chapters` 接收 `(index, title, content, page_index)` 元组。
- 书籍序列化（`backend/app/schemas/serializers.py`）新增 `is_scanned` / `page_count` / `cover_url`；章节序列化新增 `page_index`。

### 5.4 新增 API（`backend/app/api/routes/books.py`）

- `GET /api/books/{book_id}/cover`：返回封面图片文件（`FileResponse`）。
- `GET /api/books/{book_id}/pages/{page_index}`：返回扫描版指定页的 `page_XXX.jpg`（1 基页码）。

### 5.5 聊天页图附件（`backend/app/api/routes/chat.py` + `backend/app/services/chat_service.py`）

- 开关：设置页「发送页面图片」（键 `ai_send_page_image`，环境变量 `AI_SEND_PAGE_IMAGE`，默认关闭；需同时开启隐私开关「发送书籍正文」才生效）。
- `chat.py::_page_image_data_uri(book, chapter, send_enabled)`：扫描版且当前章节带 `page_index` 时读取 `pages/page_XXX.jpg`，编码为 `data:image/jpeg;base64,...`。
- `chat_service.py::build_messages(..., page_image=None)`：`enable_body_send` 为真且传入页图时，用户消息改为 parts 列表（文本 + `image_url` 部件）；隐私开关关闭时**不附带页图**。
- `LLMClient`（`backend/app/ai/client.py`）：chat 模式原样传递 messages（含图片部件）；responses 模式经 `_content_text` 提取纯文本（图片隐式退化，多模态需模型与接口支持）。

### 5.6 前端（`frontend/src/`）

- `types.ts`：`BookItem` 新增 `is_scanned/page_count/cover_url`；`ChapterItem`/`ChapterContent` 新增 `page_index`；`AiSettings` 新增 `send_page_image`。
- `HomeView.vue`：书架卡片渲染 `cover_url` 封面（`cover-img`，150px 高、object-fit: cover），无封面时回退格式徽章。
- `ReaderView.vue`：`content.page_index != null` 时进入 `pageMode`，正文区渲染 `<img class="page-img">` 显示原始页图（扫描版不渲染文本高亮/笔记）。
- `SettingsView.vue`：新增「发送页面图片」开关，保存到 `send_page_image`。

### 5.7 冒烟要点（mock LLM）

1. 导入文本 PDF 与扫描版 PDF 各一：书架显示封面；扫描书 `page_count` 为真实页数。
2. 打开扫描书：目录为「第 N 页」，正文显示页图，切换章节页图随之切换。
3. 设置页开启「发送页面图片」并保存；阅读页对扫描书提问，SSE 正常回复、无报错；关闭「发送书籍正文」后提问不再附带页图（后端单测覆盖）。
4. 回归：`pytest`（31 项）+ `ruff check app tests` + `pnpm build`。

### 5.8 封面回填、旧布局迁移与书架删除（补充修复）

- **封面串书根因**：早期封面/页图写入共享的 `data/books/cover.jpg` 与 `data/books/pages/`，后导入的书会覆盖前书的封面。v1.17 起每本书独立子目录存储（见 5.3）。
- **封面回填**（`backend/app/services/media_service.py`）：
  - `ensure_book_cover(db, book)`：缺封面或封面文件丢失时按需重新提取（PDF 渲染第 1 页 / EPUB OPF 封面）并更新 DB；`GET /api/books/{id}/cover` 会自动触发。
  - `migrate_book_layout(db, book)`：把旧扁平布局迁移到 `data/books/<file_id>/`；共享 `pages/` 页数与本书一致时整目录搬入，避免逐页重渲染。
  - `migrate_all_books(db)`：启动时（`database.py::_migrate_book_media`）自动执行迁移 + 回填，幂等，失败不阻塞启动。
- **书架删除**：
  - 前端 `HomeView.vue`：书架卡片悬停显示 🗑 按钮，确认后调用 `DELETE /api/books/{id}` 并刷新列表。
  - 后端 `books_service.py::delete_book`：先显式清理 `chat_messages / reading_logs / notes / book_assets / knowledge_points / book_relations`（部分外键无 CASCADE，直接删书会触发外键冲突），再删书籍记录（章节随 ORM 级联），最后删除整个书籍子目录（含 PDF、封面、页图）。
  - 页图端点 `GET /api/books/{id}/pages/{page_index}` 缺文件时按需渲染单页（`render_pdf_page`）。


### 5.9 扫描版页图高清化与阅读缩放（v1.22）

- **问题**：页图按 72 DPI（`page.rect` 原始点尺寸）渲染，实际扫描 PDF 内嵌图多为 300 DPI 级（如 2024×2953），阅读时被大幅降采样，正文发虚。
- **原图渲染**（`backend/app/parsers/pdf.py`）：
  - `_auto_page_zoom(page)`：取页内嵌图片原生宽度与页面宽度之比作为渲染倍率（即按「原图」分辨率渲染，上限 6x 防超大内存）；无内嵌图片（纯矢量页）时用 2.5x（≈180 DPI）兜底。
  - `render_pdf_page`：新增 `zoom` 参数；`max_width=0` 且未给 `zoom` 时走自动原图倍率；封面仍走 `max_width=600` 旧路径。`render_pdf_pages` 默认改为自动倍率（新导入即高清）。
  - `pdf_page_target_width(path, page_index)` / `jpeg_width(path)`：计算目标宽度与读取已渲染页图实际像素宽（读像素宽须用 `pymupdf.Pixmap`，JPEG 自带 DPI 元数据会让 `pymupdf.open` 按点换算失真）。
  - 页图端点 `GET /api/books/{id}/pages/{page_index}`：文件缺失或像素宽 < 目标宽 ×0.85（旧低清页）时按需重渲染单页；响应加 `Cache-Control: no-cache` 防浏览器缓存旧图。
- **阅读缩放**（`frontend/src/views/ReaderView.vue`）：
  - 扫描版阅读区上方新增缩放条：`适配宽度` / `原始大小`（1 像素 = 1 CSS 像素，页面可横向滚动）/ `＋` `－`（0.5x~3x）。
  - 实现：`pageZoom`（`'fit' | number`）+ `pageNaturalWidth`（img `naturalWidth`）+ `pageImgStyle`（fit 用 `max-width:100%`，缩放用显式像素宽度）；`.page-scroll` 横向滚动 + `justify-content: safe center` 防止放大后左侧被裁切。
- 冒烟：书 7 第 1 页由 467×666（37KB）升级为原图分辨率（1487px 宽、约 280KB）；放大到「原始大小」可横向滚动查看清晰正文。

### 5.10 PDF 页图多模态视觉提取与页级缓存（统一适用于全部 PDF）

> 状态：**已实现（M7，见 §9）**——设计要点如下，实现细节见 §9（需求 3.4.11 / 技术栈规范 §6）。

- **链路**：PDF 页图（含文本型，文本抽取数学符号会乱码）→ 多模态 LLM 逐页提取完整页面信息（Markdown 文本，含公式/表格/图注描述）→ 缓存 `data/books/<书目录>/page_text/page_XXX.md` → 文本大模型基于缓存解读（引用出处「第 X 页」）。
- **触发时机**：手动导入 PDF（含文本型）作为知识库时**批量预提取**；阅读时不预提取，**用户在当前页对 AI 提问**时按需提取（窗口 `[P-1,P,P+1]`，第 1 页/末页裁剪，仅补缺失页，需求 9.1 决策 22）。
- **缓存命中**：`page_XXX.md` 存在且非空即命中，不再调用多模态 API；缓存缺失且未配置多模态提取时仅**纯文本降级**（章节文本 / 提示先触发提取），**不再回退直发页图附件**（决策 36）。
- **预期落点**：后端 `app/ai/vision_client.py` + 任务模块提取任务 + 页图相关 API（提取/重建/读取页缓存）；前端设置页多模态配置（base_url/api_key/model 独立）与阅读页「提取本页 / 重建本书页缓存」入口。
- **依赖与约束**：多模态 API **独立配置**（`vision_base_url / vision_api_key / vision_model`，无需额度管理，需求 9.1 决策 23）；受「发送书籍内容至模型」隐私开关约束（关闭不提取、不发送）；随书删除清理页缓存。

### 5.11 位置书签与 PDF 页图涂鸦（M6 已实现）

> 状态：**已实现**（需求 3.3/3.5 / 技术栈规范 §4.7/§5；决策 22~26）。

- **位置书签（适配所有格式）**：
  - 后端：`Bookmark` 表（`book_id/chapter_id/page_index/para_pos/title/note/group_name/created_at`，随书删除级联清理）；仓储 `repositories/bookmarks.py`；路由 `api/routes/bookmarks.py`。
  - API：`GET/POST /api/books/{id}/bookmarks`（列表默认时间倒序 / 新增）、`PATCH/DELETE /api/bookmarks/{id}`（改标题/备注/分组 / 删除）。
  - 前端：`BookmarkDrawer.vue` 书签抽屉（倒序平铺 + 分组视图、新增当前章节/页书签、编辑/删除、点击定位跳转）；阅读页工具栏「🔖 书签」按钮。
  - 跳转：PDF 书签按 `page_index` 找到对应页章节加载；文本书签按 `chapter_id + para_pos` 加载章节后滚动到 `[data-para]` 段落。
- **PDF 页图涂鸦（按页阅读时）**：
  - 后端：`api/routes/annotations.py`——`GET/PUT /api/books/{id}/annotations?page_index=N`，读写 `data/books/<书目录>/annotations/page_XXX.json`；删除书籍时 `books_service._remove_book_files` 清理 `annotations/` 目录。
  - 前端：`PageDoodleCanvas.vue`（canvas 叠加层，坐标 0~1 归一化；笔刷/高亮/橡皮/文本，颜色/线宽可调；`undoStack` 上限 5 会话内撤销；橡皮命中擦除笔画/文本；划线点击弹出「💬 批注 / 🤖 就此划线提问」）；`DoodleToolbar.vue` 工具栏；ReaderView `pageMode` 下集成，切页自动保存上一页并加载当前页。
  - 存储格式：元素数组——`stroke`（tool/color/line_width/points[[x,y],...]/可选 `note`+`note_meta`）、`text`（text/color/font_size/x/y）；仅保存最终元素，不持久化历史版本。
  - **划线批注**：选中划线 → 弹窗编辑 `note`（Markdown/LaTeX），随元素保存。
  - **划线区域提问**：选中划线 → 按归一化 bbox 裁剪原图页（`cropDataUrl`，JPEG data URI）→ 复用 `POST /api/books/{id}/chat` 的 `crop_image`/`crop_label` 字段（受隐私开关约束）→ 后端在「发送页图」开启时经 `vision_extract.extract_image_attachment` 把裁剪图提取为文本后注入（内容寻址缓存，决策 36）→ 流式回答进入 AI 面板。
- **chat 扩展**：`ChatIn` 新增 `crop_image`（划线区域裁剪图）与 `crop_label`（区域说明）；`chat_service.build_messages` **不再直发图片**——划线裁剪图与正文插图经视觉模型提取为文本后注入（决策 36）。


## 8. M6 阅读体验补全：位置书签 + PDF 页图涂鸦（第 8 轮任务产出）

### 8.1 位置书签（全格式 + 分组）

**后端**

| 文件 | 说明 |
| --- | --- |
| `app/models/activity.py` | 新增 `Bookmark` 表：`book_id/chapter_id/page_index/para_pos/title/note/group_name/created_at`（外键 CASCADE） |
| `app/repositories/bookmarks.py` | `list_bookmarks`（时间倒序）/ `get_bookmark` / `create_bookmark` / `update_bookmark`（标题/备注/分组）/ `delete_bookmark` |
| `app/api/routes/bookmarks.py` | `GET/POST /api/books/{id}/bookmarks`、`PATCH/DELETE /api/bookmarks/{id}`；章节归属校验；`BookmarkIn/BookmarkUpdate` Pydantic 模型 |
| `app/schemas/serializers.py` | `bookmark_to_dict` 序列化 |

- 修改：新增字段需同步 `BookmarkIn/BookmarkUpdate`、仓储函数与 `bookmark_to_dict`；新表由 `Base.metadata.create_all` 自动建（旧库无需 ALTER）。
- 删除书籍时 `books_service.delete_book` 显式 `delete(Bookmark)` 清理。

**前端**

| 文件 | 说明 |
| --- | --- |
| `src/api/annotations.ts` | `listBookmarks/createBookmark/updateBookmark/deleteBookmark`（复用 `client.ts`，新增 `put` 封装） |
| `src/components/BookmarkDrawer.vue` | 书签抽屉：时间倒序平铺 + 分组视图、添加当前章节/页书签（书名/分组）、编辑/删除、`jump` 事件 |
| `src/views/ReaderView.vue` | 「🔖 书签」按钮 + `BookmarkDrawer` 集成；`jumpToBookmark`（PDF 按 `page_index` 定位页章节；文本书按 `chapter_id+para_pos` 滚动 `[data-para]`）；`scrollToPara` 段落滚动 |

- 修改：`BookmarkDrawer` 的分组由 `group_name` 字符串表达；如需多级分组/文件夹树，在 `Bookmark` 表加 `parent_group_id` 并扩展抽屉分组树。

### 8.2 PDF 页图涂鸦（画板 + 撤销/擦除/文本 + 划线批注/提问）

**后端**

| 文件 | 说明 |
| --- | --- |
| `app/api/routes/annotations.py` | `GET /api/books/{id}/annotations?page_index=N` 读取、`PUT /api/books/{id}/annotations`（`{page_index, elements}`）整页覆盖保存；上限 `MAX_ELEMENTS=2000` |
| `app/services/books_service.py` | `_remove_book_files` 清理 `annotations/` 目录（旧布局分支） |
| `app/api/routes/chat.py` | `ChatIn` 新增 `crop_image`（划线区域 data URI）/ `crop_label`（区域说明）；组装 `build_messages` |
| `app/services/chat_service.py` | `build_messages` 不再直发图片——划线裁剪图/正文插图经 `extract_image_attachment` 视觉提取为文本后注入（决策 36，受隐私开关约束） |

- 存储：`data/books/<书目录>/annotations/page_XXX.json`（元素数组）；`stroke` 含 `tool/color/line_width/points/note/note_meta`，`text` 含 `text/color/font_size/x/y`；坐标 0~1 归一化。
- 修改：如需历史版本，把「会话内撤销栈」升级为「每页版本快照列表」存储到同一 JSON 的 `history` 字段并调整 `undo`。

**前端**

| 文件 | 说明 |
| --- | --- |
| `src/components/PageDoodleCanvas.vue` | canvas 叠加层：尺寸以页图实际渲染尺寸同步（ResizeObserver + 兜底轮询），仅缓冲区尺寸变化时重置（避免清空画布）；点坐标兼容 `[x,y]`/`{x,y}`（`src/utils/annotations.ts`）；笔刷/高亮/橡皮/文本工具；`undoStack` 上限 5 + 切页 `resetUndo`；橡皮命中擦除；划线点击选中菜单（`edit-note` / `ask-crop`）；`cropDataUrl` 按 bbox 裁剪原图为 JPEG data URI |
| `src/components/DoodleToolbar.vue` | 工具栏：工具切换 / 颜色 / 线宽 / 撤销 / 清除本页 |
| `src/api/annotations.ts` | `getPageAnnotations/savePageAnnotations` |
| `src/views/ReaderView.vue` | `pageMode` 下集成画板；涂鸦工具栏置于阅读页顶部工具栏「第 X 页」与「第 X 章/共 XX 章」之间（仅 PDF 按页阅读显示，文本书不显示）；切页保存上一页并加载当前页（防抖 800ms）、加载时迁移旧数据点格式；划线批注弹窗；划线提问（写入 AI 面板并发起 chat） |

- 修改：工具扩展（如箭头/矩形）在 `PageDoodleCanvas` 增加 tool 分支与 `AnnotationElement.type` 联合类型；撤销栈上限调整 `undoStack.length > 5` 常量。

### 8.3 冒烟要点

- 书签：文本书添加 → 抽屉分组显示 → 点击跳转回到对应段落；PDF 书（`is_scanned=true`）添加整页书签 → 跳转加载对应页章节。
- 涂鸦：PDF 页图画笔划线 → 刷新页面仍叠加显示；撤销 5 步内恢复；橡皮擦除；划线点击 → 批注弹窗保存 → 重开仍在；划线提问 → chat 请求带 `crop_image`（无 API Key 时报配置错误而非 422）。
- 删除书籍：书签与 `annotations/` 文件一并清理（测试 `test_delete_book_cleans_bookmarks_and_annotations`）。

### 8.4 涂鸦修复轮：渲染与工具栏重排（第 8 轮补充迭代）

- 画布 1×1 / 无法绘制 / 文本不渲染根因：旧版标注把 `points` 存为 `{x,y}` 对象，`drawStroke` 用数组解构 `([x, y])` 遍历直接抛 `TypeError: object is not iterable`，`onMounted` 中断导致 ResizeObserver 未注册、画布永远 1×1。
- 修复一：新增 `src/utils/annotations.ts`（`toPoint` / `normalizeAnnotationPoints`），读取与渲染均兼容 `[x,y]` 与 `{x,y}`，旧数据自动迁移为数组并回写持久化（幂等，无对象点时不触发更新）。
- 修复二：`syncSize` 仅在实际尺寸变化时重置 canvas 缓冲区（`el.width/height` 赋值会清空画布），配合 retry 轮询修正"尺寸稳定后不再重绘"导致的清空时序 bug；mounted 内 `redraw` 异常不再阻塞画板初始化（try/catch 兜底）。
- 修复三：涂鸦工具栏从页底移入阅读页顶部工具栏，位于「第 X 页」与「第 X 章/共 XX 章」之间，仅 `pageMode`（PDF 按页阅读）显示；文本书仍显示「已读 x/y 章 · 进度 z%」。
- 修复四：切页时 `resetUndo` 清空撤销栈，避免上一页涂鸦可被"撤销"进当前页；撤销按钮可用状态由画板 `can-undo` 事件驱动（`doodleCanUndo`）。
- 冒烟：旧数据页打开即渲染高亮；笔刷/高亮/橡皮/文本均可绘制且刷新后仍存在；工具切换有 active 反馈；第 20 页无数据不残留上一页内容；`/reader/2`（文本书）无涂鸦工具栏。

### 8.5 阅读区单一滚动条（第 8 轮补充迭代）

- 问题：PDF 按页阅读时 .page-scroll（overflow: auto）与外部 .reading-scroll（overflow-y: auto）叠加产生两个滚动条，阅读区视觉割裂。
- 修复（src/views/ReaderView.vue）：.page-scroll 移除 overflow: auto，改为 width: 100%; display: flex; justify-content: safe center（仅负责水平居中页图）；缩放条 .page-zoombar 增加 position: sticky; top: 0; z-index: 2; background，外层滚动时保持可见。
- 冒烟：阅读区仅剩外层 .reading-scroll 一个滚动条，滚动到底正常，缩放条不随内容滚走；左侧书架/目录独立滚动不受影响。


## 9. M7 PDF 统一处理与多模态视觉提取（第 9 轮任务产出）

> 状态：**已实现**（需求 3.2/3.4.11 / 技术栈规范 §6；决策 2/21~23）。

### 9.1 PDF 解析统一按页（`backend/app/parsers/pdf.py`）

| 函数 | 功能 | 输入 | 输出 |
| --- | --- | --- | --- |
| `parse_pdf(path, title_hint=None)` | PDF（含文本型）统一按原始页切章：每页一章（标题「第 N 页」，content 为空，`page_index=N`），`is_scanned=True`；本地抽取文本按页放入 `ParsedBook.page_texts`（仅作全文检索索引） | 路径 | `ParsedBook` |
| `render_pdf_page(path, page_index, out_path, max_width=0, quality=90, zoom=None)` | 渲染指定页为图片（默认按内嵌原图分辨率自动放大；封面用 max_width） | 路径/页号/输出路径 | `Path` |
| `render_pdf_pages(path, out_dir, max_width=0, quality=90)` | 渲染全部页为 `page_XXX.jpg` | 路径/目录 | 页数 |
| `pdf_page_target_width / jpeg_width` | 目标像素宽度（原图）/ 已渲染页图宽度（低清升级判断） | — | int |

**如何使用**：导入 PDF 时 `import_service.import_book` 自动渲染全部页到 `<书目录>/pages/`，并把本地抽取文本写入 `<书目录>/local_text/page_XXX.txt`；阅读页按「第 N 页」章节展示原图。
**如何修改**：调整页图渲染质量/倍率改 `PAGE_AUTO_ZOOM_MIN/MAX` 或 `render_pdf_page` 的 `quality/zoom`；旧版文本型 PDF 书籍仍按旧行为展示，删除后重新导入即可升级为按页模式。

### 9.2 多模态视觉配置

- 配置项（`.env` 或设置页，独立于文本 AI，无需额度管理）：`vision_base_url / vision_api_key / vision_model / vision_timeout / vision_verify_ssl / vision_max_tokens` + 精细参数 `vision_temperature / vision_top_p / vision_frequency_penalty / vision_presence_penalty / vision_enable_thinking / vision_thinking_budget`（`backend/app/core/config.py`）。默认模板指向 SiliconFlow：`https://api.siliconflow.cn/v1` + `Qwen/Qwen2.5-VL-72B-Instruct`（可用 `deepseek-ai/DeepSeek-OCR` 等），`vision_max_tokens=4096`。
- **接口约束（按 SiliconFlow 文档）**：视觉客户端**强制 `mode="chat"`**（SiliconFlow 等仅支持 `POST /chat/completions`，`responses` 模式会 404）；`LLMClient` chat 分支按设置写入 `max_tokens / temperature / top_p / frequency_penalty / presence_penalty`，以及 SiliconFlow 推理模型专用的 `enable_thinking / thinking_budget`（`VISION_ENABLE_THINKING / VISION_THINKING_BUDGET`；Qwen 等非推理模型勿开）；页图 `image_url` 固定带 `"detail": "high"` 保证识别精度。
- **请求格式（按 SiliconFlow 多模态文档 api-docs.siliconflow.cn/docs/userguide/capabilities/multimodal-vision）**：多模态模型统一走 `POST /chat/completions`，`messages[].content` 为 parts 列表（文本 + 图片部件）；图片部件 `{"type":"image_url","image_url":{"url":..., "detail":"high"}}`，`url` 支持 base64 data URI（`data:image/jpeg;base64,...`），`detail` 取 `auto/low/high`。页提取（`vision_extract._extract_page_text`）统一该格式；对话链路附件（划线裁剪图/正文插图）**不再直发图片**，在「发送页图」开启时经 `extract_image_attachment` 视觉提取为文本后注入（决策 36；前端裁剪图由 `canvas.toDataURL('image/jpeg', 0.85)` 生成）。
- **配置优先级**：设置页保存的值（DB `settings` 表）优先于 `.env`；`.env` 仅在对应项未在设置页保存时生效。当前正式库已把原有设置页覆盖项迁移进 `backend/.env` 并清除 DB 覆盖，`.env` 为唯一配置源（改 `.env` 后需重启后端）。
- 后端：`repositories.settings.vision_client_kwargs(db)` 返回 LLMClient 构造参数（未覆盖项取 .env，不回退到文本 AI 配置）；`vision_configured(db)` 判断是否可用；设置视图/保存/测试走 `api/routes/settings.py`（`GET/PATCH /api/settings/ai`、`POST /api/settings/ai/test-vision`）。
- 前端：`SettingsView.vue`「多模态视觉接入（M7）」卡片（Base URL/API Key/模型/超时/校验 SSL/生成上限/温度/Top P/频率惩罚/存在惩罚/思考模式开关/思维链上限 + 测试视觉连接）；`types.ts` `AiSettings` 扩展 `vision_*` 字段（含精细参数）。

### 9.3 视觉提取服务（`backend/app/services/vision_extract.py`）

| 函数 | 功能 | 使用/修改 |
| --- | --- | --- |
| `page_text_path(book, page_index)` | 页缓存文件路径 `<书目录>/page_text/page_XXX.md` | 调整目录名改 `PAGE_TEXT_DIR` |
| `read_page_cache(book, page_index)` | 读缓存；缺失/空返回 None | 缓存命中判定唯一入口 |
| `ensure_page_cache(db, book, page_index, force=False)` | 单页提取：命中（非空且非 force）直接返回，否则调用多模态 LLM 提取并落盘；隐私开关关闭抛 ValueError | 修改提取提示词改 `EXTRACT_SYSTEM`；切换视觉模型改配置 |
| `extract_image_attachment(db, image_uri, hint="")` | 附件（划线裁剪图/正文插图）视觉提取为文本：命中内容寻址缓存 `data/cache/attachment_text/`（sha256 前 32 位）直接返回；未配置视觉模型（`vision_configured`）或提取空/异常返回 None 且不落盘 | 缓存目录改 `ATTACHMENT_TEXT_DIR`；提取提示词改 `ATTACHMENT_SYSTEM`（LaTeX 硬性规则）；触发开关=`ai_send_page_image`（决策 36） |
| `ensure_window_caches(db, book, page_index, force=False)` | `[P-1,P,P+1]`（首/末页裁剪）增量缓存，返回 {页号: 文本} | 窗口大小改 `start/end` 计算 |
| `rebuild_book_caches(db, book, force=False, progress=None)` | 全书重建/补齐；返回 {total, extracted, cached, failed, errors} | 单页失败不中断 |
| `extract_book_pages_task(book_id, force=False)` | 后台任务入口（独立会话） | 供导入预提取与重建路由调用；**M9 读完归档全书提取将复用该入口**（归档时先全书补齐页缓存，再以缓存全文调 `generate_rag_skill` 总结） |

### 9.4 页缓存 API（`backend/app/api/routes/vision.py`，prefix `/api/books`）

- `GET /{book_id}/page-text/status`：缓存覆盖 {total, cached}。
- `GET /{book_id}/page-text/{page_index}`：读单页缓存文本（未缓存 text=null）。
- `POST /{book_id}/page-text/{page_index}`：重新提取本页（force 覆盖）。
- `POST /{book_id}/page-text/rebuild`：提交后台重建任务（body `{"force": bool}`），返回 `{task_id}`。
- `GET /{book_id}/page-text/tasks/{task_id}`：任务状态。
- 注意：字面量路由（status/rebuild）必须注册在 `/{page_index}` 之前，避免被 int 路径参数抢先匹配。

### 9.5 提问链路（对话 + 脑图）

- `services/ai_context.py`：新增 `build_page_context_block(window_texts, enable_body_send)`（组装「【第 N 页】+ 文本」块）；`extract_citations` 支持【第X页】（para='页'）。
- `api/routes/chat.py`：PDF 按页章节提问时，若已配置多模态且隐私开启，先 `ensure_window_caches` 提取窗口并注入页缓存文本（出处「第 X 页」）；提取失败/未配置时回退当前页原图附件（`page_image_data_uri`）。
- `services/mindmap_service.py`：脑图生成同样优先页缓存文本。
- 前端 `ReaderChatPanel.vue` 引用 chip 兼容「第X页」。

### 9.6 前端入口（`frontend/src/api/vision.ts` + `ReaderView.vue`）

- `api/vision.ts`：`getPageTextStatus / getPageText / reextractPage / rebuildPageText / getPageTextTask`。
- 阅读页工具栏（PDF 页模式）：页缓存 x/y 状态、「🔄 重提本页」、「📄 重建页缓存」（确认后提交任务并轮询刷新）。
- 重建轮询可见性感知（v1.91）：`useReaderPageCache.ts` 的 2s 任务轮询在页面隐藏时暂停、恢复可见后继续（`startPolling/stopPolling/onTaskPollVisibility`），后台重建期间切走标签页不再产生周期性请求。

### 9.7 冒烟要点

1. 导入 PDF（含文本型）→ 书籍 `is_scanned=true`、章节为「第 N 页」、`/pages/N` 返回原图。
2. 设置页配置多模态并「测试视觉连接」；`GET /api/settings/ai` 返回 `vision_*` 字段（Key 掩码）。
3. 无多模态配置时 `POST /page-text/{n}` 与 `/rebuild` 返回 400「未配置多模态视觉 API」。
4. 配置后重提本页 → `page-text/status` cached 递增；`page-text/{n}` 返回文本。
5. PDF 页提问 → 回答引用【第X页】；页缓存生成后同窗口提问不再触发多模态（增量缓存）。

---


### 13.1 笔记导出服务（`backend/app/services/note_export.py`，M10）

- **`build_notes_markdown(book, notes, chapters) -> str`**：生成全书笔记 Markdown（沿用 M3 格式：`# 书名 笔记导出` → 每条 `## [类型]（第X章 标题）` + 引文 `>` + 正文），供 `?fmt=md` 与默认导出使用。
- **`build_notes_pdf(book, notes, chapters) -> bytes`**：生成 A4 PDF。使用 PyMuPDF 内嵌 CJK 字体（`pymupdf.Font("cjk")` → Droid Sans Fallback），按宽度逐字换行（`_wrap`，兼容中文与长 LaTeX），Markdown 记号转纯文本、LaTeX 公式以源码保留；文件约 1.7MB（含内嵌字体）。
- **API**：`GET /api/books/{id}/notes/export?fmt=md\|pdf`（`fmt` 缺省为 md，非法值 422）；`Content-Disposition: attachment; filename="notes.md" / "notes.pdf"`。
- **前端**：`src/api/reading.ts` `exportNotesUrl(bookId)`（md）与 `exportNotesPdfUrl(bookId)`（`?fmt=pdf`）；阅读页笔记抽屉 `drawer-actions` 两个下载链接。


