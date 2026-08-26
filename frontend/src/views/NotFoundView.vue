<template>
  <div class="not-found">
    <div class="not-found__code">404</div>
    <h1 class="not-found__title">页面不存在</h1>
    <p class="not-found__desc">您访问的页面不存在或已被移除</p>
    <a-button
      type="primary"
      size="large"
      @click="router.push({ name: 'Workbench' })"
    >
      <template #icon>
        <HomeOutlined />
      </template>
      返回工作台
    </a-button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { HomeOutlined } from '@ant-design/icons-vue'

const router = useRouter()
</script>

<style scoped>
.not-found {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  background: var(--bg-app);
  text-align: center;
  padding: var(--space-6);
}

.not-found__code {
  font-size: 96px;
  font-weight: 800;
  line-height: 1;
  color: var(--color-primary);
  opacity: 0.85;
  letter-spacing: 4px;
}

.not-found__title {
  font-size: var(--font-size-xl);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.not-found__desc {
  font-size: var(--font-size-md);
  color: var(--text-secondary);
  margin: 0 0 var(--space-3);
}
</style>
