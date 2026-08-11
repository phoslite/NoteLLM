<template>
  <div class="profile-page">
    <!-- 顶部工具栏 -->
    <header class="page-head">
      <div class="head-left">
        <h2>
          <span class="title-ico">👤</span>
          <span>读者画像</span>
        </h2>
        <p class="head-sub">三层画像随阅读行为自动维护：热（当前书细节）→ 暖（近 1~2 本 + 相关领域）→ 冷（长期偏好）</p>
      </div>
      <div class="head-actions">
        <el-button size="small" :loading="busy" @click="refresh">🔄 刷新</el-button>
        <el-button size="small" type="primary" plain :loading="busy" @click="onRebuild">🔃 重新生成</el-button>
        <el-button size="small" type="danger" plain :loading="busy" @click="onReset">重置画像</el-button>
      </div>
    </header>

    <!-- 统计卡片 -->
    <section class="stat-grid">
      <div v-for="s in statCards" :key="s.label" class="stat-card" :style="{ '--sc': s.color }">
        <span class="stat-ico">{{ s.icon }}</span>
        <div class="stat-body">
          <b>{{ s.value }}</b>
          <span>{{ s.label }}</span>
        </div>
      </div>
    </section>

    <!-- 三层画像 -->
    <section class="layers">
      <!-- L1 热画像 -->
      <article class="layer-card layer-hot">
        <header class="layer-head">
          <span class="layer-ico">🔥</span>
          <div class="layer-id">
            <h3>热画像</h3>
            <p>L1 · 当前书细节</p>
          </div>
          <el-tag size="small" type="danger" effect="plain">{{ profiles.hot?.current_title ? '进行中' : '空闲' }}</el-tag>
        </header>
        <div class="layer-body">
          <div v-if="!profiles.hot?.current_book_id" class="layer-empty">
            <span class="empty-ico">📭</span>
            <p>暂无当前书（归档后清空）</p>
          </div>
          <template v-else>
            <div class="kv-grid">
              <div class="kv-item">
                <span>当前书</span>
                <b>{{ profiles.hot.current_title }}</b>
              </div>
              <div class="kv-item">
                <span>阅读进度</span>
                <b>{{ hotProgress }}%</b>
              </div>
            </div>
            <div class="kv-row">
              <span>章节脉络</span>
              <div class="chapter-flow">{{ chapterFlow }}</div>
            </div>
            <div class="kv-grid">
              <div class="kv-item">
                <span>高亮 / 不理解</span>
                <b>{{ (profiles.hot.highlights as unknown[] || []).length }} 条</b>
              </div>
              <div class="kv-item">
                <span>进行中的问题</span>
                <b>{{ (profiles.hot.questions as string[] || []).length }} 个</b>
              </div>
            </div>
          </template>
        </div>
      </article>

      <!-- L2 暖画像 -->
      <article class="layer-card layer-warm">
        <header class="layer-head">
          <span class="layer-ico">🌤️</span>
          <div class="layer-id">
            <h3>暖画像</h3>
            <p>L2 · 近 1~2 本 + 相关领域</p>
          </div>
          <el-tag size="small" type="warning" effect="plain">{{ profiles.warm?.archived_count || 0 }} 本归档</el-tag>
        </header>
        <div class="layer-body">
          <div class="sub-head"><span>📕 近期书目</span><span class="sub-count">{{ recentBooks.length }}</span></div>
          <ul v-if="recentBooks.length" class="book-list">
            <li v-for="r in recentBooks" :key="r.book_id">
              <span class="book-dot warm-dot"></span>
              <span class="book-title">《{{ r.title }}》</span>
              <el-tag v-if="r.key_points?.length" size="small" type="warning" effect="plain">{{ r.key_points.length }} 条要点</el-tag>
            </li>
          </ul>
          <p v-else class="empty">暂无（读完归档后写入）</p>
          <div class="sub-head"><span>📚 相关领域书</span><span class="sub-count">{{ relatedBooks.length }}</span></div>
          <ul v-if="relatedBooks.length" class="book-list">
            <li v-for="r in relatedBooks" :key="r.book_id">
              <span class="book-dot cool-dot"></span>
              <span class="book-title">《{{ r.title }}》</span>
            </li>
          </ul>
          <p v-else class="empty">暂无</p>
        </div>
      </article>

      <!-- L3 冷画像 -->
      <article class="layer-card layer-cold">
        <header class="layer-head">
          <span class="layer-ico">🧊</span>
          <div class="layer-id">
            <h3>冷画像</h3>
            <p>L3 · 长期偏好</p>
          </div>
          <el-button v-if="!coldEditing" size="small" type="primary" plain @click="openColdEdit">✏️ 编辑</el-button>
        </header>
        <div class="layer-body">
          <template v-if="!coldEditing">
            <div class="sub-head"><span>🏷️ 领域偏好</span><span class="sub-count">{{ prefs.length }}</span></div>
            <div v-if="prefs.length" class="tag-cloud">
              <el-tag v-for="[k, v] in prefs" :key="k" size="small" :type="tagTypeOf(v)">{{ k }} ×{{ v }}</el-tag>
            </div>
            <p v-else class="empty">暂无（跨 3 本后沉淀）</p>
            <div class="sub-head"><span>🧭 长期兴趣</span></div>
            <div v-if="interests.length" class="chip-flow">{{ interests.join(' · ') }}</div>
            <p v-else class="empty">—</p>
            <div class="sub-head"><span>🎓 知识水平</span><span class="sub-count">{{ levelLabel(levelValue) }}</span></div>
            <div class="level-row">
              <el-select v-model="levelValue" size="small" style="width: 160px" @change="onLevelChange">
                <el-option v-for="(lab, key) in levelOptions" :key="key" :label="`${lab}（${key}）`" :value="key" />
              </el-select>
              <el-button size="small" :loading="calibrating" @click="onCalibrate">🎯 校准建议</el-button>
            </div>
          </template>
          <template v-else>
            <div class="sub-head"><span>🏷️ 领域偏好（分数 1~10）</span></div>
            <div v-for="(row, i) in coldForm.domains" :key="i" class="cold-edit-row">
              <el-input v-model="row.name" size="small" placeholder="领域名（汉字/英文）" />
              <el-input-number v-model="row.score" :min="1" :max="10" size="small" />
              <el-button size="small" text type="danger" @click="removeColdDomain(i)">删除</el-button>
            </div>
            <el-button size="small" text type="primary" @click="addColdDomain">+ 添加领域</el-button>
            <div class="sub-head"><span>🧭 长期兴趣 / 专业领域</span></div>
            <el-select v-model="coldForm.interests" multiple filterable allow-create default-first-option size="small" placeholder="输入后回车添加" style="width: 100%">
              <el-option v-for="it in coldForm.interests" :key="it" :label="it" :value="it" />
            </el-select>
            <div class="cold-edit-actions">
              <el-button size="small" type="primary" :loading="savingCold" @click="saveColdEdit">保存</el-button>
              <el-button size="small" @click="coldEditing = false">取消</el-button>
            </div>
          </template>
        </div>
      </article>
    </section>

    <!-- 画像阈值 -->
    <section class="panel">
      <header class="panel-head">
        <div>
          <h3>⚙️ 画像阈值</h3>
          <p>系统按跨书节奏自动学习，可手动覆盖</p>
        </div>
      </header>
      <div class="learn-banner">
        <div class="learn-item">
          <span class="learn-label">归档样本</span>
          <el-progress :percentage="pct(learningStats.archive)" :stroke-width="8" :show-text="false" />
          <span class="learn-val">{{ learningStats.archive.cur }} / {{ learningStats.archive.min }}</span>
        </div>
        <div class="learn-item">
          <span class="learn-label">相关度样本</span>
          <el-progress :percentage="pct(learningStats.related)" :stroke-width="8" :show-text="false" />
          <span class="learn-val">{{ learningStats.related.cur }} / {{ learningStats.related.min }}</span>
        </div>
        <div class="learn-item learn-text">
          <span class="learn-label">确认关联</span>
          <span class="learn-val">{{ learningStats.confirmedMin }} 条起参与学习</span>
        </div>
      </div>
      <div class="thr-grid">
        <div class="thr-item">
          <label>暖转冷跨书数</label>
          <el-input-number v-model="thresholdForm.warm_threshold" :min="2" :max="5" size="small" />
          <span class="thr-desc">归档满 N 本暖画像沉淀至冷画像</span>
        </div>
        <div class="thr-item">
          <label>相关度强度阈值</label>
          <el-input-number v-model="thresholdForm.related_strength" :min="45" :max="60" :step="1" size="small" />
          <span class="thr-desc">关联边 ≥ 该强度视为相关领域书（入暖记忆）</span>
        </div>
        <div class="thr-item">
          <label>复习提醒间隔（天）</label>
          <el-input-number v-model="thresholdForm.review_days" :min="1" :max="7" size="small" />
          <span class="thr-desc">归档超过该天数标为建议复习</span>
        </div>
      </div>
      <div class="thr-actions">
        <el-button size="small" type="primary" :loading="savingThresholds" @click="onSaveThresholds">保存阈值</el-button>
        <el-button size="small" :loading="learningThresholds" @click="onLearnThresholds">立即按样本学习</el-button>
        <span v-if="thresholds?.learning?.learned" class="thr-hint">上次学习：{{ thresholds.learning.learned.at || '—' }}</span>
      </div>
    </section>

    <!-- 阅读建议 -->
    <section class="panel">
      <header class="panel-head">
        <div>
          <h3>💡 阅读建议</h3>
          <p>习惯统计 · 薄弱概念 · 复习提醒 · 阅读节奏</p>
        </div>
      </header>
      <div class="rec-stats">
        <div class="rec-stat"><b class="c1">{{ rec?.stats?.archived_books ?? 0 }}</b><span>已归档书</span></div>
        <div class="rec-stat"><b class="c2">{{ rec?.stats?.read_chapters ?? 0 }}</b><span>已读章节</span></div>
        <div class="rec-stat"><b class="c3">{{ rec?.stats?.notes ?? 0 }}</b><span>笔记</span></div>
        <div class="rec-stat"><b class="c4">{{ rec?.stats?.questions ?? 0 }}</b><span>不理解标记</span></div>
        <div class="rec-stat"><b class="c5">{{ rec?.stats?.chat_messages ?? 0 }}</b><span>对话消息</span></div>
      </div>
      <div class="rec-cols">
        <div class="rec-col">
          <div class="sub-head"><span>⚠️ 薄弱概念</span></div>
          <div v-if="weakConcepts.length" class="tag-cloud">
            <el-tag v-for="w in weakConcepts" :key="w.concept" type="warning" size="small">{{ w.concept }} ×{{ w.count }}</el-tag>
          </div>
          <p v-else class="empty">暂无（标记「不理解」后聚合）</p>
        </div>
        <div class="rec-col">
          <div class="sub-head"><span>⏰ 复习提醒</span></div>
          <ul v-if="rec?.review?.length" class="book-list">
            <li v-for="r in rec.review" :key="(r.book_id ?? r.title) as any">
              <span class="book-dot" :class="r.due ? 'due-dot' : 'ok-dot'"></span>
              <span class="book-title">《{{ r.title }}》</span>
              <span class="rec-days">归档 {{ r.days_ago }} 天</span>
              <el-tag v-if="r.due" type="danger" size="small">建议复习</el-tag>
            </li>
          </ul>
          <p v-else class="empty">暂无到期复习</p>
        </div>
      </div>
      <div class="rhythm"><b>阅读节奏：</b>{{ rec?.rhythm?.tip || '—' }}</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getKnowledgeLevelSuggestion, getProfile, getRecommendations, getThresholds, learnProfileThresholds, refreshProfile, resetProfile, saveColdProfile, saveThresholds } from '@/api/profile'
