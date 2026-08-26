<template>
  <PageContainer
    title="模型设置"
    subtitle="配置大模型与向量服务（需管理员权限，密钥加密存储）"
  >
    <!-- 配置状态总览 -->
    <div class="settings-overview">
      <div class="settings-overview__item">
        <div class="settings-overview__icon settings-overview__icon--llm">
          <RobotOutlined />
        </div>
        <div class="settings-overview__info">
          <div class="settings-overview__label">LLM 大模型</div>
          <div class="settings-overview__value">
            <a-tag :color="llmConfigured ? 'success' : 'default'">
              {{ llmConfigured ? '已配置' : '未配置' }}
            </a-tag>
          </div>
        </div>
      </div>
      <div class="settings-overview__item">
        <div class="settings-overview__icon settings-overview__icon--embedding">
          <ApartmentOutlined />
        </div>
        <div class="settings-overview__info">
          <div class="settings-overview__label">Embedding 向量模型</div>
          <div class="settings-overview__value">
            <a-tag :color="embeddingConfigured ? 'success' : 'default'">
              {{ embeddingConfigured ? '已配置' : '未配置' }}
            </a-tag>
          </div>
        </div>
      </div>
      <div class="settings-overview__item">
        <div class="settings-overview__icon settings-overview__icon--mock">
          <ExperimentOutlined />
        </div>
        <div class="settings-overview__info">
          <div class="settings-overview__label">运行模式</div>
          <div class="settings-overview__value">
            <a-tag :color="form.llmMock ? 'warning' : 'success'">
              {{ form.llmMock ? 'Mock 模式' : '真实调用' }}
            </a-tag>
          </div>
        </div>
      </div>
    </div>

    <div class="settings-grid">
      <!-- LLM 大模型配置 -->
      <a-card
        class="settings-card"
        :loading="fetching"
        :bordered="false"
      >
        <template #title>
          <div class="settings-card__title">
            <RobotOutlined class="settings-card__icon settings-card__icon--llm" />
            <span>LLM 大模型</span>
            <a-tag
              v-if="llmConfigured"
              color="success"
              class="settings-card__status"
            >
              已配置
            </a-tag>
          </div>
        </template>
        <a-form
          :model="form"
          layout="vertical"
        >
          <a-form-item label="LLM 主模型">
            <a-input
              v-model:value="form.llmModel"
              placeholder="qwen72b 或 deepseek/deepseek-chat"
              @input="llmModelTouched = true"
            />
            <template #help>
              留空使用默认模型；无 provider 前缀时自动按 OpenAI 兼容接口调用（如 <code>qwen72b</code> → <code>openai/qwen72b</code>）
            </template>
          </a-form-item>
          <a-form-item label="LLM 服务地址">
            <a-input
              v-model:value="form.llmApiBase"
              placeholder="http://123.249.37.244:7778/v1"
              @input="llmApiBaseTouched = true"
            />
            <template #help>
              OpenAI 兼容服务地址（vLLM / Ollama 等）；留空使用模型默认端点；配置后不转发云端密钥，无需 API Key
            </template>
          </a-form-item>
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
        </a-form>
        <div class="settings-card__action">
          <a-button
            :loading="testingLlm"
            @click="handleTest('llm')"
          >
            <template #icon>
              <ApiOutlined />
            </template>
            测试连通性
          </a-button>
        </div>
      </a-card>

      <!-- Embedding 向量模型配置 -->
      <a-card
        class="settings-card"
        :loading="fetching"
        :bordered="false"
      >
        <template #title>
          <div class="settings-card__title">
            <ApartmentOutlined class="settings-card__icon settings-card__icon--embedding" />
            <span>Embedding 向量模型</span>
            <a-tag
              v-if="embeddingConfigured"
              color="success"
              class="settings-card__status"
            >
              已配置
            </a-tag>
          </div>
        </template>
        <a-form
          :model="form"
          layout="vertical"
        >
          <a-form-item label="Embedding 模型名称">
            <a-input
              v-model:value="form.embeddingModel"
              placeholder="dashscope/text-embedding-v3"
            />
            <template #help>
              LiteLLM provider 前缀格式，如 <code>dashscope/text-embedding-v3</code> 或 <code>openai_like/bge-m3</code>
            </template>
          </a-form-item>
          <a-form-item label="Embedding 服务地址">
            <a-input
              v-model:value="form.embeddingApiBase"
              placeholder="http://localhost:11434/v1"
            />
          </a-form-item>
          <a-form-item label="Embedding API Key">
            <a-input-password
              v-model:value="form.embeddingApiKey"
              :placeholder="embeddingPlaceholder"
              autocomplete="new-password"
              @input="embeddingTouched = true"
            />
            <template #help>
              独立密钥，优先于 LLM 密钥匹配；留空则按模型前缀回退 DeepSeek/DashScope 密钥
            </template>
          </a-form-item>
        </a-form>
        <div class="settings-card__action">
          <a-button
            :loading="testingEmbedding"
            @click="handleTest('embedding')"
          >
            <template #icon>
              <ApiOutlined />
            </template>
            测试连通性
          </a-button>
        </div>
      </a-card>
    </div>

    <!-- 运行模式与操作 -->
    <a-card
      class="settings-card settings-card--full"
      :loading="fetching"
      :bordered="false"
    >
      <template #title>
        <div class="settings-card__title">
          <ExperimentOutlined class="settings-card__icon settings-card__icon--mock" />
          <span>运行模式与操作</span>
        </div>
      </template>
      <a-form
        :model="form"
        layout="vertical"
      >
        <a-form-item label="Mock 模式">
          <a-switch
            v-model:checked="form.llmMock"
            checked-children="开启"
            un-checked-children="关闭"
          />
          <div class="settings-form__hint">
            开启后不调用真实模型，使用预设 Mock 数据返回，用于开发调试与演示
          </div>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button
              type="primary"
              :loading="saving"
              @click="handleSave"
            >
              <template #icon>
                <SaveOutlined />
              </template>
              保存配置
            </a-button>
            <a-button
              @click="fetchSettings"
            >
              <template #icon>
                <ReloadOutlined />
              </template>
              重新加载
            </a-button>
          </a-space>
        </a-form-item>
      </a-form>

      <a-alert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        :message="testResult.text"
        show-icon
        class="settings-alert"
      />

      <a-alert
        type="warning"
        message="仅当您修改了密钥输入框才会更新；清空输入框并保存将删除已保存的密钥；未改动的密钥保持不变。"
        show-icon
        class="settings-alert"
      />
    </a-card>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import type { AxiosError } from 'axios'
