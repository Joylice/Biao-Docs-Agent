<template>
  <div class="skills-panel">
    <!-- 头部 -->
    <div class="skills-panel__header">
      <div>
        <h3 class="skills-panel__title">{{ title }}</h3>
        <p class="skills-panel__desc">{{ desc }}</p>
      </div>
      <a-button size="small" :loading="loading" @click="load">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <div class="skills-panel__list">
        <div
          v-for="skill in skillRows"
          :key="skill.stageKey"
          class="skill-card"
          :class="{ 'skill-card--inactive': !skill.enabled }"
        >
          <div class="skill-card__head">
            <span class="skill-card__name">{{ skill.stageName }}</span>
            <code class="skill-card__key">{{ skill.stageKey }}</code>
            <a-switch
              :checked="skill.enabled"
              size="small"
              checked-children="ON"
              un-checked-children="OFF"
              @change="(checked: unknown) => onToggle(skill.stageKey, !!checked)"
            />
          </div>
          <div class="skill-card__bindings">
            <span class="skill-card__label">绑定工具</span>
            <a-tag
              v-for="name in skill.boundToolNames"
              :key="name"
              closable
              @close="onUnbind(name, skill.stageKey)"
            >
              {{ name }}
            </a-tag>
            <a-select
              v-if="bindableTools.length > 0"
              placeholder="绑定工具"
              size="small"
              style="width: 160px"
              @change="(val: unknown) => onBind(String(val), skill.stageKey)"
            >
              <a-select-option v-for="t in bindableTools" :key="t.id" :value="t.id">
                {{ t.name }}
              </a-select-option>
            </a-select>
            <span v-if="skill.boundToolNames.length === 0 && bindableTools.length === 0" class="skill-card__muted">
              暂无可绑定工具（先在"网络搜索"分类创建）
            </span>
          </div>
        </div>
      </div>
      <a-empty v-if="!loading && skillRows.length === 0" description="暂无技能数据" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * SkillsPanel：技能分类（P1-3）——流水线阶段视图.
 *
 * 技能 = 流水线阶段：启停即时保存（PUT /settings/routes/{stage_key}
 * { enabled }），绑定工具来自 useSkillsConfig（bind/unbind 走
 * /settings/external-tools 端点）。启停/绑定均为即时操作，无表单保存
 * 语义 → registry entry.save 为 no-op。
 */
import { computed, onMounted } from 'vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { useSkillsConfig } from '@/composables/useSkillsConfig'
import type { ExternalTool } from '@/api/externalTools'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '技能列表', desc: '' },
)

const config = useSkillsConfig()

const { loading, skillRows, load, toggleEnabled, bindStage, unbindStage } = config

/** 可绑定的工具（已创建且启用） */
const bindableTools = computed<ExternalTool[]>(() =>
  config.tools.value.filter((t) => t.enabled),
)

const onToggle = (stageKey: string, checked: boolean) => {
  void toggleEnabled(stageKey, checked)
}

const onBind = (toolId: string, stageKey: string) => {
  const tool = config.tools.value.find((t) => t.id === toolId)
  if (tool) void bindStage(tool, stageKey)
}

const onUnbind = (toolName: string, stageKey: string) => {
  const tool = config.tools.value.find((t) => t.name === toolName)
  if (tool) void unbindStage(tool, stageKey)
}

onMounted(load)
</script>

<style scoped>
.skills-panel {
  max-width: 720px;
}

.skills-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.skills-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.skills-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.skills-panel__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skill-card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.skill-card--inactive {
  opacity: 0.65;
}

.skill-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.skill-card__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.skill-card__key {
  font-size: 11px;
  color: var(--color-primary);
  background: var(--color-primary-lighter);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}

.skill-card__head > :last-child {
  margin-left: auto;
}

.skill-card__bindings {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.skill-card__label {
  font-size: 11px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.skill-card__muted {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
