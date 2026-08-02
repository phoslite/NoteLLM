<template>
  <div class="profile-page">
    <div class="page-head">
      <h2>读者画像</h2>
      <el-button size="small" type="danger" plain :loading="busy" @click="onReset">重置画像</el-button>
    </div>
    <p class="tip">
      三层画像由系统随阅读行为自动维护：热画像（当前书细节）&gt; 暖画像（近 1~2 本 + 相关领域）&gt; 冷画像（长期偏好）。
      归档跨 1 本热转暖、跨 3 本暖转冷、&gt;3 本全部沉淀冷。
    </p>

    <div class="layer-grid">
      <el-card class="layer-card hot" shadow="never">
        <template #header><b>🔥 热画像</b><span class="layer-sub">当前书细节</span></template>
        <p v-if="!profiles.hot?.current_book_id" class="empty">暂无当前书（归档后清空）</p>
        <template v-else>
          <p class="kv"><b>当前书：</b>{{ profiles.hot.current_title }}</p>
          <p class="kv"><b>进度：</b>{{ Math.round((Number(profiles.hot.progress) || 0) * 100) }}%</p>
          <p class="kv"><b>章节脉络：</b>{{ (profiles.hot.chapter_titles as string[] || []).join(' → ') || '—' }}</p>
          <p class="kv"><b>高亮/不理解：</b>{{ (profiles.hot.highlights as unknown[] || []).length }} 条</p>
          <p class="kv"><b>进行中的问题：</b>{{ (profiles.hot.questions as string[] || []).length }} 个</p>
        </template>
      </el-card>

      <el-card class="layer-card warm" shadow="never">
        <template #header><b>🌤️ 暖画像</b><span class="layer-sub">近 1~2 本 + 相关领域</span></template>
        <p class="kv"><b>已归档：</b>{{ profiles.warm?.archived_count || 0 }} 本</p>
        <p class="kv"><b>近期书目：</b></p>
        <ul v-if="recentBooks.length" class="mini-list">
          <li v-for="r in recentBooks" :key="r.book_id">
            《{{ r.title }}》<span v-if="r.key_points?.length"> · {{ r.key_points.length }} 条要点</span>
          </li>
        </ul>
        <p v-else class="empty">暂无（读完归档后写入）</p>
        <p class="kv"><b>相关领域书：</b></p>
        <ul v-if="relatedBooks.length" class="mini-list">
          <li v-for="r in relatedBooks" :key="r.book_id">《{{ r.title }}》</li>
        </ul>
        <p v-else class="empty">暂无</p>
      </el-card>

      <el-card class="layer-card cold" shadow="never">
        <template #header><b>🧊 冷画像</b><span class="layer-sub">长期偏好</span></template>
        <p class="kv"><b>领域偏好：</b></p>
        <div v-if="prefs.length" class="tag-row">
          <el-tag v-for="[k, v] in prefs" :key="k" size="small">{{ k }} ×{{ v }}</el-tag>
        </div>
        <p v-else class="empty">暂无（跨 3 本后沉淀）</p>
        <p class="kv"><b>长期兴趣：</b>{{ interests.join('、') || '—' }}</p>
      </el-card>
    </div>

    <el-card class="thr-card" shadow="never">
      <template #header><b>⚙️ 画像阈值</b><span class="layer-sub">系统按跨书节奏自动学习，可手动覆盖</span></template>
      <p class="kv">自动学习：归档样本 <b>{{ thresholds?.learning?.sample_count ?? 0 }}</b> 条（≥{{ thresholds?.learning?.min_samples ?? 6 }} 触发调整）、相关度样本 <b>{{ thresholds?.learning?.related_sample_count ?? 0 }}</b> 条（≥{{ thresholds?.learning?.related_samples_min ?? 6 }} 参与相关度阈值学习）、确认关联 <b>{{ thresholds?.learning?.confirmed_edges_min ?? 3 }}</b> 条起参与相关度学习</p>
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
        <span class="thr-hint" v-if="thresholds?.learning?.learned">上次学习：{{ thresholds.learning.learned.at || '—' }}</span>
      </div>
    </el-card>

    <el-card class="rec-card" shadow="never">
      <template #header><b>💡 阅读建议</b><span class="layer-sub">统计 · 薄弱概念 · 复习提醒 · 节奏</span></template>
      <div class="rec-stats">
        <div class="rec-stat"><b>{{ rec?.stats?.archived_books ?? 0 }}</b><span>已归档书</span></div>
        <div class="rec-stat"><b>{{ rec?.stats?.read_chapters ?? 0 }}</b><span>已读章节</span></div>
        <div class="rec-stat"><b>{{ rec?.stats?.notes ?? 0 }}</b><span>笔记</span></div>
        <div class="rec-stat"><b>{{ rec?.stats?.questions ?? 0 }}</b><span>不理解标记</span></div>
        <div class="rec-stat"><b>{{ rec?.stats?.chat_messages ?? 0 }}</b><span>对话消息</span></div>
      </div>
      <p class="kv"><b>薄弱概念：</b></p>
      <div v-if="weakConcepts.length" class="tag-row">
        <el-tag v-for="w in weakConcepts" :key="w.concept" type="warning" size="small">{{ w.concept }} ×{{ w.count }}</el-tag>
      </div>
      <p v-else class="empty">暂无（标记「不理解」后聚合）</p>
      <p class="kv"><b>复习提醒：</b></p>
      <ul v-if="rec?.review?.length" class="mini-list">
        <li v-for="r in rec.review" :key="(r.book_id ?? r.title) as any">
          《{{ r.title }}》归档 {{ r.days_ago }} 天
          <el-tag v-if="r.due" type="danger" size="small">建议复习</el-tag>
        </li>
      </ul>
      <p v-else class="empty">暂无到期复习</p>
      <p class="kv rhythm"><b>阅读节奏：</b>{{ rec?.rhythm?.tip || '—' }}</p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getProfile, getRecommendations, getThresholds, learnProfileThresholds, resetProfile, saveThresholds } from '@/api/profile'
