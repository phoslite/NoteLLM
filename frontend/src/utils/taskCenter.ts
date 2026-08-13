/** 任务中心轮询循环控制器（P2-1 修复）：关闭竞态守卫 + 生命周期清理，纯逻辑可单测。
 *
 * 竞态背景：closePanel 后仍有在途 poll 在飞，其返回结果（pushRecent/visible=true）
 * 会把刚关闭的面板重新打开。本控制器保证：stop() 之后在途 poll 的结果被丢弃、
 * 不再继续轮询；重新 start()（任务提交事件驱动）可恢复。
 */

export interface PollLoopHandlers<T> {
  /** 单次轮询：返回是否还有更多（true 则 sleep 后继续）与本次结果数据。 */
  poll: () => Promise<{ more: boolean; data: T }>
  /** 结果消费回调（仅在循环未被 stop 时调用）。 */
  onData: (data: T) => void
  /** 两轮之间的等待（注入便于测试提速）。 */
  sleep: (ms: number) => Promise<void>
  /** 自然停止回调（无更多任务或轮询失败时触发；用户 stop() 不触发）。 */
  onIdle?: () => void
}

export interface PollLoop {
  /** 启动/恢复轮询（已在跑时忽略）。 */
  start: () => void
  /** 停止轮询：在途 poll 返回后结果被丢弃，循环退出。 */
  stop: () => void
}

export function createPollLoop<T>(handlers: PollLoopHandlers<T>): PollLoop {
  let running = false
  let stopped = false
  // stop 退场期间又收到 start（如关闭面板瞬间新任务事件到达）：退场后补启动。
  // stop() 会清掉该标记——最新用户意图优先（stop→start→stop 最终保持停止）。
  let pendingStart = false

  async function run() {
    let idle = false // 自然停止（无更多任务/轮询失败）标记：stop() 退场不算
    while (!stopped) {
      let result: { more: boolean; data: T }
      try {
        result = await handlers.poll()
      } catch {
        idle = true
        break // 单次轮询失败静默退出（与组件原 catch→false 语义一致）
      }
      if (stopped) break // 轮询期间被 stop：丢弃本次结果
      try {
        handlers.onData(result.data)
      } catch {
        idle = true
        break // P3-3：onData 抛错视为单次轮询失败，静默退出（running 必须释放，防楔死）
      }
      if (!result.more) {
        idle = true
        break
      }
      await handlers.sleep(1000)
    }
    running = false
    if (idle && !stopped) handlers.onIdle?.() // P3-3：stop() 后不触发 onIdle（仅自然停止触发）
    if (pendingStart) start() // 退场期间的新 start 请求：补启动
  }

  function start() {
    if (running && !stopped) return // 正常轮询中，忽略重复 start
    if (running) {
      pendingStart = true // 停止退场中：标记退场后补启动
      return
    }
    stopped = false
    pendingStart = false
    running = true
    void run()
  }

  function stop() {
    stopped = true
    pendingStart = false
  }

  return { start, stop }
}