<template>
  <PageContainer
    title="模型设置"
    subtitle="配置大模型与向量服务（需管理员权限，密钥加密存储）"
  >
    <a-card
      class="settings-card"
      :loading="fetching"
    >
      <a-form
        :model="form"
        layout="vertical"
      >
        <a-form-item label="DeepSeek API Key">
          <a-input-password
            v-model:value="form.deepseekApiKey"
            :placeholder="deepseekPlaceholder"
            autocomplete="new-password"
            @input="deepseekTouched = true"
          />
        </a-form-item>
        <a-form-item label="阿里云百炼 DashScope API Key">
          <a-input-password
            v-model:value="form.dashscopeApiKey"
            :placeholder="dashscopePlaceholder"
            autocomplete="new-password"
            @input="dashscopeTouched = true"
          />
        </a-form-item>
        <a-form-item label="Embedding 服务地址">
          <a-input
            v-model:value="form.embeddingApiBase"
            placeholder="http://localhost:11434/v1"
          />
        </a-form-item>
        <a-form-item label="Mock 模式（开启后不调用真实模型）">
          <a-switch v-model:checked="form.llmMock" />
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button
              type="primary"
              :loading="saving"
              @click="handleSave"
            >
              保存配置
            </a-button>
            <a-button
              :loading="testingLlm"
              @click="handleTest('llm')"
            >
              测试 LLM 连通性
            </a-button>
            <a-button
              :loading="testingEmbedding"
              @click="handleTest('embedding')"
            >
              测试 Embedding 连通性
            </a-button>
          </a-space>
        </a-form-item>
      </a-form>

      <a-alert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        :message="testResult.text"
        show-icon
        style="margin-bottom: 16px"
      />

      <a-alert
        type="warning"
        message="仅当您修改了密钥输入框才会更新；清空输入框并保存将删除已保存的密钥；未改动的密钥保持不变。"
        show-icon
      />
    </a-card>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import type { AxiosError } from 'axios'
import {
  getLlmSettings,
  updateLlmSettings,
  testLlmConnection,
} from '@/api/settings'
import type { ConnectionTestTarget, LlmSettingsPayload } from '@/api/settings'
import PageContainer from '@/components/PageContainer.vue'

interface ApiErrorBody {
  code?: number
  message?: string
}

const fetching = ref(false)
const saving = ref(false)
const testingLlm = ref(false)
const testingEmbedding = ref(false)

const deepseekMasked = ref('')
const dashscopeMasked = ref('')
const deepseekConfigured = ref(false)
const dashscopeConfigured = ref(false)

// 密钥输入框 touched 跟踪：用户键入过（含清空）才算修改，提交时决定字段是否进入 payload
const deepseekTouched = ref(false)
const dashscopeTouched = ref(false)

const form = reactive({
  deepseekApiKey: '',
  dashscopeApiKey: '',
  embeddingApiBase: '',
  llmMock: false,
})

const testResult = ref<{ ok: boolean; text: string } | null>(null)

const deepseekPlaceholder = computed(() =>
  deepseekConfigured.value ? deepseekMasked.value : '未配置',
)
const dashscopePlaceholder = computed(() =>
  dashscopeConfigured.value ? dashscopeMasked.value : '未配置',
)

const getErrorMessage = (error: unknown, fallback: string): string => {
  const body = (error as AxiosError<ApiErrorBody>)?.response?.data
  // code 4003：非管理员访问设置接口
  if (body?.code === 4003) {
    return '需要管理员权限'
  }
  // 其余业务错误（如 embedding_api_base 私网校验 4000）展示后端 message
  return body?.message || fallback
}

const fetchSettings = async () => {
  fetching.value = true
  try {
    const settings = await getLlmSettings()
    deepseekMasked.value = settings.deepseek_api_key
    dashscopeMasked.value = settings.dashscope_api_key
    deepseekConfigured.value = settings.deepseek_configured
    dashscopeConfigured.value = settings.dashscope_configured
    // 密钥框始终留空，placeholder 展示脱敏串，避免脱敏串被当原值回传
    form.deepseekApiKey = ''
    form.dashscopeApiKey = ''
    form.embeddingApiBase = settings.embedding_api_base
    form.llmMock = settings.llm_mock
    deepseekTouched.value = false
    dashscopeTouched.value = false
  } catch (error) {
    message.error(getErrorMessage(error, '获取模型配置失败'))
  } finally {
    fetching.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const payload: LlmSettingsPayload = {
      embedding_api_base: form.embeddingApiBase,
      llm_mock: form.llmMock,
    }
    // 三态语义：未修改的密钥字段省略（保持原值）；已修改则传输入值（空串=清除）
    if (deepseekTouched.value) {
      payload.deepseek_api_key = form.deepseekApiKey
    }
    if (dashscopeTouched.value) {
      payload.dashscope_api_key = form.dashscopeApiKey
    }
    await updateLlmSettings(payload)
    message.success('模型配置已保存')
    deepseekTouched.value = false
    dashscopeTouched.value = false
    await fetchSettings()
  } catch (error) {
    message.error(getErrorMessage(error, '保存模型配置失败'))
  } finally {
    saving.value = false
  }
}

const buildSuccessText = (target: ConnectionTestTarget, result: {
  model?: string
  latency_ms?: number
  dimension?: number
}): string => {
  const parts: string[] = ['连通性测试成功']
  if (result.model) {
    parts.push(`模型：${result.model}`)
  }
  if (target === 'embedding' && typeof result.dimension === 'number') {
    parts.push(`维度：${result.dimension}`)
  }
  if (typeof result.latency_ms === 'number') {
    parts.push(`耗时：${result.latency_ms}ms`)
  }
  return parts.join('，')
}

const handleTest = async (target: ConnectionTestTarget) => {
  const loadingRef = target === 'llm' ? testingLlm : testingEmbedding
  const label = target === 'llm' ? 'LLM' : 'Embedding'
  loadingRef.value = true
  testResult.value = null
  try {
    const result = await testLlmConnection(target)
    if (result.ok) {
      testResult.value = { ok: true, text: buildSuccessText(target, result) }
    } else {
      testResult.value = { ok: false, text: `${label} 连通性测试失败：${result.error || '未知错误'}` }
    }
  } catch (error) {
    testResult.value = {
      ok: false,
      text: `${label} 连通性测试失败：${getErrorMessage(error, '请求失败')}`,
    }
  } finally {
    loadingRef.value = false
  }
}

onMounted(fetchSettings)
</script>

<style scoped>
.settings-card {
  max-width: 640px;
}
</style>
