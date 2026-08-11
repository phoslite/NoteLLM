# 知识水平校准 + 增强点 2/3 触发方式定稿（v1.135）

> 日期：2026-08-11 ｜ 状态：已实施（v1.135） ｜ 前置：v1.132 重新生成画像（用户主动触发）

## 1. 背景与定稿

「领域偏好修复 → 画像联动」讨论中提出的三个增强联动点，本次定稿触发方式：

| 增强点 | 内容 | 触发方式定稿 |
| --- | --- | --- |
| 1 | 领域偏好修复 → 词库沉淀 | 已实施（v1.134，随「重新生成画像」执行） |
| 2 | 归档后全库画像重建 | **用户主动触发**（不随归档热路径自动执行；既有「🔃 重新生成」按钮即为此入口） |
| 3 | `knowledge_level` 校准 | **用户主动触发**（本版本实施：只建议不自动写入，用户确认后应用） |

理由：归档是高频热路径，自动全库重建会显著拖慢归档且产出用户不可预期；知识水平属于「画像结论」，自动改写会导致 AI 解读口径漂移。两者均保留为显式动作，用户知情、可控、可回退。

## 2. 设计

### 2.1 服务（`backend/app/services/profile_service.py`）

- `_normalize_knowledge_level(level)`：归一化枚举 `beginner / intermediate / advanced`（兼容中文别名：入门/初级/新手、进阶/中级、深入/高级/专家），非法值抛 `ValueError`（路由转 400）。
- `update_cold_profile(..., knowledge_level=None)`：手动设置（PATCH /profile/cold 扩展字段）。
- `calibrate_knowledge_level(db)`：**只计算不写入**，返回建议 + 证据：
  - 信号与得分：归档书数（≥10:2.0 / ≥5:1.0 / ≥3:0.5）、已建 RAG 资产的书数（同档）、长期兴趣词数（≥15:1.0 / ≥8:0.5）、领域偏好最高分（≥8:1.0 / ≥5:0.5）；
  - 总分映射：≥4.5 → advanced（深入）、≥2 → intermediate（进阶）、否则 beginner（入门），满分 6.0；
  - 返回 `current / suggested / score / max_score / levels / signals / evidence`。

### 2.2 API（`backend/app/api/routes/profile.py`）

- `GET /api/profile/calibrate`：校准建议（无副作用，不写库）。
- `PATCH /api/profile/cold`：`ColdProfileIn` 新增 `knowledge_level` 字段（手动应用建议或直接手选）。

### 2.3 前端（`frontend/src/views/ProfileView.vue`）

- 冷画像卡片新增「🎓 知识水平」行：当前等级标签 + 下拉（入门/进阶/深入，改动即 PATCH）+「🎯 校准建议」按钮。
- 校准流程：点击 → `GET /profile/calibrate` → 弹窗展示证据明细与建议等级 → 用户点「应用建议」→ PATCH 写入（取消则不改）。

## 3. 向前兼容

1. 不改任何既有字段语义：`knowledge_level` 仍是冷画像自由文本字段，默认 `intermediate` 兜底不变；LLM 提示词读取逻辑（rag_router/chat prompt）零改动；
2. 只建议不自动写入：不点「应用建议」则冷画像完全不变；手动下拉同样需用户操作；
3. 非法值后端 400 拒绝，前端只提供三个枚举选项，不会产生脏值；
4. 归档/重置/重新生成画像均不触碰知识水平（reset 除外，reset 语义本就是清空全部）。

## 4. 测试计划

- 空画像 → 建议 beginner、得分 0、默认 current=intermediate；
- 富画像（归档 12 + RAG 书 12 + 兴趣 18 + 偏好最高分 9）→ 建议 advanced 且**不写入**；
- 手动设置中文别名归一化（入门→beginner）；非法值抛 ValueError；
- 路由：GET /profile/calibrate 200；PATCH knowledge_level=深入 → advanced；非法值 → 400。

## 5. 文档登记

使用手册总纲 v1.135 变更记录；分册「图谱与画像」§11.1/§11.2 同步；技术栈规范 v1.85。