import type { KnowledgeLevelSuggestion, ProfileData, ProfileThresholds, RecommendationsData } from '@/types'

const profiles = ref<ProfileData>({ cold: {}, warm: {}, hot: {} })
const busy = ref(false)
const rec = ref<RecommendationsData | null>(null)
const thresholds = ref<ProfileThresholds | null>(null)
const thresholdForm = ref({ warm_threshold: 3, related_strength: 60, review_days: 1 })
const savingThresholds = ref(false)
const learningThresholds = ref(false)
const coldEditing = ref(false)
const savingCold = ref(false)
const coldForm = ref<{ domains: { name: string; score: number }[]; interests: string[] }>({ domains: [], interests: [] })

const weakConcepts = computed(() => rec.value?.weak_concepts || [])
const recentBooks = computed(() => (profiles.value.warm?.recent_books as any[] || []))
const relatedBooks = computed(() => (profiles.value.warm?.related_books as any[] || []))
const prefs = computed(() => Object.entries((profiles.value.cold?.domain_preferences as Record<string, number>) || {}).slice(0, 12))
const dueReviewCount = computed(() => (rec.value?.review ?? []).filter((r) => r.due).length)
const interests = computed(() => (profiles.value.cold?.long_term_interests as string[] || []))
const levelValue = ref('intermediate')
const calibrating = ref(false)
const baseLevelOptions: Record<string, string> = { beginner: '入门', intermediate: '进阶', advanced: '深入' }
const levelOptions = computed(() => {
  const raw = String(profiles.value.cold?.knowledge_level || '')
  const opts = { ...baseLevelOptions }
  if (raw && !opts[raw]) opts[raw] = raw
  return opts
})
const levelLabel = (v: string) => baseLevelOptions[v] || v || '—'

