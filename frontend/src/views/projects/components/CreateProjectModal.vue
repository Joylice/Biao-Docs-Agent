<template>
  <a-modal
    v-model:open="showCreateModal"
    title="新建项目"
    :confirm-loading="creating"
    @ok="handleCreate"
  >
    <a-form :model="newProject">
      <a-form-item label="项目名称">
        <a-input v-model:value="newProject.name" />
      </a-form-item>
      <a-form-item label="招标编号">
        <a-input v-model:value="newProject.tender_no" />
      </a-form-item>
      <a-form-item label="行业">
        <a-input v-model:value="newProject.industry" />
      </a-form-item>
      <a-form-item label="项目成员">
        <a-select
          v-model:value="newProject.member_ids"
          mode="multiple"
          :options="memberOptions"
          placeholder="选择项目成员（可多选，创建后可继续添加）"
          show-search
          allow-clear
          option-filter-prop="label"
        />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { createProject, fetchUserOptions } from '@/api'
import { currentUserId } from '@/stores/currentUser'

const emit = defineEmits<{
  /** 创建成功，父组件刷新项目列表 */
  (e: 'created'): void
}>()

const showCreateModal = ref(false)
const creating = ref(false)

const newProject = reactive({
  name: '',
  tender_no: '',
  industry: '',
  member_ids: [] as string[],
})

/* 阶段7：建项目选成员 —— 下拉数据源（GET /users/options，排除自己） */
interface UserOption {
  id: string
  email: string
  display_name: string
}
const userOptions = ref<UserOption[]>([])

const memberOptions = computed(() =>
  userOptions.value
    .filter((u) => u.id !== currentUserId.value)
    .map((u) => ({ value: u.id, label: `${u.display_name}（${u.email}）` })),
)

const loadUserOptions = async () => {
  try {
    const { data } = await fetchUserOptions()
    if (data.code === 0) {
      userOptions.value = data.data.items
    }
  } catch {
    // 下拉数据源加载失败不阻塞建项目（可不选成员）
  }
}

const open = (loadOptions = true) => {
  showCreateModal.value = true
  if (loadOptions) loadUserOptions()
}

/** 统一错误文案：优先展示后端 message */
const getErrorMessage = (err: unknown, fallback: string): string => {
  const body = (err as { response?: { data?: { message?: string } } })?.response?.data
  return body?.message || fallback
}

const handleCreate = async () => {
  if (!newProject.name.trim()) {
    message.warning('请输入项目名称')
    return
  }
  creating.value = true
  try {
    const { data } = await createProject(newProject)
    if (data.code === 0) {
      showCreateModal.value = false
      message.success('项目创建成功')
      newProject.name = ''
      newProject.tender_no = ''
      newProject.industry = ''
      newProject.member_ids = []
      emit('created')
    } else {
      message.error(data.message || '项目创建失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '项目创建失败'))
  } finally {
    creating.value = false
  }
}

defineExpose({ open })
</script>
