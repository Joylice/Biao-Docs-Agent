<template>
  <div class="generate-view">
    <a-page-header title="方案生成" :sub-title="`进度: ${Math.round(progress * 100)}%`" />

    <!-- 进度条 -->
    <a-progress :percent="Math.round(progress * 100)" :status="progressStatus" class="mb-4" />

    <!-- 大纲预览 -->
    <a-card title="方案大纲" class="mb-4" v-if="outline.length > 0">
      <a-list :data-source="outline" size="small">
        <template #renderItem="{ item }">
          <a-list-item>
            <strong>{{ item.chapter_no }}</strong> {{ item.title }}
            <template #extra>
              <a-tag v-if="chapters[item.chapter_no]" color="green">已生成</a-tag>
              <a-tag v-else-if="currentChapter === item.chapter_no" color="blue">生成中</a-tag>
              <a-tag v-else>待生成</a-tag>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </a-card>

    <!-- 章节内容预览 -->
    <a-card v-if="selectedChapter" :title="`章节 ${selectedChapter}`">
      <template #extra>
        <a-button size="small" @click="selectedChapter = ''">关闭</a-button>
      </template>
      <div class="chapter-content" v-html="renderedContent"></div>
    </a-card>

    <!-- 操作按钮 -->
    <div class="actions">
      <a-button @click="handleStartGenerate" :loading="generating" v-if="!generating && !generated">
        开始生成
      </a-button>
      <a-button type="primary" @click="goToReview" v-if="generated">
        进入审阅
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import api from '@/api/client'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const progress = ref(0)
const generating = ref(false)
const generated = ref(false)
const outline = ref<any[]>([])
const chapters = ref<Record<string, string>>({})
const currentChapter = ref('')
const selectedChapter = ref('')

const progressStatus = computed(() => {
  if (progress.value >= 1) return 'success'
  if (generating.value) return 'active'
  return 'normal'
})

const renderedContent = computed(() => {
  const content = chapters.value[selectedChapter.value] || ''
  // Simple markdown to HTML conversion
  return content
    .replace(/### (.*)/g, '<h3>$1</h3>')
    .replace(/## (.*)/g, '<h2>$1</h2>')
    .replace(/\n\n/g, '<br/><br/>')
})

let ws: WebSocket | null = null

const connectWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const token = localStorage.getItem('access_token') || ''
  const wsUrl = `${protocol}://${window.location.host}/ws/${projectId}?token=${encodeURIComponent(token)}`
  ws = new WebSocket(wsUrl)
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'progress') {
      progress.value = data.progress
      currentChapter.value = data.current_chapter || ''
      if (data.chapters) {
        chapters.value = data.chapters
      }
    } else if (data.type === 'done') {
      generated.value = true
      generating.value = false
      progress.value = 1
    }
  }
  ws.onclose = (event) => {
    if (event.code === 4001) {
      // 未认证：清除失效 token 并跳转登录
      localStorage.removeItem('access_token')
      message.warning('登录已过期，请重新登录')
      router.push({ name: 'Login' })
    } else if (event.code === 4003) {
      // 非项目成员
      generating.value = false
      message.error('无权限访问该项目')
    } else { /* reconnect logic */ }
  }
}

const handleStartGenerate = async () => {
  generating.value = true
  try {
    await api.post(`/projects/${projectId}/workflow/confirm-outline`)
    connectWebSocket()
    message.info('开始生成方案...')
  } catch {
    message.error('启动生成失败')
    generating.value = false
  }
}

const goToReview = () => {
  router.push({ name: 'Review', params: { projectId } })
}

onMounted(async () => {
  // 获取大纲
  try {
    const res = await api.get(`/projects/${projectId}/workflow/status`)
    const data = res.data?.data
    if (data?.outline) {
      outline.value = data.outline
      chapters.value = data.chapters || {}
      progress.value = data.progress || 0
      generated.value = progress.value >= 0.75
    }
  } catch {
    // ignore
  }
})

onUnmounted(() => {
  ws?.close()
})
</script>

<style scoped>
.generate-view { max-width: 1000px; }
.mb-4 { margin-bottom: 16px; }
.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
.chapter-content { max-height: 500px; overflow-y: auto; line-height: 1.8; }
</style>
