<template>
  <div class="agent-profile">
    <table class="agent-profile__table">
      <thead>
        <tr>
          <th class="agent-profile__col-name">
            解析智能体
          </th>
          <th>调用</th>
          <th>失败</th>
          <th>成功率</th>
          <th>平均耗时</th>
          <th>Token</th>
          <th>工具留痕</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in items"
          :key="row.agent_id"
        >
          <td class="agent-profile__col-name">
            <div class="agent-profile__label">
              {{ row.label }}
            </div>
            <div class="agent-profile__id">
              {{ row.agent_id }}
            </div>
          </td>
          <td>{{ row.calls }}</td>
          <td :class="{ 'agent-profile__bad': row.failed_calls > 0 }">
            {{ row.failed_calls }}
          </td>
          <td>{{ formatRate(row) }}</td>
          <td>{{ row.calls ? `${row.avg_latency_ms}ms` : '—' }}</td>
          <td>{{ row.total_tokens }}</td>
          <td>
            {{ row.tool_rows }}/{{ row.calls }}
            <span
              v-if="row.tool_calls_total"
              class="agent-profile__sub"
            >· {{ row.tool_calls_total }} 次</span>
          </td>
        </tr>
      </tbody>
    </table>

    <p
      v-if="noToolTrace"
      class="agent-profile__note"
    >
      本窗口内没有工具调用留痕：解析工具受「解析调优 → 工具开关」与各 Agent 白名单双重控制，
      默认均为关闭，开启后此处才开始计数。
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * AgentProfileTable：解析智能体执行画像表（ADR-0004 A2 / T5）.
 *
 * 纯展示组件：数据由 RuntimePanel 经 useRuntimeConfig 取得。
 * label 一律用后端返回的中文名（前端禁止自贴名，避免同名不同源）；
 * 失败列与 Token 列必须并存 —— 失败行无 usage 计量，只看 Token 会把
 * 「有调用但全失败」误读成「没跑」。
 */
import { computed } from 'vue'
import { hasNoToolTrace, type AgentProfileItem } from '@/api/usage'

const props = defineProps<{
  items: AgentProfileItem[]
}>()

const noToolTrace = computed(() => hasNoToolTrace(props.items))

/** 零调用不显示 0.0%（会被误读为「跑了但全失败」） */
const formatRate = (row: AgentProfileItem): string =>
  row.calls === 0 ? '—' : `${(row.success_rate * 100).toFixed(1)}%`
</script>

<style scoped>
.agent-profile {
  overflow-x: auto;
}

.agent-profile__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: var(--text-primary);
}

.agent-profile__table th {
  padding: 6px var(--space-2);
  font-weight: 500;
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: right;
  white-space: nowrap;
  border-bottom: 1px solid var(--border-color);
}

.agent-profile__table td {
  padding: var(--space-2);
  text-align: right;
  font-family: var(--font-family-mono);
  white-space: nowrap;
  border-bottom: 1px solid var(--border-color);
}

.agent-profile__table tbody tr:last-child td {
  border-bottom: none;
}

.agent-profile__col-name {
  text-align: left;
}

.agent-profile__label {
  font-family: var(--font-family-sans);
  font-weight: 500;
}

.agent-profile__id {
  font-size: 11px;
  color: var(--text-tertiary);
}

.agent-profile__bad {
  color: var(--color-error);
}

.agent-profile__sub {
  color: var(--text-tertiary);
}

.agent-profile__note {
  margin: var(--space-3) 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}
</style>
