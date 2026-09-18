<template>
  <div class="routes-panel">
    <!-- 头部：标题 + 改动计数 -->
    <div class="routes-panel__header">
      <div>
        <h3 class="routes-panel__title">{{ title }}</h3>
        <p class="routes-panel__desc">{{ desc }}</p>
      </div>
      <a-tag v-if="changedStages.size > 0" color="warning">
        {{ changedStages.size }} 项待保存
      </a-tag>
      <a-tag v-else>{{ STAGE_NODE_GROUPS.length }} 个编制节点</a-tag>
    </div>

    <a-spin :spinning="loading">
      <div class="routes-panel__list">
        <div
          v-for="group in nodeGroups"
          :key="group.key"
          class="node-group"
          :class="{ 'node-group--expanded': expandedGroups.has(group.key) }"
        >
          <!-- 节点头部：模型（一处编辑，组内同步） -->
          <div class="node-group__head">
            <div class="node-group__head-left">
              <span class="node-group__index">{{ group.index }}</span>
              <div class="node-group__head-info">
                <span class="node-group__name">{{ group.label }}</span>
                <div class="node-group__keys">
                  <code
                    v-for="sk in group.stageKeys"
                    :key="sk"
                    class="node-group__key"
                  >{{ sk }}</code>
                </div>
              </div>
            </div>
            <div class="node-group__head-right">
              <div class="node-group__model-field">
                <span class="node-group__label">目标模型</span>
                <a-select
                  :value="group.model || undefined"
                  placeholder="选择目标模型（留空回退全局）"
                  show-search
                  allow-clear
                  :options="modelOptions"
                  :filter-option="filterModelOption"
                  style="width: 280px"
                  @change="(value: unknown) => onGroupModelChange(group, typeof value === 'string' ? value : '')"
                />
              </div>
              <a-button
                type="text"
                size="small"
                class="node-group__expand-btn"
                @click="toggleExpand(group.key)"
              >
                {{ expandedGroups.has(group.key) ? '收起' : '参数' }}
              </a-button>
            </div>
          </div>

          <!-- 子阶段参数（展开后可见） -->
          <div v-if="expandedGroups.has(group.key)" class="node-group__body">
            <div
              v-for="route in group.routes"
              :key="route.stageKey"
              class="sub-route"
            >
              <div class="sub-route__head">
                <span class="sub-route__name">{{ route.stageName }}</span>
                <code class="sub-route__key">{{ route.stageKey }}</code>
                <a-tag v-if="!route.enabled" color="default">已停用</a-tag>
                <span v-if="route.hint" class="sub-route__hint">{{ route.hint }}</span>
              </div>
              <div class="sub-route__fields">
                <div class="sub-route__field">
                  <span class="sub-route__label">温度</span>
                  <a-input-number
                    :value="route.temperature ?? undefined"
                    :min="0"
                    :max="2"
                    :step="0.1"
                    placeholder="默认"
                    size="small"
                    @change="(v: unknown) => onNumberChange(route, 'temperature', v)"
                  />
                </div>
                <div class="sub-route__field">
                  <span class="sub-route__label">最大 Token</span>
                  <a-input-number
                    :value="route.maxTokens ?? undefined"
                    :min="1"
                    :precision="0"
                    placeholder="默认"
                    size="small"
                    @change="(v: unknown) => onNumberChange(route, 'maxTokens', v)"
                  />
                </div>
                <div class="sub-route__field">
                  <span class="sub-route__label">超时（秒）</span>
                  <a-input-number
                    :value="route.timeout ?? undefined"
                    :min="1"
                    :precision="0"
                    placeholder="默认"
                    size="small"
                    @change="(v: unknown) => onNumberChange(route, 'timeout', v)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <a-empty v-if="!loading && routes.length === 0" description="暂无阶段路由数据" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * StageRoutesPanel：阶段路由条目（P1-5，归属"语言模型"分类）.
 *
 * 8 条 stage_key 路由行按 5 个投标编制节点分组展示（归并表见
 * @/config/stageNodes，与后端 migration 0029_unify_stages 同口径）；
 * 模型在节点级一处编辑、自动同步到组内所有 stage_key（一处配置、
 * 批量生效）；温度/Token/超时保留子阶段级独立编辑（展开后可见）。
 *
 * changedStages 集合驱动导航 dirty 角标，保存经底部 footer →
 * configCenterStore.saveCurrent → registry entry.save → useRoutesConfig.save
 * 批量提交（仅触碰过的 stage_key）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useConfigCenterStore } from '@/stores/configCenter'
import { useRoutesConfig, type RoutesConfigApi } from '@/composables/useRoutesConfig'
import { useProvidersConfig } from '@/composables/useProvidersConfig'
import {
  groupRoutesByNode,
  STAGE_NODE_GROUPS,
  type StageNodeGroup,
} from '@/config/stageNodes'
import type { ModelRoute } from '@/api/providers'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '阶段路由', desc: '5 个编制节点的模型分配' },
)

