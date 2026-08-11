/** 全局常量收敛（四轮审查 m10）：魔法数字下沉为命名常量，统一注释与后端任务 TTL 对齐。 */

/** 后台任务最长轮询等待（ms）：与后端任务 TTL/清理周期对齐（RagView/RagDetailView/useReaderArchive）。 */
export const TASK_TIMEOUT_MS = 180000

/** SSE 空闲超时（ms）：无新数据达到该时长即中断（收到数据会重置，见 streamSse）。 */
export const SSE_IDLE_TIMEOUT_MS = 120000

/** 设置页 AI 连接测试任务最长轮询等待（ms）：与后端 ai_timeout/vision_timeout 120s 对齐（五轮审查 n1 收口）。 */
export const AI_TEST_TASK_TIMEOUT_MS = 120000

/** HTTP 传输层请求超时（ms）：axios 整体超时（含任务型 POST；五轮审查 n1 收口）。 */
export const HTTP_TIMEOUT_MS = 120000