const hotProgress = computed(() => Math.round((Number(profiles.value.hot?.progress) || 0) * 100))
const chapterFlow = computed(() => ((profiles.value.hot?.chapter_titles as string[] | undefined) || []).join(' → ') || '—')

const statCards = computed(() => [
  { icon: '🔥', label: '热画像', value: profiles.value.hot?.current_title ? 1 : 0, color: 'var(--status-err)' },
  { icon: '🌤️', label: '暖画像归档', value: Number(profiles.value.warm?.archived_count ?? 0), color: 'var(--status-warn)' },
  { icon: '🧊', label: '领域偏好', value: prefs.value.length, color: 'var(--accent)' },
  { icon: '📖', label: '已读章节', value: rec.value?.stats?.read_chapters ?? 0, color: 'var(--status-ok)' },
  { icon: '⏰', label: '建议复习', value: dueReviewCount.value, color: '#9b59b6' },
])

const learningStats = computed(() => {
  const l = thresholds.value?.learning
  return {
    archive: { cur: l?.sample_count ?? 0, min: l?.min_samples ?? 6 },
    related: { cur: l?.related_sample_count ?? 0, min: l?.related_samples_min ?? 6 },
    confirmedMin: l?.confirmed_edges_min ?? 3,
  }
})

function pct(p: { cur: number; min: number }): number {
  return Math.min(100, Math.round((p.cur / Math.max(1, p.min)) * 100))
}