const store = useConfigCenterStore()
const config: RoutesConfigApi = useRoutesConfig()
const providersConfig = useProvidersConfig()

const { loading, routes, changedStages, load, touch } = config
const { providers } = providersConfig

/**
 * 从已配置的 Provider 列表构建下拉选项（单一数据源）.
 * 仅展示 configured && enabled 的 Provider，每个 model 格式为 prefix/model-name.
 * custom 端点的实际模型名已由后端 list_providers 合并进 models 列表返回，
 * 前端无需交叉读 llm_settings。
 */
const modelOptions = computed(() => {
  const options: { label: string; value: string }[] = []
  for (const p of providers.value) {
    if (!p.configured || !p.enabled) continue
    for (const m of p.models) {
      const val = `${p.prefix}/${m}`
      options.push({ label: val, value: val })
    }
  }
  return options
})

/** a-select 搜索过滤：label/value 均参与匹配 */
const filterModelOption = (input: string, option: { label: string; value: string }) => {
  const lower = input.toLowerCase()
  return option.value.toLowerCase().includes(lower) || option.label.toLowerCase().includes(lower)
}

/** 展开状态（默认全部展开方案生成节点，其余折叠） */
const expandedGroups = ref<Set<string>>(new Set(['generate']))

const toggleExpand = (key: string) => {
  const next = new Set(expandedGroups.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedGroups.value = next
}

/** 编制节点分组行：共享归并表 + 组内路由 + 节点级模型汇总 */
interface NodeGroup extends StageNodeGroup {
  routes: ModelRoute[]
  model: string
}

/**
 * 路由按 5 个投标编制节点分组（归并口径见 @/config/stageNodes）；
 * 节点级模型取组内首条非空值（子阶段独立编辑后可能不同）。
 */
const nodeGroups = computed<NodeGroup[]>(() =>
  groupRoutesByNode(routes.value).map((g) => ({
    ...g,
    model: g.routes.find((r) => r.model)?.model ?? '',
  })),
)

/** 节点级模型编辑：同步写入组内所有 stage_key 并 touch */
const onGroupModelChange = (group: NodeGroup, value: string) => {
  for (const route of group.routes) {
    route.model = value
    touch(route.stageKey)
  }
}

type NumericRouteField = 'temperature' | 'maxTokens' | 'timeout'

/** InputNumber 受控编辑：数值/可解析数字串写回，空值写回 null */
const onNumberChange = (route: ModelRoute, field: NumericRouteField, value: unknown) => {
  if (typeof value === 'number') {
    route[field] = value
  } else if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) {
    route[field] = Number(value)
  } else {
    route[field] = null
  }
  touch(route.stageKey)
}

watch(
  () => config.isDirty.value,
  (dirty) => {
    if (dirty) {
      store.markDirty('llm:routes')
    } else {
      store.clearDirty('llm:routes')
    }
  },
  { immediate: true },
)

onMounted(() => {
  load()
  providersConfig.load()
})
</script>

<style scoped>
.routes-panel {
  max-width: 760px;
}

.routes-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.routes-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.routes-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.routes-panel__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* === 编制节点分组卡片 === */
.node-group {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color var(--transition-fast);
}

.node-group--expanded {
  border-color: var(--border-color-strong);
}

.node-group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
}

.node-group__head-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.node-group__index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.node-group__head-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.node-group__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.node-group__keys {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.node-group__key {
  font-size: 10px;
  color: var(--color-primary);
  background: var(--color-primary-lighter);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}

.node-group__head-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.node-group__model-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 280px;
}

.node-group__label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.node-group__expand-btn {
  color: var(--text-secondary);
  flex-shrink: 0;
}

/* === 子阶段参数区 === */
.node-group__body {
  border-top: 1px solid var(--border-color-light);
  padding: var(--space-2) var(--space-4) var(--space-3);
  background: var(--bg-app);
}

.sub-route {
  padding: var(--space-2) 0;
}

.sub-route + .sub-route {
  border-top: 1px dashed var(--border-color-light);
}

.sub-route__head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.sub-route__name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.sub-route__key {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-surface-hover);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}

.sub-route__hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sub-route__fields {
  display: flex;
  gap: var(--space-4);
}

.sub-route__field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.sub-route__field :deep(.ant-input-number) {
  width: 120px;
}

.sub-route__label {
  font-size: 11px;
  color: var(--text-tertiary);
}

@media (max-width: 1024px) {
  .node-group__head {
    flex-direction: column;
    align-items: flex-start;
  }

  .node-group__head-right {
    width: 100%;
  }

  .node-group__model-field {
    width: 100%;
  }

  .sub-route__fields {
    flex-wrap: wrap;
    gap: var(--space-2);
  }
}
</style>
