# -*- coding: utf-8 -*-
"""本地知识库 - FAISS 向量库加载/构建"""
import os
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from llm import embeddings, QUERY_INSTRUCTION, IS_BGE
from config import KKB_PATH, INDEX_PATH


def _normalize_cosine_score(raw_score: float) -> float:
    """
    将 FAISS inner product 分数（即 cosine similarity，范围 [-1, 1]）
    归一化到 [0, 1] 区间，数值越高越相关。
    BGE 模型使用 normalize_embeddings=True，因此 inner_product = cosine_similarity
    """
    # cosine similarity 范围约 [-1, 1]，线性映射到 [0, 1]
    return max(0.0, min(1.0, (raw_score + 1.0) / 2.0))


def search_with_scores(query: str, top_k: int = 4):
    """
    带归一化分数的检索。
    返回 [(document, normalized_score), ...]，按相关度降序排列，score 范围 [0, 1]
    """
    search_query = QUERY_INSTRUCTION + query if IS_BGE else query
    # 使用 similarity_search_with_score 获取原始 inner product 分数
    results = vectorstore.similarity_search_with_score(search_query, k=top_k)
    # 归一化分数到 [0, 1]
    normalized = [(doc, _normalize_cosine_score(float(score))) for doc, score in results]
    # 按分数降序排列（FAISS 默认已是降序，但确保一下）
    normalized.sort(key=lambda x: x[1], reverse=True)
    return normalized


# 初始化或加载向量库
if os.path.exists(INDEX_PATH):
    vectorstore = FAISS.load_local(
        INDEX_PATH, embeddings, allow_dangerous_deserialization=True
    )
    print(f"[KnowledgeBase] 加载已有向量库，路径: {INDEX_PATH}")
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
    print(f"[KnowledgeBase] 向量库已构建并保存，路径: {INDEX_PATH}")


# ===== 提供给检索评估脚本使用的检索函数 =====
def search_knowledge_base(query: str, top_k: int = 3):
    """
    在本地知识库中检索相关文档
    :param query: 用户的查询问题
    :param top_k: 返回相关文档的数量
    :return: 检索到的文档对象列表
    """
    results = search_with_scores(query, top_k=top_k)
    return [doc for doc, _ in results]