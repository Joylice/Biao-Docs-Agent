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
    <a-card class="kb-card">
      <a-space wrap>
        <span class="kb-muted">知识库：</span>
        <a-select
          v-model:value="selectedKbId"
          style="width: 260px"
          :loading="basesLoading"
          @change="handleKbChange"
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

    <!-- 检索测试 -->
    <a-card class="kb-card">
      <a-input-search
        id="materials-search-input"
        v-model:value="searchQuery"
        placeholder="检索资料内容（RAG 命中验证）"
        enter-button="检索"
        allow-clear
        :loading="searching"
        @change="onSearchInputChange"
        @search="onSearchSubmit"
      />
      <a-list
        v-if="searchResults.length > 0"
        size="small"
        class="kb-search-results"
        :data-source="searchResults"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="item.title"
              :description="item.content"
            />
            <template #extra>
              <a-tag color="blue">
                相关度 {{ item.score?.toFixed(2) ?? '—' }}
              </a-tag>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </a-card>

    <!-- 资料列表 -->
    <a-card
      title="全部资料"
      class="kb-card"
    >
      <!-- 三期 S2：分类 / 标签筛选 -->
      <template #extra>
        <a-space>
          <a-select
            v-model:value="filterCategory"
            placeholder="全部分类"
            allow-clear
            style="width: 140px"
            :options="categoryOptions"
            @change="handleFilterChange"
          />
          <a-input
            v-model:value="filterTag"
            placeholder="按标签筛选"
            allow-clear
            style="width: 160px"
            @press-enter="onTagFilterEnter"
            @change="onTagInputChange"
          />
        </a-space>
      </template>

      <EmptyState
        v-if="!loading && materials.length === 0"
        illustration="box"
        description="还没有资料，点击右上角「上传资料」开始建设素材库"
      />
      <LoadingSkeleton
        v-else-if="loading"
        :rows="4"
      />
      <a-table
        v-else
        :data-source="materials"
        :columns="columns"
        :pagination="pagination"
        :scroll="{ x: 1060 }"
        row-key="id"
        size="middle"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'file'">
            <FileTextOutlined class="kb-file-icon" />
            <a-tooltip :title="record.title">
              <span class="kb-file-name">{{ record.title }}</span>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'category'">
            <a-tag
              v-if="record.category"
              color="geekblue"
            >
              {{ categoryLabel(record.category) }}
            </a-tag>
            <span
              v-else
              class="kb-muted"
            >未分类</span>
          </template>
          <template v-else-if="column.key === 'tags'">
            <template v-if="record.tags?.length">
              <a-tag
                v-for="tag in record.tags"
                :key="tag"
                class="kb-tag"
              >
                {{ tag }}
              </a-tag>
            </template>
            <span
              v-else
              class="kb-muted"
            >—</span>
          </template>
          <template v-else-if="column.key === 'uploader_name'">
            {{ record.uploader_name || '—' }}
          </template>
          <template v-else-if="column.key === 'status'">
            <a-badge
              :status="statusMeta[record.status]?.badge ?? 'default'"
              :text="statusMeta[record.status]?.text ?? record.status"
            />
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'action'">
            <!-- 阶段 2：下载所有登录用户可用 -->
            <a-button
              type="link"
              size="small"
              :loading="downloadingId === record.id"
              @click="handleDownload(record)"
            >
              下载
            </a-button>
            <!-- 编辑/删除：资料库管理员或上传者本人 -->
            <template v-if="canEditMaterial(record.uploader_id)">
              <a-button
                type="link"
                size="small"
                @click="openEdit(record)"
              >
                编辑
              </a-button>
              <a-popconfirm
                title="删除该资料？"
                description="删除后不可恢复，已挂载到项目方案的素材将无法检索。"
                ok-text="删除"
                cancel-text="取消"
                :ok-button-props="{ danger: true }"
                @confirm="handleDelete(record)"
              >
                <a-button
                  type="link"
                  danger
                  size="small"
                >
                  删除
                </a-button>
              </a-popconfirm>
            </template>
          </template>
        </template>
      </a-table>
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

    <!-- 上传弹窗：上传文件 / 从公司库选取 -->
    <a-modal
      v-model:open="uploadOpen"
      title="上传资料"
      ok-text="确认"
      cancel-text="取消"
      :confirm-loading="uploading || importingFromCompany"
      :ok-button-props="{ disabled: uploadTab === 'upload' ? !uploadFile : selectedCompanyDocs.length === 0 }"
      @ok="handleUploadSubmit"
      @cancel="resetUploadForm"
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
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  FileTextOutlined,
  InboxOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { isKbAdmin, currentUserId } from '@/stores/currentUser'
