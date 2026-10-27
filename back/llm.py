# -*- coding: utf-8 -*-
"""
大模型与 Embedding 初始化
=========================
容错机制：
  - ChatOpenAI 配置超时 + 重试次数
  - Embedding 本地 BGE 加载失败 → 自动回退 DashScope 云端
"""
import os
import logging
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from config import (
    LLM_MODEL, LLM_BASE_URL, LLM_API_KEY,
    BGE_LOCAL_DIR, EMBEDDING_MODE,
    LLM_TIMEOUT, LLM_MAX_RETRIES,
)
import os.path as osp

logger = logging.getLogger("llm")

# ===== 大模型 =====
model = ChatOpenAI(
    model=LLM_MODEL,
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
    timeout=LLM_TIMEOUT,         # 单次请求超时时间（秒）
    max_retries=LLM_MAX_RETRIES, # 自动重试次数（指数退避）
    temperature=0.1,             # 降低随机性，事实核查需要稳定输出
)
logger.info(
    "大模型已初始化 | 模型=%s | 超时=%ds | 重试=%d次",
    LLM_MODEL, LLM_TIMEOUT, LLM_MAX_RETRIES,
)

# ===== Embedding =====
def _build_embeddings():
    """返回 (embeddings, QUERY_INSTRUCTION, IS_BGE, 实际生效的模式)。"""
    if EMBEDDING_MODE == "local":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            model_name = BGE_LOCAL_DIR if osp.isdir(BGE_LOCAL_DIR) else os.getenv(
                "BGE_MODEL_NAME", "BAAI/bge-small-zh-v1.5"
            )
            emb = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": os.getenv("BGE_DEVICE", "cpu")},
                encode_kwargs={"normalize_embeddings": True},
            )
            logger.info("本地 BGE Embedding 加载成功：%s", model_name)
            return emb, "为这个句子生成表示以用于检索相关文章：", True, "local"
        except Exception as e:
            logger.warning("本地 BGE 加载失败(%s)，自动回退 DashScope 云端 embedding。", str(e)[:100])

    emb = OpenAIEmbeddings(
        model="text-embedding-v3",
        base_url=os.getenv("DASHSCOPE_BASE_URL"),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        check_embedding_ctx_length=False,
    )
    logger.info("使用 DashScope 云端 text-embedding-v3")
    return emb, "", False, "dashscope"


embeddings, QUERY_INSTRUCTION, IS_BGE, _EMBEDDING_MODE_EFFECTIVE = _build_embeddings()
