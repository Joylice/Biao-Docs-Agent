<template>
  <div class="parse-confirm">
    <a-page-header
      title="招标解析确认"
      sub-title="确认评分点和技术需求"
    />

    <a-spin
      :spinning="loading"
      tip="解析中..."
    >
      <!-- 评分点表格 -->
      <a-card
        title="评分点"
        class="mb-4"
      >
        <a-table
          :columns="scoreColumns"
          :data-source="scorePoints"
          :pagination="false"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'is_star'">
              <a-tag :color="record.is_star ? 'red' : 'default'">
                {{ record.is_star ? '重点' : '普通' }}
              </a-tag>
            </template>
            <template v-if="column.key === 'risk_level'">
              <a-tag :color="riskColor(record.risk_level)">
                {{ record.risk_level || '-' }}
              </a-tag>
            </template>
            <template v-if="column.key === 'strategy'">
              <a-input
                v-model:value="record.strategy"
                placeholder="填写应对策略..."
                :rows="2"
                type="textarea"
              />
            </template>
          </template>
        </a-table>
      </a-card>

      <!-- 技术需求 -->
      <a-card
        title="技术需求"
        class="mb-4"
      >
        <a-table
          :columns="techColumns"
          :data-source="techRequirements"
          :pagination="false"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'is_mandatory'">
              <a-tag :color="record.is_mandatory ? 'red' : 'blue'">
                {{ record.is_mandatory ? '强制' : '建议' }}
              </a-tag>
            </template>
          </template>
        </a-table>
      </a-card>

      <!-- 操作按钮 -->
      <div class="actions">
        <a-button
          :loading="loading"
          @click="handleReparse"
        >
          重新解析
        </a-button>
        <a-button
          type="primary"
          :loading="confirming"
          @click="handleConfirm"
        >
          确认并生成大纲
        </a-button>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import api from '@/api/client'

interface ScorePoint {
  id: string
  clause_no: string
  item: string
  score: number
  criteria: string
  is_star: boolean
  risk_level: string
  strategy: string
}

interface TechRequirement {
  id: string
  seq: number
  description: string
  category: string
  is_mandatory: boolean
}

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const loading = ref(false)
const confirming = ref(false)
const scorePoints = ref<ScorePoint[]>([])
const techRequirements = ref<TechRequirement[]>([])

const scoreColumns = [
  { title: '条款号', dataIndex: 'clause_no', key: 'clause_no', width: 100 },
  { title: '评分项', dataIndex: 'item', key: 'item' },
  { title: '分值', dataIndex: 'score', key: 'score', width: 80 },
  { title: '评分标准', dataIndex: 'criteria', key: 'criteria' },
  { title: '类型', key: 'is_star', width: 80 },
  { title: '风险', key: 'risk_level', width: 80 },
  { title: '应对策略', key: 'strategy', width: 200 },
]

const techColumns = [
  { title: '序号', dataIndex: 'seq', key: 'seq', width: 60 },
  { title: '需求描述', dataIndex: 'description', key: 'description' },
  { title: '分类', dataIndex: 'category', key: 'category', width: 100 },
  { title: '类型', key: 'is_mandatory', width: 80 },
]

const riskColor = (level: string) => {
  const colors: Record<string, string> = { high: 'red', mid: 'orange', low: 'green' }
  return colors[level] || 'default'
}

const fetchData = async () => {
  loading.value = true
  try {
    const [spRes, trRes] = await Promise.all([
      api.get(`/projects/${projectId}/score-points`),
      api.get(`/projects/${projectId}/tech-requirements`),
    ])
    scorePoints.value = spRes.data?.data || []
    techRequirements.value = trRes.data?.data || []
  } catch {
    message.error('获取数据失败')
  } finally {
    loading.value = false
  }
}

const handleConfirm = async () => {
  confirming.value = true
  try {
    await api.post(`/projects/${projectId}/workflow/confirm-score-points`)
    message.success('已确认，开始生成大纲...')
    router.push({ name: 'Generate', params: { projectId } })
  } catch {
    message.error('确认失败')
  } finally {
    confirming.value = false
  }
}

const handleReparse = () => {
  message.info('重新解析功能开发中...')
}

onMounted(fetchData)
</script>

<style scoped>
.parse-confirm { max-width: 1200px; }
.mb-4 { margin-bottom: 16px; }
.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
</style>
