from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from pydantic import BaseModel as PydanticBaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import uvicorn
import  os,os.path as osp

load_dotenv()

# ===== 1. 大模型 =====
model = ChatOpenAI(
    model="qwen3-max",
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
    api_key=os.getenv("DASHSCOPE_API_KEY"),
)

# ===== 2. Embedding：默认本地化部署(bge)，自动/手动切换云端兜底 =====
# 优先级：本地模型目录存在 -> 本地离线加载；目录不存在且 EMBEDDING_MODE=local -> 镜像在线下载；
#         若镜像也失败 -> 自动回退 DashScope 云端 embedding，保证服务一定能启动。
# 依赖： uv add langchain-huggingface sentence-transformers
BGE_LOCAL_DIR = os.getenv("BGE_LOCAL_DIR", r"D:\Langchain\test\models\bge-small-zh-v1.5")
EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "local").lower()


def _build_embeddings():
    """返回 (embeddings, QUERY_INSTRUCTION, IS_BGE, 实际生效的模式)。"""
    # 2.1 本地 bge（优先指向已下载的本地目录，彻底离线）
    if EMBEDDING_MODE == "local":
        from langchain_huggingface import HuggingFaceEmbeddings
        # 本地目录存在就用本地路径（离线），否则回退到仓库名（会走镜像在线下载）
        model_name = BGE_LOCAL_DIR if osp.isdir(BGE_LOCAL_DIR) else os.getenv(
            "BGE_MODEL_NAME", "BAAI/bge-small-zh-v1.5"
        )
        try:
            emb = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": os.getenv("BGE_DEVICE", "cpu")},
                encode_kwargs={"normalize_embeddings": True},
            )
            print(f"[Embedding] 本地 BGE 加载成功：{model_name}")
            # bge 官方推荐：对“查询”加指令前缀，可显著提升召回
            return emb, "为这个句子生成表示以用于检索相关文章：", True, "local"
        except Exception as e:
            print(f"[Embedding] 本地 BGE 加载失败({e})，自动回退 DashScope 云端 embedding。")

    # 2.2 云端 DashScope embedding（兜底，需联网）
    from langchain_openai import OpenAIEmbeddings
    emb = OpenAIEmbeddings(
        model="text-embedding-v3",
        base_url=os.getenv("DASHSCOPE_BASE_URL"),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        check_embedding_ctx_length=False,
    )
    print("[Embedding] 使用 DashScope 云端 text-embedding-v3。")
    return emb, "", False, "dashscope"


embeddings, QUERY_INSTRUCTION, IS_BGE, EMBEDDING_MODE = _build_embeddings()

# ===== 3. 本地知识库 =====
KKB_PATH = os.getenv("KKB_PATH", r"D:\Langchain\test\Lie")
INDEX_PATH = os.getenv("INDEX_PATH", r"D:\Langchain\test\faiss_index")
# 不同 embedding 的向量空间不通用，索引按实际生效的模式隔离，避免维度/语义错配
INDEX_PATH = f"{INDEX_PATH}_{EMBEDDING_MODE}"

if osp.exists(INDEX_PATH):
    vectorstore = FAISS.load_local(
        INDEX_PATH, embeddings, allow_dangerous_deserialization=True
    )
else:
    docs = DirectoryLoader(
        KKB_PATH, glob="**.md", loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    ).load()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600, chunk_overlap=100,
        separators=["\n\n", "\n", "。", "，", " "],
    )
    chunks = splitter.split_documents(docs)
    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(INDEX_PATH)

LOCAL_SCORE_THRESHOLD = 0.3  # bge 归一化后可用余弦相关度，阈值按实际效果微调

# ===== 4. 工具定义 =====
tavily = TavilySearch(max_results=3, topic="general", include_answer=True)


@tool
def web_search(query: str):
    """联网检索最新信息。即使本地知识库已命中，也必须调用此工具进行事实核查，提供权威依据。"""
    result = tavily.invoke(query)
    if isinstance(result, dict):
        ai_summary = result.get("answer", "无总结")
        # 格式化返回，明确区分标题和URL，便于大模型准确提取填入 reference
        urls = []
        if result.get("results"):
            for item in result.get("results"):
                title = item.get("title", "")
                url = item.get("url", "")
                if url:
                    urls.append(f"- 来源：{title} | 链接：{url}")

        urls_str = "\n".join(urls) if urls else "无有效来源网址"
        return f"【AI总结】{ai_summary}\n\n【真实来源网址】\n{urls_str}"
    return str(result)


@tool
def local_kb_search(query: str):
    """在本地辟谣知识库中检索证据。"""
    search_query = QUERY_INSTRUCTION + query if IS_BGE else query
    results = vectorstore.similarity_search_with_relevance_scores(search_query, k=4)
    hits = [(d, s) for d, s in results if s >= LOCAL_SCORE_THRESHOLD]
    if not hits:
        return "本地知识库未命中，请改用 web_search 联网检索。"
    context_str = ""
    for d, s in hits:
        content = d.page_content if isinstance(d.page_content, str) else str(d.page_content)
        context_str += f"[本地证据 相关度{s:.2f}] {content}\n\n"
    return context_str


