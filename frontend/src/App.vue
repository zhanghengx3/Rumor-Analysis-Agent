<script setup>
import { ref, nextTick, onMounted, computed } from 'vue'
import RumorCard from './components/RumorCard.vue'
import botAvatar from './assets/avatar.png'

// ===== 状态 =====
const messages = ref([])           // 消息列表
const inputText = ref('')          // 输入框内容
const isLoading = ref(false)       // 是否加载中
const sessionId = ref('')          // 会话ID
const messagesEnd = ref(null)      // 滚动到底部用的 ref
const inputRef = ref(null)         // 输入框 ref

// API 地址
const API_BASE = 'http://localhost:8000'

// 预设的快捷问题
const quickQuestions = [
  '你好呀',
  '你能做什么？',
  '吃头孢喝酒会猝死吗',
  '微波炉加热食物致癌是真的吗',
]

// ===== 初始化 =====
onMounted(() => {
  // 从 localStorage 读取 session_id
  let sid = localStorage.getItem('rumor_session_id')
  if (!sid) {
    sid = 'session_' + Math.random().toString(36).slice(2, 14)
    localStorage.setItem('rumor_session_id', sid)
  }
  sessionId.value = sid

  // 添加欢迎消息
  addBotText('你好呀！我是谣言终结者 🛡️\n专职鉴别各类谣言，也可以陪你聊天~')
  inputRef.value?.focus()
})

// ===== 工具函数 =====
function scrollToBottom() {
  nextTick(() => {
    messagesEnd.value?.scrollIntoView({ behavior: 'smooth' })
  })
}

function addUserMessage(text) {
  messages.value.push({
    id: Date.now() + Math.random(),
    role: 'user',
    type: 'text',
    content: text,
  })
  scrollToBottom()
}

function addBotText(text) {
  messages.value.push({
    id: Date.now() + Math.random(),
    role: 'bot',
    type: 'text',
    content: text,
  })
  scrollToBottom()
}

function addBotRumor(result) {
  messages.value.push({
    id: Date.now() + Math.random(),
    role: 'bot',
    type: 'rumor',
    rumorResult: result,
  })
  scrollToBottom()
}

function addBotLoading() {
  const msg = {
    id: Date.now() + Math.random(),
    role: 'bot',
    type: 'loading',
    content: '正在思考中...',
  }
  messages.value.push(msg)
  scrollToBottom()
  return msg
}

function removeLoading(loadingMsg) {
  const idx = messages.value.indexOf(loadingMsg)
  if (idx > -1) {
    messages.value.splice(idx, 1)
  }
}

// ===== 发送消息 =====
async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isLoading.value) return

  isLoading.value = true
  addUserMessage(text)
  inputText.value = ''

  const loadingMsg = addBotLoading()

  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        session_id: sessionId.value,
      }),
    })

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}))
      throw new Error(errData.detail || '请求失败')
    }

    const data = await response.json()
    removeLoading(loadingMsg)

    // 根据返回类型展示不同消息
    if (data.type === 'rumor' && data.rumor_result) {
      addBotRumor(data.rumor_result)
    } else {
      addBotText(data.content || '抱歉，我没有理解你的意思 😅')
    }

    // 更新 session_id（如果服务端返回了新的）
    if (data.session_id) {
      sessionId.value = data.session_id
      localStorage.setItem('rumor_session_id', data.session_id)
    }
  } catch (err) {
    removeLoading(loadingMsg)
    addBotText(`出错了：${err.message} 😢`)
  } finally {
    isLoading.value = false
    nextTick(() => inputRef.value?.focus())
  }
}

// 快捷提问
function askQuick(question) {
  inputText.value = question
  sendMessage()
}

// 新会话
function startNewSession() {
  if (!confirm('确定要开启新会话吗？当前对话记录将会清空。')) return
  const newSid = 'session_' + Math.random().toString(36).slice(2, 14)
  sessionId.value = newSid
  localStorage.setItem('rumor_session_id', newSid)
  messages.value = []
  addBotText('新会话开始啦！有什么想聊的吗？😊')
}

// 处理回车发送
function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}
</script>

