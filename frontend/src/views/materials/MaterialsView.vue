<template>
  <PageContainer
    title="资料库"
    subtitle="公司级共享素材库 · 方案生成时选择挂载"
  >
    <template #extra>
      <a-button
        v-if="canUploadMaterial()"
        type="primary"
        @click="uploadOpen = true"
      >
        <template #icon>
          <UploadOutlined />
        </template>
        上传资料
      </a-button>
    </template>

    <!-- 知识库选择（阶段 1：多知识库容器，公司/个人分组） -->
    <KbBasePanel
      :selected-kb-id="selectedKbId"
      :bases-loading="basesLoading"
      :company-bases="companyBases"
      :project-bases="projectBases"
      :personal-bases="personalBases"
      :selected-base="selectedBase"
      :can-delete-selected-base="canDeleteSelectedBase"
      :owned-project-options="ownedProjectOptions"
      @change="handleKbChange"
      @created="handleBaseCreated"
      @deleted="handleBaseDeleted"
    />

    <!-- 检索测试 -->
    <MaterialSearchPanel />

    <!-- 资料列表 -->
    <MaterialTablePanel
      ref="tableRef"
      :selected-kb-id="selectedKbId"
      @edit="handleEdit"
    />

    <!-- 上传弹窗：上传文件 / 从公司库选取 -->
    <MaterialUploadModal
      :open="uploadOpen"
      :default-kb-id="selectedKbId"
      :writable-base-options="writableBaseOptions"
      :personal-project-base-options="personalProjectBaseOptions"
      @update:open="(val) => (uploadOpen = val)"
      @submitted="handleUploadSubmitted"
    />

    <!-- 三期 S2：编辑弹窗（kb_admin 可见） -->
    <MaterialEditModal
      ref="editRef"
      @saved="handleEditSaved"
    />
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { nextTick } from 'vue'
import { UploadOutlined } from '@ant-design/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { usePermission } from '@/composables/usePermission'
import { useHotkeys } from '@/composables/useHotkeys'
import { useKbBases } from './composables/useKbBases'
import KbBasePanel from './components/KbBasePanel.vue'
import MaterialSearchPanel from './components/MaterialSearchPanel.vue'
import MaterialTablePanel from './components/MaterialTablePanel.vue'
import MaterialUploadModal from './components/MaterialUploadModal.vue'
import MaterialEditModal from './components/MaterialEditModal.vue'
import type { Material } from './constants'

const { canUploadMaterial } = usePermission()

/* 快捷键：Ctrl+K 聚焦页面主搜索框 */
useHotkeys([
  {
    combo: 'ctrl+k',
    handler: () => document.getElementById('materials-search-input')?.focus(),
  },
])

// 阶段 1：知识库容器状态与派生选项
const {
  basesLoading,
  selectedKbId,
  companyBases,
  projectBases,
  personalBases,
  fetchMyProjects,
  ownedProjectOptions,
  writableBaseOptions,
  personalProjectBaseOptions,
  selectedBase,
  canDeleteSelectedBase,
  fetchBases,
} = useKbBases()

const tableRef = ref<InstanceType<typeof MaterialTablePanel> | null>(null)
const editRef = ref<InstanceType<typeof MaterialEditModal> | null>(null)
const uploadOpen = ref(false)

/** 切换知识库：重置分页并刷新 */
const handleKbChange = async (kbId: string) => {
  selectedKbId.value = kbId
  await nextTick()
  tableRef.value?.refresh()
}

/** 新建知识库成功：刷新库列表 → 选中新库 → 重置分页刷新素材 */
const handleBaseCreated = async (baseId: string) => {
  await fetchBases()
  selectedKbId.value = baseId
  await nextTick()
  tableRef.value?.refresh()
}

/** 删除知识库成功：回到全部资料（保持当前分页刷新） */
const handleBaseDeleted = async () => {
  selectedKbId.value = ''
  await fetchBases()
  await nextTick()
  tableRef.value?.fetch()
}

/** 上传 / 从公司库导入成功：刷新素材列表 + 库内素材数 */
const handleUploadSubmitted = () => {
  tableRef.value?.fetch()
  fetchBases()
}

const handleEdit = (record: Material) => {
  editRef.value?.open(record)
}

/** 编辑保存成功：保持当前分页刷新 */
const handleEditSaved = () => {
  tableRef.value?.fetch()
}

onMounted(() => {
  fetchMyProjects()
  fetchBases()
  tableRef.value?.fetch()
})
</script>

<style scoped>
.kb-no-perm {
  color: var(--text-secondary);
}
</style>
