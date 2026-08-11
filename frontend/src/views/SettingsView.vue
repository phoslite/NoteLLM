<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAiSettings, reloadEnvSettings, saveAiSettings, testAiSettings, testSelectorAiSettings, testVisionAiSettings } from '@/api/settings'
import type { AiSettings } from '@/types'
import { notifyTaskSubmitted, waitForTask } from '@/utils/task'
import { AI_TEST_TASK_TIMEOUT_MS } from '@/utils/constants'

const loading = ref(false)
const testing = ref(false)
const visionTesting = ref(false)
const selectorTesting = ref(false)
const reloadingEnv = ref(false)
const activeTab = ref('text')
const form = reactive<AiSettings>({
  base_url: '',
  api_key: '',
  api_key_set: false,
  model: '',
  mode: 'responses',
  timeout: 120,
  verify_ssl: true,
  enable_body_send: true,
  send_page_image: false,
  temperature: null,
  max_tokens: null,
  thinking_type: '',
  reasoning_effort: '',
  top_p: null,
  frequency_penalty: null,
  presence_penalty: null,
  stop: '',
  vision_base_url: '',
  vision_api_key: '',
  vision_api_key_set: false,
  vision_model: '',
  vision_timeout: 120,
  vision_verify_ssl: true,
  vision_max_tokens: 4096,
  vision_temperature: null,
  vision_top_p: null,
  vision_frequency_penalty: null,
  vision_presence_penalty: null,
  vision_enable_thinking: false,
  vision_thinking_budget: null,
  rag_select_enabled: true,
  rag_select_base_url: '',
  rag_select_api_key: '',
  rag_select_api_key_set: false,
  rag_select_model: '',
  rag_select_mode: '',
  rag_select_timeout: 60,
  rag_select_verify_ssl: true,
  rag_select_max_tokens: 512,
  rag_select_temperature: 0,
  rag_select_thinking_type: 'disabled',
  rag_select_reasoning_effort: '',
  rag_select_max_books: 3,
  rag_select_max_skills: 2,
  rag_select_cache_ttl_minutes: 60,
})

type FieldType = 'text' | 'password' | 'number' | 'switch' | 'select'

interface FieldDef {
  key: string
  label: string
  type: FieldType
  section: string
  placeholder?: string
  tip?: string
  options?: { label: string; value: string }[]
  min?: number
  max?: number
  step?: number
  clearable?: boolean
  wide?: boolean
}

const textFields: FieldDef[] = [
  { key: 'base_url', label: 'Base URL', type: 'text', section: '连接信息', placeholder: '基础地址或完整接口 URL', tip: '两种写法：① 基础地址（如 https://api.deepseek.com 或 https://host/v1），按接口模式自动补全（chat→/v1/chat/completions、responses→/v1/responses、anthropic→/v1/messages）；② 完整接口 URL（如 https://host/v1/chat/completions），直接使用不再补全', wide: true },
  { key: 'api_key', label: 'API Key', type: 'password', section: '连接信息' },
  { key: 'model', label: '模型', type: 'text', section: '连接信息', placeholder: '如 deepseek-v4-flash / gpt-4o-mini' },
  { key: 'mode', label: '接口模式', type: 'select', section: '连接信息', options: [{ label: 'responses（instructions/input）', value: 'responses' }, { label: 'chat（messages）', value: 'chat' }, { label: 'anthropic（Messages API）', value: 'anthropic' }] },
  { key: 'timeout', label: '超时（秒）', type: 'number', section: '连接信息', min: 5, max: 600 },
  { key: 'verify_ssl', label: '校验 SSL', type: 'switch', section: '连接信息' },
  { key: 'temperature', label: '温度', type: 'number', section: '采样参数', min: 0, max: 2, step: 0.1, tip: 'DeepSeek 思考模式下不生效（官方：设置不报错也不生效）' },
  { key: 'max_tokens', label: '生成上限', type: 'number', section: '采样参数', min: 256, max: 65536, step: 512, tip: 'max_tokens：DeepSeek 默认 32K、最大 64K，含思考 token（chat 模式）' },
  { key: 'top_p', label: 'Top P', type: 'number', section: '采样参数', min: 0, max: 1, step: 0.05 },
  { key: 'frequency_penalty', label: '频率惩罚', type: 'number', section: '采样参数', min: -2, max: 2, step: 0.1 },
  { key: 'presence_penalty', label: '存在惩罚', type: 'number', section: '采样参数', min: -2, max: 2, step: 0.1 },
  { key: 'stop', label: '停止词', type: 'text', section: '采样参数', placeholder: '多个用英文逗号分隔，如 结论,总结', tip: 'chat 模式；留空不传', wide: true },
  { key: 'thinking_type', label: '思考模式', type: 'select', section: '思考模式', clearable: true, placeholder: '默认（不传）', options: [{ label: '开启思考', value: 'enabled' }, { label: '关闭思考', value: 'disabled' }], tip: 'DeepSeek thinking.type；V4 模型默认开启（chat 模式）' },
  { key: 'reasoning_effort', label: '推理强度', type: 'select', section: '思考模式', clearable: true, placeholder: '默认（不传）', options: [{ label: 'low', value: 'low' }, { label: 'medium', value: 'medium' }, { label: 'high', value: 'high' }, { label: 'max', value: 'max' }], tip: 'DeepSeek reasoning_effort；关闭思考时不要同时设置' },
  { key: 'enable_body_send', label: '发送书籍正文', type: 'switch', section: '隐私与附件', tip: '隐私开关：关闭后不向模型发送书籍正文，仅用元信息与问题' },
  { key: 'send_page_image', label: '发送页面图片', type: 'switch', section: '隐私与附件', tip: '扫描版 PDF：提问时附带当前页图片作为附件（需模型支持视觉输入，chat 模式）' },
]

