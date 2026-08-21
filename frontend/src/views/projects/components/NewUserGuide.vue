<template>
  <!-- 新用户 5 步引导（无项目时显示，按项目状态自动勾选） -->
  <a-card class="guide-card mb-4">
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
              @click="s.action"
            >
              去完成
            </a-button>
          </div>
        </template>
      </a-step>
    </a-steps>
  </a-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { RocketOutlined } from '@ant-design/icons-vue'
import type { ProjectItem } from '../constants'

const props = defineProps<{
  projects: ProjectItem[]
}>()

const emit = defineEmits<{
  /** 引导第一步：打开新建项目弹窗 */
  (e: 'create'): void
}>()

const router = useRouter()

interface GuideStep {
  title: string
  description: string
  done: boolean
  action: () => void
}

/** 按项目状态自动勾选：状态阶段覆盖该步即视为完成 */
const guideSteps = computed<GuideStep[]>(() => {
  const status = props.projects[0]?.status || ''
  return [
    {
      title: '创建项目',
      description: '录入招标项目名称与编号',
      done: props.projects.length > 0,
      action: () => {
        emit('create')
      },
    },
    {
      title: '上传招标文件',
      description: '在「招标解析」上传招标文件，公司素材到「全局资料库」',
      done: ['parsing', 'parsed', 'generating', 'generated', 'reviewed'].includes(status),
      action: () => {
        if (props.projects.length > 0) {
          router.push({ name: 'Parse', params: { projectId: props.projects[0].id } })
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
</script>

<style scoped>
.guide-card {
  background: var(--bg-surface);
}

.guide-step {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 12px;
  color: var(--text-secondary);
}

</style>