# ===== 5. 结构化 Schema =====
class KeyEntities(PydanticBaseModel):
    subject: str = Field(description="传闻涉及的主体/对象，如某种食物、药品、人物、机构；无法确定填'未提及'")
    time: str = Field(description="传闻涉及的时间或时段；未提及填'未提及'")
    location: str = Field(description="传闻涉及的地点或范围；未提及填'未提及'")
    event: str = Field(description="用一句话概括传闻的核心论断/事件")


class Reference(PydanticBaseModel):
    source: str = Field(description="证据来源说明，例如'本地辟谣知识库'或联网检索到的网页标题")
    url: str = Field(description="网页的真实URL。本地证据留空，联网证据必须从 web_search 返回的真实来源网址中提取，严禁捏造。")


class AnswerInfo(PydanticBaseModel):
    key_entities: KeyEntities = Field(description="从用户传闻中自动抽取的关键信息")
    verdict: str = Field(description="判断结果：真实、虚假或存疑")
    confidence: float = Field(description="置信度：0.0到1.0")
    basis: list[str] = Field(description="推理依据，分条列出，每条写明证据内容及其来源(本地/联网)")
    conflict_analysis: str = Field(
        description="多源证据冲突分析：明确指出本地证据与联网证据(若有)之间是否存在冲突、"
                    "冲突点是什么、以及最终采信哪一方及理由；若来源一致或仅有单一来源，也要明确说明。"
    )
    conclusion: str = Field(description="最终结论的总结性陈述")
    reference: list[Reference] = Field(description="引用的来源列表")


# ===== 6. 创建 Agent =====
agent = create_agent(
    model=model,
    tools=[local_kb_search, web_search],
    system_prompt=(
        "你是一名专业的谣言分析智能体，必须严格按以下流程处理用户传闻：\n"
        "0. 【抽取】先从用户传闻中抽取关键信息(主体、时间、地点、核心事件)，填入 key_entities；\n"
        "1. 【第一步】必须调用 local_kb_search 在本地辟谣知识库检索证据；\n"
        "2. 【第二步】无论本地是否命中，都必须继续调用 web_search 进行联网事实核查，以获取互联网权威依据；\n"
        "3. 【第三步】对照本地证据与联网证据，进行多源冲突分析，在 conflict_analysis 中明确写出各来源是否一致、"
        "冲突点为何、最终采信哪一方及理由；\n"
        "4. 【第四步】交叉验证所有证据后，严格按照 AnswerInfo 格式输出最终结果：\n"
        "   - verdict 只能从【真实、虚假、存疑】中选一个；\n"
        "   - basis 中每条依据要写明证据内容及其来源标签(本地/联网)；\n"
        "   - reference 中必须包含【本地来源】和【联网来源】。本地来源 source 填'本地辟谣知识库'且 url 留空；"
        "联网来源必须严格从 web_search 返回的【真实来源网址】中提取 URL 和对应标题，严禁自行捏造URL。"
    ),
    response_format=ToolStrategy(AnswerInfo, handle_errors=True),
)

# ===== 7. FastAPI 接口 =====
app = FastAPI(title="谣言分析智能体 API", version="2.0.0")
import fastapi_cdn_host
fastapi_cdn_host.patch_docs(app)  # 离线/翻墙环境加载 docs 资源
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class QueryRequest(PydanticBaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class KeyEntitiesResp(PydanticBaseModel):
    subject: str
    time: str
    location: str
    event: str


class QueryResponse(PydanticBaseModel):
    key_entities: KeyEntitiesResp
    verdict: str
    confidence: float
    basis: List[str]
    conflict_analysis: str
    conclusion: str
    reference: List[dict]


@app.post("/api/analyze", response_model=QueryResponse)
async def analyze_rumor(req: QueryRequest):
    try:
        response = agent.invoke({"messages": [HumanMessage(content=req.question)]})
        raw_data = response.get("structured_response")
        if raw_data is None:
            for msg in reversed(response.get("messages", [])):
                if hasattr(msg, "structured_output") and msg.structured_output:
                    raw_data = msg.structured_output
                    break
        if raw_data is None:
            raise HTTPException(status_code=500, detail="Agent 未返回结构化结果")
        result = raw_data.model_dump() if isinstance(raw_data, PydanticBaseModel) else raw_data
        return QueryResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "service": "谣言分析智能体", "embedding_mode": EMBEDDING_MODE}


# ==================== 启动服务 ====================
if __name__ == "__main__":
    print("=" * 50)
    print("谣言分析助手后端服务已启动")
    print(f"Embedding 模式: {EMBEDDING_MODE}")
    print(f"本地模型目录: {BGE_LOCAL_DIR} (存在={osp.isdir(BGE_LOCAL_DIR)})")
    print("API 文档地址: http://localhost:8000/docs")
    print("健康检查地址: http://localhost:8000/health")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)