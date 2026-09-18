<template>
  <div class="retrieval-panel">
    <!-- 头部：标题 + 重建索引 -->
    <div class="retrieval-panel__header">
      <div>
        <h3 class="retrieval-panel__title">{{ title }}</h3>
        <p class="retrieval-panel__desc">{{ desc }}</p>
      </div>
      <a-button danger :loading="reindexing" @click="onReindex">
        <template #icon><ThunderboltOutlined /></template>
        重建索引
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <!-- ── Embedding 配置 ── -->
      <div class="retrieval-panel__card">
        <div class="retrieval-panel__card-title">
          <span>向量嵌入（Embedding）</span>
          <a-tag :color="embed.configured ? 'success' : 'warning'">
            {{ embed.configured ? '已配置' : '未配置' }}
          </a-tag>
        </div>
        <a-form layout="vertical" class="retrieval-panel__form">
          <a-form-item label="模型名称">
            <a-input v-model:value="embed.model" placeholder="dashscope/text-embedding-v3" />
            <div class="retrieval-panel__quick-models">
              <span
                v-for="m in quickEmbedModels"
                :key="m"
                class="retrieval-panel__quick-model"
                @click="embed.model = m"
              >{{ m }}</span>
            </div>
          </a-form-item>
          <a-form-item label="服务地址（可选）">
            <a-input v-model:value="embed.apiBase" placeholder="留空使用默认端点" />
            <div class="retrieval-panel__hint">支持 http/https 完整 URL；R1 后密钥真源在 providers 表，按模型前缀匹配</div>
          </a-form-item>
          <a-form-item label="API Key">
            <div class="retrieval-panel__key-row">
              <a-input-password
                v-model:value="embed.keyInput"
                :placeholder="embed.configured ? '已配置，留空保持现有密钥不变' : '输入 API Key（留空则按模型前缀回退 LLM 密钥）'"
                autocomplete="new-password"
              />
              <a-button v-if="embed.configured && !embed.keyCleared" danger @click="clearEmbedKey">清除</a-button>
            </div>
            <div v-if="embed.keyCleared" class="retrieval-panel__key-cleared">
              <a-tag color="warning">保存后将清除已存密钥</a-tag>
              <a-button type="link" size="small" @click="resetEmbedKeyClear">撤销</a-button>
            </div>
            <div class="retrieval-panel__hint">脱敏回显：{{ embed.apiKeyMasked || '未配置' }}；留空 = 保持原值，清除需显式操作</div>
          </a-form-item>
        </a-form>
        <div class="retrieval-panel__test">
          <a-button :loading="testing" @click="testEmbedding">
            <template #icon><ApiOutlined /></template>
            测试连通性
          </a-button>
          <a-alert
            v-if="testResult?.ok"
            type="success"
            show-icon
            class="retrieval-panel__test-result"
            :message="`连通正常${typeof testResult.dimension === 'number' ? `（维度 ${testResult.dimension}）` : ''}`"
          />
          <a-alert
            v-else-if="testResult && !testResult.ok"
            type="error"
            show-icon
            class="retrieval-panel__test-result"
            :message="`连通失败：${testResult.error || '未知错误'}`"
          />
        </div>
      </div>

      <!-- ── 检索参数 ── -->
      <div class="retrieval-panel__card">
        <div class="retrieval-panel__card-title"><span>检索参数</span></div>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="召回 Top-K（1 ~ 50）">
              <a-input-number v-model:value="params.recallTopK" :min="1" :max="50" :precision="0" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="相似度阈值（0 ~ 1）">
              <a-input-number v-model:value="params.similarityThreshold" :min="0" :max="1" :step="0.05" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="混合检索权重（0 ~ 1）">
              <a-input-number v-model:value="params.hybridWeight" :min="0" :max="1" :step="0.1" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <div class="retrieval-panel__hint">DB 持久化；后端不可达时前端以 localStorage 回退（下次启动自动重读）</div>
      </div>

      <!-- ── Rerank ── -->
      <div class="retrieval-panel__card">
        <div class="retrieval-panel__card-title">
          <span>重排序（Rerank）</span>
          <a-tag :color="rerank.configured ? 'success' : 'default'">
            {{ rerank.configured ? '已配置' : '可选' }}
          </a-tag>
          <a-switch
            v-model:checked="rerank.enabled"
            checked-children="启用"
            un-checked-children="关闭"
            class="retrieval-panel__rerank-switch"
          />
        </div>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="模型名称">
              <a-input v-model:value="rerank.model" placeholder="dashscope/gte-rerank" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="重排 Top-K（1 ~ 20）">
              <a-input-number v-model:value="rerank.topK" :min="1" :max="20" :precision="0" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="API Key（可复用 Embedding Key）">
          <div class="retrieval-panel__key-row">
            <a-input-password
              v-model:value="rerank.keyInput"
              :placeholder="rerank.configured ? '已配置，留空保持现有密钥不变' : '留空复用 Embedding 密钥'"
              autocomplete="new-password"
            />
            <a-button v-if="rerank.configured && !rerank.keyCleared" danger @click="clearRerankKey">清除</a-button>
          </div>
          <div v-if="rerank.keyCleared" class="retrieval-panel__key-cleared">
            <a-tag color="warning">保存后将清除已存密钥</a-tag>
            <a-button type="link" size="small" @click="resetRerankKeyClear">撤销</a-button>
          </div>
          <div class="retrieval-panel__hint">脱敏回显：{{ rerank.apiKeyMasked || '未配置' }}</div>
        </a-form-item>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/**
 * RetrievalPanel：知识库参数分类面板（P0-5，迁移 RetrievalView 逻辑）.
 *
 * embedding 配置 + 检索参数 + rerank + 重建索引入口，全部编辑态由
 * useRetrievalConfig 模块级单例承载（面板切换不丢）；底部 footer 保存经
 * registry entry.save → composable.save（校验 + 双端点提交 + reload）。
 * 编辑经 watch 联动 store.markDirty/clearDirty 驱动导航角标。
 */
