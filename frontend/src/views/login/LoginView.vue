<template>
  <div class="login-container">
    <a-card
      title="投标软件技术方案智能体"
      class="login-card"
    >
      <a-form
        :model="form"
        @finish="handleLogin"
      >
        <a-form-item
          name="email"
          :rules="[{ required: true, message: '请输入邮箱' }]"
        >
          <a-input
            v-model:value="form.email"
            placeholder="邮箱"
            size="large"
          />
        </a-form-item>
        <a-form-item
          name="password"
          :rules="[{ required: true, message: '请输入密码' }]"
        >
          <a-input-password
            v-model:value="form.password"
            placeholder="密码"
            size="large"
          />
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
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/client'

const router = useRouter()
const loading = ref(false)
const form = reactive({
  email: '',
  password: '',
})

const handleLogin = async () => {
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', form)
    if (data.code === 0) {
      localStorage.setItem('access_token', data.data.access_token)
      router.push({ name: 'Projects' })
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: #f0f2f5;
}
.login-card {
  width: 400px;
}
</style>
