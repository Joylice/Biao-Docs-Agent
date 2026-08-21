<template>
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
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { searchMaterials } from '@/api'
import { debounce } from '@/utils/debounce'
import type { SearchItem } from '../constants'

const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<SearchItem[]>([])

const handleSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    return
  }
  searching.value = true
  searchResults.value = []
  try {
    const { data } = await searchMaterials({ q, top_k: 5 })
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

onUnmounted(() => {
  debouncedSearch.cancel()
})
</script>

<style scoped>
.kb-card {
  margin-bottom: var(--space-4);
}
.kb-search-results {
  margin-top: var(--space-3);
}
</style>