import { usePermission } from '@/composables/usePermission'
import { useHotkeys } from '@/composables/useHotkeys'
import { debounce } from '@/utils/debounce'

const { canUploadMaterial, canEditMaterial } = usePermission()

/* 快捷键：Ctrl+K 聚焦页面主搜索框 */
useHotkeys([
  {
    combo: 'ctrl+k',
    handler: () => document.getElementById('materials-search-input')?.focus(),
  },
])

interface Material {
  id: string
  title: string
  doc_type: string
  status: string
  created_at: string
  category?: string | null
  tags?: string[]
  uploader_name?: string
  uploader_id?: string | null
}

interface SearchItem {
  title: string
  content: string
  score?: number
}

interface KbBase {
  id: string
  name: string
  description?: string | null
  scope: 'personal' | 'project' | 'company'
  project_id?: string | null
  project_name?: string | null
  owner_id?: string | null
  material_count: number
}

// 三期 S2：素材分类枚举（与后端 schemas/document.py MATERIAL_CATEGORIES 对齐）
const categoryOptions = [
  { value: 'product_material', label: '产品资料' },
  { value: 'history_proposal', label: '历史方案' },
  { value: 'qualification', label: '资质证书' },
  { value: 'other', label: '其他' },
]
const categoryLabel = (value?: string | null) =>
  categoryOptions.find((o) => o.value === value)?.label ?? value ?? ''

const statusMeta: Record<string, { badge: string; text: string }> = {
  uploaded: { badge: 'default', text: '待处理' },
  indexing: { badge: 'processing', text: '索引中' },
  indexed: { badge: 'success', text: '已完成' },
  failed: { badge: 'error', text: '失败' },
}

const columns = [
  { title: '文件', key: 'file', dataIndex: 'title', width: 220, fixed: 'left' as const },
  { title: '分类', key: 'category', dataIndex: 'category', width: 110 },
  { title: '标签', key: 'tags', dataIndex: 'tags', width: 180 },
  { title: '上传者', key: 'uploader_name', dataIndex: 'uploader_name', width: 100 },
  { title: '状态', key: 'status', dataIndex: 'status', width: 110 },
  { title: '上传时间', key: 'created_at', dataIndex: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 180 },
]

const loading = ref(false)
const uploading = ref(false)
const saving = ref(false)
const downloadingId = ref('')

