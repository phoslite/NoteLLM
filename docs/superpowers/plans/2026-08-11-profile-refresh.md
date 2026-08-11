# 「重新生成画像」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为画像页新增「重新生成画像」：后端 `POST /api/profile/refresh` 重算暖主题 + 清洗冷画像脏词（不清空任何层），前端加按钮并展示统计。

**Architecture:** 服务函数 `profile_service.refresh_profiles` 复用 v1.131 画像术语层（`extract_profile_terms` / `sanitize_profile_term_freq`）；路由薄封装；前端按钮走既有 `refresh()` 拉取链路。

**Tech Stack:** FastAPI + SQLAlchemy（SQLite WAL）、Vue 3 + Element Plus、pytest、ruff。

**前置**：先提交 v1.131 冷记忆分词修复的未提交改动（单独 commit），再按任务执行。

---

### Task 1: 服务函数 `refresh_profiles`（TDD）

**Files:**
- Modify: `backend/app/services/profile_service.py`
- Test: `backend/tests/test_profile_refresh.py`（Create）

- [ ] **Step 1: 提交上轮未提交改动（v1.131 冷记忆修复）**

```bash
git add backend/app/services/graph/terms.py backend/app/services/profile_service.py backend/scripts/clean_profiles.py backend/tests/test_profile_terms.py "docs/使用手册.md" "docs/使用手册-图谱与画像.md" "技术栈规范.md"
git commit -m "fix: 冷记忆分词修复（画像术语层 + 旧数据清洗 + 文档 v1.131）"
```

- [ ] **Step 2: 写失败测试 `backend/tests/test_profile_refresh.py`**

```python
"""「重新生成画像」：暖主题重算 + 冷画像清洗（v1.132 spec §2.1）。"""
from app.core.database import SessionLocal
from app.services.profile_service import (
    COLD, HOT, WARM, _save, get_all_profiles, refresh_profiles,
)


def _seed(db):
    _save(db, WARM, "default", {
        "recent_books": [{
            "book_id": 1, "title": "甲", "archived_at": "2026-08-11T00:00:00",
            "summary": "变分法研究泛函极值", "key_points": ["线性代数核心"],
        }],
        "related_books": [],
        "themes": {"定义": 100.0, "的稳": 50.0, "系统": 55.0, "质点": 44.0},
        "archived_count": 3,
    })
    _save(db, COLD, "default", {
        "domain_preferences": {"定义": 515.0, "任意": 234.0, "的稳": 22.0, "Hilbert": 5.0},
        "long_term_interests": ["实分析", "的稳"],
    })
    _save(db, HOT, "current", {
        "current_book_id": 7, "current_title": "热书", "progress": 0.5,
        "chapter_titles": [], "highlights": [], "questions": [],
    })


def test_refresh_rebuilds_warm_themes_and_cleans_cold():
    db = SessionLocal()
    try:
        _seed(db)
        hot_before = get_all_profiles(db)["hot"]
        stats = refresh_profiles(db)
        profiles = get_all_profiles(db)
        warm, cold = profiles["warm"], profiles["cold"]
        # 暖主题按近期书原文重算（不再含脏词/旧累积）
        assert "定义" not in warm["themes"] and "的稳" not in warm["themes"]
        assert "变分" in warm["themes"] and "泛函" in warm["themes"]
        # 冷画像脏词剔除、手动整词保留
        assert "定义" not in cold["domain_preferences"] and "任意" not in cold["domain_preferences"]
        assert cold["domain_preferences"].get("Hilbert") == 5.0
        assert cold["long_term_interests"] == ["实分析"]
        # 热画像不变
        assert profiles["hot"] == hot_before
        # 统计字段齐全
        assert stats["themes_before"] == 4 and stats["themes_after"] > 0
        assert stats["cold_before"] == 4
        assert stats["removed_sample"]
    finally:
        db.close()


def test_refresh_empty_profiles_ok():
    db = SessionLocal()
    try:
        stats = refresh_profiles(db)
        assert stats["themes_before"] == 0 and stats["themes_after"] == 0
        assert stats["cold_before"] == 0 and stats["cold_after"] == 0
    finally:
        db.close()


def test_refresh_idempotent_second_run_no_change():
    db = SessionLocal()
    try:
        _seed(db)
        refresh_profiles(db)
        stats2 = refresh_profiles(db)
        assert stats2["themes_before"] == stats2["themes_after"]
        assert stats2["cold_before"] == stats2["cold_after"]
    finally:
        db.close()
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_profile_refresh.py -q -p no:cacheprovider
```
Expected: `FAILED ... cannot import name 'refresh_profiles'`

