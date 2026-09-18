<template>
  <div class="auto-review">
    <div class="auto-review__head">
      <span class="auto-review__title">
        <RobotOutlined />
        AI 自动审阅意见
      </span>
      <a-tag
        v-if="list.length > 0"
        color="blue"
        class="auto-review__count"
      >
        {{ list.length }} 条
      </a-tag>
      <a-tag
        v-else
        class="auto-review__count"
      >
        无
      </a-tag>
    </div>

    <!-- 空态不隐藏：「没有自动意见」本身是有效信息（审阅环节被跳过） -->
    <div
      v-if="list.length === 0"
      class="auto-review__empty"
    >
      本次审阅未生成自动审阅意见（审阅阶段未配置模型或调用失败时为空，不影响人工审阅）
    </div>

    <div
      v-else
      class="auto-review__list"
    >
      <div
        v-for="(item, index) in list"
        :key="`${item.chapter_no}-${index}`"
        class="auto-review__item"
      >
        <div class="auto-review__item-head">
          <a-tag
            :color="severityColor(item.severity)"
            class="auto-review__tag"
          >
            {{ severityLabel(item.severity) }}
          </a-tag>
          <span
            class="auto-review__chapter"
            :title="chapterLabel(item.chapter_no)"
          >
            {{ chapterLabel(item.chapter_no) }}
          </span>
          <a-tag
            v-if="actionLabel(item.action)"
            class="auto-review__tag"
          >
            {{ actionLabel(item.action) }}
          </a-tag>
          <a-button
            type="link"
            size="small"
            @click="emit('locate', item.chapter_no)"
          >
            定位
          </a-button>
        </div>
        <div class="auto-review__text">
          {{ item.comment }}
        </div>
      </div>
    </div>

    <div
      v-if="list.length > 0"
      class="auto-review__footnote"
    >
      意见在首次进入方案评审时生成一次（打回反馈后不再重跑），基于各章内容摘要，仅供参考，最终以人工审阅结论为准
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ReviewAutoComments：AI 自动审阅意见卡片（review 节点 interrupt 前一轮 LLM 输出）.
 *
 * 数据源 = 工作流 state.review_comments（后端 workflow_runtime.get_status_dict 透出，
 * 与 interrupt.payload.auto_comments 同源）。空态**刻意不隐藏**：「没有自动意见」
 * 本身是有效信息（审阅阶段未配模型 / 调用失败即被跳过）。
 *
 * 🔴 生成时机：由后端 `auto_review_node` 在**首次到达审阅阶段时跑一次**
 * （图：integrate → auto_review → review）；反馈回环 review_route → "review" 绕过该节点
 * ⇒ 打回反馈后卡片仍展示首轮意见、**不再重跑 LLM**。故文案必须写明「首轮生成」——
 * 否则用户会误以为看到的是针对当前修订稿的最新意见。
 *
 * 口径（勿凭记忆改写）：
 * - severity：info|warning|critical
 * - action：keep|revise|rewrite
 * 两者均取自 `backend/prompts/review.yaml`，与 review_service 的 JSON schema 一致。
 *
 * 纯展示组件，不做任何写操作；「定位」只 emit，由父组件按当前审阅单元粒度解析
 * （自动意见的 chapter_no 是章级，分工模式下审阅单元是子节）。
 */
import { computed } from 'vue'
import { RobotOutlined } from '@ant-design/icons-vue'
import type { AutoReviewComment } from '@/types'

const props = withDefaults(
  defineProps<{
    /** AI 自动审阅意见（后端 review_comments） */
    comments?: AutoReviewComment[]
    /** 章节号 → 标题（缺省回退「章节 <号>」） */
    titles?: Record<string, string>
  }>(),
  { comments: () => [], titles: () => ({}) },
)

const emit = defineEmits<{ (e: 'locate', chapterNo: string): void }>()

const list = computed<AutoReviewComment[]>(() => props.comments ?? [])

/** 严重程度 → 标签配色（未分级不编造，原样透出） */
const SEVERITY_META: Record<string, { color: string; label: string }> = {
  critical: { color: 'red', label: '严重' },
  warning: { color: 'orange', label: '关注' },
  info: { color: 'default', label: '提示' },
}

/** 建议操作 → 中文（未知取值回落空串，不显示该标签） */
const ACTION_LABELS: Record<string, string> = {
  keep: '可保留',
  revise: '建议修改',
  rewrite: '建议重写',
}

const severityLabel = (severity?: string): string =>
  severity ? (SEVERITY_META[severity]?.label ?? severity) : '未分级'

const severityColor = (severity?: string): string =>
  severity ? (SEVERITY_META[severity]?.color ?? 'default') : 'default'

const actionLabel = (action?: string): string => (action ? (ACTION_LABELS[action] ?? '') : '')

const chapterLabel = (chapterNo: string): string => {
  const title = props.titles?.[chapterNo]
  return title ? `${chapterNo} ${title}` : `章节 ${chapterNo}`
}
</script>

<style scoped>
.auto-review {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 16px 0;
}

.auto-review__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.auto-review__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.auto-review__count {
  font-size: 11px;
  margin: 0;
}

.auto-review__empty,
.auto-review__footnote {
  font-size: 12px;
  color: var(--text-tertiary, #888);
  line-height: 1.5;
}

.auto-review__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}

.auto-review__item {
  padding: 8px 12px;
  background: var(--bg-surface, #2a2a2a);
  border: 1px solid var(--border-color, #444);
  border-left: 3px solid #1890ff;
  border-radius: 6px;
}

.auto-review__item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.auto-review__tag {
  font-size: 10px;
  margin: 0;
}

.auto-review__chapter {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #ccc);
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.auto-review__text {
  font-size: 12px;
  color: var(--text-secondary, #ccc);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