import {
  RobotOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  ApiOutlined,
  SaveOutlined,
  ReloadOutlined,
} from '@ant-design/icons-vue'
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
const embeddingMasked = ref('')
const deepseekConfigured = ref(false)
const dashscopeConfigured = ref(false)
const embeddingConfigured = ref(false)

// 密钥/自定义模型输入框 touched 跟踪：用户键入过（含清空）才算修改，提交时决定字段是否进入 payload
const deepseekTouched = ref(false)
const dashscopeTouched = ref(false)
const embeddingTouched = ref(false)
const llmModelTouched = ref(false)
const llmApiBaseTouched = ref(false)

const form = reactive({
  deepseekApiKey: '',
  dashscopeApiKey: '',
  llmModel: '',
  llmApiBase: '',
  embeddingModel: '',
  embeddingApiBase: '',
  embeddingApiKey: '',
  llmMock: false,
})

const testResult = ref<{ ok: boolean; text: string } | null>(null)

const deepseekPlaceholder = computed(() =>
  deepseekConfigured.value ? deepseekMasked.value : '未配置',
)
const dashscopePlaceholder = computed(() =>
  dashscopeConfigured.value ? dashscopeMasked.value : '未配置',
)
const embeddingPlaceholder = computed(() =>
  embeddingConfigured.value ? embeddingMasked.value : '留空则按模型前缀回退 LLM 密钥',
)

