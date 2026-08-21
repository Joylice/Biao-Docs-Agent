<template>
  <!-- 上传弹窗：上传文件 / 从公司库选取 -->
  <a-modal
    :open="open"
    title="上传资料"
    ok-text="确认"
    cancel-text="取消"
    :confirm-loading="uploading || importingFromCompany"
    :ok-button-props="{ disabled: uploadTab === 'upload' ? !uploadFile : selectedCompanyDocs.length === 0 }"
    @ok="handleUploadSubmit"
    @cancel="onCancel"
    @update:open="(val: boolean) => emit('update:open', val)"
  >
    <a-tabs v-model:activeKey="uploadTab">
      <!-- Tab1: 上传文件 -->
      <a-tab-pane
        key="upload"
        tab="上传文件"
      >
        <a-space
          direction="vertical"
          style="width: 100%"
          :size="12"
        >
          <a-upload-dragger
            :before-upload="pickUploadFile"
            :show-upload-list="false"
            accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
          >
            <p class="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p class="ant-upload-text">
              {{ uploadFile ? uploadFile.name : '点击或拖拽文件到此处（pdf/doc/docx/jpg/png）' }}
            </p>
          </a-upload-dragger>
          <a-select
            v-model:value="uploadForm.kbId"
            placeholder="归入知识库（可选，缺省公司公共可见）"
            allow-clear
            :options="writableBaseOptions"
          />
          <a-select
            v-model:value="uploadForm.category"
            placeholder="素材分类（可选）"
            allow-clear
            :options="categoryOptions"
          />
          <a-select
            v-model:value="uploadForm.tags"
            mode="tags"
            placeholder="标签（回车添加，最多 10 个）"
            :max-tag-count="10"
          />
        </a-space>
      </a-tab-pane>

      <!-- Tab2: 从公司库选取 -->
      <a-tab-pane
        key="company"
        tab="从公司库选取"
      >
        <a-space
          direction="vertical"
          style="width: 100%"
          :size="12"
        >
          <a-select
            v-model:value="uploadForm.kbId"
            placeholder="选择目标知识库（个人/项目库）"
            :options="personalProjectBaseOptions"
            style="width: 100%"
          />
          <a-input-search
            v-model:value="companySearchKeyword"
            placeholder="搜索公司库资料"
            allow-clear
            @search="onCompanySearchSubmit"
            @change="onCompanySearchChange"
          />
          <div class="company-material-list">
            <div
              v-if="companyMaterialsLoading"
              class="company-material-skeleton"
            >
              <a-skeleton
                v-for="i in 4"
                :key="i"
                active
                :title="false"
                :paragraph="{ rows: 1, width: '100%' }"
              />
            </div>
            <template v-else>
              <a-empty
                v-if="companyMaterials.length === 0"
                description="暂无公司库资料"
              />
              <a-checkbox-group
                v-else
                v-model:value="selectedCompanyDocIds"
                class="company-checkbox-group"
              >
                <div
                  v-for="doc in companyMaterials"
                  :key="doc.id"
                  class="company-material-item"
                >
                  <a-checkbox :value="doc.id">
                    <div class="company-material-item__content">
                      <FileTextOutlined class="company-material-item__icon" />
                      <span class="company-material-item__title">{{ doc.title }}</span>
                      <a-tag
                        v-if="doc.category"
                        color="geekblue"
                        class="company-material-item__tag"
                      >
                        {{ categoryLabel(doc.category) }}
                      </a-tag>
                    </div>
                  </a-checkbox>
                </div>
              </a-checkbox-group>
            </template>
          </div>
          <div class="company-select-hint">
            已选择 {{ selectedCompanyDocIds.length }} 份资料，将复制到目标知识库
          </div>
        </a-space>
      </a-tab-pane>
    </a-tabs>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { FileTextOutlined, InboxOutlined } from '@ant-design/icons-vue'
import {
  fetchMaterials as fetchMaterialsApi,
  uploadMaterial,
  addDocumentToKbBase,
  type MaterialListParams,
} from '@/api'
import { debounce } from '@/utils/debounce'
import { categoryOptions, categoryLabel, type Material } from '../constants'

const props = defineProps<{
  open: boolean
  /** 当前选中知识库，作为弹窗缺省归入库 */
  defaultKbId: string
  writableBaseOptions: { value: string; label: string }[]
  personalProjectBaseOptions: { value: string; label: string }[]
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  /** 上传 / 导入成功后触发，父组件刷新列表与库内素材数 */
  (e: 'submitted'): void
}>()