function tagTypeOf(count: number): 'danger' | 'warning' | 'info' {
  return count >= 5 ? 'danger' : count >= 3 ? 'warning' : 'info'
}

async function refresh() {
  const [profileR, recsR, thsR] = await Promise.allSettled([getProfile(), getRecommendations(), getThresholds()])
  if (profileR.status === 'fulfilled') {
    profiles.value = profileR.value
    levelValue.value = String(profiles.value.cold?.knowledge_level || 'intermediate')
  } else {
    ElMessage.warning(`画像加载失败：${(profileR.reason as Error)?.message ?? '未知错误'}`)
  }
  if (recsR.status === 'fulfilled') rec.value = recsR.value
  if (thsR.status === 'fulfilled') {
    thresholds.value = thsR.value
    thresholdForm.value = {
      warm_threshold: thsR.value.warm_threshold,
      related_strength: thsR.value.related_strength,
      review_days: thsR.value.review_days,
    }
  }
}

function openColdEdit() {
  const raw = (profiles.value.cold?.domain_preferences as Record<string, number> | undefined) || {}
  coldForm.value = {
    domains: Object.entries(raw).map(([name, score]) => ({ name, score })),
    interests: [...((profiles.value.cold?.long_term_interests as string[] | undefined) || [])],
  }
  coldEditing.value = true
}

function addColdDomain() {
  coldForm.value.domains.push({ name: '', score: 1 })
}

function removeColdDomain(i: number) {
  coldForm.value.domains.splice(i, 1)
}

async function saveColdEdit() {
  savingCold.value = true
  try {
    const payload: Record<string, number> = {}
    for (const d of coldForm.value.domains) {
      if (d.name.trim()) payload[d.name.trim()] = d.score
    }
    profiles.value.cold = await saveColdProfile({
      domain_preferences: payload,
      long_term_interests: coldForm.value.interests,
    })
    coldEditing.value = false
    ElMessage.success('冷画像已保存')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    savingCold.value = false
  }
}

