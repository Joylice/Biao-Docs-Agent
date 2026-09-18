<template>
  <div class="provider-panel">
    <!-- 头部：标题 + 状态 -->
    <div class="provider-panel__header">
      <div>
        <h3 class="provider-panel__title">
          {{ title }}
        </h3>
        <p class="provider-panel__desc">
          {{ desc }}
        </p>
      </div>
      <a-tag
        v-if="!isCustom"
        :color="providerRow?.configured ? 'success' : 'warning'"
      >
        {{ providerRow?.configured ? '密钥已配置' : '密钥未配置' }}
      </a-tag>
      <a-tag
        v-else
        :color="customRow?.configured ? 'success' : 'warning'"
      >
        {{ customRow?.configured ? '端点密钥已配置' : '端点密钥未配置' }}
      </a-tag>
    </div>

    <a-spin :spinning="loading">
      <!-- ── 云端提供方（deepseek / zhipu）── -->
      <a-form
        v-if="!isCustom && providerRow"
        layout="vertical"
        class="provider-panel__form"
      >
        <a-form-item label="API Key">
          <div class="provider-panel__key-row">
            <a-input-password
              v-model:value="form.keyInput"
              placeholder="输入 API Key（留空保持现有密钥不变）"
              autocomplete="new-password"
              class="provider-panel__key-input"
            />
            <a-button
              v-if="providerRow.configured && !form.keyCleared"
              danger
              @click="clearKey(entryId as ProviderEntryId)"
            >
              清除
            </a-button>
          </div>
          <div
            v-if="form.keyCleared"
            class="provider-panel__key-cleared"
          >
            <a-tag color="warning">
              保存后将清除已存密钥
            </a-tag>
            <a-button
              type="link"
              size="small"
              @click="resetKeyClear(entryId as ProviderEntryId)"
            >
              撤销
            </a-button>
          </div>
          <div class="provider-panel__hint">
            密钥 Fernet 加密存储，仅脱敏回显（{{ providerRow.apiKeyMasked || '未配置' }}）；留空 =
            保持原值，清除需显式操作
          </div>
        </a-form-item>

        <a-form-item label="自定义请求地址（可选）">
          <a-input
            v-model:value="form.apiBase"
            :placeholder="providerRow.defaultBase || '留空使用厂商默认端点'"
            @change="form.apiBaseTouched = true"
          />
          <div class="provider-panel__hint">
            厂商默认端点：<code>{{ providerRow.defaultBase || '—' }}</code>
          </div>
        </a-form-item>

        <a-form-item label="能力">
          <a-tag
            v-if="providerRow.capabilities.text"
            color="blue"
          >
            文本生成
          </a-tag>
          <a-tag
            v-if="providerRow.capabilities.embedding"
            color="green"
          >
            向量嵌入
          </a-tag>
          <a-tag
            v-if="providerRow.capabilities.rerank"
            color="purple"
          >
            重排序
          </a-tag>
          <a-tag
            v-if="providerRow.capabilities.vision"
            color="orange"
          >
            视觉理解
          </a-tag>
          <span
            v-if="!hasAnyCapability"
            class="provider-panel__muted"
          >未启用</span>
        </a-form-item>
      </a-form>

      <!-- ── 自定义端点（custom）── -->
      <a-form
        v-else-if="isCustom"
        layout="vertical"
        class="provider-panel__form"
      >
        <a-form-item label="主模型（llm_model）">
          <a-input
            v-model:value="customGlobal.llmModel"
            placeholder="如 qwen72b 或 deepseek/deepseek-chat"
          />
          <div class="provider-panel__hint">
            运行时优先使用该模型；留空回退环境变量默认模型
          </div>
        </a-form-item>

        <a-form-item label="服务地址（OpenAI 兼容）">
          <a-input
            v-model:value="customGlobal.llmApiBase"
            placeholder="如 http://host.docker.internal:3100/v1"
          />
          <div class="provider-panel__hint">
            填 base 地址（到 /v1 为止，系统自动拼接 /chat/completions）；后端运行在
            Docker 容器内，主机上的服务请用 host.docker.internal 而非 localhost。留空 =
            不启用自定义端点（按模型前缀走云端厂商）
          </div>
        </a-form-item>

        <a-form-item label="端点专用密钥">
          <div class="provider-panel__key-row">
            <a-input-password
              v-model:value="customForm.keyInput"
              placeholder="输入 API Key（留空保持现有密钥不变）"
              autocomplete="new-password"
              class="provider-panel__key-input"
            />
            <a-button
              v-if="customRow?.configured && !customForm.keyCleared"
              danger
              @click="clearKey('llm:custom')"
            >
              清除
            </a-button>
          </div>
          <div
            v-if="customForm.keyCleared"
            class="provider-panel__key-cleared"
          >
            <a-tag color="warning">
              保存后将清除已存密钥
            </a-tag>
            <a-button
              type="link"
              size="small"
              @click="resetKeyClear('llm:custom')"
            >
              撤销
            </a-button>
          </div>
          <div class="provider-panel__hint">
            仅用于该端点，绝不透传至云端厂商；无鉴权端点可留空。脱敏回显：{{
              customRow?.apiKeyMasked || '未配置'
            }}
          </div>
        </a-form-item>
      </a-form>

      <!-- ── 测试连接（P0-4，共用）── -->
      <div class="provider-panel__test">
        <a-button
          :loading="testing"
          @click="onTest"
        >
          <template #icon>
            <ApiOutlined />
          </template>
          测试连接
        </a-button>
        <a-alert
          v-if="testResult?.ok"
          type="success"
          show-icon
          class="provider-panel__test-result"
          :message="`连通正常${typeof testResult.latency_ms === 'number' ? `（耗时 ${testResult.latency_ms}ms）` : ''}`"
        />
        <a-alert
          v-else-if="testResult && !testResult.ok"
          type="error"
          show-icon
          class="provider-panel__test-result"
          :message="`连通失败：${testResult.error || '未知错误'}`"
        />
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * ProviderPanel：语言模型分类单提供方表单（P0-3/P0-4）.
 *
 * 同一面板承载三类条目（entryId 区分）：
 * - llm:deepseek / llm:zhipu：providers 行 key（三态）+ api_base + 能力 chips 只读；
 * - llm:custom：llm_model/llm_api_base（llm_settings）+ 端点专用密钥（providers
 *   'custom' 行三态）。
 * 保存不设面板级按钮——底部 footer 的"保存"经 configCenterStore.saveCurrent →
 * registry entry.save → 本面板绑定的 useProvidersConfig 闭包完成；面板编辑即
 * markDirty，导航角标与关闭确认联动。
 */
