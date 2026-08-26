<template>
  <!-- 知识库选择（阶段 1：多知识库容器，公司/个人分组） -->
  <a-card class="kb-card">
    <a-space wrap>
      <span class="kb-muted">知识库：</span>
      <a-select
        :value="selectedKbId"
        style="width: 260px"
        :loading="basesLoading"
        @change="(val) => emit('change', val as string)"
      >
        <a-select-option value="">
          全部资料（含未归档）
        </a-select-option>
        <a-select-opt-group label="公司级">
          <a-select-option
            v-for="b in companyBases"
            :key="b.id"
            :value="b.id"
          >
            {{ b.name }}（{{ b.material_count }}）
          </a-select-option>
        </a-select-opt-group>
        <a-select-opt-group label="项目级">
          <a-select-option
            v-for="b in projectBases"
            :key="b.id"
            :value="b.id"
          >
            {{ b.name }} · {{ b.project_name || '项目' }}（{{ b.material_count }}）
          </a-select-option>
        </a-select-opt-group>
        <a-select-opt-group label="个人">
          <a-select-option
            v-for="b in personalBases"
            :key="b.id"
            :value="b.id"
          >
            {{ b.name }}（{{ b.material_count }}）
          </a-select-option>
        </a-select-opt-group>
      </a-select>
      <a-button @click="createBaseOpen = true">
        <template #icon>
          <PlusOutlined />
        </template>
        新建知识库
      </a-button>
      <a-popconfirm
        v-if="canDeleteSelectedBase"
        :title="`删除知识库「${selectedBase?.name ?? ''}」？`"
        :description="`库内 ${selectedBase?.material_count ?? 0} 份素材将一并删除，不可恢复。`"
        ok-text="删除"
        cancel-text="取消"
        :ok-button-props="{ danger: true }"
        @confirm="handleDeleteBase"
      >
        <a-button
          type="link"
          danger
        >
          删除当前知识库
        </a-button>
      </a-popconfirm>
    </a-space>
  </a-card>

  <!-- 阶段 1：新建知识库弹窗（personal 任意用户 / company 仅管理员） -->
  <a-modal
    v-model:open="createBaseOpen"
    title="新建知识库"
    ok-text="创建"
    cancel-text="取消"
    :confirm-loading="creatingBase"
    @ok="handleCreateBase"
  >
    <a-space
      direction="vertical"
      style="width: 100%"
      :size="12"
    >
      <a-radio-group v-model:value="createBaseForm.scope">
        <a-radio value="personal">
          个人库（仅本人可见）
        </a-radio>
        <a-radio value="project">
          项目库（仅项目成员可见，需选择所属项目）
        </a-radio>
        <a-radio
          v-if="isKbAdmin"
          value="company"
        >
          公司库（全员可见）
        </a-radio>
      </a-radio-group>
      <a-select
        v-if="createBaseForm.scope === 'project'"
        v-model:value="createBaseForm.projectId"
        placeholder="选择所属项目（仅我负责的项目可建库）"
        allow-clear
        :options="ownedProjectOptions"
      />
      <a-input
        v-model:value="createBaseForm.name"
        placeholder="知识库名称"
        allow-clear
      />
      <a-textarea
        v-model:value="createBaseForm.description"
        placeholder="描述（可选）"
        :rows="2"
      />
    </a-space>
  </a-modal>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { createKbBase, deleteKbBase } from '@/api'
import { isKbAdmin } from '@/stores/currentUser'
import type { KbBase } from '../constants'

const props = defineProps<{
  selectedKbId: string
  basesLoading: boolean
  companyBases: KbBase[]
  projectBases: KbBase[]
  personalBases: KbBase[]
  selectedBase?: KbBase
  canDeleteSelectedBase: boolean
  ownedProjectOptions: { value: string; label: string }[]
}>()

const emit = defineEmits<{
  (e: 'change', kbId: string): void
  (e: 'created', baseId: string): void
  (e: 'deleted'): void
}>()

// ---- 新建知识库 ----
const createBaseOpen = ref(false)
const creatingBase = ref(false)
const createBaseForm = reactive<{
  scope: 'personal' | 'project' | 'company'
  name: string
  description: string
  projectId?: string
}>({
  scope: 'personal',
  name: '',
  description: '',
  projectId: undefined,
})

const handleCreateBase = async () => {
  const name = createBaseForm.name.trim()
  if (!name) {
    message.warning('请输入知识库名称')
    return
  }
  if (createBaseForm.scope === 'project' && !createBaseForm.projectId) {
    message.warning('请选择项目库所属项目')
    return
  }
  creatingBase.value = true
  try {
    const { data } = await createKbBase({
      scope: createBaseForm.scope,
      name,
      description: createBaseForm.description.trim() || null,
      project_id: createBaseForm.scope === 'project' ? createBaseForm.projectId : null,
    })
    if (data.code === 0) {
      message.success(`已创建知识库「${name}」`)
      createBaseOpen.value = false
      createBaseForm.name = ''
      createBaseForm.description = ''
      createBaseForm.projectId = undefined
      emit('created', data.data.id)
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '创建失败')
  } finally {
    creatingBase.value = false
  }
}

/** 删除知识库（Popconfirm 二次确认，无需填写理由） */
const handleDeleteBase = async () => {
  const base = props.selectedBase
  if (!base) return
  try {
    const { data } = await deleteKbBase(base.id)
    if (data.code === 0) {
      message.success('已删除知识库')
      emit('deleted')
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '删除失败')
  }
}
</script>

<style scoped>
.kb-card {
  margin-bottom: var(--space-4);
}
.kb-muted {
  color: var(--text-secondary);
}
</style>
