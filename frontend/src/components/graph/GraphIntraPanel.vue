<template>
  <section v-if="intra" class="stat-grid stat-grid-small">
    <div class="stat-card mini"><b>{{ intraStats.chapters }}</b><span>章节</span></div>
    <div class="stat-card mini"><b>{{ intraStats.nodes }}</b><span>知识点</span></div>
    <div class="stat-card mini"><b>{{ intraStats.edges }}</b><span>关系</span></div>
    <div class="stat-card mini">
      <b>{{ Object.values(levelFilter).filter(Boolean).length }}/3</b><span>层级显示</span>
    </div>
  </section>

  <section class="filter-bar">
    <span class="filter-label">知识点层级</span>
    <div class="level-tags">
      <el-check-tag :checked="levelFilter['章节级']" @click="emit('level-toggle', '章节级')">章节级</el-check-tag>
      <el-check-tag :checked="levelFilter['重要段落']" @click="emit('level-toggle', '重要段落')">重要段落</el-check-tag>
      <el-check-tag :checked="levelFilter['用户标记']" @click="emit('level-toggle', '用户标记')">用户标记</el-check-tag>
    </div>
    <span class="count-tip">{{ intra ? `${intra.nodes.length} 个知识点 / ${intra.edges.length} 条关系` : '' }}</span>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntraGraph } from '@/types'

const props = defineProps<{ intra: IntraGraph | null; levelFilter: Record<string, boolean> }>()
const emit = defineEmits<{ (e: 'level-toggle', level: string): void }>()

const intraStats = computed(() => ({
  chapters: props.intra?.chapters.length ?? 0,
  nodes: props.intra?.nodes.length ?? 0,
  edges: props.intra?.edges.length ?? 0,
}))
</script>

<style scoped>
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 10px; margin-bottom: 12px; }
.stat-grid-small { grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); }
.stat-card { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--reading-bg); border: 1px solid var(--border-color); border-radius: 12px; box-shadow: 0 1px 4px rgba(0, 0, 0, .03); }
.stat-card.mini { justify-content: flex-start; padding: 8px 14px; }
.stat-card.mini b { font-size: 17px; }
.stat-body { display: flex; flex-direction: column; line-height: 1.25; }
.stat-body b { font-size: 19px; color: var(--sc, var(--primary-color)); }
.stat-body span { font-size: 13px; color: var(--text-secondary); }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 2px 0 12px; }
.filter-label { color: var(--text-secondary); font-size: 13px; flex-shrink: 0; }
.level-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.count-tip { color: var(--text-secondary); font-size: 13px; margin-left: auto; }
</style>