- [ ] **Step 4: 实现 `refresh_profiles`（`profile_service.py` 顶部常量 + 函数）**

```python
PROFILE_REFRESH_TOP_N = 40  # 重新生成画像：暖主题聚合上限（v1.132）


def refresh_profiles(db: Session) -> dict:
    """重新生成画像（v1.132）：暖主题按近期书+相关书重算，冷画像脏词清洗；不清空任何层。"""
    warm = get_warm(db)
    cold = get_cold(db)

    texts: list[str] = []
    for group in ("recent_books", "related_books"):
        for item in warm.get(group) or []:
            if not isinstance(item, dict):
                continue
            if item.get("summary"):
                texts.append(str(item["summary"]))
            kps = item.get("key_points") or []
            if isinstance(kps, list):
                texts.extend(str(k) for k in kps)
            else:
                texts.append(str(kps))
    themes_before = dict(warm.get("themes") or {})
    warm["themes"] = (
        {k: float(v) for k, v in extract_profile_terms(" ".join(texts), PROFILE_REFRESH_TOP_N).items()}
        if texts else {}
    )

    prefs_before = dict(cold.get("domain_preferences") or {})
    interests_before = list(cold.get("long_term_interests") or [])
    cold["domain_preferences"] = sanitize_profile_term_freq(
        {str(k): float(v) for k, v in prefs_before.items()}
    )
    if interests_before:
        cold["long_term_interests"] = list(
            sanitize_profile_term_freq({str(t): 1.0 for t in interests_before})
        )

    removed = sorted(set(themes_before) - set(warm["themes"]), key=lambda k: -float(themes_before.get(k, 0)))[:12]
    _save(db, WARM, "default", warm)
    _save(db, COLD, "default", cold)
    return {
        "themes_before": len(themes_before),
        "themes_after": len(warm["themes"]),
        "cold_before": len(prefs_before),
        "cold_after": len(cold["domain_preferences"]),
        "interests_before": len(interests_before),
        "interests_after": len(cold["long_term_interests"]),
        "removed_sample": removed,
    }
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_profile_refresh.py -q -p no:cacheprovider
```
Expected: `3 passed`

- [ ] **Step 6: ruff + 提交**

```bash
cd backend && .\.venv\Scripts\python.exe -m ruff check --no-cache app/services/profile_service.py tests/test_profile_refresh.py
git add backend/app/services/profile_service.py backend/tests/test_profile_refresh.py
git commit -m "feat: refresh_profiles 服务函数（暖主题重算 + 冷画像清洗，v1.132）"
```

### Task 2: 路由 `POST /api/profile/refresh`

**Files:**
- Modify: `backend/app/api/routes/profile.py`

- [ ] **Step 1: 加路由**（文件顶部 import 区加 `refresh_profiles`；`reset_profile` 附近加函数）

```python
@router.post("/profile/refresh")
def refresh_profile(db: Session = Depends(get_db)):
    """重新生成画像（v1.132）：暖主题重算 + 冷画像清洗，不清空任何层。"""
    stats = refresh_profiles(db)
    return ok(stats, "画像已重新生成")
```

