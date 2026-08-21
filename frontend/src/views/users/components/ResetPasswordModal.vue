<template>
  <a-modal
    v-model:open="resetPwdOpen"
    title="重置密码"
    ok-text="重置"
    cancel-text="取消"
    :confirm-loading="resetPwdSubmitting"
    @ok="submitResetPwd"
  >
    <p class="form-hint">
      正在重置「{{ resetPwdTarget?.display_name || resetPwdTarget?.email }}」的密码
    </p>
    <a-form
      ref="resetPwdFormRef"
      :model="resetPwdForm"
      :rules="resetPwdRules"
      layout="vertical"
    >
      <a-form-item
        label="新密码"
        name="password"
      >
        <a-input-password v-model:value="resetPwdForm.password" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { message, type FormInstance } from 'ant-design-vue'
import { resetUserPassword } from '@/api'
import { errMsg, type UserItem } from '../constants'

const resetPwdOpen = ref(false)
const resetPwdSubmitting = ref(false)
const resetPwdFormRef = ref<FormInstance>()
const resetPwdTarget = ref<UserItem | null>(null)
const resetPwdForm = reactive({ password: '' })
const resetPwdRules = {
  password: [
    { required: true, message: '请输入新密码' },
    { min: 6, message: '密码至少 6 位' },
  ],
}

const open = (record: UserItem) => {
  resetPwdTarget.value = record
  resetPwdForm.password = ''
  resetPwdOpen.value = true
}

const submitResetPwd = async () => {
  await resetPwdFormRef.value?.validate()
  if (!resetPwdTarget.value) return
  resetPwdSubmitting.value = true
  try {
    const { data } = await resetUserPassword(resetPwdTarget.value.id, resetPwdForm.password)
    if (data.code === 0) {
      message.success('密码已重置')
      resetPwdOpen.value = false
    } else {
      message.error(data.message || '重置失败')
    }
  } catch (e) {
    message.error(errMsg(e, '重置密码失败'))
  } finally {
    resetPwdSubmitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.form-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
