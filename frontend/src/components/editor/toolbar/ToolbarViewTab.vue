<template>
  <a-space
    wrap
    :size="2"
    class="word-toolbar__group"
  >
    <!-- 标尺（P2） -->
    <a-tooltip title="P2 实现">
      <span class="word-toolbar__switch-wrap">
        <a-switch
          v-model:checked="rulerVisible"
          size="small"
          disabled
        />
        <span class="word-toolbar__label">标尺</span>
      </span>
    </a-tooltip>

    <!-- 网格线（P2） -->
    <a-tooltip title="P2 实现">
      <span class="word-toolbar__switch-wrap">
        <a-switch
          v-model:checked="gridVisible"
          size="small"
          disabled
        />
        <span class="word-toolbar__label">网格</span>
      </span>
    </a-tooltip>

    <a-divider type="vertical" />

    <!-- 导航窗格 -->
    <span class="word-toolbar__switch-wrap">
      <a-switch
        v-model:checked="outlineVisible"
        size="small"
      />
      <span class="word-toolbar__label">导航窗格</span>
    </span>

    <a-divider type="vertical" />

    <!-- 缩放 -->
    <span class="word-toolbar__label">缩放</span>
    <a-slider
      v-model:value="zoomValue"
      :min="10"
      :max="500"
      :step="10"
      style="width: 120px"
    />
    <span class="word-toolbar__zoom-value">{{ zoomValue }}%</span>

    <a-divider type="vertical" />

    <!-- 视图模式 -->
    <a-button-group>
      <a-button
        size="small"
        type="primary"
      >
        <template #icon>
          <FileTextOutlined />
        </template>
        页面
      </a-button>
      <a-tooltip title="P2 实现">
        <a-button
          size="small"
          disabled
        >
          <template #icon>
            <ReadOutlined />
          </template>
          大纲
        </a-button>
      </a-tooltip>
    </a-button-group>
  </a-space>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { FileTextOutlined, ReadOutlined } from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'update:outlineVisible', value: boolean): void
  (e: 'update:zoom', value: number): void
}>()

/* 标尺/网格（P2 占位） */
const rulerVisible = ref(false)
const gridVisible = ref(false)

/* 导航窗格：emit 给父组件控制大纲面板显示 */
const outlineVisible = ref(false)
watch(outlineVisible, (val) => emit('update:outlineVisible', val))

/* 缩放：emit 给父组件控制纸面 transform: scale */
const zoomValue = ref(100)
watch(zoomValue, (val) => emit('update:zoom', val))
</script>

<style scoped>
.word-toolbar__group {
  width: 100%;
}

.word-toolbar__label {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.word-toolbar__switch-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.word-toolbar__zoom-value {
  font-size: 12px;
  color: var(--text-secondary, #999);
  min-width: 42px;
}
</style>
