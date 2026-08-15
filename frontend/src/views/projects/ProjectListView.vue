<template>
  <div class="project-list">
    <a-page-header title="我的项目" />
    <a-button type="primary" @click="showCreateModal = true">新建项目</a-button>
    <a-list :data-source="projects" :loading="loading" style="margin-top: 16px">
      <template #renderItem="{ item }">
        <a-list-item>
          <a-list-item-meta :title="item.name" :description="`招标编号: ${item.tenderNo || '无'}`" />
          <template #actions>
            <a-button type="link" @click="enterProject(item.id)">进入</a-button>
          </template>
        </a-list-item>
      </template>
    </a-list>

    <a-modal v-model:open="showCreateModal" title="新建项目" @ok="handleCreate">
      <a-form :model="newProject">
        <a-form-item label="项目名称">
          <a-input v-model:value="newProject.name" />
        </a-form-item>
        <a-form-item label="招标编号">
          <a-input v-model:value="newProject.tenderNo" />
        </a-form-item>
        <a-form-item label="行业">
          <a-input v-model:value="newProject.industry" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/client'

const router = useRouter()
const loading = ref(false)
const showCreateModal = ref(false)
const projects = ref<Array<{ id: string; name: string; tenderNo: string }>>([])

const newProject = reactive({
  name: '',
  tenderNo: '',
  industry: '',
})

const fetchProjects = async () => {
  loading.value = true
  try {
    const { data } = await api.get('/projects')
    if (data.code === 0) {
      projects.value = data.data.items
    }
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  const { data } = await api.post('/projects', newProject)
  if (data.code === 0) {
    showCreateModal.value = false
    fetchProjects()
  }
}

const enterProject = (projectId: string) => {
  router.push({ name: 'KnowledgeBase', params: { projectId } })
}

onMounted(fetchProjects)
</script>
