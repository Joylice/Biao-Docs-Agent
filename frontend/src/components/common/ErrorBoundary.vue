<template>
  <div
    v-if="hasError"
    class="error-boundary"
  >
    <a-result
      status="error"
      title="页面渲染异常"
      sub-title="抱歉，页面发生了意外错误"
    >
      <template #extra>
        <a-space>
          <a-button @click="reload">
            刷新页面
          </a-button>
          <a-button
            type="primary"
            @click="goHome"
          >
            返回首页
          </a-button>
        </a-space>
      </template>
    </a-result>
    <div
      v-if="errorMessage"
      class="error-boundary__detail"
    >
      <a-alert
        type="error"
        :message="errorMessage"
        show-icon
      />
    </div>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
import { ref, onErrorCaptured, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const hasError = ref(false)
const errorMessage = ref('')
const router = useRouter()

onErrorCaptured((err) => {
  hasError.value = true
  errorMessage.value = err instanceof Error ? err.message : String(err)
  console.error('[ErrorBoundary] 捕获到组件错误:', err)
  return false
})

const reload = () => {
  hasError.value = false
  errorMessage.value = ''
  window.location.reload()
}

const goHome = () => {
  hasError.value = false
  errorMessage.value = ''
  router.push('/')
}

// 全局未捕获错误监听
onMounted(() => {
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[ErrorBoundary] 未处理的 Promise 拒绝:', event.reason)
  })
})
</script>

<style scoped>
.error-boundary {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 24px;
}

.error-boundary__detail {
  max-width: 600px;
  width: 100%;
  margin-top: 16px;
}
</style>
