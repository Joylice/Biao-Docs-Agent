<template>
  <Teleport to="body">
    <TransitionGroup
      name="toast"
      tag="div"
      class="global-toast-container"
    >
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="global-toast"
        :class="`global-toast--${toast.type}`"
        @click="removeToast(toast.id)"
      >
        <CheckCircleFilled
          v-if="toast.type === 'success'"
          class="global-toast__icon"
        />
        <CloseCircleFilled
          v-else-if="toast.type === 'error'"
          class="global-toast__icon"
        />
        <ExclamationCircleFilled
          v-else-if="toast.type === 'warning'"
          class="global-toast__icon"
        />
        <InfoCircleFilled
          v-else
          class="global-toast__icon"
        />
        <span class="global-toast__message">{{ toast.message }}</span>
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<script setup lang="ts">
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
} from '@ant-design/icons-vue'
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()
const toasts = uiStore.toasts
const removeToast = (id: string) => uiStore.removeToast(id)
</script>

<style scoped>
.global-toast-container {
  position: fixed;
  top: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}
.global-toast {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 280px;
  max-width: 420px;
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-lg);
  cursor: pointer;
  pointer-events: auto;
  transition: all var(--transition-normal);
}
.global-toast--success { border-left: 3px solid var(--color-success); }
.global-toast--success .global-toast__icon { color: var(--color-success); }
.global-toast--error { border-left: 3px solid var(--color-error); }
.global-toast--error .global-toast__icon { color: var(--color-error); }
.global-toast--warning { border-left: 3px solid var(--color-warning); }
.global-toast--warning .global-toast__icon { color: var(--color-warning); }
.global-toast--info { border-left: 3px solid var(--color-info); }
.global-toast--info .global-toast__icon { color: var(--color-info); }
.global-toast__icon { font-size: 18px; flex-shrink: 0; }
.global-toast__message {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  line-height: 1.5;
  word-break: break-word;
}
.toast-enter-active,
.toast-leave-active {
  transition: all var(--transition-normal);
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
