# -*- coding: utf-8 -*-
"""谣言分析智能体 - 模块化入口
================================
项目结构：
  config.py        - 全局配置（环境变量）
  logger_setup.py  - 日志系统初始化
  llm.py           - 大模型 + Embedding 初始化
  knowledge_base.py - 本地知识库 FAISS 加载
  memory.py        - 长时记忆模块（SQLite + FAISS）
  tools.py         - 工具定义（web_search / local_kb_search / confidence）
  schemas.py       - Pydantic 数据模型
  session.py       - 会话管理辅助函数
  agent.py         - Agent 创建
  api.py           - FastAPI 路由定义
  callbacks.py     - 监控回调（AgentMonitor）
  lie_server.py    - 本文件：入口与启动
"""
from dotenv import load_dotenv
import uvicorn
import os

# ===== 日志初始化（必须在所有模块导入之前） =====
load_dotenv()
from logger_setup import setup_logging
setup_logging()

import logging
logger = logging.getLogger("lie_server")

# 按依赖顺序导入各模块（确保全局对象被正确初始化）
import config          # 配置
import llm             # 大模型 + embedding
import knowledge_base   # 知识库向量库
import tools           # 工具定义
import schemas         # 数据模型
import session         # 会话管理
import agent           # Agent 创建
from api import app    # FastAPI 应用
import callbacks  # 确保 AgentMonitor 被加载

# ===== 启动服务 =====
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("谣言分析助手后端服务已启动 (v3.1 - 模块化)")
    logger.info("Embedding 模式: %s", llm._EMBEDDING_MODE_EFFECTIVE)
    logger.info("本地模型目录: %s (存在=%s)", config.BGE_LOCAL_DIR, os.path.isdir(config.BGE_LOCAL_DIR))
    logger.info("记忆数据库: %s", config.MEMORY_DB_PATH)
    logger.info("FAISS语义检索: %s", "已启用" if config.MEMORY_USE_FAISS else "已禁用")
    logger.info("日志级别: %s | 目录: %s", config.LOG_LEVEL, config.LOG_DIR)
    logger.info("API 文档地址: http://localhost:8000/docs")
    logger.info("健康检查地址: http://localhost:8000/health")
    logger.info("记忆统计: http://localhost:8000/api/memory/stats")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)