/** 阶段 2：下载素材（后端代理字节流 → blob 保存本地） */
const handleDownload = async (record: Material) => {
  downloadingId.value = record.id
  try {
    const resp = await api.get(`/kb/materials/${record.id}/download`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = record.title || '素材'
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    message.error('下载失败，请重试')
  } finally {
    downloadingId.value = ''
  }
}
const materials = ref<Material[]>([])
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<SearchItem[]>([])

// 三期 S2：筛选状态
const filterCategory = ref<string | undefined>(undefined)
const filterTag = ref('')

// 阶段 1：知识库容器状态（素材页无项目上下文 → 后端仅返回公司库 + 本人个人库）
const kbBases = ref<KbBase[]>([])
const basesLoading = ref(false)
const selectedKbId = ref<string>('')
const companyBases = computed(() => kbBases.value.filter((b) => b.scope === 'company'))
const projectBases = computed(() => kbBases.value.filter((b) => b.scope === 'project'))
const personalBases = computed(() => kbBases.value.filter((b) => b.scope === 'personal'))

// ---- 项目列表（阶段 3：项目库建库选项 + 写权限判定）----
interface ProjectLite {
  id: string
  name: string
  owner_id: string
}
const myProjects = ref<ProjectLite[]>([])
const fetchMyProjects = async () => {
  try {
    const { data } = await api.get('/projects', { params: { page: 1, page_size: 100 } })
    if (data.code === 0) myProjects.value = data.data.items
  } catch {
    // 静默：项目库选项为空时建库弹窗会提示
  }
}
// 仅我负责的项目可建项目库（后端 create_base 同样限定 owner）
const ownedProjectOptions = computed(() =>
  myProjects.value
    .filter((p) => p.owner_id === currentUserId.value)
    .map((p) => ({ value: p.id, label: p.name })),
)
const ownedProjectIds = computed(
  () => new Set(myProjects.value.filter((p) => p.owner_id === currentUserId.value).map((p) => p.id)),
)

// 上传可选库：个人库（后端仅返回本人）+ 项目库（仅负责人可写）+ 公司库（仅管理员可写）
const writableBaseOptions = computed(() =>
  kbBases.value
    .filter(
      (b) =>
        b.scope === 'personal' ||
        (b.scope === 'project' && !!b.project_id && ownedProjectIds.value.has(b.project_id)) ||
        (b.scope === 'company' && isKbAdmin.value),
    )
    .map((b) => ({
      value: b.id,
      label:
        b.scope === 'project'
          ? `${b.name}（项目·${b.project_name || ''}）`
          : `${b.name}（${b.scope === 'company' ? '公司' : '个人'}）`,
    })),
)
const selectedBase = computed(() => kbBases.value.find((b) => b.id === selectedKbId.value))
const canDeleteSelectedBase = computed(() => {
  const base = kbBases.value.find((b) => b.id === selectedKbId.value)
  if (!base) return false
  if (base.scope === 'personal') return true
  if (base.scope === 'project') {
    return !!base.project_id && ownedProjectIds.value.has(base.project_id)
  }
  return isKbAdmin.value
})

const fetchBases = async () => {
  basesLoading.value = true
  try {
    const { data } = await api.get('/kb-bases')
    if (data.code === 0) kbBases.value = data.data.items
  } catch {
    message.error('加载知识库失败')
  } finally {
    basesLoading.value = false
  }
}

const handleKbChange = () => {
  pagination.current = 1
  fetchMaterials()
}

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
    const { data } = await api.post('/kb-bases', {
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
      await fetchBases()
      selectedKbId.value = data.data.id
      handleKbChange()
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
  const base = kbBases.value.find((b) => b.id === selectedKbId.value)
  if (!base) return
  try {
    const { data } = await api.delete(`/kb-bases/${base.id}`)
    if (data.code === 0) {
      message.success('已删除知识库')
      selectedKbId.value = ''
      await fetchBases()
      fetchMaterials()
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '删除失败')
  }
}

const pagination = reactive({
  current: 1,
  pageSize: 10,
  total: 0,
  showTotal: (t: number) => `共 ${t} 条`,
})

const fetchMaterials = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    if (filterCategory.value) params.category = filterCategory.value
    const tag = filterTag.value.trim()
    if (tag) params.tag = tag
    if (selectedKbId.value) params.kb_id = selectedKbId.value
    const { data } = await api.get('/kb/materials', { params })
    if (data.code === 0) {
      materials.value = data.data.items
      pagination.total = data.data.total
    }
  } catch {
    message.error('加载资料失败')
  } finally {
    loading.value = false
  }
}

const handleFilterChange = () => {
  pagination.current = 1
  fetchMaterials()
}

/** 标签筛选输入防抖（沿用 500ms；回车立即过滤） */
const debouncedTagFilter = debounce(handleFilterChange, 500)
const onTagInputChange = () => {
  debouncedTagFilter()
}
const onTagFilterEnter = () => {
  debouncedTagFilter.cancel()
  handleFilterChange()
}

// ---- 上传（弹窗式：文件 + 分类 + 标签） ----
const uploadOpen = ref(false)
const uploadTab = ref<'upload' | 'company'>('upload')
const uploadFile = ref<File | null>(null)
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

