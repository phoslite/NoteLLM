import type { AiSettings } from '@/types'
import { get, patch, post } from './client'

export function getAiSettings() {
  return get<AiSettings>('/settings/ai')
}

export function saveAiSettings(body: Partial<AiSettings>) {
  return patch<AiSettings>('/settings/ai', body)
}

/** 测试连接（后台任务）：不传 body 时使用当前已保存配置，传 body 时用临时覆盖值测试；返回 task_id 供轮询。 */
export function testAiSettings(body?: Partial<AiSettings>) {
  return post<{ task_id: string }>('/settings/ai/test', body ?? {})
}

/** 强制载入 .env 配置文件：后端以 .env 当前内容为准重置运行时 AI/视觉配置，返回掩码视图。 */
export function reloadEnvSettings() {
  return post<AiSettings>('/settings/ai/reload-env')
}

/** 测试多模态视觉连接（后台任务）：用视觉配置发起最小请求，返回 task_id 供轮询。 */
export function testVisionAiSettings(body?: Partial<AiSettings>) {
  return post<{ task_id: string }>('/settings/ai/test-vision', body ?? {})
}

/** 测试挑选器连接（后台任务）：用挑选器配置（未填项回退主模型）发起最小请求，返回 task_id 供轮询。 */
export function testSelectorAiSettings(body?: Partial<AiSettings>) {
  return post<{ task_id: string }>('/settings/ai/test-selector', body ?? {})
}