import type { ProfileThresholds } from '@/types'
import type { ProfileData, RecommendationsData } from '@/types'

const profiles = ref<ProfileData>({ cold: {}, warm: {}, hot: {} })
const busy = ref(false)
const rec = ref<RecommendationsData | null>(null)
const thresholds = ref<ProfileThresholds | null>(null)
const thresholdForm = ref({ warm_threshold: 3, related_strength: 60, review_days: 1 })
const savingThresholds = ref(false)
const learningThresholds = ref(false)

const weakConcepts = computed(() => rec.value?.weak_concepts || [])

const recentBooks = computed(() => (profiles.value.warm?.recent_books as any[] || []))
const relatedBooks = computed(() => (profiles.value.warm?.related_books as any[] || []))
const prefs = computed(() => Object.entries((profiles.value.cold?.domain_preferences as Record<string, number>) || {}).slice(0, 12))
const interests = computed(() => (profiles.value.cold?.long_term_interests as string[] || []))

async function refresh() {
  profiles.value = await getProfile()
  rec.value = await getRecommendations()
  thresholds.value = await getThresholds()
  thresholdForm.value = {
    warm_threshold: thresholds.value.warm_threshold,
    related_strength: thresholds.value.related_strength,
    review_days: thresholds.value.review_days,
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
.profile-page { padding: 20px; max-width: 1100px; }
.page-head { display: flex; align-items: center; gap: 16px; }
.tip { color: var(--text-secondary); font-size: 13px; }
.layer-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-top: 12px; }
.layer-card :deep(.el-card__header) { display: flex; align-items: baseline; gap: 8px; font-size: 15px; }
.layer-sub { color: var(--text-secondary); font-size: 12px; }
.kv { margin: 6px 0; font-size: 13px; }
.mini-list { margin: 4px 0 10px 18px; font-size: 13px; }
.empty { color: var(--text-secondary); font-size: 13px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }
.thr-card { margin-top: 16px; }
.thr-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 8px 0; }
.thr-item { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.thr-item label { color: var(--text-secondary); }
.thr-desc { color: var(--text-secondary); font-size: 12px; }
.thr-actions { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.thr-hint { color: var(--text-secondary); font-size: 12px; }
.rec-card { margin-top: 16px; }
.rec-stats { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }
.rec-stat { min-width: 90px; padding: 6px 10px; background: var(--bg-secondary, #f5f7fa); border-radius: 8px; text-align: center; }
.rec-stat b { display: block; font-size: 16px; }
.rec-stat span { font-size: 12px; color: var(--text-secondary); }
.rhythm { padding: 8px 10px; background: var(--bg-secondary, #f5f7fa); border-radius: 8px; }
</style>
