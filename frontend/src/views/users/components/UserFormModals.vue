<template>
  <a-modal
    v-model:open="createOpen"
    title="新建用户"
    ok-text="创建"
    cancel-text="取消"
    :confirm-loading="createSubmitting"
    @ok="submitCreate"
  >
    <a-form
      ref="createFormRef"
      :model="createForm"
      :rules="createRules"
      layout="vertical"
    >
      <a-form-item
        label="邮箱"
        name="email"
      >
        <a-input
          v-model:value="createForm.email"
          placeholder="user@example.com"
        />
      </a-form-item>
      <a-form-item
        label="姓名"
        name="display_name"
      >
        <a-input v-model:value="createForm.display_name" />
      </a-form-item>
      <a-form-item
        label="初始密码"
        name="password"
      >
        <a-input-password v-model:value="createForm.password" />
      </a-form-item>
      <a-form-item
        label="角色"
        name="role"
      >
        <a-select
          v-model:value="createForm.role"
          :options="roleOptions"
        />
      </a-form-item>
    </a-form>
  </a-modal>

  <a-modal
    v-model:open="editOpen"
    title="编辑用户"
    ok-text="保存"
    cancel-text="取消"
    :confirm-loading="editSubmitting"
    @ok="submitEdit"
  >
    <a-form
      ref="editFormRef"
      :model="editForm"
      :rules="editRules"
      layout="vertical"
    >
      <a-form-item
        label="姓名"
        name="display_name"
      >
        <a-input v-model:value="editForm.display_name" />
      </a-form-item>
      <a-form-item
        label="角色"
        name="role"
      >
        <a-select
          v-model:value="editForm.role"
          :options="roleOptions"
          :disabled="editIsSelf"
        />
        <div
          v-if="editIsSelf"
          class="form-hint"
        >
          不能变更自己的角色
        </div>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { message, type FormInstance } from 'ant-design-vue'
import { createUser, updateUser } from '@/api'
import { currentUserId, type UserRole } from '@/stores/currentUser'
import { roleOptions, errMsg, type UserItem } from '../constants'

const emit = defineEmits<{
  /** 新建成功，父组件重置分页并刷新列表 */
  (e: 'created'): void
  /** 编辑成功，父组件刷新列表与自身角色状态 */
  (e: 'updated'): void
}>()

/* ---------------- 新建用户 ---------------- */
const createOpen = ref(false)
const createSubmitting = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({ email: '', display_name: '', password: '', role: 'member' as UserRole })
const createRules = {
  email: [
    { required: true, message: '请输入邮箱' },
    { type: 'email' as const, message: '邮箱格式不正确' },
  ],
  display_name: [{ required: true, message: '请输入姓名' }],
  password: [
    { required: true, message: '请输入初始密码' },
    { min: 6, message: '密码至少 6 位' },
  ],
}

const openCreate = () => {
  createForm.email = ''
  createForm.display_name = ''
  createForm.password = ''
  createForm.role = 'member'
  createOpen.value = true
}

const submitCreate = async () => {
  await createFormRef.value?.validate()
  createSubmitting.value = true
  try {
    const { data } = await createUser({ ...createForm })
    if (data.code === 0) {
      message.success('用户已创建')
      createOpen.value = false
      emit('created')
    } else {
      message.error(data.message || '创建失败')
    }
  } catch (e) {
    message.error(errMsg(e, '创建用户失败'))
  } finally {
    createSubmitting.value = false
  }
}

/* ---------------- 编辑用户 ---------------- */
const editOpen = ref(false)
const editSubmitting = ref(false)
const editFormRef = ref<FormInstance>()
const editTarget = ref<UserItem | null>(null)
const editForm = reactive({ display_name: '', role: 'member' as UserRole })
const editRules = {
  display_name: [{ required: true, message: '请输入姓名' }],
}
const editIsSelf = computed(() => editTarget.value?.id === currentUserId.value)

const openEdit = (record: UserItem) => {
  editTarget.value = record
  editForm.display_name = record.display_name
  editForm.role = record.role
  editOpen.value = true
}

const submitEdit = async () => {
  await editFormRef.value?.validate()
  if (!editTarget.value) return
  editSubmitting.value = true
  try {
    const body: { display_name: string; role?: UserRole } = {
      display_name: editForm.display_name,
    }
    if (!editIsSelf.value) body.role = editForm.role
    const { data } = await updateUser(editTarget.value.id, body)
    if (data.code === 0) {
      message.success('用户已更新')
      editOpen.value = false
      emit('updated')
    } else {
      message.error(data.message || '更新失败')
    }
  } catch (e) {
    message.error(errMsg(e, '更新用户失败'))
  } finally {
    editSubmitting.value = false
  }
}

defineExpose({ openCreate, openEdit })
</script>

<style scoped>
.form-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