async function onSaveThresholds() {
  savingThresholds.value = true
  try {
    thresholds.value = await saveThresholds(thresholdForm.value)
    ElMessage.success('画像阈值已保存（后续自动学习将基于新值）')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    savingThresholds.value = false
  }
}

async function onLearnThresholds() {
  learningThresholds.value = true
  try {
    thresholds.value = await learnProfileThresholds()
    thresholdForm.value = {
      warm_threshold: thresholds.value.warm_threshold,
      related_strength: thresholds.value.related_strength,
      review_days: thresholds.value.review_days,
    }
    ElMessage.success('已按归档节奏与确认关联样本重新学习阈值')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    learningThresholds.value = false
  }
}

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

async function onLevelChange(v: string) {
  const prev = levelValue.value
  try {
    profiles.value.cold = await saveColdProfile({ knowledge_level: v })
    ElMessage.success(`知识水平已设为：${levelLabel(v)}`)
  } catch (err) {
    levelValue.value = prev
    ElMessage.error((err as Error).message)
  }
}

async function onCalibrate() {
  calibrating.value = true
  let suggestion: KnowledgeLevelSuggestion
  try {
    suggestion = await getKnowledgeLevelSuggestion()
  } catch (err) {
    ElMessage.error((err as Error).message)
    calibrating.value = false
    return
  }
  calibrating.value = false
  const lines = [
    `建议：<b>${suggestion.levels[suggestion.suggested] || suggestion.suggested}</b>（${suggestion.suggested}），总分 ${suggestion.score} / ${suggestion.max_score}`,
    ...suggestion.signals.map((s) => `· ${s.label}：${s.value}${s.unit}（+${s.points}）`),
  ]
  try {
    await ElMessageBox.confirm(lines.join('<br>'), '🎓 知识水平校准', {
      type: 'info',
      confirmButtonText: '应用建议',
      cancelButtonText: '取消',
      dangerouslyUseHTMLString: true,
    })
  } catch {
    return
  }
  try {
    profiles.value.cold = await saveColdProfile({ knowledge_level: suggestion.suggested })
    levelValue.value = suggestion.suggested
    ElMessage.success(`已按建议更新知识水平：${levelLabel(suggestion.suggested)}`)
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function onReset() {
  try {
    await ElMessageBox.confirm('将清空冷/暖/热三层画像并重新积累？', '重置画像', { type: 'warning' })
  } catch {
    return
  }
  busy.value = true
  try {
    await resetProfile()
    await refresh()
    ElMessage.success('画像已重置')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}

onMounted(refresh)
</script>
<style scoped>
.profile-page { padding: 20px 24px; max-width: 1180px; margin: 0 auto; }

/* 顶部工具栏 */
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.head-left { display: flex; flex-direction: column; gap: 4px; }
.page-head h2 { margin: 0; font-size: 20px; display: flex; align-items: center; gap: 8px; }
.title-ico { font-size: 20px; }
.head-sub { color: var(--text-secondary); font-size: 13px; line-height: 1.6; max-width: 720px; margin: 0; }
.head-actions { display: flex; gap: 8px; }

/* 统计卡片 */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin: 14px 0; }
.stat-card { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--reading-bg); border: 1px solid var(--border-color); border-radius: 12px; box-shadow: 0 1px 4px rgba(0, 0, 0, .03); }
.stat-ico { font-size: 20px; }
.stat-body { display: flex; flex-direction: column; line-height: 1.25; }
.stat-body b { font-size: 19px; color: var(--sc, var(--primary-color)); }
.stat-body span { font-size: 13px; color: var(--text-secondary); }

/* 三层画像 */
.layers { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-bottom: 16px; }
.layer-card { background: var(--reading-bg); border: 1px solid var(--border-color); border-radius: 14px; overflow: hidden; box-shadow: 0 1px 4px rgba(0, 0, 0, .03); }
.layer-hot { border-top: 4px solid var(--status-err); }
.layer-warm { border-top: 4px solid var(--status-warn); }
.layer-cold { border-top: 4px solid var(--accent); }
.layer-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--border-color); }
.layer-ico { width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; background: var(--panel-bg); }
.layer-hot .layer-ico { background: rgba(245, 108, 108, .12); }
.layer-warm .layer-ico { background: rgba(230, 162, 60, .12); }
.layer-cold .layer-ico { background: rgba(64, 158, 255, .12); }
.layer-id { flex: 1; min-width: 0; }
.layer-id h3 { margin: 0; font-size: 15px; }
.layer-id p { margin: 2px 0 0; font-size: 13px; color: var(--text-secondary); }
.layer-body { padding: 12px 16px 14px; }
.layer-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 18px 0; color: var(--text-secondary); }
.layer-empty p { margin: 0; font-size: 13px; }
.empty-ico { font-size: 26px; }

