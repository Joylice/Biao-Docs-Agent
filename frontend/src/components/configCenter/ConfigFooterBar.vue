<template>
  <div class="config-footer">
    <div class="config-footer__hint">
      <template v-if="dirtyCount > 0">
        <span class="config-footer__dot" />
        <span>{{ currentDirty ? '当前条目有未保存改动' : `${dirtyCount} 个条目有未保存改动` }}</span>
      </template>
      <template v-else>
        <span class="config-footer__hint-idle">所有改动均已保存</span>
      </template>
    </div>
    <div class="config-footer__actions">
      <a-button @click="store.requestClose()">关闭</a-button>
      <a-button
        type="primary"
        :loading="isSaving"
        :disabled="!store.activeItemId || store.savingId !== null"
        @click="store.saveCurrent()"
      >
        保存
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 配置中心弹窗底部操作栏（自定义 footer 插槽内容，ARCH §1.3）。
 *
 * 左侧：脏状态提示（当前条目优先展示，否则展示全局未保存计数）；
 * 右侧：关闭（走 requestClose 确认流）/ 保存（走当前条目 saveHandler，
 * 保存中禁用全部保存入口，成功后 store 自动 clearDirty + bumpOverview）。
 */
import { computed } from 'vue'
import { useConfigCenterStore } from '@/stores/configCenter'

const store = useConfigCenterStore()

const dirtyCount = computed(() => store.dirtyItems.size)
const currentDirty = computed(
  () => store.activeItemId !== null && store.dirtyItems.has(store.activeItemId),
)
const isSaving = computed(
  () => store.savingId !== null && store.savingId === store.activeItemId,
)
</script>

<style scoped>
.config-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 12px 20px;
  border-top: 1px solid var(--border-color-light);
  background: var(--bg-surface);
}

.config-footer__hint {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 0;
}

.config-footer__hint-idle {
  color: var(--text-tertiary);
}

.config-footer__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-warning);
  flex-shrink: 0;
}

.config-footer__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
</style>
