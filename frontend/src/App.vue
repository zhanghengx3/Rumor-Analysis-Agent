<script setup>
import { ref } from 'vue'

const question = ref('')
const result = ref(null)
const isLoading = ref(false)
const errorMessage = ref('')

// 点击按钮触发接口调用
async function handleSubmit() {
  if (!question.value.trim()) return
  isLoading.value = true
  result.value = null
  errorMessage.value = ''

  try {
    const response = await fetch('http://localhost:8000/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: question.value })
    })

    if (!response.ok) {
      const errData = await response.json()
      throw new Error(errData.detail || '接口请求失败')
    }

    result.value = await response.json()
  } catch (err) {
    errorMessage.value = `发生错误: ${err.message}`
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="container">
    <h1>🔍 谣言辟谣分析系统</h1>

    <div class="input-group">
      <input v-model="question" type="text" placeholder="请输入需要验证的传闻（例如：吃头孢喝酒会猝死吗？）" />
      <button @click="handleSubmit" :disabled="isLoading">
        {{ isLoading ? '大模型推理中...' : '开始辟谣分析' }}
      </button>
    </div>

    <!-- 错误提示 -->
    <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

    <!-- 结果展示区域 -->
    <div v-if="result" class="result-card">
      <h2>分析结果报告</h2>

      <!-- 补强2：关键信息自动抽取 -->
      <div v-if="result.key_entities" class="entities-block">
        <span class="label">关键信息抽取：</span>
        <div class="entities-grid">
          <div class="entity-item"><b>主体：</b>{{ result.key_entities.subject || '未提及' }}</div>
          <div class="entity-item"><b>时间：</b>{{ result.key_entities.time || '未提及' }}</div>
          <div class="entity-item"><b>地点：</b>{{ result.key_entities.location || '未提及' }}</div>
          <div class="entity-item"><b>核心事件：</b>{{ result.key_entities.event || '未提及' }}</div>
        </div>
      </div>

      <div class="verdict-block">
        <div class="verdict-item">
          <span class="label">判断结果：</span>
          <span :class="['verdict-badge', result.verdict]">{{ result.verdict }}</span>
        </div>
        <div class="verdict-item">
          <span class="label">置信度：</span>
          <span class="value">{{ (result.confidence * 100).toFixed(1) }}%</span>
        </div>
      </div>

      <div class="basis-block">
        <span class="label">分析依据：</span>
        <ul>
          <li v-for="(item, index) in result.basis" :key="index">{{ item }}</li>
        </ul>
      </div>

      <!-- 补强3：多源冲突分析 -->
      <div v-if="result.conflict_analysis" class="conflict-block">
        <span class="label">多源冲突分析：</span>
        <p>{{ result.conflict_analysis }}</p>
      </div>

      <div class="conclusion-block">
        <span class="label">最终结论：</span>
        <p>{{ result.conclusion }}</p>
      </div>

      <div v-if="result.reference && result.reference.length > 0" class="reference-block">
        <span class="label">引用来源：</span>
        <ul>
          <li v-for="(item, index) in result.reference" :key="index">
            <!-- 修隐患：url 为空时不渲染空链接，只显示来源说明 -->
            <a v-if="item.url" :href="item.url" target="_blank">{{ item.source }} ({{ item.url }})</a>
            <span v-else>{{ item.source }}（本地知识库）</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.container { max-width: 800px; margin: 40px auto; padding: 20px; font-family: sans-serif; }
.input-group { display: flex; gap: 10px; margin-bottom: 30px; }
input { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; }
button { padding: 0 20px; border: none; border-radius: 6px; background-color: #1a73e8; color: white; cursor: pointer; font-size: 16px; }
button:disabled { background-color: #ccc; cursor: not-allowed; }

.result-card { border: 1px solid #eee; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.label { font-weight: bold; color: #333; }
ul { margin-top: 8px; padding-left: 20px; color: #555; }

/* 补强2：关键信息抽取卡片 */
.entities-block { background: #f5f8ff; border: 1px solid #dbe6ff; border-radius: 8px; padding: 14px 16px; margin-bottom: 20px; }
.entities-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.entity-item { color: #444; font-size: 15px; }

.verdict-block { display: flex; gap: 20px; margin-bottom: 20px; }
.verdict-badge { font-weight: bold; font-size: 1.2em; }
.verdict-badge.虚假 { color: #e53935; }
.verdict-badge.真实 { color: #43a047; }
.verdict-badge.存疑 { color: #ff9800; }

.basis-block { margin-bottom: 20px; }

/* 补强3：多源冲突分析区块（橙色高亮） */
.conflict-block { background: #fff7e6; border-left: 4px solid #ff9800; border-radius: 6px; padding: 14px 16px; margin-bottom: 20px; }
.conflict-block p { margin-top: 8px; line-height: 1.6; color: #6b4e00; }

.conclusion-block { margin-top: 20px; padding-top: 20px; border-top: 1px dashed #eee; }
.conclusion-block p { margin-top: 8px; line-height: 1.6; }
.error { color: #e53935; margin-top: 20px; }
a { color: #1a73e8; text-decoration: none; }
</style>