const visionFields: FieldDef[] = [
  { key: 'vision_base_url', label: 'Base URL', type: 'text', section: '连接信息', placeholder: '基础地址或完整接口 URL', tip: '两种写法：① 基础地址（如 https://api.siliconflow.cn/v1），自动补全 /chat/completions；② 完整接口 URL（如 https://host/v1/chat/completions），直接使用不再补全', wide: true },
  { key: 'vision_api_key', label: 'API Key', type: 'password', section: '连接信息' },
  { key: 'vision_model', label: '模型', type: 'text', section: '连接信息', placeholder: '如 Qwen/Qwen2.5-VL-72B-Instruct / deepseek-ai/DeepSeek-OCR' },
  { key: 'vision_timeout', label: '超时（秒）', type: 'number', section: '连接信息', min: 5, max: 600 },
  { key: 'vision_verify_ssl', label: '校验 SSL', type: 'switch', section: '连接信息' },
  { key: 'vision_max_tokens', label: '生成上限', type: 'number', section: '采样参数', min: 256, max: 32768, step: 256, tip: 'SiliconFlow 建议设置 max_tokens（预留上下文余量）' },
  { key: 'vision_temperature', label: '温度', type: 'number', section: '采样参数', min: 0, max: 2, step: 0.1, tip: 'SiliconFlow 参数；若开启思考模式则可能不生效' },
  { key: 'vision_top_p', label: 'Top P', type: 'number', section: '采样参数', min: 0, max: 1, step: 0.05 },
  { key: 'vision_frequency_penalty', label: '频率惩罚', type: 'number', section: '采样参数', min: -2, max: 2, step: 0.1 },
  { key: 'vision_presence_penalty', label: '存在惩罚', type: 'number', section: '采样参数', min: -2, max: 2, step: 0.1 },
  { key: 'vision_enable_thinking', label: '思考模式', type: 'switch', section: '思考模式', tip: 'SiliconFlow enable_thinking（DeepSeek/Zhipu 系推理模型）；Qwen 等非推理模型勿开' },
  { key: 'vision_thinking_budget', label: '思维链上限', type: 'number', section: '思考模式', min: 256, max: 65536, step: 256, tip: 'SiliconFlow thinking_budget，仅推理模型使用' },
]

