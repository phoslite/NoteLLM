/**
 * 流式会话共享常量与纯函数（MO3 抽取，第 6 轮）：
 * 原 useReaderAi.ts / useGlobalAi.ts 各自内联重复的常量组与 hasUnclosedMath 收敛于此，
 * useStreamSession 内核与未来第三个流式调用方（如主页搜索 AI/新面板）共用。
 * 抽取保持逐字节语义，未改任何值。
 */

/** 渲染节流（手册 §18）：每 80ms 批量刷出一次；公式未闭合时最多等待 500ms 再强制刷出。 */
export const FLUSH_INTERVAL_MS = 80
/** 公式未闭合时最多推迟刷出的等待时长（ms）：避免流式中 KaTeX 闪错。 */
export const MATH_MAX_WAIT_MS = 500
/** 方案2：流式期间固定频率轮询历史（SSE 静默/丢失时自动补增量，无需刷新）。 */
export const POLL_INTERVAL_MS = 2000
/** 思考过程渲染节流（thinking 事件可能高频小片）。 */
export const THINKING_FLUSH_MS = 150
/** SSE 活跃守卫（ms）：距最近一次 SSE 事件不足该时长时不做 DB 补差轮询（审查 I-2，防尾部重放重复）。 */
export const SSE_ACTIVE_GUARD_MS = 500

/** 检测缓冲区尾部是否有未闭合的 $$…$$ 或 $…$（避免流式中 KaTeX 闪错）。
 *  P3-6：统计前剔除转义 `\$`，避免转义美元被误判为未闭合。 */
export function hasUnclosedMath(text: string): boolean {
  const plain = text.replace(/\\\$/g, '')
  const blockPairs = (plain.match(/\$\$/g) ?? []).length
  const inlineDollars = (plain.replace(/\$\$/g, '').match(/\$/g) ?? []).length
  return blockPairs % 2 === 1 || inlineDollars % 2 === 1
}

/** 用户主动中断判定：fetch/SSE abort 抛 DOMException AbortError（调用方静默，不弹错误横幅）。 */
export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

/** 会话/流式键生成（原两个内核各自内联的 crypto.randomUUID 兜底表达式，语义不变）。 */
export function uuid(): string {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}