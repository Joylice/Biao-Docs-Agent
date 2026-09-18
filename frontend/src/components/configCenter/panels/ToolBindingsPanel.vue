<template>
  <div class="tool-bindings-panel">
    <!-- 头部 -->
    <div class="tool-bindings-panel__header">
      <div>
        <h3 class="tool-bindings-panel__title">{{ title }}</h3>
        <p class="tool-bindings-panel__desc">
          {{ desc || '以外部工具为主，按绑定的投标编制节点归类；每个工具可绑定到其所属节点下的阶段。' }}
        </p>
      </div>
      <a-button size="small" :loading="loading" @click="load">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <div class="tool-bindings-panel__list">
        <div
          v-for="tool in toolRows"
          :key="tool.toolId"
          class="tool-card"
          :class="{ 'tool-card--inactive': !tool.toolEnabled }"
        >
          <!-- 工具为主实体：名称 + 关联编制节点徽标 + 工具启用态（展示） -->
          <div class="tool-card__head">
            <span class="tool-card__name">{{ tool.toolName }}</span>
            <a-tag
              v-for="label in tool.nodeLabels"
              :key="label"
              class="tool-card__node"
            >{{ label }}</a-tag>
            <a-tag
              v-if="tool.nodeLabels.length === 0"
              class="tool-card__node tool-card__node--none"
            >未关联编制节点</a-tag>
            <a-tag
              class="tool-card__tool-state"
              :color="tool.toolEnabled ? 'green' : 'default'"
            >{{ tool.toolEnabled ? '工具启用' : '工具停用' }}</a-tag>
          </div>

          <!-- 该工具绑定的阶段（含逐阶段启停 / 解绑）+ 绑定新阶段的下拉 -->
          <div class="tool-card__bindings">
            <span class="tool-card__label">绑定阶段</span>
            <span
              v-for="s in tool.boundStages"
              :key="s.stageKey"
              class="tool-card__stage"
              :class="{ 'tool-card__stage--off': !s.stageEnabled }"
            >
              <code class="tool-card__stage-key">{{ s.stageKey }}</code>
              <span class="tool-card__stage-name">{{ s.stageName }}</span>
              <a-switch
                :checked="s.stageEnabled"
                size="small"
                checked-children="ON"
                un-checked-children="OFF"
                @change="(c: unknown) => onToggleStage(s.stageKey, !!c)"
              />
              <CloseOutlined
                class="tool-card__unbind"
                title="解绑该阶段"
                @click="onUnbindStage(tool.toolId, s.stageKey)"
              />
            </span>
            <span v-if="tool.boundStages.length === 0" class="tool-card__muted">
              尚未绑定任何阶段
            </span>

            <a-select
              v-if="stagesUnbound(tool).length > 0"
              placeholder="绑定到阶段"
              size="small"
              style="width: 200px"
              @change="(val: unknown) => onBindStage(tool.toolId, String(val))"
            >
              <a-select-opt-group
                v-for="node in nodeGroups"
                :key="node.key"
                :label="node.label"
              >
                <a-select-option
                  v-for="s in stagesOfNodeUnbound(node, tool)"
                  :key="s.stageKey"
                  :value="s.stageKey"
                >{{ s.stageName }} · {{ s.stageKey }}</a-select-option>
              </a-select-opt-group>
            </a-select>
            <span v-else class="tool-card__muted">已绑定全部阶段</span>
          </div>
        </div>
      </div>
      <a-empty v-if="!loading && toolRows.length === 0" description="暂无外部工具" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * ToolBindingsPanel：外部工具管理 —— 工具为主、关联编制节点视图.
 *
 * 🔴 S4 改名说明：本文件原名 `SkillsPanel.vue`。SKILL.md 契约体系（S4）引入后，
 * 「skill」这个名字被让给行为准则资产（SkillPanel.vue），本面板管理的其实是
 * 「外部工具 ↔ 编制阶段绑定」，故更名为 ToolBindingsPanel（语义对齐）。
 *
 * 与「阶段路由」面板不同，本页不按 5 个编制节点做分组区，而是以「外部工具」
 * 为主实体：每张卡 = 一个工具，卡内展示它关联的编制节点（经 @/config/stageNodes
 * 归并）及已绑定阶段。绑定关系本质仍是「阶段 ↔ 工具」（后端 bind/unbind 以
 * stage_key 为键），启停 = PUT /settings/routes/{stage_key} { enabled }，均为
 * 即时操作，无表单保存语义 → registry entry.save 为 no-op。
 */
