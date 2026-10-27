# -*- coding: utf-8 -*-
"""全局配置 - 环境变量与路径"""
import os

# ===== 大模型配置 =====
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.5")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")

# ===== Embedding 配置 =====
BGE_LOCAL_DIR = os.getenv("BGE_LOCAL_DIR", r"D:\Langchain\test\models\bge-small-zh-v1.5")
EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "local").lower()

# ===== 知识库配置 =====
KKB_PATH = os.getenv("KKB_PATH", os.path.join(os.path.dirname(__file__), "knowledge_base"))
INDEX_PATH_BASE = os.getenv("INDEX_PATH", r"D:\Langchain\test\faiss_index")
INDEX_PATH = f"{INDEX_PATH_BASE}_{EMBEDDING_MODE}"

# ===== 记忆配置 =====
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", "memory.db")
MEMORY_USE_FAISS = os.getenv("MEMORY_USE_FAISS", "0").strip().lower() in ("1", "true", "yes")
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "memory_faiss_index")
SEMANTIC_SEARCH_TOP_K = int(os.getenv("SEMANTIC_SEARCH_TOP_K", "3"))
SEMANTIC_SCORE_THRESHOLD = float(os.getenv("SEMANTIC_SCORE_THRESHOLD", "0.3"))
MESSAGE_RETENTION_DAYS = int(os.getenv("MESSAGE_RETENTION_DAYS", "30"))

# ===== 日志配置 =====
# 全局日志级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# 日志目录
LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(__file__), "logs"))
# 主日志文件名
LOG_FILE = os.getenv("LOG_FILE", "app.log")

# --- 轮转策略 ---
# 轮转方式：size（按大小） / time（按时间） / both（大小+时间双重触发）
LOG_ROTATE_MODE = os.getenv("LOG_ROTATE_MODE", "size").lower()
# 按大小轮转：单文件最大大小（MB）
LOG_MAX_FILE_SIZE_MB = int(os.getenv("LOG_MAX_FILE_SIZE_MB", "50"))
# 按大小轮转：备份文件个数
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "30"))
# 按时间轮转：时间单位 - S(秒) / M(分) / H(时) / D(天) / midnight(午夜) / W0-W6(周几)
LOG_ROTATE_WHEN = os.getenv("LOG_ROTATE_WHEN", "midnight")
# 按时间轮转：时间间隔数量
LOG_ROTATE_INTERVAL = int(os.getenv("LOG_ROTATE_INTERVAL", "1"))

# --- 保留与清理 ---
# 日志保留天数（0 表示不限制）
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
# 自动清理检查间隔（小时），0 表示仅启动时清理一次
LOG_CLEANUP_INTERVAL_HOURS = int(os.getenv("LOG_CLEANUP_INTERVAL_HOURS", "24"))
# 轮转后的旧日志是否压缩（gz）
LOG_COMPRESS_OLD = os.getenv("LOG_COMPRESS_OLD", "1").strip().lower() in ("1", "true", "yes")

# --- 日志格式 ---
# 输出格式：text（纯文本） / json（结构化 JSON）
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
# 控制台输出格式（独立于文件格式）
LOG_CONSOLE_FORMAT = os.getenv("LOG_CONSOLE_FORMAT", "text").lower()

# --- 分级分类 ---
# 是否将错误日志单独存文件（ERROR 及以上）
LOG_ERROR_SEPARATE = os.getenv("LOG_ERROR_SEPARATE", "1").strip().lower() in ("1", "true", "yes")
# 是否启用独立的访问日志文件（API 请求日志）
LOG_ACCESS_ENABLED = os.getenv("LOG_ACCESS_ENABLED", "1").strip().lower() in ("1", "true", "yes")
# 访问日志文件名
LOG_ACCESS_FILE = os.getenv("LOG_ACCESS_FILE", "access.log")

# --- 模块级别 ---
# 各模块独立日志级别配置，格式："module1=DEBUG,module2=WARNING"
LOG_MODULE_LEVELS = os.getenv("LOG_MODULE_LEVELS", "")

# --- 第三方库 ---
# 是否将第三方库日志静音（建议生产环境开启）
LOG_MUTE_THIRD_PARTY = os.getenv("LOG_MUTE_THIRD_PARTY", "1").strip().lower() in ("1", "true", "yes")

# --- Trace ID ---
# HTTP 请求头中 Trace ID 的字段名
LOG_TRACE_ID_HEADER = os.getenv("LOG_TRACE_ID_HEADER", "X-Trace-Id")

# ===== 工具配置 =====
LOCAL_SCORE_THRESHOLD = float(os.getenv("LOCAL_SCORE_THRESHOLD", "0.5"))

# ===== 重试与容错配置 =====
# LLM 调用超时时间（秒）
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
# LLM 最大重试次数
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))

# 联网搜索工具最大重试次数
WEB_SEARCH_MAX_RETRIES = int(os.getenv("WEB_SEARCH_MAX_RETRIES", "3"))
# 联网搜索每次重试间隔（秒，指数退避的基础值）
WEB_SEARCH_RETRY_DELAY = float(os.getenv("WEB_SEARCH_RETRY_DELAY", "1.0"))
# 联网搜索超时时间（秒）
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "15"))

# Agent 调用最大重试次数（整体失败时）
AGENT_MAX_RETRIES = int(os.getenv("AGENT_MAX_RETRIES", "2"))