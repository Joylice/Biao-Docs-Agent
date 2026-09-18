<template>
  <div class="runtime-panel">
    <!-- 头部：标题 -->
    <div class="runtime-panel__header">
      <div>
        <h3 class="runtime-panel__title">
          {{ title }}
        </h3>
        <p class="runtime-panel__desc">
          {{ desc }}
        </p>
      </div>
    </div>

    <a-spin :spinning="loading">
      <!-- ── Mock 运行控制 ── -->
      <div class="runtime-panel__card">
        <div class="runtime-panel__card-title">
          <span>运行模式</span>
        </div>
        <div class="runtime-panel__mode">
          <div class="runtime-panel__mode-info">
            <div class="runtime-panel__mode-name">
              Mock 模式
            </div>
            <div class="runtime-panel__mode-desc">
              开启后不调用真实 LLM，使用预设 Mock 数据返回。用于开发调试、演示和 CI 回归测试。
            </div>
          </div>
          <a-switch
            :checked="mockEnabled"
            :loading="saving"
            checked-children="开启"
            un-checked-children="关闭"
            @change="(checked: boolean | string | number) => onMockChange(Boolean(checked))"
          />
        </div>
        <a-alert
          v-if="mockEnabled"
          type="warning"
          show-icon
          class="runtime-panel__alert"
          message="当前为 Mock 模式，所有 LLM 调用返回预设数据，不会产生真实输出"
        />
      </div>

      <!-- ── 用量摘要 ── -->
      <div class="runtime-panel__card">
        <div class="runtime-panel__card-title">
          <span>用量摘要（近 30 天）</span>
        </div>
        <div
          v-if="usage"
          class="runtime-panel__usage"
        >
          <div class="runtime-panel__usage-item">
            <span class="runtime-panel__usage-label">调用次数</span>
            <span class="runtime-panel__usage-value">{{ usage.total_calls }}</span>
          </div>
          <div class="runtime-panel__usage-item">
            <span class="runtime-panel__usage-label">成功率</span>
            <span class="runtime-panel__usage-value">{{ (usage.success_rate * 100).toFixed(1) }}%</span>
          </div>
          <div class="runtime-panel__usage-item">
            <span class="runtime-panel__usage-label">总 Token</span>
            <span class="runtime-panel__usage-value">{{ usage.total_tokens }}</span>
          </div>
          <div class="runtime-panel__usage-item">
            <span class="runtime-panel__usage-label">平均延迟</span>
            <span class="runtime-panel__usage-value">{{ usage.avg_latency_ms }}ms</span>
          </div>
        </div>
        <a-empty
          v-else
          description="暂无用量数据"
        />
      </div>

      <!-- ── 解析智能体执行画像（ADR-0004 A2）── -->
      <div class="runtime-panel__card">
        <div class="runtime-panel__card-title">
          <span>解析智能体执行画像（近 30 天）</span>
        </div>
        <AgentProfileTable
          v-if="agentProfiles?.items.length"
          :items="agentProfiles.items"
        />
        <a-empty
          v-else
          description="暂无解析智能体调用数据"
        />
        <div class="runtime-panel__hint">
          按 llm_usage_log.agent_id 归属统计：失败行不含 Token 计量，
          故「调用/失败」与「Token」需分开看；「工具留痕」为带工具调用记录的调用次数。
        </div>
      </div>

      <!-- ── Token 用量趋势（智能体/模型双口径）── -->
      <div class="runtime-panel__card">
        <div class="runtime-panel__card-title">
          <span>{{ trendDimension === 'model' ? '各模型 Token 用量（近 30 天）' : '各智能体 Token 用量（近 30 天）' }}</span>
          <!-- 单向绑定：v-model 回写先于 @change 会使命中 setTrendDimension 的幂等早退，导致不重新拉数 -->
          <a-radio-group
            :value="trendDimension"
            size="small"
            button-style="solid"
            class="runtime-panel__dim"
            @change="onDimensionChange"
          >
            <a-radio-button value="agent">
              按智能体
            </a-radio-button>
            <a-radio-button value="model">
              按模型
            </a-radio-button>
          </a-radio-group>
        </div>
        <UsageTrendChart
          :dates="usageTrend?.dates ?? []"
          :series="usageTrend?.series ?? []"
        />
        <div class="runtime-panel__hint">
          {{ trendDimension === 'model'
            ? '按模型统计每日 Token 消耗（跨路由变更的历史数据可看出费用集中在哪个模型）'
            : '按业务智能体统计每日 Token 消耗（招标解析 = 文件解析 + 评分点解析）；悬浮图例可查看阶段与模型构成' }}
        </div>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * RuntimePanel：系统设置分类面板（P1-4，迁移 RuntimeView 逻辑）.
 *
 * 本轮改造：移除审计日志表格（独立页面 views/audit/AuditLogsView.vue 已覆盖），
 * 改为「各智能体 Token 用量」折线图（UsageTrendChart），
 * 并新增「解析智能体执行画像」表（AgentProfileTable，ADR-0004 A2）。
 * mock 开关为即改即存（确认流 + 失败回滚），本面板无表单保存语义，
 * registry entry.save 为 no-op。
 */
import { onMounted } from 'vue'
import type { RadioChangeEvent } from 'ant-design-vue'
import { useRuntimeConfig, type TrendDimension } from '@/composables/useRuntimeConfig'
import UsageTrendChart from '../UsageTrendChart.vue'
import AgentProfileTable from '../AgentProfileTable.vue'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '运行控制', desc: '' },
)

const config = useRuntimeConfig()

const { loading, saving, mockEnabled, usage, usageTrend, agentProfiles, trendDimension, load, setMock, setTrendDimension } = config

const onMockChange = (next: boolean) => {
  void setMock(next)
}

const onDimensionChange = (event: RadioChangeEvent) => {
  // antd @change 先于 v-model 回写触发：必须从事件负载取目标值，
  // 读 trendDimension.value 会拿到旧值导致幂等早退、数据不重取
  const next = (event?.target?.value as TrendDimension | undefined) ?? trendDimension.value
  void setTrendDimension(next)
}

onMounted(load)
</script>

<style scoped>
.runtime-panel {
  max-width: 760px;
}

.runtime-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.runtime-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.runtime-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.runtime-panel__card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-3);
}

.runtime-panel__card-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.runtime-panel__dim {
  margin-left: auto;
  font-weight: 400;
}

.runtime-panel__mode {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--bg-app);
  border-radius: var(--radius-md);
}

.runtime-panel__mode-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.runtime-panel__mode-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}

.runtime-panel__alert {
  margin-top: var(--space-2);
}

.runtime-panel__usage {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

.runtime-panel__usage-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-app);
  border-radius: var(--radius-sm);
}

.runtime-panel__usage-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.runtime-panel__usage-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-family-mono);
}

.runtime-panel__hint {
  margin-top: var(--space-2);
  font-size: 12px;
  color: var(--text-tertiary);
}

@media (max-width: 768px) {
  .runtime-panel__usage {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
