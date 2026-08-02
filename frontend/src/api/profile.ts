import type { ProfileData, ProfileThresholds, RecommendationsData } from '@/types'
import { get, patch, post } from './client'

/** 读取三层画像（冷/暖/热）。 */
export function getProfile() {
  return get<ProfileData>('/profile')
}

/** 重置三层画像（清空重新积累）。 */
export function resetProfile() {
  return post<null>('/profile/reset')
}

/** 读取阅读建议（习惯统计 / 薄弱概念 / 复习提醒 / 阅读节奏）。 */
export function getRecommendations() {
  return get<RecommendationsData>('/profile/recommendations')
}

/** 读取画像阈值与学习状态（需求 3.4.1）。 */
export function getThresholds() {
  return get<ProfileThresholds>('/profile/thresholds')
}

/** 手动覆盖画像阈值。 */
export function saveThresholds(payload: Partial<Pick<ProfileThresholds, 'warm_threshold' | 'related_strength' | 'review_days'>>) {
  return patch<ProfileThresholds>('/profile/thresholds', payload)
}

/** 立即按归档节奏/确认关联样本重新学习画像阈值。 */
export function learnProfileThresholds() {
  return post<ProfileThresholds>('/profile/learn')
}