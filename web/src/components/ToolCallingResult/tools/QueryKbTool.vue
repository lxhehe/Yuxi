<template>
  <BaseToolCall :tool-call="toolCall" :hide-params="true">
    <template #header>
      <div class="sep-header">
        <span class="note">{{ operationLabel }}</span>
        <span class="separator" v-if="resourceLabel">|</span>
        <span class="description" v-if="resourceLabel">知识库: {{ resourceLabel }}</span>
        <span class="separator" v-if="queryText">|</span>
        <span class="description">{{ queryText }}</span>
        <span class="separator" v-if="resultSummary">|</span>
        <span class="description" v-if="resultSummary">{{ resultSummary }}</span>
      </div>
    </template>
    <template #result="{ resultContent }">
      <div class="query-kb-result">
        <KbResultGroupedList
          v-if="parsedResult(resultContent).chunks.length > 0"
          :chunks="parsedResult(resultContent).chunks"
        />

        <div v-if="parsedResult(resultContent).chunks.length === 0" class="no-results">
          未找到相关知识库内容
        </div>
      </div>
    </template>
  </BaseToolCall>
</template>

<script setup>
import { computed } from 'vue'
import BaseToolCall from '../BaseToolCall.vue'
import KbResultGroupedList from '@/components/sources/KbResultGroupedList.vue'
import { useDatabaseStore } from '@/stores/database'
import { parseToolCallArgs } from '../toolRegistry'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  }
})

const databaseStore = useDatabaseStore()

const args = computed(() => parseToolCallArgs(props.toolCall))

const operationLabel = computed(() => '搜索知识库')

const resourceLabel = computed(
  () => args.value.kb_name || databaseStore.getDatabaseNameById(args.value.kb_id)
)
const queryText = computed(() => args.value.query_text || '')

const resultSummary = computed(() => {
  const content = props.toolCall.tool_call_result?.content
  if (!content && props.toolCall.status !== 'success') return ''
  const result = parseResult(content)
  const chunkCount = result.chunks?.length || 0

  if (chunkCount > 0) {
    return `${chunkCount} 个结果`
  }
  if (props.toolCall.tool_call_result || props.toolCall.status === 'success') {
    return '未找到结果'
  }
  return ''
})

const EMPTY_RESULT = Object.freeze({
  chunks: []
})

let lastResultContent = null
let lastParsedResult = EMPTY_RESULT

const normalizeChunks = (payload) => {
  if (!payload || typeof payload !== 'object') return []

  if (Array.isArray(payload.results)) return payload.results
  if (Array.isArray(payload.chunks)) return payload.chunks

  return []
}

const parseResult = (content) => {
  if (content === lastResultContent) return lastParsedResult

  let payload = content
  if (typeof content === 'string') {
    try {
      payload = JSON.parse(content)
    } catch {
      lastResultContent = content
      lastParsedResult = EMPTY_RESULT
      return lastParsedResult
    }
  }

  if (!payload || typeof payload !== 'object') {
    lastResultContent = content
    lastParsedResult = EMPTY_RESULT
    return lastParsedResult
  }

  const nextResult = {
    chunks: normalizeChunks(payload)
  }

  lastResultContent = content
  lastParsedResult = nextResult
  return nextResult
}

const parsedResult = (content) => parseResult(content)
</script>

<style scoped lang="less">
.query-kb-result {
  background: var(--gray-0);
  border-radius: 8px;
  padding: 4px;

  .no-results {
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
    color: var(--gray-600);
  }
}
</style>
