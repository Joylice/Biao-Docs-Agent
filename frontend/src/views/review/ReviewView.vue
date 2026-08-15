<template>
  <div class="review-view">
    <a-page-header title="审阅与导出" sub-title="审阅生成内容，确认导出" />

    <!-- 审阅意见列表 -->
    <a-card title="审阅意见" class="mb-4" v-if="reviewComments.length > 0">
      <a-list :data-source="reviewComments" size="small">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta :title="`章节 ${item.chapter_no}`" :description="item.comment">
              <template #avatar>
                <a-tag :color="severityColor(item.severity)">{{ item.severity }}</a-tag>
              </template>
            </a-list-item-meta>
            <template #actions>
              <a-button
                size="small"
                type="primary"
                v-if="item.action === 'revise' || item.action === 'rewrite'"
                @click="handleRewrite(item)"
                :loading="rewriting === item.chapter_no"
              >
                重写
              </a-button>
              <a-button size="small" v-else>保留</a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </a-card>

    <!-- 章节内容浏览 -->
    <a-card title="章节内容" class="mb-4">
      <a-tabs v-model:activeKey="activeChapter">
        <a-tab-pane v-for="(content, chapterNo) in chapters" :key="chapterNo" :tab="`章节 ${chapterNo}`">
          <div class="chapter-content" v-html="renderContent(content)"></div>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <!-- 导出操作 -->
    <div class="actions">
      <a-button @click="goToGenerate">返回修改</a-button>
      <a-button type="primary" @click="handleExport" :loading="exporting" size="large">
        导出 Word 文档
      </a-button>
    </div>

    <!-- 导出结果 -->
    <a-result
      v-if="exportStatus === 'done'"
      status="success"
      title="导出成功"
      sub-title="技术方案已生成，可下载编辑"
    >
      <template #extra>
        <a-button type="primary" @click="handleDownload">下载文档</a-button>
      </template>
    </a-result>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import api from '@/api/client'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const reviewComments = ref<any[]>([])
const chapters = ref<Record<string, string>>({})
const activeChapter = ref('')
const rewriting = ref('')
const exporting = ref(false)
const exportStatus = ref('')

const severityColor = (severity: string) => {
  const colors: Record<string, string> = { critical: 'red', warning: 'orange', info: 'blue' }
  return colors[severity] || 'default'
}

const renderContent = (content: string) => {
  return content
    .replace(/### (.*)/g, '<h3>$1</h3>')
    .replace(/## (.*)/g, '<h2>$1</h2>')
    .replace(/\n\n/g, '<br/><br/>')
}

const handleRewrite = async (item: any) => {
  rewriting.value = item.chapter_no
  try {
    const res = await api.post(
      `/projects/${projectId}/workflow/rewrite-chapter`,
      null,
      { params: { chapter_no: item.chapter_no, comment: item.comment } }
    )
    if (res.data?.data?.content) {
      chapters.value[item.chapter_no] = res.data.data.content
      message.success(`章节 ${item.chapter_no} 已重写`)
    }
  } catch {
    message.error('重写失败')
  } finally {
    rewriting.value = ''
  }
}

const handleExport = async () => {
  exporting.value = true
  try {
    const res = await api.get(`/projects/${projectId}/workflow/export`)
    exportStatus.value = res.data?.data?.export_status || 'pending'
    if (exportStatus.value === 'done') {
      message.success('导出成功')
    }
  } catch {
    message.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const handleDownload = () => {
  message.info('下载功能开发中...')
}

const goToGenerate = () => {
  router.push({ name: 'Generate', params: { projectId } })
}

onMounted(async () => {
  try {
    const res = await api.get(`/projects/${projectId}/workflow/status`)
    const data = res.data?.data
    if (data) {
      reviewComments.value = data.review_comments || []
      chapters.value = data.chapters || {}
      const keys = Object.keys(chapters.value)
      if (keys.length > 0) activeChapter.value = keys[0]
    }
  } catch {
    // ignore
  }
})
</script>

<style scoped>
.review-view { max-width: 1000px; }
.mb-4 { margin-bottom: 16px; }
.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
.chapter-content { max-height: 500px; overflow-y: auto; line-height: 1.8; }
</style>
