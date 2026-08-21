<template>
  <!-- 三期 S2：编辑弹窗（kb_admin 可见） -->
  <a-modal
    v-model:open="editOpen"
    title="编辑资料"
    ok-text="保存"
    cancel-text="取消"
    :confirm-loading="saving"
    @ok="handleEditSubmit"
  >
    <a-space
      direction="vertical"
      style="width: 100%"
      :size="12"
    >
      <a-input
        v-model:value="editForm.title"
        placeholder="资料标题"
        allow-clear
      />
      <a-select
        v-model:value="editForm.category"
        placeholder="素材分类（可选）"
        allow-clear
        :options="categoryOptions"
      />
      <a-select
        v-model:value="editForm.tags"
        mode="tags"
        placeholder="标签（回车添加，最多 10 个）"
        :max-tag-count="10"
      />
    </a-space>
  </a-modal>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { updateMaterial } from '@/api'
import { categoryOptions, type Material } from '../constants'

const emit = defineEmits<{
  /** 保存成功后触发，父组件刷新素材列表 */
  (e: 'saved'): void
}>()

const editOpen = ref(false)
const editingId = ref('')
const saving = ref(false)
const editForm = reactive<{ title: string; category?: string; tags: string[] }>({
  title: '',
  category: undefined,
  tags: [],
})

const open = (record: Material) => {
  editingId.value = record.id
  editForm.title = record.title
  editForm.category = record.category ?? undefined
  editForm.tags = record.tags ? [...record.tags] : []
  editOpen.value = true
}

const handleEditSubmit = async () => {
  const title = editForm.title.trim()
  if (!title) {
    message.warning('标题不能为空')
    return
  }
  saving.value = true
  try {
    const { data } = await updateMaterial(editingId.value, {
      title,
      category: editForm.category ?? null,
      tags: editForm.tags,
    })
    if (data.code === 0) {
      message.success('已保存')
      editOpen.value = false
      emit('saved')
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

defineExpose({ open })
</script>
