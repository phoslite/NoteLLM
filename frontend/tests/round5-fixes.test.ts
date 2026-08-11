/** 2026-08-11 第 5 轮复审修复回归测试（fix-round5-frontend）：
 * - n1：魔法数字 120000 收口（AI_TEST_TASK_TIMEOUT_MS / HTTP_TIMEOUT_MS），源码无裸字面量残留；
 * - E2E#4：--text-secondary #5f6672 在纯白与浅灰 #f5f6f7 上对比度均 >= 4.5（旧值 #6b7280 在浅灰底 < 4.5）；
 * - E2E#1/#2/#3/#5：观感类修复的 CSS 存在性断言（选择器 + 关键属性），防回归删除；
 * - n2：未使用声明清理后无残留（RagView mergedCount、HomeView 拖拽参数、DoodleToolbar props、ReaderView 解构）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  AI_TEST_TASK_TIMEOUT_MS,
  HTTP_TIMEOUT_MS,
  SSE_IDLE_TIMEOUT_MS,
  TASK_TIMEOUT_MS,
} from '../src/utils/constants'

function read(rel: string): string {
  return readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')
}

/** WCAG 2.x 相对亮度（与 .e2e_logs/r5_common.js luminance 同算法）。 */
function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  const f = (v: number) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4))
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
}
function contrast(fg: string, bg: string): number {
  const [l1, l2] = [luminance(fg), luminance(bg)].sort((a, b) => b - a)
  return (l1 + 0.05) / (l2 + 0.05)
}

describe('n1 · 魔法数字 120000 收口', () => {
  it('constants.ts 定义三类超时常量（值保持既有行为）', () => {
    expect(SSE_IDLE_TIMEOUT_MS).toBe(120000)
    expect(AI_TEST_TASK_TIMEOUT_MS).toBe(120000)
    expect(HTTP_TIMEOUT_MS).toBe(120000)
    expect(TASK_TIMEOUT_MS).toBe(180000)
  })

  it('SettingsView 轮询与 client 传输层不再出现裸 120000', () => {
    const settings = read('views/SettingsView.vue')
    const client = read('api/client.ts')
    expect(settings).not.toMatch(/timeoutMs:\s*120000/)
    expect(settings).toMatch(/timeoutMs:\s*AI_TEST_TASK_TIMEOUT_MS/)
    expect(client).not.toMatch(/timeout:\s*120000/)
    expect(client).toMatch(/timeout:\s*HTTP_TIMEOUT_MS/)
  })
})

describe('E2E#4 · --text-secondary 对比度（#5f6672）', () => {
  it('纯白底与浅灰 #f5f6f7 底均 >= 4.5:1（WCAG AA 正文）', () => {
    const onWhite = contrast('#5f6672', '#ffffff')
    const onLightGray = contrast('#5f6672', '#f5f6f7')
    expect(onWhite).toBeGreaterThanOrEqual(4.5)
    expect(onLightGray).toBeGreaterThanOrEqual(4.5)
    expect(Math.round(onWhite * 100) / 100).toBeGreaterThanOrEqual(5.7) // 注释声称 5.79
    expect(Math.round(onLightGray * 100) / 100).toBeGreaterThanOrEqual(5.3) // 注释声称 5.35
  })

  it('旧值 #6b7280 在浅灰底确实 < 4.5（修复必要性）', () => {
    expect(contrast('#6b7280', '#f5f6f7')).toBeLessThan(4.5)
  })

  it('theme.css 已切换为 #5f6672 且注释比值相符', () => {
    const theme = read('styles/theme.css')
    expect(theme).toContain('--text-secondary: #5f6672')
    expect(theme).toMatch(/白底 5\.79:1/)
    expect(theme).toMatch(/浅灰 #f5f6f7 底 5\.35:1/)
  })
})

describe('E2E#1 · 目录/聊天区横向溢出修复（CSS 存在性）', () => {
  it('目录标题保留省略号三件套（overflow/ellipsis/nowrap）', () => {
    const panel = read('components/ReaderLeftPanel.vue')
    expect(panel).toMatch(/\.chapter-title\s*\{[^}]*overflow:\s*hidden[^}]*text-overflow:\s*ellipsis[^}]*white-space:\s*nowrap/s)
  })

  it('聊天区 Markdown 列表内 KaTeX 允许内部滚动（不再撑破气泡）', () => {
    const panel = read('components/ReaderChatPanel.vue')
    expect(panel).toMatch(/\.chat-content :deep\(\.katex\)\s*\{[^}]*max-width:\s*100%[^}]*overflow-x:\s*auto/s)
  })
})

describe('E2E#2 · 阅读页点击目标 >= 24px（CSS 存在性）', () => {
  it('工具栏小按钮（重提/重建）min-height 24px', () => {
    const rv = read('views/ReaderView.vue')
    expect(rv).toMatch(/\.toolbar-tools \.el-button\s*\{[^}]*min-height:\s*24px/s)
  })

  it('聊天复制按钮 min-height 24px', () => {
    const panel = read('components/ReaderChatPanel.vue')
    expect(panel).toMatch(/\.chat-copy\s*\{[^}]*min-height:\s*24px/s)
  })
})

describe('E2E#5 · ProfileView 数字步进按钮 >= 24px（CSS 存在性）', () => {
  it('el-input-number 增减按钮 min-height 24px 覆盖', () => {
    const pv = read('views/ProfileView.vue')
    expect(pv).toMatch(/:deep\(\.el-input-number__decrease\)[^}]*min-height:\s*24px/s)
    expect(pv).toMatch(/:deep\(\.el-input-number__increase\)[^}]*min-height:\s*24px/s)
  })
})

describe('E2E#3 · /rag/15 分块公式窄容器溢出修复（CSS 存在性）', () => {
  it('MdRender 统一隐藏 KaTeX MathML 分支溢出（窄容器审计口径）', () => {
    const md = read('components/MdRender.vue')
    expect(md).toMatch(/\.md-render :deep\(\.katex-mathml\), \.md-render :deep\(\.katex-mathml \*\)\s*\{\s*overflow:\s*hidden/s)
  })

  it('.chunk-text / .read-area 内 KaTeX 允许内部滚动', () => {
    const rdv = read('views/RagDetailView.vue')
    expect(rdv).toMatch(/\.chunk-text :deep\(\.katex\), \.read-area :deep\(\.katex\)\s*\{[^}]*max-width:\s*100%[^}]*overflow-x:\s*auto/s)
  })
})

describe('n2 · 未使用声明清理后无残留', () => {
  it('RagView 无死函数 mergedCount', () => {
    expect(read('views/RagView.vue')).not.toMatch(/function mergedCount/)
  })

  it('HomeView 拖拽回调无未使用参数 id', () => {
    const hv = read('views/HomeView.vue')
    expect(hv).not.toMatch(/function onDragLeave\(e: DragEvent, id: number\)/)
    expect(hv).toMatch(/@dragleave="onDragLeave\(\$event\)"/)
  })

  it('DoodleToolbar 无未使用 props 绑定', () => {
    expect(read('components/DoodleToolbar.vue')).not.toMatch(/const props = defineProps/)
  })

  it('ReaderView 无未使用解构 onScroll / loadDoodle / scheduleDoodleSave', () => {
    const rv = read('views/ReaderView.vue')
    expect(rv).not.toMatch(/const \{ onScroll,/)
    expect(rv).not.toMatch(/loadDoodle, scheduleDoodleSave/)
  })
})