- [ ] **Step 2: 跑既有画像测试确认无回归**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_profile.py tests/test_profile_refresh.py -q -p no:cacheprovider
```
Expected: `23 passed`

- [ ] **Step 3: 提交**

```bash
git add backend/app/api/routes/profile.py
git commit -m "feat: POST /api/profile/refresh 路由（v1.132）"
```

### Task 3: 前端按钮

**Files:**
- Modify: `frontend/src/api/profile.ts`、`frontend/src/types.ts`、`frontend/src/views/ProfileView.vue`

- [ ] **Step 1: types.ts 加统计类型**

```typescript
/** 重新生成画像统计（v1.132）。 */
export interface ProfileRefreshStats {
  themes_before: number
  themes_after: number
  cold_before: number
  cold_after: number
  interests_before: number
  interests_after: number
  removed_sample: string[]
}
```

- [ ] **Step 2: api/profile.ts 加函数**

```typescript
/** 重新生成画像（清洗脏词 + 按近期阅读重算暖主题，不清空）。 */
export function refreshProfile(): Promise<ProfileRefreshStats> {
  return post<ProfileRefreshStats>('/profile/refresh')
}
```

- [ ] **Step 3: ProfileView.vue 加按钮与处理函数**

模板头部按钮组（「🔄 刷新」与「重置画像」之间）：
```html
<el-button size="small" type="primary" plain :loading="busy" @click="onRebuild">🔃 重新生成</el-button>
```
script（import 加 `refreshProfile`；`onReset` 前加函数）：
```typescript
async function onRebuild() {
  try {
    await ElMessageBox.confirm('将清洗画像脏词并按近期阅读重新生成暖主题，不会清空任何层？', '重新生成画像', { type: 'warning' })
  } catch {
    return
  }
  busy.value = true
  try {
    const stats = await refreshProfile()
    await refresh()
    ElMessage.success(`画像已重新生成：暖主题 ${stats.themes_before} → ${stats.themes_after}，冷画像 ${stats.cold_before} → ${stats.cold_after}`)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}
```

- [ ] **Step 4: 前端构建验证**

```bash
cd frontend && node node_modules\vite\bin\vite.js build 2>&1 | Select-Object -Last 5
```
Expected: `✓ built in ...`

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/profile.ts frontend/src/types.ts frontend/src/views/ProfileView.vue
git commit -m "feat: 画像页「重新生成画像」按钮（v1.132）"
```

### Task 4: 文档登记

**Files:**
- Modify: `docs/使用手册-图谱与画像.md`、`docs/使用手册.md`、`docs/superpowers/specs/2026-08-11-profile-refresh-design.md`（状态改已实施）

- [ ] **Step 1: 分册 §11.1 表格加行 + §11.2 API 列表加行**

§11.1 表格加：
```
| `refresh_profiles(db)` | 重新生成画像（v1.132）：暖主题按 recent_books+related_books 重算（`extract_profile_terms`，`PROFILE_REFRESH_TOP_N=40`）、冷画像 `sanitize_profile_term_freq` 清洗；热画像不动、不清空任何层；返回前后统计 | 前端「🔃 重新生成」按钮调用；幂等（第二次统计变化≈0） |
```
§11.2 列表加：
```
- `POST /profile/refresh`：重新生成画像（暖主题重算 + 冷画像清洗，返回前后统计）。
```

- [ ] **Step 2: 总纲变更记录 v1.132（置顶）+ 版本号**

```markdown
# 使用手册（总纲 v1.132）
| v1.132 | 2026-08-11 | 「重新生成画像」功能（spec: docs/superpowers/specs/2026-08-11-profile-refresh-design.md） | ① 后端 `refresh_profiles` + `POST /api/profile/refresh`：暖主题按近期书+相关书重算（画像术语层 `extract_profile_terms`，修正历史过度累积）、冷画像脏词清洗（`sanitize_profile_term_freq`），热画像不动/不清空任何层/幂等收敛/失败安全；② 前端画像页「🔃 重新生成」按钮（确认 + 统计提示）；③ 测试 3 项新增（test_profile_refresh.py，含幂等/空画像/热画像不变）；验证：后端 pytest + ruff、前端 vite build；同步 分册 图谱 §11.1/§11.2 |
```

- [ ] **Step 3: spec 状态改已实施 + 提交**

```bash
git add "docs/使用手册.md" "docs/使用手册-图谱与画像.md" "docs/superpowers/specs/2026-08-11-profile-refresh-design.md"
git commit -m "docs: 「重新生成画像」功能登记（手册 v1.132）"
```

### Task 5: 收尾验证

- [ ] **Step 1: 后端全量 + ruff**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp E:\python\LLMnotebook\.pytest_tmp_pf
```
Expected: 全量通过（≥295）

- [ ] **Step 2: 汇报（含剩余未提交的上轮文档改动说明）**
