<template>
  <div class="parse-warnings-panel">
    <!-- 页顶告警总览（仅非空时渲染） -->
    <a-alert
      v-if="warnings.length > 0"
      :type="hasHighSeverity ? 'error' : 'warning'"
      :show-icon="true"
      class="parse-warnings-panel__summary"
    >
      <template #message>
        <span>解析交叉校验发现 {{ warnings.length }} 条告警</span>
        <a-tag v-if="highCount > 0" color="red" class="ml-2">高风险 {{ highCount }}</a-tag>
        <a-tag v-if="midCount > 0" color="orange" class="ml-1">中风险 {{ midCount }}</a-tag>
        <a-tag v-if="lowCount > 0" color="blue" class="ml-1">建议 {{ lowCount }}</a-tag>
      </template>
    </a-alert>

    <!-- 无告警时不渲染任何内容（空态不展示） -->
    <template v-if="warnings.length > 0">
      <!-- 折叠明细 -->
      <a-collapse
        :bordered="false"
        class="parse-warnings-panel__collapse"
      >
        <a-collapse-panel key="details" header="告警明细">
          <a-list
            :data-source="warnings"
            size="small"
          >
            <template #renderItem="{ item }">
              <a-list-item>
                <a-list-item-meta>
                  <template #title>
                    <div class="parse-warnings-panel__item-title">
                      <a-tag :color="warningSeverityColor(item.severity)">
                        {{ severityLabel(item.severity) }}
                      </a-tag>
                      <a-tag>{{ warningTypeLabel(item.type) }}</a-tag>
                      <span class="parse-warnings-panel__item-message">{{ item.message }}</span>
                    </div>
                  </template>
                </a-list-item-meta>
              </a-list-item>
            </template>
          </a-list>
        </a-collapse-panel>
      </a-collapse>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  warningSeverityColor,
  WARNING_TYPE_LABELS,
  type ParseWarning,
} from '@/types'

const props = defineProps<{
  warnings: ParseWarning[]
}>()

const hasHighSeverity = computed(() => props.warnings.some((w) => w.severity === 'high'))
const highCount = computed(() => props.warnings.filter((w) => w.severity === 'high').length)
const midCount = computed(() => props.warnings.filter((w) => w.severity === 'mid').length)
const lowCount = computed(() => props.warnings.filter((w) => w.severity === 'low').length)

const warningTypeLabel = (type: string): string => WARNING_TYPE_LABELS[type] || type

const severityLabel = (severity: string): string => {
  const map: Record<string, string> = {
    high: '高风险',
    mid: '中风险',
    low: '建议',
  }
  return map[severity] || severity
}
</script>

<style scoped>
.parse-warnings-panel {
  width: 100%;
}

.parse-warnings-panel__summary {
  margin-bottom: 12px;
}

.parse-warnings-panel__collapse {
  margin-top: 4px;
}

.parse-warnings-panel__item-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.parse-warnings-panel__item-message {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.ml-1 { margin-left: 4px; }
.ml-2 { margin-left: 8px; }
</style>
