<template>
  <button
    class="theme-toggle"
    :title="toggleLabel"
    :aria-label="toggleLabel"
    @click="toggleTheme"
  >
    <BulbFilled v-if="isDark" />
    <BulbOutlined v-else />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { BulbOutlined, BulbFilled } from '@ant-design/icons-vue'
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()
// storeToRefs 保持 isDark 计算属性的响应性（直接解构 store 实例会丢失）
const { isDark } = storeToRefs(uiStore)
// aria-label 与 title 同值（图标按钮无障碍）
const toggleLabel = computed(() => (isDark.value ? '切换到浅色模式' : '切换到深色模式'))
const toggleTheme = () => uiStore.toggleTheme()
</script>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 16px;
}
.theme-toggle:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}
</style>
