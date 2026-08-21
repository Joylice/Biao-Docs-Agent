<template>
  <div class="login-page">
    <div class="login-page__card">
      <div class="login-page__brand">
        <span class="login-page__logo">
          <FileSearchOutlined />
        </span>
        <h1 class="login-page__title">
          投标软件技术方案智能体
        </h1>
        <p class="login-page__subtitle">
          招标解析 · 评分对标 · 方案生成 · Word 导出
        </p>
      </div>
      <a-form
        :model="form"
        @finish="handleLogin"
      >
        <a-form-item
          name="username"
          :rules="[{ required: true, message: '请输入用户名' }]"
        >
          <a-input
            v-model:value="form.username"
            placeholder="用户名"
            size="large"
          >
            <template #prefix>
              <UserOutlined />
            </template>
          </a-input>
        </a-form-item>
        <a-form-item
          name="password"
          :rules="[{ required: true, message: '请输入密码' }]"
        >
          <a-input-password
            v-model:value="form.password"
            placeholder="密码"
            size="large"
          >
            <template #prefix>
              <LockOutlined />
            </template>
          </a-input-password>
        </a-form-item>
        <a-form-item>
          <a-button
            type="primary"
            html-type="submit"
            size="large"
            block
            :loading="loading"
          >
            登录
          </a-button>
        </a-form-item>
      </a-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { FileSearchOutlined, LockOutlined, UserOutlined } from '@ant-design/icons-vue'
import { login } from '@/api'

interface ApiErrorBody {
  code?: number
  message?: string
}

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

const handleLogin = async () => {
  loading.value = true
  try {
    // 同时发送 username 和 email，兼容新旧后端（新后端优先 username，旧后端用 email）
    const payload = { username: form.username, email: form.username, password: form.password }
    const { data } = await login(payload)
    if (data.code === 0) {
      localStorage.setItem('access_token', data.data.access_token)
      if (data.data.refresh_token) {
        localStorage.setItem('refresh_token', data.data.refresh_token)
      }
      message.success('登录成功')
      // 登录前被守卫拦截时携带的 redirect 回跳地址；无回跳默认进入工作台
      const redirect = route.query.redirect as string | undefined
      router.push(redirect && redirect.startsWith('/') ? redirect : { name: 'Workbench' })
    }
  } catch (error) {
    const body = (error as { response?: { data?: ApiErrorBody } })?.response?.data
    message.error(body?.message || '登录失败，请检查用户名和密码')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-6);
  background: var(--bg-login-gradient);
}

.login-page__card {
  width: 400px;
  padding: 40px 36px 28px;
  border-radius: 10px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-deep);
}

.login-page__brand {
  text-align: center;
  margin-bottom: 28px;
}

.login-page__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  margin-bottom: var(--space-3);
  border-radius: 12px;
  background: var(--color-primary);
  color: var(--text-inverse);
  font-size: 28px;
}

.login-page__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.login-page__subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