import { onMounted, watch } from 'vue'
import {
  ApiOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { useConfigCenterStore } from '@/stores/configCenter'
import { useRetrievalConfig } from '@/composables/useRetrievalConfig'

withDefaults(
  defineProps<{
    title?: string
    desc?: string
  }>(),
  { title: '检索参数', desc: '' },
)

const store = useConfigCenterStore()
const config = useRetrievalConfig()

const {
  loading,
  reindexing,
  testing,
  testResult,
  embed,
  params,
  rerank,
  load,
  clearEmbedKey,
  resetEmbedKeyClear,
  clearRerankKey,
  resetRerankKeyClear,
  testEmbedding,
  runReindex,
} = config

const quickEmbedModels = [
  'dashscope/text-embedding-v3',
  'openai/text-embedding-3-small',
  'ollama/bge-m3',
]

const onReindex = () => {
  void runReindex()
}

/** 编辑即置脏（保存成功后 load() 重置，watch 随之清除角标） */
watch(
  () => config.isDirty(),
  (dirty) => {
    if (dirty) {
      store.markDirty('retrieval:params')
    } else {
      store.clearDirty('retrieval:params')
    }
  },
  { immediate: true },
)

onMounted(load)
</script>

<style scoped>
.retrieval-panel {
  max-width: 760px;
}

.retrieval-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.retrieval-panel__title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.retrieval-panel__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.retrieval-panel__card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-3);
}

.retrieval-panel__card-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.retrieval-panel__rerank-switch {
  margin-left: auto;
}

.retrieval-panel__key-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.retrieval-panel__key-row > :first-child {
  flex: 1;
}

.retrieval-panel__key-cleared {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.retrieval-panel__hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.retrieval-panel__quick-models {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.retrieval-panel__quick-model {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-family: var(--font-family-mono);
  background: var(--bg-app);
  color: var(--text-secondary);
  border: 1px solid var(--border-color-light);
  cursor: pointer;
}

.retrieval-panel__quick-model:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.retrieval-panel__test {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.retrieval-panel__test-result {
  flex: 1;
  min-width: 0;
}
</style>
