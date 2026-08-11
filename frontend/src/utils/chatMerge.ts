/**
 * 会话历史合并（C-I2 修复）：把本地消息与后端历史行合并，避免重复显示。
 *
 * 语义（两个 use*Ai 流式内核共用，为后续抽取 useStreamSession 提供统一缝）：
 * - 按 stream_key 排除「在途流」的 DB 行：流式进行中本地气泡是唯一展示源，
 *   后端滚动落库的部分行不整体加入（否则折叠再展开出现「半截 + 完整」重复）；
 * - 其余已落库行按「角色 + 内容」去重，本地新增消息（local 标记）保留。
 * 返回 [rows（去重过滤）, ...本地 extras]，与 loadChatHistory/loadHistory 原语义兼容。
 */
import type { ChatMessageItem } from '@/types'

export type MergeableMsg = ChatMessageItem & { local?: boolean }

export function mergeChatHistory<T extends MergeableMsg>(local: T[], rows: T[]): T[] {
  const localStreamKeys = new Set(
    local.filter((m) => m.stream_key).map((m) => m.stream_key as string),
  )
  const filteredRows = rows.filter((r) => !r.stream_key || !localStreamKeys.has(r.stream_key))
  const seen = new Set(filteredRows.map((r) => `${r.role}:${r.content}`))
  const extras = local.filter((m) => m.local || !seen.has(`${m.role}:${m.content}`))
  return extras.length ? [...filteredRows, ...extras] : filteredRows
}
