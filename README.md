# Rumor Analysis Agent

基于大语言模型（LLM）与检索增强生成（RAG）技术的谣言分析系统。系统结合本地辟谣知识库与互联网权威检索，对用户输入的传闻进行多源交叉验证，输出结构化的辟谣分析报告。

## 功能特性

- **本地知识库检索**：基于 FAISS 向量数据库检索本地辟谣资料，支持语义相似度匹配
- **联网事实核查**：通过 Tavily 搜索获取互联网权威信息，与本地证据交叉验证
- **多源冲突分析**：自动对比本地与联网证据，指出冲突点并说明采信逻辑
- **关键信息抽取**：自动提取传闻中的主体、时间、地点及核心事件
- **置信度评分**：基于本地相关度、来源数量及证据冲突情况客观计算（0 ~ 100%）
- **结构化报告**：统一输出格式，包含判断结论、推理依据、引用来源等

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端 | Python + FastAPI |
| AI Agent | LangChain + OpenAI 兼容接口 |
| 向量检索 | FAISS + BGE Embedding |
| 联网搜索 | Tavily Search API |
| 前端 | Vue 3 + Vite |

## 快速开始

### 环境要求

- Python >= 3.10
- Node.js >= 18
- 可用的 OpenAI 兼容大模型 API
- Tavily API Key（联网搜索）

### 1. 克隆与安装

```bash
git clone <your-repo-url>
cd yaoyan/back

# 方式一：使用 uv（推荐，更快）
uv sync

# 方式二：使用 pip + pyproject.toml
pip install -e .

# 方式三：使用 requirements.txt
pip install -r requirements.txt
```

### 2. 配置环境变量

复制模板文件并填写你的密钥：

```bash
cp .env.example .env
```

编辑 `.env`，填入以下信息：

```env
# 大模型（OpenAI 兼容格式）
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-llm-api-key

# Tavily 联网搜索
TAVILY_API_KEY=your-tavily-api-key

# Embedding 配置
# 模式：local（本地 BGE）或 dashscope（云端）
EMBEDDING_MODE=local

# 本地 BGE 模型路径（可选，默认自动下载 BAAI/bge-small-zh-v1.5）
BGE_LOCAL_DIR=./models/bge-small-zh-v1.5
BGE_DEVICE=cpu

# DashScope 云端兜底（当本地模型加载失败时自动回退）
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=your-dashscope-key

# 知识库与索引路径
KKB_PATH=./knowledge_base
INDEX_PATH=./faiss_index
```

### 3. 准备知识库

在 `back/knowledge_base/` 目录下放入你的辟谣资料（支持 `.md` 文件）。系统启动时会自动构建向量索引。

### 4. 启动后端

```bash
cd back
python lie_server.py
```

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 5. 启动前端

```bash
cd ../frontend
npm install
npm run dev
```

打开浏览器访问 http://localhost:5173 即可使用。

## API 说明

### POST `/api/analyze`

提交传闻进行分析。

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"question": "吃头孢喝酒会猝死吗？"}'
```

**响应示例：**

```json
{
  "key_entities": {
    "subject": "头孢",
    "time": "未提及",
    "location": "未提及",
    "event": "吃头孢后喝酒会导致猝死"
  },
  "verdict": "真实",
  "confidence": 0.92,
  "basis": [
    "本地证据：头孢类药物与酒精同服可能引发双硫仑样反应，严重时可致命（本地辟谣知识库）",
    "联网证据：多家医学权威网站确认头孢+酒精存在致命风险（联网检索）"
  ],
  "conflict_analysis": "本地证据与联网证据一致，均确认该传闻具有医学依据，无冲突。",
  "conclusion": "该传闻属实，服用头孢期间及停药后一周内应严格禁酒。",
  "reference": [
    { "source": "本地辟谣知识库", "url": "" },
    { "source": "某医学权威网站", "url": "https://example.com/article" }
  ]
}
```

### GET `/health`

检查服务状态。

```bash
curl http://localhost:8000/health
```

## 项目结构

```
yaoyan/
├── back/                          # 后端服务
│   ├── lie_server.py              # FastAPI 后端主服务
│   ├── pyproject.toml             # Python 依赖配置（uv / pip）
│   ├── requirements.txt           # Python 依赖清单（pip 兼容）
│   ├── .env.example               # 环境变量模板
│   └── knowledge_base/            # 本地辟谣知识库（Markdown 文件）
│       └── 谣言.md
│
├── frontend/                      # 前端页面
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       └── App.vue                # 前端主页面
│
├── README.md                      # 项目说明
└── .gitignore
```

> 注：`faiss_index/`（向量索引）和 `models/`（本地模型）会在首次运行时自动生成，已被 `.gitignore` 排除。

## 注意事项

1. **索引隔离**：不同 Embedding 模型生成的向量空间互不兼容，系统会自动按实际生效的 Embedding 模式（`local` / `dashscope`）隔离索引目录，避免混用导致检索异常。

2. **模型自动回退**：当 `EMBEDDING_MODE=local` 且本地 BGE 模型加载失败时，系统会自动回退到 DashScope 云端 Embedding，确保服务仍能启动。

3. **来源真实性**：联网搜索返回的引用 URL 直接来自 Tavily 检索结果，严禁捏造或修改 URL。

4. **CORS**：后端默认开启全跨域支持（`allow_origins=["*"]`），生产环境请按需收紧。

## License

MIT