// 个人/项目库选项（排除公司库，用于从公司库选取时的目标库）
const personalProjectBaseOptions = computed(() =>
  kbBases.value
    .filter((b) => b.scope !== 'company')
    .map((b) => ({
      value: b.id,
      label:
        b.scope === 'project'
          ? `${b.name}（项目·${b.project_name || ''}）`
          : `${b.name}（个人）`,
    })),
)

const fetchCompanyMaterials = async () => {
  companyMaterialsLoading.value = true
  try {
    const params: Record<string, unknown> = { page: 1, page_size: 50, scope: 'company' }
    const q = companySearchKeyword.value.trim()
    if (q) params.keyword = q
    const { data } = await api.get('/kb/materials', { params })
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
  uploadForm.kbId = selectedKbId.value || undefined
  selectedCompanyDocIds.value = []
  companySearchKeyword.value = ''
  companyMaterials.value = []
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
    const { data } = await api.post('/kb/materials', form)
    if (data.code === 0) {
      message.success(`已上传「${file.name}」，正在索引...`)
      uploadOpen.value = false
      resetUploadForm()
      fetchMaterials()
      fetchBases()  // 刷新库内素材数
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
  if (!uploadForm.kbId) {
    message.warning('请选择目标知识库')
    return
  }
  importingFromCompany.value = true
  try {
    let successCount = 0
    for (const docId of selectedCompanyDocIds.value) {
      try {
        const { data } = await api.post(`/kb-bases/${uploadForm.kbId}/documents`, { document_id: docId })
        if (data.code === 0) successCount += 1
      } catch {
        // 单条失败不中断，继续导入其他
      }
    }
    if (successCount > 0) {
      message.success(`已从公司库导入 ${successCount} 份资料到目标知识库`)
      uploadOpen.value = false
      resetUploadForm()
      fetchMaterials()
      fetchBases()
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

// ---- 编辑（三期 S2，kb_admin） ----
const editOpen = ref(false)
const editingId = ref('')
const editForm = reactive<{ title: string; category?: string; tags: string[] }>({
  title: '',
  category: undefined,
  tags: [],
})

const openEdit = (record: Material) => {
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
    const { data } = await api.patch(`/kb/materials/${editingId.value}`, {
      title,
      category: editForm.category ?? null,
      tags: editForm.tags,
    })
    if (data.code === 0) {
      message.success('已保存')
      editOpen.value = false
      fetchMaterials()
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

/** 删除资料（Popconfirm 二次确认，无需填写理由） */
const handleDelete = async (record: Material) => {
  try {
    const { data } = await api.delete(`/kb/materials/${record.id}`)
    if (data.code === 0) {
      message.success('已删除')
      fetchMaterials()
    }
  } catch {
    message.error('删除失败')
  }
}

const handleSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    return
  }
  searching.value = true
  searchResults.value = []
  try {
    const { data } = await api.get('/kb/materials/search', {
      params: { q, top_k: 5 },
    })
    if (data.code === 0) {
      searchResults.value = data.data.items
      if (data.data.items.length === 0) message.info('未检索到相关内容')
    }
  } catch {
    message.error('检索失败')
  } finally {
    searching.value = false
  }
}

/** 主搜索输入 300ms 防抖；回车 / 点击「检索」即时触发 */
const debouncedSearch = debounce(() => {
  void handleSearch()
}, 300)

const onSearchInputChange = () => {
  debouncedSearch()
}

const onSearchSubmit = () => {
  debouncedSearch.cancel()
  void handleSearch()
}

const handleTableChange = (pag: { current: number; pageSize: number }) => {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchMaterials()
}

const formatTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(() => {
  fetchMyProjects()
  fetchBases()
  fetchMaterials()
})

onUnmounted(() => {
  debouncedSearch.cancel()
  debouncedTagFilter.cancel()
  debouncedCompanySearch.cancel()
})
</script>

<style scoped>
.kb-card {
  margin-bottom: var(--space-4);
}
.kb-search-results {
  margin-top: var(--space-3);
}
.kb-file-icon {
  color: var(--color-primary);
  margin-right: var(--space-2);
}
.kb-file-name {
  max-width: 360px;
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.kb-tag {
  margin-bottom: 2px;
}
.kb-muted {
  color: var(--text-secondary);
}
.kb-no-perm {
  color: var(--text-secondary);
}

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
