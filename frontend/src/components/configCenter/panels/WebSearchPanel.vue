<template>
  <div class="websearch-panel">
    <!-- 头部：标题 + 状态 -->
    <div class="websearch-panel__header">
      <div>
        <h3 class="websearch-panel__title">{{ title }}</h3>
        <p class="websearch-panel__desc">{{ desc }}</p>
      </div>
      <a-tag v-if="form.exists" :color="toolRow?.enabled ? 'success' : 'warning'">
        {{ toolRow?.enabled ? '已启用' : '已停用' }}
      </a-tag>
      <a-tag v-else color="default">未创建</a-tag>
    </div>

    <a-spin :spinning="loading">
      <a-form layout="vertical" class="websearch-panel__form">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="工具名称">
              <a-input v-model:value="form.name" :placeholder="defaultName" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="请求地址（可选）">
              <a-input v-model:value="form.baseUrl" placeholder="留空使用预设默认端点" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="超时（毫秒）">
              <a-input-number v-model:value="form.timeoutMs" :min="1000" :step="1000" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="查询最大字符数">
              <a-input-number v-model:value="form.maxQueryChars" :min="50" :step="50" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="API Key">
          <div class="websearch-panel__key-row">
            <a-input-password
              v-model:value="form.keyInput"
              :placeholder="form.configured ? '已配置，留空保持现有密钥不变' : '输入 API Key'"
              autocomplete="new-password"
            />
            <a-button v-if="form.configured && !form.keyCleared" danger @click="clearKey(preset)">
              清除
            </a-button>
          </div>
          <div v-if="form.keyCleared" class="websearch-panel__key-cleared">
            <a-tag color="warning">保存后将清除已存密钥</a-tag>
            <a-button type="link" size="small" @click="resetKeyClear(preset)">撤销</a-button>
          </div>
          <div class="websearch-panel__hint">
            密钥加密存储，仅脱敏回显（{{ form.apiKeyMasked || '未配置' }}）；{{ presetHint }}
          </div>
        </a-form-item>
      </a-form>

      <!-- 启停 / 测试 / 删除 -->
      <div class="websearch-panel__actions">
        <a-switch
          v-if="form.exists && toolRow"
          :checked="toolRow.enabled"
          checked-children="启用"
          un-checked-children="停用"
          @change="(checked: unknown) => onToggle(!!checked)"
        />
        <a-button :disabled="!form.exists" @click="runTest(preset)">
          <template #icon><ApiOutlined /></template>
          测试
        </a-button>
        <a-button v-if="form.exists" danger @click="onRemove">
          <template #icon><DeleteOutlined /></template>
          删除工具
        </a-button>
      </div>

      <!-- 阶段绑定 -->
      <div v-if="form.exists && toolRow" class="websearch-panel__bindings">
        <div class="websearch-panel__bindings-title">阶段绑定</div>
        <div class="websearch-panel__bindings-list">
          <a-tag
            v-for="stage in boundStages"
            :key="stage"
            closable
            @close="unbindStage(toolRow!, stage)"
          >
            {{ stageLabels[stage] || stage }}
          </a-tag>
          <a-select
            v-if="availableStages.length > 0"
            placeholder="绑定阶段"
            size="small"
            style="width: 140px"
            @change="(val: unknown) => bindStage(toolRow!, String(val))"
          >
            <a-select-option v-for="s in availableStages" :key="s" :value="s">
              {{ stageLabels[s] || s }}
            </a-select-option>
          </a-select>
          <span v-else class="websearch-panel__muted">已绑定全部可绑定阶段</span>
        </div>
        <div class="websearch-panel__hint">
          绑定后流水线节点按需调用该工具；绑定列表为会话内口径（刷新后需重新查看）
        </div>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * WebSearchPanel：网络搜索分类单 preset 表单（P1-2）.
 *
 * 同一面板承载 tavily / brave / searxng 三条目（entryId=preset，ConfigCenterModal
 * 传入）；保存带 expected_version 乐观锁（409 → "配置已被他人修改"），无行走
 * 创建分流。启停/删除为即时操作（确认流），保存经 registry entry.save →
 * useExternalToolsConfig.savePreset；编辑经 watch 联动导航角标。
 */
import { computed, onMounted, watch } from 'vue'
import { ApiOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import { useConfigCenterStore } from '@/stores/configCenter'
import {
  PRESET_DEFAULT_NAMES,
  TOOL_BINDABLE_STAGES,
  useExternalToolsConfig,
  type WebsearchPreset,
} from '@/composables/useExternalToolsConfig'

const props = withDefaults(
  defineProps<{
    title?: string
    desc?: string
    /** registry 条目 id（websearch:tavily 等），末段为 preset */
    entryId?: string | null
  }>(),
  { title: '搜索工具', desc: '', entryId: null },
)

const store = useConfigCenterStore()
const config = useExternalToolsConfig()

const {
  loading,
  tools,
  forms,
  load,
  clearKey,
  resetKeyClear,
  toggleEnable,
  remove,
  runTest,
  bindStage,
  unbindStage,
  isDirtyPreset,
} = config

const preset = computed<WebsearchPreset>(() => {
  const last = (props.entryId ?? '').split(':')[1] as WebsearchPreset
  return (['tavily', 'brave', 'searxng'] as const).includes(last) ? last : 'tavily'
})

const form = computed(() => forms[preset.value])
const defaultName = computed(() => PRESET_DEFAULT_NAMES[preset.value])
const toolRow = computed(() => tools.value.find((t) => t.preset === preset.value) ?? null)

const presetHints: Record<WebsearchPreset, string> = {
  tavily: 'Tavily：密钥注入 JSON body（api_key 字段）',
  brave: 'Brave：密钥注入请求头（X-Subscription-Token）',
  searxng: 'SearXNG：无鉴权，自建实例需填写请求地址',
}
const presetHint = computed(() => presetHints[preset.value])

/** 展示层归并映射（与 UsageTrendChart 同步） */
const stageLabels: Record<string, string> = {
  parse: '招标解析',
  score: '招标解析',
  outline: '方案大纲生成',
  write: '方案生成',
  validate: '方案生成',
  consistency: '方案生成',
  review: '方案评审',
  export: '方案导出',
}

const boundStages = computed(() =>
  toolRow.value ? (config.bindings.value[toolRow.value.id] ?? []) : [],
)
const availableStages = computed(() =>
  TOOL_BINDABLE_STAGES.filter((s) => !boundStages.value.includes(s)),
)

const onToggle = (checked: boolean) => {
  if (toolRow.value) void toggleEnable(toolRow.value, checked)
}

const onRemove = () => {
  void remove(preset.value)
}

/** 编辑即置脏（保存成功后 load() 重置，watch 随之清除角标） */
watch(
  () => isDirtyPreset(preset.value),
  (dirty) => {
    const entryId = `websearch:${preset.value}`
    if (dirty) {
      store.markDirty(entryId)
    } else {
      store.clearDirty(entryId)
    }
  },
  { immediate: true },
)

onMounted(load)
</script>

<style scoped>
.websearch-panel {
  max-width: 640px;
}

.websearch-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.websearch-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.websearch-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.websearch-panel__key-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.websearch-panel__key-row > :first-child {
  flex: 1;
}

.websearch-panel__key-cleared {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.websearch-panel__hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.websearch-panel__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.websearch-panel__bindings {
  padding: var(--space-3);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.websearch-panel__bindings-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}

.websearch-panel__bindings-list {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.websearch-panel__muted {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