.kv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.kv-item { display: flex; flex-direction: column; gap: 3px; padding: 8px 10px; background: var(--panel-bg); border-radius: 8px; }
.kv-item span { font-size: 13px; color: var(--text-secondary); }
.kv-item b { font-size: 13px; line-height: 1.5; word-break: break-all; }
.kv-row { margin-bottom: 8px; }
.kv-row > span { display: block; font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; }
.chapter-flow { font-size: 13px; line-height: 1.9; background: var(--panel-bg); border-radius: 8px; padding: 8px 10px; word-break: break-all; }

.sub-head { display: flex; align-items: center; justify-content: space-between; margin: 10px 0 6px; font-size: 13px; font-weight: 600; }
.sub-count { font-size: 13px; color: var(--text-secondary); font-weight: 400; }
.book-list { list-style: none; margin: 0 0 4px; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.book-list li { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: var(--panel-bg); border-radius: 8px; font-size: 13px; }
.book-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.warm-dot { background: var(--status-warn); }
.cool-dot { background: var(--accent); }
.due-dot { background: var(--status-err); }
.ok-dot { background: var(--status-ok); }
.book-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rec-days { color: var(--text-secondary); font-size: 13px; }
.tag-cloud { display: flex; flex-wrap: wrap; gap: 6px; }
.chip-flow { font-size: 13px; line-height: 1.9; background: var(--panel-bg); border-radius: 8px; padding: 8px 10px; word-break: break-all; }
.level-row { display: flex; align-items: center; gap: 8px; margin-top: 2px; }
.empty { color: var(--text-secondary); font-size: 13px; margin: 6px 0; }

/* 通用面板（阈值 / 建议） */
.panel { background: var(--reading-bg); border: 1px solid var(--border-color); border-radius: 14px; padding: 14px 18px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0, 0, 0, .03); }
.panel-head { margin-bottom: 10px; }
.panel-head h3 { margin: 0; font-size: 15px; font-weight: 700; }
.panel-head p { margin: 2px 0 0; font-size: 13px; color: var(--text-secondary); }

/* 阈值 */
.learn-banner { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; padding: 12px; margin-bottom: 12px; background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 10px; }
.learn-item { display: flex; flex-direction: column; gap: 6px; }
.learn-label { font-size: 13px; color: var(--text-secondary); }
.learn-val { font-size: 13px; }
.learn-text { justify-content: center; }
.learn-text .learn-val { font-size: 13px; }
.thr-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.thr-item { display: flex; flex-direction: column; gap: 6px; font-size: 13px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--panel-bg); }
.thr-item label { font-size: 13px; font-weight: 600; }
.thr-desc { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.thr-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.thr-hint { color: var(--text-secondary); font-size: 13px; }

/* 阅读建议 */
.rec-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; margin-bottom: 12px; }
.rec-stat { padding: 10px 12px; background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 10px; text-align: center; }
.rec-stat b { display: block; font-size: 18px; }
.rec-stat span { font-size: 13px; color: var(--text-secondary); }
.rec-stat .c1 { color: var(--status-err); }
.rec-stat .c2 { color: var(--status-warn); }
.rec-stat .c3 { color: var(--status-ok); }
.rec-stat .c4 { color: var(--accent); }
.rec-stat .c5 { color: #909399; }
.rec-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.rec-col { min-width: 0; }
.cold-edit-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.cold-edit-row .el-input { flex: 1; }
.cold-edit-row :deep(.el-input-number__decrease), .cold-edit-row :deep(.el-input-number__increase), .thr-item :deep(.el-input-number__decrease), .thr-item :deep(.el-input-number__increase) { min-height: 24px; } /* E2E 五轮 #5：数字步进按钮可点击高度 >= 24px */
.cold-edit-actions { display: flex; gap: 8px; margin-top: 12px; }
.rhythm { padding: 10px 12px; background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 10px; font-size: 13px; line-height: 1.7; margin-top: 12px; }
</style>
