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
            v-for="node in boundNodes"
            :key="node.key"
            closable
            @close="onUnbindNode(node.key)"
          >
            {{ node.label }}
          </a-tag>
          <!-- 存量假绑定清理通道：非可绑定节点若历史上绑过，仍需可见 + 可解绑（不静默隐藏） -->
          <a-tag
            v-for="node in legacyBoundNodes"
            :key="node.key"
            color="warning"
            closable
            :title="LEGACY_BIND_HINT"
            @close="onUnbindNode(node.key)"
          >
            {{ node.label }}（不生效）
          </a-tag>
          <a-select
            v-if="unboundNodes.length > 0"
            placeholder="绑定编制节点"
            size="small"
            style="width: 160px"
            @change="(val: unknown) => onBindNode(String(val))"
          >
            <a-select-option v-for="n in unboundNodes" :key="n.key" :value="n.key">
              {{ n.label }}
            </a-select-option>
          </a-select>
          <span v-else class="websearch-panel__muted">已绑定全部可绑定节点</span>
        </div>
        <div class="websearch-panel__hint">
          绑定即生效（无需再开联网开关）。已接线节点：招标解析、方案大纲生成、方案生成、方案评审；「方案导出」为纯渲染阶段、无模型调用点，不提供绑定。
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
  useExternalToolsConfig,
  type WebsearchPreset,
} from '@/composables/useExternalToolsConfig'
import {
  BINDABLE_NODE_GROUPS,
  STAGE_NODE_GROUPS,
  type StageNodeGroup,
} from '@/config/stageNodes'

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
  bindNode,
  unbindNode,
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

/** 存量「不生效」绑定说明（方案导出等无模型调用点节点） */
const LEGACY_BIND_HINT = '该节点无模型调用点（如方案导出为纯渲染），绑定不会触发，建议解绑'

/** 该工具当前已绑定的 stage_key[]（无工具行时为空） */
function boundStageKeys(): string[] {
  return toolRow.value ? (config.bindings.value[toolRow.value.id] ?? []) : []
}

/** 该工具已绑定的**可绑定**节点（stage_key 归并到节点；整节点展示与解绑） */
const boundNodes = computed(() => {
  const bound = boundStageKeys()
  return (BINDABLE_NODE_GROUPS as readonly StageNodeGroup[]).filter((n) =>
    n.stageKeys.some((k) => bound.includes(k)),
  )
})

/**
 * 历史上绑过的**非可绑定**节点（如方案导出）—— 只用于展示 + 解绑清理，不进下拉.
 * 不静默隐藏：隐藏会让存量假绑定再也无法从 UI 清除。
 */
const legacyBoundNodes = computed(() => {
  const bound = boundStageKeys()
  return (STAGE_NODE_GROUPS as readonly StageNodeGroup[])
    .filter((n) => !BINDABLE_NODE_GROUPS.some((b) => b.key === n.key))
    .filter((n) => n.stageKeys.some((k) => bound.includes(k)))
})

/** 尚未绑定的**可绑定**节点（绑定下拉项；「方案导出」不在其中） */
const unboundNodes = computed(() => {
  const boundKeys = new Set(boundNodes.value.map((n) => n.key))
  return (BINDABLE_NODE_GROUPS as readonly StageNodeGroup[]).filter((n) => !boundKeys.has(n.key))
})

const onBindNode = (nodeKey: string) => {
  if (toolRow.value) void bindNode(toolRow.value, nodeKey)
}

const onUnbindNode = (nodeKey: string) => {
  if (toolRow.value) void unbindNode(toolRow.value, nodeKey)
}

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