// LLM 配置状态：主模型/服务地址/任一密钥已配置即为已配置
const llmConfigured = computed(() =>
  !!form.llmModel || !!form.llmApiBase || deepseekConfigured.value || dashscopeConfigured.value,
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
    embeddingMasked.value = settings.embedding_api_key
    deepseekConfigured.value = settings.deepseek_configured
    dashscopeConfigured.value = settings.dashscope_configured
    embeddingConfigured.value = settings.embedding_configured
    // 密钥框始终留空，placeholder 展示脱敏串，避免脱敏串被当原值回传
    form.deepseekApiKey = ''
    form.dashscopeApiKey = ''
    form.embeddingApiKey = ''
    form.llmModel = settings.llm_model
    form.llmApiBase = settings.llm_api_base
    form.embeddingModel = settings.embedding_model
    form.embeddingApiBase = settings.embedding_api_base
    form.llmMock = settings.llm_mock
    deepseekTouched.value = false
    dashscopeTouched.value = false
    embeddingTouched.value = false
    llmModelTouched.value = false
    llmApiBaseTouched.value = false
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
      embedding_model: form.embeddingModel,
      llm_mock: form.llmMock,
    }
    // 三态语义：未修改的密钥/自定义模型字段省略（保持原值）；已修改则传输入值（空串=清除）
    if (deepseekTouched.value) {
      payload.deepseek_api_key = form.deepseekApiKey
    }
    if (dashscopeTouched.value) {
      payload.dashscope_api_key = form.dashscopeApiKey
    }
    if (llmModelTouched.value) {
      payload.llm_model = form.llmModel
    }
    if (llmApiBaseTouched.value) {
      payload.llm_api_base = form.llmApiBase
    }
    if (embeddingTouched.value) {
      payload.embedding_api_key = form.embeddingApiKey
    }
    await updateLlmSettings(payload)
    message.success('模型配置已保存')
    deepseekTouched.value = false
    dashscopeTouched.value = false
    embeddingTouched.value = false
    llmModelTouched.value = false
    llmApiBaseTouched.value = false
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
/* 配置状态总览 */
.settings-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.settings-overview__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.settings-overview__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  font-size: 18px;
  flex-shrink: 0;
}

.settings-overview__icon--llm {
  background: linear-gradient(135deg, var(--color-primary), var(--color-info));
  color: var(--text-inverse);
}

.settings-overview__icon--embedding {
  background: linear-gradient(135deg, var(--color-success), var(--color-info));
  color: var(--text-inverse);
}

.settings-overview__icon--mock {
  background: linear-gradient(135deg, var(--color-warning), var(--color-error));
  color: var(--text-inverse);
}

.settings-overview__info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.settings-overview__label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.settings-overview__value {
  font-size: var(--font-size-base);
  font-weight: 600;
  color: var(--text-primary);
}

/* 配置卡片网格 */
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  margin-bottom: 20px;
}

.settings-card {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
}

.settings-card--full {
  margin-bottom: 0;
}

.settings-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}

.settings-card__icon {
  font-size: 16px;
}

.settings-card__icon--llm {
  color: var(--color-primary);
}

.settings-card__icon--embedding {
  color: var(--color-success);
}

.settings-card__icon--mock {
  color: var(--color-warning);
}

.settings-card__status {
  margin-left: 8px;
}

.settings-card__action {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}

.settings-form__hint {
  margin-top: 4px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.settings-alert {
  margin-top: 16px;
}

/* 响应式：小屏单列 */
@media (max-width: 992px) {
  .settings-overview {
    grid-template-columns: 1fr;
  }
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