// ---- 上传（弹窗式：文件 + 分类 + 标签） ----
const uploadTab = ref<'upload' | 'company'>('upload')
const uploadFile = ref<File | null>(null)
const uploading = ref(false)
const uploadForm = reactive<{ category?: string; tags: string[]; kbId?: string }>({
  category: undefined,
  tags: [],
  kbId: undefined,
})

// ---- 从公司库选取 ----
const companyMaterials = ref<Material[]>([])
const companyMaterialsLoading = ref(false)
const companySearchKeyword = ref('')
const selectedCompanyDocIds = ref<string[]>([])
const importingFromCompany = ref(false)

const selectedCompanyDocs = computed(() =>
  companyMaterials.value.filter((d) => selectedCompanyDocIds.value.includes(d.id)),
)

const fetchCompanyMaterials = async () => {
  companyMaterialsLoading.value = true
  try {
    const params: MaterialListParams = { page: 1, page_size: 50, scope: 'company' }
    const q = companySearchKeyword.value.trim()
    if (q) params.keyword = q
    const { data } = await fetchMaterialsApi(params)
    if (data.code === 0) {
      companyMaterials.value = data.data.items
    }
  } catch {
    message.error('加载公司库资料失败')
  } finally {
    companyMaterialsLoading.value = false
  }
}

const debouncedCompanySearch = debounce(() => {
  void fetchCompanyMaterials()
}, 500)
const onCompanySearchChange = () => {
  debouncedCompanySearch()
}
const onCompanySearchSubmit = () => {
  debouncedCompanySearch.cancel()
  void fetchCompanyMaterials()
}

// 切换到公司库选取Tab时加载资料
watch(uploadTab, (tab) => {
  if (tab === 'company' && companyMaterials.value.length === 0) {
    fetchCompanyMaterials()
  }
})

const pickUploadFile = (file: File) => {
  uploadFile.value = file
  return false // 阻止自动上传，由弹窗确认触发
}

const resetUploadForm = () => {
  uploadTab.value = 'upload'
  uploadFile.value = null
  uploadForm.category = undefined
  uploadForm.tags = []
  uploadForm.kbId = props.defaultKbId || undefined
  selectedCompanyDocIds.value = []
  companySearchKeyword.value = ''
  companyMaterials.value = []
}

const onCancel = () => {
  resetUploadForm()
  emit('update:open', false)
}

const handleUploadSubmit = async () => {
  if (uploadTab.value === 'company') {
    await handleImportFromCompany()
    return
  }
  const file = uploadFile.value
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  if (uploadForm.category) form.append('category', uploadForm.category)
  if (uploadForm.tags.length) form.append('tags', uploadForm.tags.join(','))
  if (uploadForm.kbId) form.append('kb_id', uploadForm.kbId)
  uploading.value = true
  try {
    // 不手动设 Content-Type：axios 自动带 boundary（手动设置会丢失导致后端解析失败）
    const { data } = await uploadMaterial(form)
    if (data.code === 0) {
      message.success(`已上传「${file.name}」，正在索引...`)
      emit('update:open', false)
      resetUploadForm()
      emit('submitted')
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

/** 从公司库选取资料复制到目标知识库（个人/项目库） */
const handleImportFromCompany = async () => {
  if (selectedCompanyDocIds.value.length === 0) {
    message.warning('请选择要导入的资料')
    return
  }
  const targetKbId = uploadForm.kbId
  if (!targetKbId) {
    message.warning('请选择目标知识库')
    return
  }
  importingFromCompany.value = true
  try {
    let successCount = 0
    for (const docId of selectedCompanyDocIds.value) {
      try {
        const { data } = await addDocumentToKbBase(targetKbId, docId)
        if (data.code === 0) successCount += 1
      } catch {
        // 单条失败不中断，继续导入其他
      }
    }
    if (successCount > 0) {
      message.success(`已从公司库导入 ${successCount} 份资料到目标知识库`)
      emit('update:open', false)
      resetUploadForm()
      emit('submitted')
    } else {
      message.error('导入失败，请重试')
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '导入失败')
  } finally {
    importingFromCompany.value = false
  }
}

onUnmounted(() => {
  debouncedCompanySearch.cancel()
})
</script>

<style scoped>
/* 从公司库选取 */
.company-material-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-1) var(--space-2);
}

.company-material-list {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: var(--space-2);
}

.company-checkbox-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.company-material-item {
  padding: 6px 8px;
  border-radius: 4px;
  transition: background 0.15s;
}

.company-material-item:hover {
  background: var(--bg-surface-hover);
}

.company-material-item__content {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.company-material-item__icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.company-material-item__title {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.company-material-item__tag {
  flex-shrink: 0;
}

.company-select-hint {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
}
</style>