import { computed, onMounted, watch } from 'vue'
import { ApiOutlined } from '@ant-design/icons-vue'
import { useConfigCenterStore } from '@/stores/configCenter'
import {
  useProvidersConfig,
  type CloudProviderEntryId,
  type ProviderEntryId,
} from '@/composables/useProvidersConfig'

const props = withDefaults(
  defineProps<{
    title?: string
    desc?: string
    /** registry 条目 id（ConfigCenterModal 传入），决定面板形态 */
    entryId?: string | null
  }>(),
  { title: '语言模型', desc: '', entryId: null },
)

const store = useConfigCenterStore()
const config = useProvidersConfig()

const {
  loading,
  testing,
  testResult,
  entries,
  customGlobal,
  load,
  clearKey,
  resetKeyClear,
  runTest,
} = config

const isCustom = computed(() => props.entryId === 'llm:custom')
const providerRow = computed(() =>
  props.entryId ? entries[props.entryId as ProviderEntryId]?.provider ?? null : null,
)
/** 当前条目表单（恒非空：entryId 缺失/未注册时回退 deepseek，分支由 v-if 守卫） */
const form = computed(() => {
  if (props.entryId === 'llm:custom') return entries['llm:custom'].form
  if (props.entryId === 'llm:deepseek' || props.entryId === 'llm:zhipu') {
    return entries[props.entryId].form
  }
  return entries['llm:deepseek'].form
})
const customRow = computed(() => entries['llm:custom'].provider)
const customForm = computed(() => entries['llm:custom'].form)

const hasAnyCapability = computed(() => {
  const caps = providerRow.value?.capabilities
  return !!caps && (caps.text || caps.embedding || caps.rerank || caps.vision)
})

/** 测试连接：自定义端点按表单未保存值测（key 留空回退已存密钥）；云端条目测已存配置 */
const onTest = () => {
  if (isCustom.value) {
    const key = customForm.value.keyInput.trim()
    return runTest({
      model: customGlobal.llmModel.trim(),
      api_base: customGlobal.llmApiBase.trim(),
      api_key: customForm.value.keyCleared || !key || key.includes('****') ? '' : key,
    })
  }
  return runTest()
}

/** 编辑即置脏（面板切换存活：composable 为模块级单例，状态不随卸载销毁） */
watch(
  () =>
    props.entryId === 'llm:custom'
      ? config.isDirtyCustom()
      : props.entryId
        ? config.isDirtyProvider(props.entryId as CloudProviderEntryId)
        : false,
  (dirty) => {
    if (!props.entryId) return
    if (dirty) {
      store.markDirty(props.entryId)
    } else {
      store.clearDirty(props.entryId)
    }
  },
  { immediate: true },
)

onMounted(load)
</script>

<style scoped>
.provider-panel {
  max-width: 640px;
}

.provider-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.provider-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.provider-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.provider-panel__form {
  margin-top: var(--space-2);
}

.provider-panel__key-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.provider-panel__key-input {
  flex: 1;
}

.provider-panel__key-cleared {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.provider-panel__hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.provider-panel__hint code {
  font-size: 11px;
  color: var(--color-primary);
  background: var(--color-primary-lighter);
  padding: 1px 4px;
  border-radius: var(--radius-sm);
}

.provider-panel__muted {
  font-size: 12px;
  color: var(--text-tertiary);
}

.provider-panel__test {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.provider-panel__test-result {
  flex: 1;
  min-width: 0;
}
</style>