const selectorFields: FieldDef[] = [
  { key: 'rag_select_enabled', label: '启用挑选器', type: 'switch', section: '总开关', tip: '总开关：关闭后跳过 LLM 挑选，直接使用规则回退（暖画像 top3 + 谱系 top2 + 关键词）' },
  { key: 'rag_select_base_url', label: 'Base URL', type: 'text', section: '连接信息', placeholder: '留空跟随主模型', tip: '两种写法：① 基础地址（如 https://api.deepseek.com 或 https://host/v1），按接口模式自动补全（chat→/v1/chat/completions、responses→/v1/responses、anthropic→/v1/messages）；② 完整接口 URL，直接使用。留空则复用文本模型配置', wide: true },
  { key: 'rag_select_api_key', label: 'API Key', type: 'password', section: '连接信息' },
  { key: 'rag_select_model', label: '模型', type: 'text', section: '连接信息', placeholder: '留空跟随主模型', tip: '如 deepseek-chat / deepseek-v4-flash；留空则复用文本模型' },
  { key: 'rag_select_mode', label: '接口模式', type: 'select', section: '连接信息', clearable: true, placeholder: '跟随主模型', options: [{ label: '跟随主模型（留空）', value: '' }, { label: 'chat（messages）', value: 'chat' }, { label: 'responses（instructions/input）', value: 'responses' }, { label: 'anthropic（Messages API）', value: 'anthropic' }], tip: 'DeepSeek 官方推荐 chat；responses 需模型与网关支持' },
  { key: 'rag_select_timeout', label: '超时（秒）', type: 'number', section: '连接信息', min: 5, max: 600 },
  { key: 'rag_select_verify_ssl', label: '校验 SSL', type: 'switch', section: '连接信息' },
  { key: 'rag_select_temperature', label: '温度', type: 'number', section: '采样参数', min: 0, max: 2, step: 0.1, tip: '挑选要确定性，默认 0.0；DeepSeek 思考模式下不生效' },
  { key: 'rag_select_max_tokens', label: '生成上限', type: 'number', section: '采样参数', min: 64, max: 8192, step: 64, tip: '挑选输出上限（轻量 JSON 输出，默认 512）' },
  { key: 'rag_select_thinking_type', label: '思考模式', type: 'select', section: '思考模式', clearable: true, placeholder: '默认（不传）', options: [{ label: '关闭思考', value: 'disabled' }, { label: '开启思考', value: 'enabled' }], tip: 'DeepSeek thinking.type；挑选是轻量结构化任务，默认 disabled' },
  { key: 'rag_select_reasoning_effort', label: '推理强度', type: 'select', section: '思考模式', clearable: true, placeholder: '跟随主模型', options: [{ label: '跟随主模型（留空）', value: '' }, { label: 'low', value: 'low' }, { label: 'medium', value: 'medium' }, { label: 'high', value: 'high' }, { label: 'max', value: 'max' }], tip: 'DeepSeek reasoning_effort（chat 模式）；关闭思考时不要同时设置' },
  { key: 'rag_select_max_books', label: '注入书数上限', type: 'number', section: '预算', min: 1, max: 10, tip: '最多注入的书数（含当前书），默认 3' },
  { key: 'rag_select_max_skills', label: 'Skill 数上限', type: 'number', section: '预算', min: 0, max: 10, tip: '最多注入的 Skill 数，默认 2' },
  { key: 'rag_select_cache_ttl_minutes', label: '会话缓存 TTL（分钟）', type: 'number', section: '预算', min: 0, max: 1440, tip: '同一 session_id 的挑选结果缓存时长；0=不缓存，默认 60' },
]

const sectionIcons: Record<string, string> = {
  连接信息: '🔌',
  采样参数: '🎛️',
  思考模式: '🧠',
  隐私与附件: '🔒',
  总开关: '🎚️',
  预算: '💰',
}

function sectionsOf(fields: FieldDef[]) {
  return [...new Set(fields.map((f) => f.section))]
}

function getField(key: string): any {
  return (form as any)[key]
}

function setField(key: string, value: any) {
  ;(form as any)[key] = value
}

function fieldPlaceholder(f: FieldDef): string {
  if (f.key === 'api_key') return form.api_key_set ? '已设置（留空保持不变）' : '请输入 API Key'
  if (f.key === 'vision_api_key') return form.vision_api_key_set ? '已设置（留空保持不变）' : '请输入多模态 API Key'
  if (f.key === 'rag_select_api_key') return form.rag_select_api_key_set ? '已设置（留空保持不变）' : '请输入挑选器 API Key'
  return f.placeholder ?? ''
}

