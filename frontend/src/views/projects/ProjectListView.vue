<template>
  <PageContainer
    title="我的项目"
    subtitle="管理招标项目：上传招标文件、生成技术方案、审阅导出"
  >
    <template #extra>
      <a-button
        type="primary"
        @click="showCreateModal = true"
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
          v-model:value="searchKeyword"
          placeholder="搜索项目名称 / 招标编号"
          allow-clear
          style="width: 280px"
        />
        <a-select
          v-model:value="industryFilter"
          placeholder="全部行业"
          allow-clear
          style="width: 160px"
          :options="industryOptions"
        />
        <span class="toolbar-count">
          共 {{ filteredProjects.length }} 个项目
        </span>
      </a-space>
    </a-card>

    <LoadingSkeleton
      v-if="loading"
      :rows="4"
    />
    <ErrorState
      v-else-if="loadError"
      :description="loadError"
    >
      <template #action>
        <a-button
          type="primary"
          @click="fetchProjects"
        >
          重试
        </a-button>
      </template>
    </ErrorState>
    <!-- 新用户 5 步引导（无项目时显示，按项目状态自动勾选） -->
    <a-card
      v-if="projects.length === 0 && !loading && !loadError"
      class="guide-card mb-4"
    >
      <template #title>
        <RocketOutlined /> 快速上手：5 步完成第一份技术方案
      </template>
      <a-steps
        :current="guideCurrent"
        size="small"
        responsive
      >
        <a-step
          v-for="(s, i) in guideSteps"
          :key="i"
          :title="s.title"
          :status="guideStepStatus(i)"
        >
          <template #description>
            <div class="guide-step">
              <span>{{ s.description }}</span>
              <a-button
                v-if="i === guideCurrent"
                size="small"
                type="primary"
                @click="s.action"
              >
                去完成
              </a-button>
            </div>
          </template>
        </a-step>
      </a-steps>
    </a-card>

    <EmptyState
      v-else-if="filteredProjects.length === 0"
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
              type="primary"
              size="small"
              @click.stop="enterProject(item.id)"
            >
              进入工作台
            </a-button>
          </div>
        </a-card>
      </a-col>
    </a-row>

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
      </a-form>
    </a-modal>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { FolderOutlined, PlusOutlined, RocketOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'

interface ProjectItem {
  id: string
  name: string
  // 后端字段为 snake_case（ProjectOut.tender_no），与创建请求保持一致
  tender_no?: string
  industry?: string
  status?: string
  created_at?: string
  owner_id?: string
}

const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const showCreateModal = ref(false)
const creating = ref(false)
const projects = ref<ProjectItem[]>([])
const searchKeyword = ref('')
const industryFilter = ref<string | undefined>(undefined)

const newProject = reactive({
  name: '',
  tender_no: '',
  industry: '',
})

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
    generating: 'cyan',
    generated: 'green',
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

const filteredProjects = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  return projects.value.filter((p) => {
    const matchKw =
      !kw ||
      p.name.toLowerCase().includes(kw) ||
      (p.tender_no || '').toLowerCase().includes(kw)
    const matchIndustry = !industryFilter.value || p.industry === industryFilter.value
    return matchKw && matchIndustry
  })
})

const fetchProjects = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get('/projects')
    if (data.code === 0) {
      projects.value = data.data.items
    }
  } catch {
    loadError.value = '项目列表加载失败'
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  if (!newProject.name.trim()) {
    message.warning('请输入项目名称')
    return
  }
  creating.value = true
  try {
    const { data } = await api.post('/projects', newProject)
    if (data.code === 0) {
      showCreateModal.value = false
      message.success('项目创建成功')
      newProject.name = ''
      newProject.tender_no = ''
      newProject.industry = ''
      fetchProjects()
    } else {
      message.error(data.message || '项目创建失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '项目创建失败'))
  } finally {
    creating.value = false
  }
}

const enterProject = (projectId: string) => {
  // 工作流第一步：招标解析（资料库已独立为全局页）
  router.push({ name: 'Parse', params: { projectId } })
}

/* ---------------- 新用户 5 步引导 ---------------- */
interface GuideStep {
  title: string
  description: string
  done: boolean
  action: () => void
}

/** 按项目状态自动勾选：状态阶段覆盖该步即视为完成 */
const guideSteps = computed<GuideStep[]>(() => {
  const status = projects.value[0]?.status || ''
  return [
    {
      title: '创建项目',
      description: '录入招标项目名称与编号',
      done: projects.value.length > 0,
      action: () => {
        showCreateModal.value = true
      },
    },
    {
      title: '上传招标文件',
      description: '在「招标解析」上传招标文件，公司素材到「全局资料库」',
      done: ['parsing', 'parsed', 'generating', 'generated', 'reviewed'].includes(status),
      action: () => {
        if (projects.value.length > 0) {
          router.push({ name: 'Parse', params: { projectId: projects.value[0].id } })
        }
      },
    },
    {
      title: '确认评分点',
      description: '核对解析出的评分点与技术需求',
      done: ['generating', 'generated', 'reviewed'].includes(status),
      action: () => {},
    },
    {
      title: '生成方案',
      description: '按大纲流式生成各章节',
      done: ['generated', 'reviewed'].includes(status),
      action: () => {},
    },
    {
      title: '审阅导出',
      description: '审阅修改并导出 Word 文档',
      done: status === 'reviewed',
      action: () => {},
    },
  ]
})

const guideCurrent = computed(() => {
  const idx = guideSteps.value.findIndex((s) => !s.done)
  return idx === -1 ? guideSteps.value.length : idx
})

const guideStepStatus = (i: number): 'wait' | 'process' | 'finish' => {
  if (i < guideCurrent.value) return 'finish'
  if (i === guideCurrent.value) return 'process'
  return 'wait'
}

/** 统一错误文案：优先展示后端 message */
const getErrorMessage = (err: unknown, fallback: string): string => {
  const body = (err as { response?: { data?: { message?: string } } })?.response?.data
  return body?.message || fallback
}

onMounted(() => {
  fetchProjects()
  // 同步当前用户 ID（「我创建」标记比对 owner_id）
  fetchCurrentUserRole()
})
</script>

<style scoped>
.toolbar-card {
  margin-bottom: 16px;
  background: var(--card-bg);
}

.guide-card {
  background: var(--card-bg);
}

.guide-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary, #666);
}

.toolbar-count {
  color: var(--text-secondary, #666);
  font-size: 13px;
}

.project-card {
  background: var(--card-bg);
  height: 100%;
}

.project-card__header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.project-card__avatar {
  background: var(--color-primary);
  color: #fff;
  flex-shrink: 0;
}

.project-card__title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
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
  color: var(--text-secondary, #666);
}

.project-card__meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.project-card__label {
  width: 64px;
  flex-shrink: 0;
  color: var(--text-secondary, #666);
}

.project-card__progress {
  margin: 12px 0 4px;
}

.project-card__footer {
  display: flex;
  justify-content: flex-end;
}
</style>
