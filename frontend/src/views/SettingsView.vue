<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAiSettings, saveAiSettings, testAiSettings, testVisionAiSettings } from '@/api/settings'
import type { AiSettings } from '@/types'

const loading = ref(false)
const testing = ref(false)
const visionTesting = ref(false)
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
})

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
  }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  if (form.vision_api_key.trim()) payload.vision_api_key = form.vision_api_key.trim()
  return payload
}

async function load() {
  loading.value = true
  try {
    const data = await getAiSettings()
    Object.assign(form, data, { api_key: '', vision_api_key: '' })
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function save() {
  try {
    const view = await saveAiSettings(toPayload())
    Object.assign(form, view, { api_key: '', vision_api_key: '' })
    ElMessage.success('AI 配置已保存')
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function test() {
  testing.value = true
  try {
    const result = await testAiSettings(toPayload())
    if (result.ok) ElMessage.success(result.message)
    else ElMessage.warning(result.message)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    testing.value = false
  }
}

async function testVision() {
  visionTesting.value = true
  try {
    const result = await testVisionAiSettings(toPayload())
    if (result.ok) ElMessage.success(result.message)
    else ElMessage.warning(result.message)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    visionTesting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="settings-page">
    <h2>设置</h2>
    <el-card v-loading="loading" class="ai-card">
      <template #header>
        <div class="card-head">
          <span>AI 接入（M4）</span>
          <span class="tip">配置外部大模型 API，用于阅读问答与后续能力；PDF 页面提取使用下方多模态配置</span>
        </div>
      </template>
      <el-form label-width="130px" label-position="left">
        <el-form-item label="Base URL">
          <el-input
            v-model="form.base_url"
            placeholder="基础地址或完整 URL：https://api.deepseek.com 或 https://host/v1/chat/completions"
          />
          <span class="tip">两种写法：① 基础地址（如 https://api.deepseek.com 或 https://host/v1），按接口模式自动补全（chat→/v1/chat/completions、responses→/v1/responses、anthropic→/v1/messages）；② 完整接口 URL（如 https://host/v1/chat/completions），直接使用不再补全</span>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="form.api_key_set ? '已设置（留空保持不变）' : '请输入 API Key'"
          />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="form.model" placeholder="如 deepseek-v4-flash / gpt-4o-mini" />
        </el-form-item>
        <el-form-item label="接口模式">
          <el-select v-model="form.mode" style="width: 100%">
            <el-option label="responses（instructions/input）" value="responses" />
            <el-option label="chat（messages）" value="chat" />
            <el-option label="anthropic（Messages API）" value="anthropic" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout" :min="5" :max="600" style="width: 160px" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" style="width: 160px" />
          <span class="tip">DeepSeek 思考模式下不生效（官方：设置不报错也不生效）</span>
        </el-form-item>
        <el-form-item label="生成上限">
          <el-input-number v-model="form.max_tokens" :min="256" :max="65536" :step="512" style="width: 160px" />
          <span class="tip">max_tokens：DeepSeek 默认 32K、最大 64K，含思考 token（chat 模式）</span>
        </el-form-item>
        <el-form-item label="思考模式">
          <el-select v-model="form.thinking_type" style="width: 200px" clearable placeholder="默认（不传）">
            <el-option label="开启思考" value="enabled" />
            <el-option label="关闭思考" value="disabled" />
          </el-select>
          <span class="tip">DeepSeek thinking.type；V4 模型默认开启（chat 模式）</span>
        </el-form-item>
        <el-form-item label="推理强度">
          <el-select v-model="form.reasoning_effort" style="width: 200px" clearable placeholder="默认（不传）">
            <el-option label="low" value="low" />
            <el-option label="medium" value="medium" />
            <el-option label="high" value="high" />
            <el-option label="max" value="max" />
          </el-select>
          <span class="tip">DeepSeek reasoning_effort；关闭思考时不要同时设置</span>
        </el-form-item>
        <el-form-item label="Top P">
          <el-input-number v-model="form.top_p" :min="0" :max="1" :step="0.05" style="width: 160px" />
        </el-form-item>
        <el-form-item label="频率惩罚">
          <el-input-number v-model="form.frequency_penalty" :min="-2" :max="2" :step="0.1" style="width: 160px" />
        </el-form-item>
        <el-form-item label="存在惩罚">
          <el-input-number v-model="form.presence_penalty" :min="-2" :max="2" :step="0.1" style="width: 160px" />
        </el-form-item>
        <el-form-item label="停止词">
          <el-input v-model="form.stop" placeholder="多个用英文逗号分隔，如 结论,总结" />
          <span class="tip">chat 模式；留空不传</span>
        </el-form-item>
        <el-form-item label="校验 SSL">
          <el-switch v-model="form.verify_ssl" />
        </el-form-item>
        <el-form-item label="发送书籍正文">
          <el-switch v-model="form.enable_body_send" />
          <span class="tip">隐私开关：关闭后不向模型发送书籍正文，仅用元信息与问题</span>
        </el-form-item>
        <el-form-item label="发送页面图片">
          <el-switch v-model="form.send_page_image" />
          <span class="tip">扫描版 PDF：提问时附带当前页图片作为附件（需模型支持视觉输入，chat 模式）</span>
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button type="primary" :loading="testing" @click="test">测试连接</el-button>
        <el-button type="success" @click="save">保存</el-button>
      </div>
    </el-card>

    <el-card v-loading="loading" class="ai-card">
      <template #header>
        <div class="card-head">
          <span>多模态视觉接入（M7）</span>
          <span class="tip">用于 PDF 页面信息提取（扫描件与文本型统一），独立于文本 AI，无需额度管理</span>
        </div>
      </template>
      <el-form label-width="130px" label-position="left">
        <el-form-item label="Base URL">
          <el-input
            v-model="form.vision_base_url"
            placeholder="基础地址或完整 URL：https://api.siliconflow.cn/v1 或 https://host/v1/chat/completions"
          />
          <span class="tip">两种写法：① 基础地址（如 https://api.siliconflow.cn/v1），自动补全 /chat/completions；② 完整接口 URL（如 https://host/v1/chat/completions），直接使用不再补全</span>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.vision_api_key"
            type="password"
            show-password
            :placeholder="form.vision_api_key_set ? '已设置（留空保持不变）' : '请输入多模态 API Key'"
          />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="form.vision_model" placeholder="如 Qwen/Qwen2.5-VL-72B-Instruct / deepseek-ai/DeepSeek-OCR" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.vision_timeout" :min="5" :max="600" style="width: 160px" />
        </el-form-item>
        <el-form-item label="校验 SSL">
          <el-switch v-model="form.vision_verify_ssl" />
        </el-form-item>
        <el-form-item label="生成上限">
          <el-input-number v-model="form.vision_max_tokens" :min="256" :max="32768" :step="256" style="width: 160px" />
          <span class="tip">SiliconFlow 建议设置 max_tokens（预留上下文余量）</span>
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="form.vision_temperature" :min="0" :max="2" :step="0.1" style="width: 160px" />
          <span class="tip">SiliconFlow 参数；若开启思考模式则可能不生效</span>
        </el-form-item>
        <el-form-item label="Top P">
          <el-input-number v-model="form.vision_top_p" :min="0" :max="1" :step="0.05" style="width: 160px" />
        </el-form-item>
        <el-form-item label="频率惩罚">
          <el-input-number v-model="form.vision_frequency_penalty" :min="-2" :max="2" :step="0.1" style="width: 160px" />
        </el-form-item>
        <el-form-item label="存在惩罚">
          <el-input-number v-model="form.vision_presence_penalty" :min="-2" :max="2" :step="0.1" style="width: 160px" />
        </el-form-item>
        <el-form-item label="思考模式">
          <el-switch v-model="form.vision_enable_thinking" />
          <span class="tip">SiliconFlow enable_thinking（DeepSeek/Zhipu 系推理模型）；Qwen 等非推理模型勿开</span>
        </el-form-item>
        <el-form-item label="思维链上限">
          <el-input-number v-model="form.vision_thinking_budget" :min="256" :max="65536" :step="256" style="width: 160px" />
          <span class="tip">SiliconFlow thinking_budget，仅推理模型使用</span>
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button :loading="visionTesting" @click="testVision">测试视觉连接</el-button>
        <el-button type="success" @click="save">保存</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.settings-page { padding: 20px; max-width: 760px; }
.tip { color: var(--text-secondary); font-size: 12px; margin-left: 10px; }
.card-head { display: flex; align-items: baseline; gap: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 10px; }
</style>
