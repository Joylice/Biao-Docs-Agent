<template>
  <div class="empty-state">
    <a-empty :description="description">
      <template #image>
        <slot name="icon">
          <!-- folder：文件夹 + 内容线条 -->
          <svg
            v-if="illustration === 'folder'"
            class="empty-state__illustration"
            viewBox="0 0 120 96"
            width="120"
            height="96"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M12 74 V30 a6 6 0 0 1 6-6 h23 l8 10 h53 a6 6 0 0 1 6 6 v34 a6 6 0 0 1-6 6 H18 a6 6 0 0 1-6-6 Z"
              fill="var(--bg-surface-hover)"
              stroke="var(--border-color-strong)"
              stroke-width="2"
              stroke-linejoin="round"
            />
            <path
              d="M12 46 h96"
              stroke="var(--text-tertiary)"
              stroke-width="2"
              stroke-linecap="round"
            />
            <path
              d="M34 58 h36"
              stroke="var(--text-tertiary)"
              stroke-width="2"
              stroke-linecap="round"
            />
            <path
              d="M34 66 h22"
              stroke="var(--text-tertiary)"
              stroke-width="2"
              stroke-linecap="round"
            />
            <circle
              cx="92"
              cy="62"
              r="5"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
          </svg>

          <!-- box：等轴纸箱 -->
          <svg
            v-else-if="illustration === 'box'"
            class="empty-state__illustration"
            viewBox="0 0 120 96"
            width="120"
            height="96"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M60 12 L96 28 L60 44 L24 28 Z"
              fill="var(--bg-surface-hover)"
              stroke="var(--border-color-strong)"
              stroke-width="2"
              stroke-linejoin="round"
            />
            <path
              d="M24 28 V64 L60 80 V44 Z"
              fill="var(--bg-surface)"
              stroke="var(--border-color-strong)"
              stroke-width="2"
              stroke-linejoin="round"
            />
            <path
              d="M96 28 V64 L60 80 V44 Z"
              fill="var(--bg-surface)"
              stroke="var(--border-color-strong)"
              stroke-width="2"
              stroke-linejoin="round"
            />
            <path
              d="M78 20 L42 36"
              stroke="var(--text-tertiary)"
              stroke-width="2"
              stroke-linecap="round"
            />
            <path
              d="M42 36 V48"
              stroke="var(--text-tertiary)"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>

          <!-- board：看板三列 + 卡片 -->
          <svg
            v-else
            class="empty-state__illustration"
            viewBox="0 0 120 96"
            width="120"
            height="96"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <rect
              x="14"
              y="14"
              width="92"
              height="68"
              rx="8"
              fill="var(--bg-surface-hover)"
              stroke="var(--border-color-strong)"
              stroke-width="2"
            />
            <path
              d="M45 14 V82"
              stroke="var(--border-color-strong)"
              stroke-width="2"
            />
            <path
              d="M75 14 V82"
              stroke="var(--border-color-strong)"
              stroke-width="2"
            />
            <rect
              x="21"
              y="24"
              width="18"
              height="11"
              rx="2"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
            <rect
              x="21"
              y="42"
              width="18"
              height="11"
              rx="2"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
            <rect
              x="51"
              y="24"
              width="18"
              height="11"
              rx="2"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
            <rect
              x="81"
              y="24"
              width="18"
              height="11"
              rx="2"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
            <rect
              x="81"
              y="42"
              width="18"
              height="11"
              rx="2"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
            <rect
              x="81"
              y="60"
              width="18"
              height="11"
              rx="2"
              stroke="var(--text-tertiary)"
              stroke-width="2"
            />
          </svg>
        </slot>
      </template>
    </a-empty>
    <div
      v-if="$slots.action"
      class="empty-state__action"
    >
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
/** 空状态插画类型：folder 文件夹 / box 纸箱 / board 看板 */
type IllustrationKind = 'folder' | 'box' | 'board'

withDefaults(
  defineProps<{
    description?: string
    illustration?: IllustrationKind
  }>(),
  {
    description: '暂无数据',
    illustration: 'folder',
  },
)
</script>

<style scoped>
.empty-state {
  padding: 48px 16px;
  text-align: center;
}

.empty-state__icon {
  font-size: 48px;
  color: var(--text-disabled);
}

.empty-state__illustration {
  display: block;
  margin: 0 auto;
}

.empty-state__action {
  margin-top: 16px;
}
</style>