/** API Key 是否已设置（用于「已设置（留空保持不变）」徽标）。 */
function keySet(key: string): boolean {
  if (key === 'api_key') return form.api_key_set
  if (key === 'vision_api_key') return form.vision_api_key_set
  if (key === 'rag_select_api_key') return form.rag_select_api_key_set
  return false
}

const tabs = computed(() => [
  {
    name: 'text',
    label: '文本模型',
    icon: '📝',
    desc: '阅读问答 · 解读 / 概论 / 脑图 · RAG / Skill 总结',
    fields: textFields,
    sections: sectionsOf(textFields),
    testing: testing.value,
    testLabel: '测试文本连接',
    onTest: test,
  },
  {
    name: 'vision',
    label: '多模态视觉模型',
    icon: '🖼️',
    desc: 'PDF 页面信息提取 · 独立于文本 AI，无需额度管理',
    fields: visionFields,
    sections: sectionsOf(visionFields),
    testing: visionTesting.value,
    testLabel: '测试视觉连接',
    onTest: testVision,
  },
  {
    name: 'selector',
    label: '挑选模型',
    icon: '🎯',
    desc: 'AI 自主挑选 RAG / Skill · 未填项自动跟随文本模型',
    fields: selectorFields,
    sections: sectionsOf(selectorFields),
    testing: selectorTesting.value,
    testLabel: '测试挑选连接',
    onTest: testSelector,
  },
])

function toPayload() {
  const payload: Partial<AiSettings> = {
    base_url: form.base_url,
    model: form.model,
    mode: form.mode,
    timeout: form.timeout,
    verify_ssl: form.verify_ssl,
    enable_body_send: form.enable_body_send,
    send_page_image: form.send_page_image,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    thinking_type: form.thinking_type,
    reasoning_effort: form.reasoning_effort,
    top_p: form.top_p,
    frequency_penalty: form.frequency_penalty,
    presence_penalty: form.presence_penalty,
    stop: form.stop,
    vision_base_url: form.vision_base_url,
    vision_model: form.vision_model,
    vision_timeout: form.vision_timeout,
    vision_verify_ssl: form.vision_verify_ssl,
    vision_max_tokens: form.vision_max_tokens,
    vision_temperature: form.vision_temperature,
    vision_top_p: form.vision_top_p,
    vision_frequency_penalty: form.vision_frequency_penalty,
    vision_presence_penalty: form.vision_presence_penalty,
    vision_enable_thinking: form.vision_enable_thinking,
    vision_thinking_budget: form.vision_thinking_budget,
    rag_select_enabled: form.rag_select_enabled,
    rag_select_base_url: form.rag_select_base_url,
    rag_select_model: form.rag_select_model,
    rag_select_mode: form.rag_select_mode,
    rag_select_timeout: form.rag_select_timeout,
    rag_select_verify_ssl: form.rag_select_verify_ssl,
    rag_select_max_tokens: form.rag_select_max_tokens,
    rag_select_temperature: form.rag_select_temperature,
    rag_select_thinking_type: form.rag_select_thinking_type,
    rag_select_reasoning_effort: form.rag_select_reasoning_effort,
    rag_select_max_books: form.rag_select_max_books,
    rag_select_max_skills: form.rag_select_max_skills,
    rag_select_cache_ttl_minutes: form.rag_select_cache_ttl_minutes,
  }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  if (form.vision_api_key.trim()) payload.vision_api_key = form.vision_api_key.trim()
  if (form.rag_select_api_key.trim()) payload.rag_select_api_key = form.rag_select_api_key.trim()
  return payload
}

