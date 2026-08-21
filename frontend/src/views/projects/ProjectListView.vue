<template>
  <PageContainer
    title="我的项目"
    subtitle="管理招标项目：上传招标文件、生成技术方案、审阅导出"
  >
    <template #extra>
      <a-button
        v-if="can('project:create')"
        type="primary"
        @click="createModalRef?.open()"
      >
        <template #icon>
          <PlusOutlined />
        </template>
        新建项目
      </a-button>
    </template>

    <!-- 工具栏：搜索 + 行业筛选 -->
    <a-card
      :bordered="false"
      class="toolbar-card"
    >
      <a-space wrap>
        <a-input-search
          id="project-search-input"
          v-model:value="searchKeyword"
          placeholder="搜索项目名称 / 招标编号"
          allow-clear
          style="width: 280px"
          @change="onSearchChange"
          @search="onSearchSubmit"
        />
        <a-select
          v-model:value="industryFilter"
          placeholder="全部行业"
          allow-clear
          style="width: 160px"
          :options="industryOptions"
        />
        <a-select
          v-model:value="sortBy"
          style="width: 140px"
          :options="sortOptions"
        />
        <span class="toolbar-count">
          共 {{ filteredProjects.length }} 个项目
        </span>
      </a-space>
    </a-card>

    <LoadingSkeleton
      v-if="loading"
      :columns="4"
      :rows="3"
    />
    <ErrorState
      v-else-if="loadError"
      :description="loadError"
    >
      <template #action>
        <a-button
          @click="fetchProjects"
        >
          重试
        </a-button>
      </template>
    </ErrorState>
    <!-- 新用户 5 步引导（无项目时显示，按项目状态自动勾选） -->
    <template v-else-if="projects.length === 0">
      <NewUserGuide
        :projects="projects"
        @create="handleGuideCreate"
      />

      <EmptyState
        illustration="folder"
        description="还没有项目，创建第一个项目开始使用"
      >
        <template #action>
          <a-button
            v-if="can('project:create')"
            type="primary"
            @click="createModalRef?.open()"
          >
            <template #icon>
              <PlusOutlined />
            </template>
            新建项目
          </a-button>
        </template>
      </EmptyState>
    </template>

    <EmptyState
      v-else-if="filteredProjects.length === 0"
      illustration="folder"
      description="没有匹配的项目，调整搜索或筛选条件试试"
    />

    <!-- 卡片栅格：断点 1440/1280/768（antd 标准断点 xxl=1600/xl=1200/md=768） -->
    <a-row
      v-else
      :gutter="[16, 16]"
    >
      <a-col
        v-for="item in filteredProjects"
        :key="item.id"
        :xs="24"
        :md="12"
        :xl="8"
        :xxl="6"
      >
        <a-card
          hoverable
          class="project-card"
          @click="enterProject(item.id)"
        >
          <div class="project-card__header">
            <a-avatar
              :size="40"
              class="project-card__avatar"
            >
              <FolderOutlined />
            </a-avatar>
            <div class="project-card__title-wrap">
              <div
                class="project-card__name"
                :title="item.name"
              >
                {{ item.name }}
              </div>
              <a-tag
                v-if="item.owner_id === currentUserId"
                color="blue"
              >
                我创建
              </a-tag>
              <a-tag
                v-if="item.status"
                :color="statusTagColor(item.status)"
              >
                {{ statusText(item.status) }}
              </a-tag>
            </div>
          </div>

          <div class="project-card__meta">
            <div class="project-card__meta-row">
              <span class="project-card__label">招标编号</span>
              <span>{{ item.tender_no || '无' }}</span>
            </div>
            <div class="project-card__meta-row">
              <span class="project-card__label">行业</span>
              <a-tag
                v-if="item.industry"
                :color="industryTagColor(item.industry)"
              >
                {{ item.industry }}
              </a-tag>
              <span v-else>—</span>
            </div>
            <div class="project-card__meta-row">
              <span class="project-card__label">创建时间</span>
              <span>{{ formatTime(item.created_at) }}</span>
            </div>
          </div>

          <!-- 方案进度（后端暂无 progress 字段，按状态阶段推算展示） -->
          <div class="project-card__progress">
            <a-progress
              :percent="statusProgress(item.status)"
              size="small"
              :status="progressStatus(item.status)"
            />
          </div>

          <div class="project-card__footer">
            <a-button
              size="small"
              @click.stop="enterProject(item.id)"
            >
              进入工作台
            </a-button>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <CreateProjectModal
      ref="createModalRef"
      @created="fetchProjects"
    />
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { FolderOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { fetchProjects as fetchProjectsApi } from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import { usePermission } from '@/composables/usePermission'
import { useHotkeys } from '@/composables/useHotkeys'
import { debounce } from '@/utils/debounce'
import { type ProjectItem } from './constants'
import CreateProjectModal from './components/CreateProjectModal.vue'
import NewUserGuide from './components/NewUserGuide.vue'

const { can } = usePermission()

const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const projects = ref<ProjectItem[]>([])
const searchKeyword = ref('')
/** 防抖后生效的搜索词：输入停顿 300ms 后参与过滤；回车 / 点击搜索即时生效 */
const debouncedKeyword = ref('')
const industryFilter = ref<string | undefined>(undefined)
const sortBy = ref('created_desc')
const createModalRef = ref<InstanceType<typeof CreateProjectModal> | null>(null)

const sortOptions = [
  { label: '最新创建', value: 'created_desc' },
  { label: '最早创建', value: 'created_asc' },
  { label: '名称 A-Z', value: 'name_asc' },
  { label: '名称 Z-A', value: 'name_desc' },
]

/** 引导第一步：仅打开弹窗（原实现不加载成员选项） */
const handleGuideCreate = () => {
  createModalRef.value?.open(false)
}

const statusText = (status: string): string => {
  const texts: Record<string, string> = {
    created: '已创建',
    parsing: '解析中',
    parsed: '已解析',
    generating: '生成中',
    generated: '已生成',
    reviewed: '已审阅',
  }
  return texts[status] || status
}

const statusTagColor = (status: string): string => {
  const colors: Record<string, string> = {
    created: 'default',
    parsing: 'processing',
    parsed: 'blue',
    generating: 'processing',
    generated: 'success',
    reviewed: 'success',
  }
  return colors[status] || 'default'
}

/** 后端暂无 progress 字段：按阶段推算方案进度（待后端补充字段） */
const statusProgress = (status?: string): number => {
  const map: Record<string, number> = {
    created: 0,
    parsing: 10,
    parsed: 30,
    generating: 60,
    generated: 85,
    reviewed: 100,
  }
  return map[status || ''] ?? 0
}

const progressStatus = (status?: string): 'active' | 'normal' | 'success' => {
  if (status === 'parsing' || status === 'generating') return 'active'
  if (status === 'reviewed') return 'success'
  return 'normal'
}

const industryTagColor = (industry: string): string => {
  const colors: Record<string, string> = {
    政务: 'blue',
    金融: 'gold',
    能源: 'orange',
    交通: 'purple',
    医疗: 'red',
    教育: 'green',
  }
  return colors[industry] || 'default'
}

const industryOptions = computed(() => {
  const set = new Set<string>()
  for (const p of projects.value) {
    if (p.industry) set.add(p.industry)
  }
  return [...set].map((value) => ({ label: value, value }))
})

const formatTime = (time?: string): string => {
  if (!time) return '—'
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return time
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/* ---------------- 搜索防抖 + 快捷键 ---------------- */
const applySearchKeyword = debounce((kw: string) => {
  debouncedKeyword.value = kw
}, 300)

const onSearchChange = () => {
  applySearchKeyword(searchKeyword.value)
}

const onSearchSubmit = (value: string) => {
  applySearchKeyword.cancel()
  debouncedKeyword.value = value
}

/** 快捷键 Ctrl+K：聚焦页面主搜索框 */
const focusMainSearch = () => {
  document.getElementById('project-search-input')?.focus()
}

useHotkeys([{ combo: 'ctrl+k', handler: focusMainSearch }])

const filteredProjects = computed(() => {
  const kw = debouncedKeyword.value.trim().toLowerCase()
  let list = projects.value.filter((p) => {
    const matchKw =
      !kw ||
      p.name.toLowerCase().includes(kw) ||
      (p.tender_no || '').toLowerCase().includes(kw)
    const matchIndustry = !industryFilter.value || p.industry === industryFilter.value
    return matchKw && matchIndustry
  })
  // 排序
  list = [...list].sort((a, b) => {
    switch (sortBy.value) {
      case 'created_asc':
        return new Date(a.created_at || '').getTime() - new Date(b.created_at || '').getTime()
      case 'name_asc':
        return a.name.localeCompare(b.name)
      case 'name_desc':
        return b.name.localeCompare(a.name)
      case 'created_desc':
      default:
        return new Date(b.created_at || '').getTime() - new Date(a.created_at || '').getTime()
    }
  })
  return list
})

const fetchProjects = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await fetchProjectsApi()
    if (data.code === 0) {
      projects.value = data.data.items
    }
  } catch {
    loadError.value = '项目列表加载失败'
  } finally {
    loading.value = false
  }
}

const enterProject = (projectId: string) => {
  // 工作流第一步：招标解析（资料库已独立为全局页）
  router.push({ name: 'Parse', params: { projectId } })
}

onMounted(() => {
  fetchProjects()
  // 同步当前用户 ID（「我创建」标记比对 owner_id）
  fetchCurrentUserRole()
})

onUnmounted(() => {
  applySearchKeyword.cancel()
})
</script>

<style scoped>
.toolbar-card {
  margin-bottom: var(--space-4);
  background: var(--bg-surface);
}

.toolbar-count {
  color: var(--text-secondary);
  font-size: 13px;
}

.project-card {
  background: var(--bg-surface);
  height: 100%;
}

.project-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.project-card__avatar {
  background: var(--color-primary);
  color: var(--text-inverse);
  flex-shrink: 0;
}

.project-card__title-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.project-card__name {
  font-weight: 600;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-card__meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.project-card__meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.project-card__label {
  width: 64px;
  flex-shrink: 0;
  color: var(--text-secondary);
}

.project-card__progress {
  margin: 12px 0 4px;
}

.project-card__footer {
  display: flex;
  justify-content: flex-end;
}
</style>
