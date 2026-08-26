<template>
  <a-modal
    v-model:open="showCreateModal"
    :width="560"
    :confirm-loading="creating"
    ok-text="创建项目"
    cancel-text="取消"
    :closable="true"
    @ok="handleCreate"
  >
    <template #title>
      <div class="modal-title">
        <div class="modal-title__icon">
          <FolderAddOutlined />
        </div>
        <div class="modal-title__text">
          <div class="modal-title__main">新建项目</div>
          <div class="modal-title__sub">填写项目基本信息，创建后可继续添加成员和上传招标文件</div>
        </div>
      </div>
    </template>
    <a-form
      :model="newProject"
      layout="vertical"
      class="create-project-form"
    >
      <a-form-item
        label="项目名称"
        name="name"
        :rules="[{ required: true, message: '请输入项目名称', trigger: 'blur' }]"
      >
        <a-input
          v-model:value="newProject.name"
          placeholder="请输入项目名称，如：XX市智慧交通平台建设项目"
          allow-clear
        />
      </a-form-item>
      <a-form-item
        label="招标编号"
        name="tender_no"
      >
        <a-input
          v-model:value="newProject.tender_no"
          placeholder="请输入招标编号（选填）"
          allow-clear
        />
      </a-form-item>
      <a-form-item
        label="行业"
        name="industry"
      >
        <a-select
          v-model:value="newProject.industry"
          placeholder="请选择所属行业（选填）"
          :options="industryOptions"
          allow-clear
          show-search
          option-filter-prop="label"
        />
      </a-form-item>
      <a-form-item
        label="项目成员"
        name="member_ids"
      >
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
import { FolderAddOutlined } from '@ant-design/icons-vue'
import { createProject, fetchUserOptions } from '@/api'
import { currentUserId } from '@/stores/currentUser'

const emit = defineEmits<{
  /** 创建成功，父组件刷新项目列表 */
  (e: 'created'): void
}>()

const showCreateModal = ref(false)
const creating = ref(false)

/* 行业预设选项 */
const industryOptions = [
  { label: '政务', value: '政务' },
  { label: '金融', value: '金融' },
  { label: '能源', value: '能源' },
  { label: '交通', value: '交通' },
  { label: '医疗', value: '医疗' },
  { label: '教育', value: '教育' },
  { label: '制造', value: '制造' },
  { label: '建筑', value: '建筑' },
  { label: '通信', value: '通信' },
  { label: '其他', value: '其他' },
]

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

<style scoped>
.modal-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.modal-title__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--color-primary), var(--color-info));
  color: var(--text-inverse);
  font-size: 18px;
  flex-shrink: 0;
}

.modal-title__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.modal-title__main {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}

.modal-title__sub {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.create-project-form {
  margin-top: 8px;
}

.create-project-form :deep(.ant-form-item) {
  margin-bottom: 18px;
}

.create-project-form :deep(.ant-form-item-label) {
  font-weight: 500;
}

.create-project-form :deep(.ant-form-item-label > label) {
  height: 24px;
  font-size: 14px;
}
</style>