async function load() {
  loading.value = true
  try {
    const data = await getAiSettings()
    Object.assign(form, data, { api_key: '', vision_api_key: '', rag_select_api_key: '' })
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function save() {
  try {
    const view = await saveAiSettings(toPayload())
    Object.assign(form, view, { api_key: '', vision_api_key: '', rag_select_api_key: '' })
    ElMessage.success('AI 配置已保存')
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function reloadEnv() {
  try {
    await ElMessageBox.confirm(
      '将丢弃设置页未保存的修改，并以 backend/.env 文件当前内容为准重置全部 AI/视觉配置（含已保存的运行时覆盖）。继续？',
      '强制载入 .env',
      { confirmButtonText: '载入', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  reloadingEnv.value = true
  try {
    const view = await reloadEnvSettings()
    Object.assign(form, view, { api_key: '', vision_api_key: '', rag_select_api_key: '' })
    ElMessage.success('已从 .env 强制载入')
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    reloadingEnv.value = false
  }
}

const taskAbort = new AbortController()
onBeforeUnmount(() => taskAbort.abort())

/** 中止轮询产生的错误在 catch 中静默忽略。 */
function isTaskAbort(err: unknown): boolean {
  return (err as Error)?.name === 'AbortError'
}

async function test() {
  testing.value = true
  try {
    // 测试连接后台化（决策 35）：提交任务后轮询结果
    const { task_id } = await testAiSettings(toPayload())
    notifyTaskSubmitted()
    const t = await waitForTask(task_id, { intervalMs: 1000, timeoutMs: AI_TEST_TASK_TIMEOUT_MS, signal: taskAbort.signal })
    if (t.status === 'failed') {
      ElMessage.error(t.error || '连接测试失败')
    } else {
      const result = (t.result ?? {}) as { ok?: boolean; message?: string }
      if (result.ok) ElMessage.success(result.message || '连接成功')
      else ElMessage.warning(result.message || '连接失败')
    }
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    testing.value = false
  }
}

async function testVision() {
  visionTesting.value = true
  try {
    const { task_id } = await testVisionAiSettings(toPayload())
    notifyTaskSubmitted()
    const t = await waitForTask(task_id, { intervalMs: 1000, timeoutMs: AI_TEST_TASK_TIMEOUT_MS, signal: taskAbort.signal })
    if (t.status === 'failed') {
      ElMessage.error(t.error || '视觉连接测试失败')
    } else {
      const result = (t.result ?? {}) as { ok?: boolean; message?: string }
      if (result.ok) ElMessage.success(result.message || '视觉连接成功')
      else ElMessage.warning(result.message || '视觉连接失败')
    }
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    visionTesting.value = false
  }
}

async function testSelector() {
  selectorTesting.value = true
  try {
    const { task_id } = await testSelectorAiSettings(toPayload())
    notifyTaskSubmitted()
    const t = await waitForTask(task_id, { intervalMs: 1000, timeoutMs: AI_TEST_TASK_TIMEOUT_MS, signal: taskAbort.signal })
    if (t.status === 'failed') {
      ElMessage.error(t.error || '挑选器连接测试失败')
    } else {
      const result = (t.result ?? {}) as { ok?: boolean; message?: string }
      if (result.ok) ElMessage.success(result.message || '挑选器连接成功')
      else ElMessage.warning(result.message || '挑选器连接失败')
    }
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    selectorTesting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="settings-page">
    <header class="page-head">
      <div class="head-left">
        <h2>
          <span class="title-ico">⚙️</span>
          <span>设置</span>
        </h2>
        <p class="head-sub">文本模型负责阅读问答与 RAG/Skill 总结；多模态视觉模型负责 PDF 页面信息提取（扫描件与文本型统一）；挑选模型由 AI 自主挑选 RAG / Skill（未填项自动跟随文本模型）</p>
      </div>
      <div class="head-actions">
        <el-button :loading="reloadingEnv" @click="reloadEnv">🔄 强制载入 .env</el-button>
        <el-button type="primary" :loading="testing || visionTesting || selectorTesting" @click="save">💾 保存配置</el-button>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane v-for="tab in tabs" :key="tab.name" :name="tab.name">
      <template #label>
        <span class="tab-label">{{ tab.icon }} {{ tab.label }}</span>
      </template>
        <div v-loading="loading" class="tab-panel">
          <p class="panel-desc">{{ tab.desc }}</p>
          <section v-for="sec in tab.sections" :key="sec" class="panel">
            <header class="panel-head">
              <h3>{{ sectionIcons[sec] }} {{ sec }}</h3>
            </header>
            <el-form label-position="top" class="field-form">
              <div class="form-grid">
                <el-form-item
                  v-for="f in tab.fields.filter((x) => x.section === sec)"
                  :key="f.key"
                  :class="{ 'form-item-wide': f.wide }"
                >
                  <template #label>
                    <span class="field-label">
                      {{ f.label }}
                      <el-tag v-if="keySet(f.key)" size="small" type="success" effect="plain" class="key-tag">已设置</el-tag>
                    </span>
                  </template>
                  <el-input
                    v-if="f.type === 'text' || f.type === 'password'"
                    :model-value="getField(f.key)"
                    :type="f.type"
                    :show-password="f.type === 'password'"
                    :placeholder="fieldPlaceholder(f)"
                    @update:model-value="setField(f.key, $event)"
                  />
                  <el-input-number
                    v-else-if="f.type === 'number'"
                    :model-value="getField(f.key)"
                    :min="f.min"
                    :max="f.max"
                    :step="f.step"
                    class="num-input"
                    @update:model-value="setField(f.key, $event)"
                  />
                  <el-switch
                    v-else-if="f.type === 'switch'"
                    :model-value="getField(f.key)"
                    @update:model-value="setField(f.key, $event)"
                  />
                  <el-select
                    v-else
                    :model-value="getField(f.key)"
                    class="sel-input"
                    :clearable="f.clearable"
                    :placeholder="f.placeholder ?? '默认（不传）'"
                    @update:model-value="setField(f.key, $event)"
                  >
                    <el-option v-for="o in f.options ?? []" :key="o.value" :label="o.label" :value="o.value" />
                  </el-select>
                  <span v-if="f.tip" class="tip">{{ f.tip }}</span>
                </el-form-item>
              </div>
            </el-form>
          </section>
          <div class="actions">
            <el-button :loading="tab.testing" @click="tab.onTest">{{ tab.testLabel }}</el-button>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.settings-page { padding: 20px 24px 40px; max-width: 920px; margin: 0 auto; }

/* 顶部工具栏 */
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 10px; }
.head-left { display: flex; flex-direction: column; gap: 6px; }
.page-head h2 { margin: 0; font-size: 20px; display: flex; align-items: center; gap: 8px; }
.title-ico { font-size: 20px; }
.head-sub { color: var(--text-secondary); font-size: 13px; line-height: 1.7; max-width: 720px; margin: 0; }
.head-actions { display: flex; gap: 8px; }

/* 页签 */
.settings-tabs { margin-top: 6px; }
.settings-tabs :deep(.el-tabs__item.is-active) { color: #2f6fb0; } /* E2E 二轮：激活 tab 蓝字对比度 2.78:1 → #2f6fb0（≥4.5:1） */
.settings-tabs :deep(.el-tabs__item.is-active::after) { background-color: #2f6fb0; }
.settings-tabs :deep(.el-tabs__header) { margin-bottom: 16px; }
.settings-tabs :deep(.el-tabs__nav-wrap::after) { height: 1px; }
.settings-tabs :deep(.el-tabs__item) { font-size: 14px; padding: 0 18px; height: 44px; }
.tab-label { display: inline-flex; align-items: center; gap: 6px; }

.tab-panel { display: flex; flex-direction: column; gap: 16px; }
.panel-desc { color: var(--text-secondary); font-size: 13px; margin: 0; padding: 0 2px; }

/* 分区面板 */
.panel { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--radius-lg); padding: 16px 20px 6px; box-shadow: var(--shadow-sm); }
.panel:hover { border-color: var(--primary-soft); }
.panel-head { margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
.panel-head h3 { margin: 0; font-size: 14px; font-weight: 700; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.panel-head::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, var(--border-color), transparent); }

/* 表单双列网格 */
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px 22px; }
.form-item-wide { grid-column: 1 / -1; }
.field-form :deep(.el-form-item) { margin-bottom: 14px; }
.field-form :deep(.el-form-item__label) { font-size: 13px; color: var(--text-secondary); line-height: 1.4; padding-bottom: 6px; }
.field-label { display: inline-flex; align-items: center; gap: 6px; }
.key-tag { transform: scale(.86); transform-origin: left center; }
.num-input, .sel-input { width: 100%; }
.tip { color: var(--text-secondary); font-size: 13px; line-height: 1.6; display: block; margin-top: 5px; padding: 6px 10px; background: var(--panel-bg); border-radius: 8px; border-left: 3px solid var(--primary-soft); }
.actions { display: flex; justify-content: flex-end; gap: 10px; padding: 12px 0 16px; border-top: 1px dashed var(--border-color); margin-top: 2px; }

@media (max-width: 720px) {
  .form-grid { grid-template-columns: 1fr; }
  .settings-page { padding: 16px; }
}
</style>
