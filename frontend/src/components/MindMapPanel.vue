<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import type { MindMapNode } from '@/types'
import { escapeHtml } from '@/utils/graphLabel'
import { toPlainDisplayText } from '@/utils/text'

const props = defineProps<{
  tree: MindMapNode | null
  title: string
  loading: boolean
  error: string
  markdown: string
  /** 命中 LLM 结果缓存直接回放（性能优化 §7 决策 5）。 */
  cached?: boolean
}>()
const emit = defineEmits<{
  (e: 'jump', pos: { chapter: number; para: string }): void
  (e: 'insert-note'): void
}>()

const el = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const TYPE_COLOR: Record<string, string> = { 大纲: '#2f6fb0', 细节: '#529b2e', 重要定理: '#e0382e' } // 四轮 MO1：与 theme.css 语义 token 同值（ECharts canvas 不支持 CSS var，用字面量）

function buildTree(node: MindMapNode): Record<string, any> {
  return {
    name: toPlainDisplayText(node.name),
    value: node.nodeType ?? '大纲',
    itemStyle: { color: TYPE_COLOR[node.nodeType ?? '大纲'] },
    ref: node.ref ?? null,
    children: (node.children ?? []).map(buildTree),
  }
}

function render() {
  if (!el.value || !props.tree) return
  if (!chart) chart = echarts.init(el.value)
  chart.setOption(
    {
      tooltip: {
        trigger: 'item',
        triggerOn: 'mousemove',
        formatter: (p: any) => {
          const d = p.data ?? {}
          const ref = d.ref ? `【第${d.ref.chapter}章 第${d.ref.para}段】` : ''
          return `<b>${escapeHtml(String(d.name ?? ''))}</b><br/>类型：${d.value}${ref ? `<br/>出处：${escapeHtml(ref)}` : ''}`
        },
      },
      series: [
        {
          type: 'tree',
          data: [buildTree(props.tree)],
          top: '4%',
          left: '8%',
          bottom: '4%',
          right: '16%',
          symbolSize: 8,
          orient: 'LR',
          initialTreeDepth: 3,
          expandAndCollapse: true,
          label: { position: 'left', verticalAlign: 'middle', align: 'right', fontSize: 12 },
          leaves: { label: { position: 'right', verticalAlign: 'middle', align: 'left' } },
          emphasis: { focus: 'descendant' },
          animationDuration: 400,
          lineStyle: { color: '#bbb' },
        },
      ],
    },
    true,
  )
  chart.off('click')
  chart.on('click', (params: any) => {
    const ref = params.data?.ref
    if (ref && ref.chapter) emit('jump', { chapter: ref.chapter, para: String(ref.para) })
  })
}

function resize() {
  chart?.resize()
}

function copyMarkdown() {
  if (!props.markdown) return
  navigator.clipboard
    .writeText(props.markdown)
    .then(() => ElMessage.success('大纲已复制'))
    .catch(() => ElMessage.error('复制失败'))
}

function downloadMarkdown() {
  if (!props.markdown) return
  const blob = new Blob([props.markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.title || '思维导图'}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function exportPng() {
  if (!chart) return
  const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.title || '思维导图'}.png`
  a.click()
}

onMounted(() => {
  window.addEventListener('resize', resize)
  void nextTick(render)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
watch(
  () => [props.tree, props.loading],
  () => void nextTick(render),
)
</script>

<template>
  <div class="mindmap-panel">
    <div class="mindmap-toolbar">
      <span class="mindmap-title">{{ title || '思维导图' }}</span>
      <span v-if="cached" class="mindmap-cached" title="命中 LLM 结果缓存，未重复调用大模型">已缓存</span>
      <div class="mindmap-actions">
        <button type="button" class="mini-btn" :disabled="!markdown" @click="copyMarkdown">复制大纲</button>
        <button type="button" class="mini-btn" :disabled="!markdown" @click="downloadMarkdown">下载大纲</button>
        <button type="button" class="mini-btn" :disabled="!markdown" @click="emit('insert-note')">插入为批注</button>
        <button type="button" class="mini-btn" :disabled="!tree" @click="exportPng">导出图片</button>
      </div>
    </div>
    <div class="mindmap-legend">
      <span><i class="dot" style="background:#2f6fb0"></i>大纲</span>
      <span><i class="dot" style="background:#529b2e"></i>细节</span>
      <span><i class="dot" style="background:#e0382e"></i>重要定理</span>
      <span class="legend-tip">点击节点可跳转原文</span>
    </div>
    <div v-if="loading" class="mindmap-tip">生成中…（大章节可能需要几十秒，请稍候）</div>
    <div v-else-if="error" class="mindmap-tip error">{{ error }}</div>
    <div v-else-if="!tree" class="mindmap-tip">点击「脑图」为当前章节生成思维导图</div>
    <div v-else ref="el" class="mindmap-canvas"></div>
  </div>
</template>

<style scoped>
.mindmap-panel { display: flex; flex-direction: column; height: 100%; }
.mindmap-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; gap: 8px; }
.mindmap-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mindmap-cached { font-size: 11px; color: var(--primary-color); border: 1px solid var(--primary-color); border-radius: 4px; padding: 0 6px; opacity: 0.85; flex: none; }
.mindmap-actions { display: flex; gap: 6px; flex: none; flex-wrap: wrap; }
.mindmap-legend { display: flex; gap: 14px; align-items: center; font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; flex-wrap: wrap; }
.mindmap-legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
.mindmap-legend .legend-tip { margin-left: auto; color: #909399; }
.mindmap-canvas { flex: 1; min-height: 380px; }
.mindmap-tip { color: var(--text-secondary); padding: 40px 0; text-align: center; }
.mindmap-tip.error { color: var(--status-err); }
.mini-btn { border: 1px solid var(--border-color); background: transparent; border-radius: 4px; padding: 5px 10px; font-size: 13px; cursor: pointer; min-height: 24px; display: inline-flex; align-items: center; }
.mini-btn:hover:not(:disabled) { border-color: var(--primary-color); color: var(--primary-color); }
.mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
