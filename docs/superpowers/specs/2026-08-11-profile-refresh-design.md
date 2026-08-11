# 「重新生成画像」功能设计（v1.132）

> 日期：2026-08-11 ｜ 状态：待用户审阅 ｜ 关联：冷记忆分词修复（v1.131，`graph/terms.py` 画像术语层 + `scripts/clean_profiles.py`）

## 1. 背景与目标

冷记忆分词修复（v1.131）后，新增画像术语层 `extract_profile_terms` / `sanitize_profile_term_freq`，并提供了命令行清洗脚本。但现有画像页只有「🔄 刷新」（重新拉取显示）与「重置画像」（清空三层），用户缺少一个**不清空、可随时执行**的画像维护入口。

目标：新增「重新生成画像」功能——一键完成
1. 暖主题重算（贴合暖画像「近 1~2 本 + 相关领域」定义，修正历史过度累积）；
2. 冷画像脏词清洗（泛化词 / 虚词碎片 / LaTeX 残留剔除，手动编辑词保留）；
3. 热画像与任何有效数据均不清空。

## 2. 设计

### 2.1 后端

- 服务函数：`profile_service.refresh_profiles(db) -> dict`
  1. `warm.themes` 重算：取 `warm.recent_books`（近 2 本）+ `warm.related_books` 的 `summary/key_points`，经 `extract_profile_terms`（`PROFILE_REFRESH_TOP_N = 40`，常量收口于 `profile_service`）聚合词频后整体替换 themes；
  2. `cold.domain_preferences`：`sanitize_profile_term_freq` 清洗后写回；
  3. `cold.long_term_interests`：同规则清洗；
  4. `hot` 不读取、不修改；
  5. 返回统计：`{themes_before, themes_after, cold_before, cold_after, removed_sample: [...]}`。
- 路由：`POST /api/profile/refresh`（`api/routes/profile.py`），成功返回 `ok(data, "画像已重新生成")`。
- 异常处理：与既有路由一致，DB 异常由 `get_db` 回滚；统计计算失败不落库（先算后写，或事务内整体回滚）。

### 2.2 前端

- `api/profile.ts`：新增 `refreshProfile()`（POST `/profile/refresh`）。
- `ProfileView.vue` 头部按钮组：「🔄 刷新」旁新增「🔃 重新生成」（`type="primary" plain`）。
- 交互：点击 → `ElMessageBox.confirm`（文案：将清洗画像脏词并按近期阅读重新生成暖主题，不会清空）→ 调用 → 成功后 `refresh()` 并 `ElMessage.success` 展示统计（如 `暖主题 1126 → 260，冷画像 1126 → 1126`）。
- busy 态复用现有 `busy` 标志。

## 3. 数据流

```
前端按钮 → POST /api/profile/refresh
  → refresh_profiles(db)
      ├─ warm.themes ← Σ extract_profile_terms(recent_books + related_books 的 summary/key_points)
      ├─ cold.domain_preferences ← sanitize_profile_term_freq(旧值)
      ├─ cold.long_term_interests ← sanitize_profile_term_freq(旧值)
      └─ 返回统计
前端 refresh() 重新拉取 → 页面展示新画像
```

## 4. 错误处理

- 画像为空（无 warm/cold 行）：视为成功，统计为 0，不报错；
- DB 写入失败：`get_db` 回滚，前端提示错误；
- 极端脏数据（JSON 解析失败）：`_load` 已兜底返回默认值，不崩溃。

## 5. 向前兼容（用户明确要求单独说明）

本功能**不破坏**既有画像数据与后续行为，理由如下：

1. **不清空任何层**：热画像（当前书细节）完全不触碰；暖画像仅替换 `themes`（派生统计字段），`recent_books` / `related_books` 原文条目原样保留；冷画像仅删除规则判定为脏词的条目。
2. **与既有语义一致**：暖主题重算遵循暖画像「近 1~2 本 + 相关领域」的既有定义（`migrate_profiles_on_archive` 也是从这些条目的 key_points 聚合主题），只是把「历史累积」修正为「当前窗口」，与归档迁移链路（暖→冷阈值）完全兼容——重新生成后再次归档仍正常累积与迁移。
3. **无信息丢失**：被清洗的脏词本身是无意义碎片（跨词/虚词/LaTeX），合法词与用户手动编辑的整词均保留；`recent_books` 原文文本（summary/key_points）是主题的唯一事实来源且未被修改，任何误删都可从原文重算恢复。
4. **幂等收敛**：重复执行第二次变化≈0（themes 由固定原文集合重算，冷画像已无脏词可删），不会反复漂移。
5. **可回退**：不满意可走既有「重置画像」完全清空重来，或手动编辑冷画像；无需新增迁移/回滚脚本。
6. **失败安全**：计算失败不落库（整体事务），已有画像保持不变。

## 6. 测试计划

- 后端 pytest（`tests/test_profile_terms.py` 或新增 `tests/test_profile_refresh.py`）：
  1. 构造含脏词 themes + 脏冷画像 + recent_books 原文 → refresh 后 themes 仅含原文抽取的合法词、冷画像脏词移除、手动整词保留；
  2. 统计字段（before/after/removed_sample）正确；
  3. 空画像 refresh 成功且统计为 0；
  4. 幂等：连续两次 refresh 第二次统计变化为 0；
  5. hot 画像在 refresh 前后不变。
- 前端：按钮存在性 + 调用链由人工冒烟验证（项目前端测试以 E2E 冒烟为主）。

## 7. 文档登记

- 使用手册分册「图谱与画像」§11.2（画像 API 表新增 refresh 行）；
- 使用手册总纲变更记录 v1.132；
- 技术栈规范 v1.83 关联文档行同步（如版本递增则 v1.84）。
