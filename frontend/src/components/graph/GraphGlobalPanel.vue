<template>
  <section v-if="graph" class="stat-grid">
    <div v-for="s in statCards" :key="s.label" class="stat-card" :style="{ '--sc': s.color }">
      <span class="stat-ico">{{ s.icon }}</span>
      <div class="stat-body">
        <b>{{ s.value }}</b>
        <span>{{ s.label }}</span>
      </div>
    </div>
  </section>

  <section class="filter-bar">
    <span class="filter-label">领域筛选</span>
    <div class="cluster-tags">
      <el-check-tag :checked="clusterFilter === ''" @click="emit('cluster-change', '')">全部</el-check-tag>
      <el-check-tag
        v-for="c in graph?.clusters ?? []"
        :key="c.name"
        :checked="clusterFilter === c.name"
        @click="emit('cluster-change', c.name)"
      >
        {{ c.name }}<span class="count-badge">{{ c.book_count }}</span>
      </el-check-tag>
    </div>
    <span v-if="graph && graph.nodes.length === 0" class="empty-tip">暂无书籍，请先导入书籍</span>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { GlobalGraph } from '@/types'

const props = defineProps<{ graph: GlobalGraph | null; clusterFilter: string }>()
const emit = defineEmits<{ (e: 'cluster-change', name: string): void }>()

const globalStats = computed(() => {
  const nodes = props.graph?.nodes ?? []
  const edges = props.graph?.edges ?? []
  return {
    books: nodes.length,
    edges: edges.length,
    clusters: new Set(nodes.map((n) => n.cluster)).size,
    built: nodes.filter((n) => n.graph_built).length,
    directed: edges.filter((e) => e.direction !== '无').length,
  }
})

const statCards = computed(() => [
  { icon: '📚', label: '书籍', value: globalStats.value.books, color: '#409eff' },
  { icon: '🔗', label: '关联', value: globalStats.value.edges, color: '#67c23a' },
  { icon: '➡️', label: '有向传承', value: globalStats.value.directed, color: '#f56c6c' },
  { icon: '🗂️', label: '领域', value: globalStats.value.clusters, color: '#e6a23c' },
  { icon: '✅', label: '已建图谱', value: globalStats.value.built, color: '#9b59b6' },
])
</script>

<style scoped>
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 10px; margin-bottom: 12px; }
.stat-card { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--reading-bg); border: 1px solid var(--border-color); border-radius: 12px; box-shadow: 0 1px 4px rgba(0, 0, 0, .03); }
.stat-ico { font-size: 20px; }
.stat-body { display: flex; flex-direction: column; line-height: 1.25; }
.stat-body b { font-size: 19px; color: var(--sc, var(--primary-color)); }
.stat-body span { font-size: 12px; color: var(--text-secondary); }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 2px 0 12px; }
.filter-label { color: var(--text-secondary); font-size: 13px; flex-shrink: 0; }
.cluster-tags { display: flex; gap: 6px; flex-wrap: wrap; max-height: 76px; overflow-y: auto; }
.count-badge { margin-left: 5px; font-size: 11px; opacity: .7; background: var(--panel-bg); border-radius: 999px; padding: 0 6px; }
.empty-tip { color: var(--text-secondary); font-size: 13px; margin-left: auto; }
</style>