<template>
  <div class="chat-app">
    <!-- 顶部标题栏 -->
    <header class="chat-header">
      <div class="header-left">
        <img class="logo-img" :src="botAvatar" alt="谣言终结者" />
        <div class="title-wrap">
          <h1>谣言终结者</h1>
          <p class="subtitle">智能辟谣 · 多智能体协作</p>
        </div>
      </div>
      <button class="new-session-btn" @click="startNewSession" title="新会话">
        💬 新会话
      </button>
    </header>

    <!-- 消息区域 -->
    <main class="chat-messages">
      <!-- 快捷问题（只有一条消息都没有时显示） -->
      <div v-if="messages.length <= 1" class="quick-questions">
        <p class="quick-title">试试这些问题 👇</p>
        <div class="quick-grid">
          <button
            v-for="q in quickQuestions"
            :key="q"
            class="quick-btn"
            @click="askQuick(q)"
            :disabled="isLoading"
          >
            {{ q }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['message-row', msg.role === 'user' ? 'is-user' : 'is-bot']"
      >
        <!-- 头像 -->
        <div class="avatar">
          <span v-if="msg.role === 'user'">🧑</span>
          <img v-else :src="botAvatar" alt="bot" class="avatar-img" />
        </div>

        <!-- 消息气泡 -->
        <div class="message-content">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="bubble user-bubble">
            {{ msg.content }}
          </div>

          <!-- Bot 加载中 -->
          <div v-else-if="msg.type === 'loading'" class="bubble bot-bubble loading-bubble">
            <div class="typing-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>

          <!-- Bot 文本消息 -->
          <div v-else-if="msg.type === 'text'" class="bubble bot-bubble">
            <p v-for="(line, idx) in msg.content.split('\n')" :key="idx">
              {{ line }}
            </p>
          </div>

          <!-- Bot 谣言分析卡片 -->
          <RumorCard v-else-if="msg.type === 'rumor'" :result="msg.rumorResult" />
        </div>
      </div>

      <!-- 滚动锚点 -->
      <div ref="messagesEnd"></div>
    </main>

    <!-- 底部输入栏 -->
    <footer class="chat-input-bar">
      <div class="input-wrap">
        <textarea
          ref="inputRef"
          v-model="inputText"
          placeholder="说点什么吧...（Enter 发送，Shift+Enter 换行）"
          rows="1"
          @keydown="handleKeydown"
          :disabled="isLoading"
        ></textarea>
        <button
          class="send-btn"
          @click="sendMessage"
          :disabled="isLoading || !inputText.trim()"
        >
          {{ isLoading ? '...' : '发送' }}
        </button>
      </div>
      <p class="footer-tip">💡 输入传闻即可自动识别并分析，也可以直接聊天</p>
    </footer>
  </div>
</template>

<style scoped>
* {
  box-sizing: border-box;
}

.chat-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0f2f5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* ===== 顶部栏 ===== */
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: white;
  border-bottom: 1px solid #e5e7eb;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  font-size: 32px;
}

.logo-img {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid #e5e7eb;
}

.title-wrap h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  color: #9ca3af;
}

.new-session-btn {
  padding: 8px 16px;
  font-size: 13px;
  background: #f3f4f6;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.new-session-btn:hover {
  background: #e5e7eb;
}

/* ===== 消息区域 ===== */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 快捷问题 */
.quick-questions {
  text-align: center;
  padding: 20px 0 10px;
}

.quick-title {
  color: #9ca3af;
  font-size: 14px;
  margin-bottom: 14px;
}

.quick-grid {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  max-width: 500px;
  margin: 0 auto;
}

.quick-btn {
  padding: 8px 16px;
  font-size: 13px;
  background: white;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-btn:hover:not(:disabled) {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.quick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 消息行 */
.message-row {
  display: flex;
  gap: 10px;
  max-width: 100%;
}

.message-row.is-user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.avatar-img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}

.message-row.is-user .avatar {
  background: #dbeafe;
}

.message-content {
  max-width: calc(100% - 60px);
  display: flex;
  flex-direction: column;
}

.message-row.is-user .message-content {
  align-items: flex-end;
}

/* 气泡 */
.bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-wrap: break-word;
  word-break: break-word;
}

.bubble p {
  margin: 0;
}

.bubble p + p {
  margin-top: 6px;
}

.user-bubble {
  background: #3b82f6;
  color: white;
  border-bottom-right-radius: 4px;
}

.bot-bubble {
  background: white;
  color: #1f2937;
  border: 1px solid #e5e7eb;
  border-bottom-left-radius: 4px;
}

/* 加载中动画 */
.loading-bubble {
  padding: 12px 16px;
}

.typing-dots {
  display: flex;
  gap: 4px;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  background: #9ca3af;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out both;
}

.typing-dots span:nth-child(1) { animation-delay: -0.32s; }
.typing-dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes typing {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* ===== 底部输入栏 ===== */
.chat-input-bar {
  background: white;
  border-top: 1px solid #e5e7eb;
  padding: 12px 20px;
}

.input-wrap {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  max-width: 900px;
  margin: 0 auto;
}

.input-wrap textarea {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.5;
  resize: none;
  max-height: 120px;
  transition: border-color 0.2s;
}

.input-wrap textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.input-wrap textarea:disabled {
  background: #f9fafb;
  cursor: not-allowed;
}

.send-btn {
  padding: 10px 24px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
  height: 40px;
}

.send-btn:hover:not(:disabled) {
  background: #2563eb;
}

.send-btn:disabled {
  background: #9ca3af;
  cursor: not-allowed;
}

.footer-tip {
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
  margin: 8px 0 0;
}

/* ===== 滚动条美化 ===== */
.chat-messages::-webkit-scrollbar {
  width: 6px;
}

.chat-messages::-webkit-scrollbar-track {
  background: transparent;
}

.chat-messages::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}

.chat-messages::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}
</style>