import { onMounted } from 'vue'
import { ReloadOutlined, CloseOutlined } from '@ant-design/icons-vue'
import { useToolBindingsConfig } from '@/composables/useToolBindingsConfig'
import type { ExternalTool } from '@/api/externalTools'
import type { ToolRow } from '@/composables/useToolBindingsConfig'
import { STAGE_NODE_GROUPS, type StageNodeGroup } from '@/config/stageNodes'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '外部工具', desc: '' },
)

const config = useToolBindingsConfig()

const { loading, toolRows, routes, tools, load, toggleEnabled, bindStage, unbindStage } = config

/** 5 个投标编制节点（用于绑定下拉的分组） */
const nodeGroups = STAGE_NODE_GROUPS as readonly StageNodeGroup[]

/** 工具尚未绑定的阶段（用于绑定下拉总集） */
function stagesUnbound(tool: ToolRow) {
  const bound = new Set(tool.boundStages.map((s) => s.stageKey))
  return routes.value.filter((r) => !bound.has(r.stageKey))
}

/** 某编制节点下、该工具尚未绑定的阶段（绑定下拉的分组项） */
function stagesOfNodeUnbound(node: StageNodeGroup, tool: ToolRow) {
  const bound = new Set(tool.boundStages.map((s) => s.stageKey))
  return routes.value.filter((r) => node.stageKeys.includes(r.stageKey) && !bound.has(r.stageKey))
}

const onToggleStage = (stageKey: string, checked: boolean) => {
  void toggleEnabled(stageKey, checked)
}

const onBindStage = (toolId: string, stageKey: string) => {
  const tool = tools.value.find((t: ExternalTool) => t.id === toolId)
  if (tool) void bindStage(tool, stageKey)
}

const onUnbindStage = (toolId: string, stageKey: string) => {
  const tool = tools.value.find((t: ExternalTool) => t.id === toolId)
  if (tool) void unbindStage(tool, stageKey)
}

onMounted(load)
</script>

<style scoped>
.tool-bindings-panel {
  max-width: 760px;
}

.tool-bindings-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.tool-bindings-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.tool-bindings-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.tool-bindings-panel__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.tool-card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.tool-card--inactive {
  opacity: 0.65;
}

.tool-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}

.tool-card__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.tool-card__node {
  font-size: 11px;
  color: var(--color-primary);
  background: var(--color-primary-lighter);
  border-color: transparent;
}

.tool-card__node--none {
  color: var(--text-tertiary);
  background: var(--bg-muted, #f0f0f0);
}

.tool-card__head > :last-child {
  margin-left: auto;
}

.tool-card__bindings {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.tool-card__label {
  font-size: 11px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.tool-card__stage {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  background: var(--bg-muted, #f5f5f5);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
}

.tool-card__stage--off {
  opacity: 0.6;
}

.tool-card__stage-key {
  font-size: 11px;
  color: var(--color-primary);
}

.tool-card__stage-name {
  font-size: 12px;
  color: var(--text-primary);
}

.tool-card__unbind {
  font-size: 12px;
  color: var(--text-tertiary);
  cursor: pointer;
}

.tool-card__unbind:hover {
  color: var(--color-danger, #ff4d4f);
}

.tool-card__muted {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
