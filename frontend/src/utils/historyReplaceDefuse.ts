/**
 * 规避 Chromium/Edge 窗口恢复缺陷。
 *
 * 背景：Edge/Chromium 中，当页面处于 hidden 状态（窗口最小化或标签页切到后台）时，
 * 页面调用 history.replaceState() 会把已最小化的浏览器窗口重新“恢复”到前台
 * （实测：最小化后约 10~70ms 窗口被 SetForegroundWindow/还原）。
 *
 * 触发链：vue-router 4.6.x 会注册 visibilitychange 监听器（beforeUnloadListener），
 * 在 document.visibilityState 变为 hidden 时调用 history.replaceState() 保存滚动位置，
 * 从而触发上述缺陷，导致阅读器标签页激活时浏览器无法最小化、Win+D 失效。
 *
 * 方案：包装 history.replaceState，当页面处于 hidden 时把调用延迟到页面重新可见后
 * 再执行。滚动位置照常保存（仅延迟），对 vue-router 的滚动恢复功能无实质影响。
 */
export function defuseHiddenReplaceState(): void {
  const originalReplaceState = history.replaceState.bind(history)
  let deferred: Parameters<typeof history.replaceState> | null = null

  history.replaceState = ((...args: Parameters<typeof history.replaceState>) => {
    if (document.visibilityState === 'hidden') {
      deferred = args
      document.addEventListener(
        'visibilitychange',
        () => {
          if (document.visibilityState === 'visible' && deferred) {
            const pending = deferred
            deferred = null
            originalReplaceState(...pending)
          }
        },
        { once: true },
      )
      return
    }
    originalReplaceState(...args)
  }) as typeof history.replaceState
}
