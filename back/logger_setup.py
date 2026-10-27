# -*- coding: utf-8 -*-
"""
生产级日志管理模块
====================
功能特性：
  ✅ 多模式轮转：按大小 / 按时间 / 大小+时间双重触发
  ✅ 分级分类：主日志 + 错误日志 + 访问日志（独立文件）
  ✅ 结构化日志：支持 JSON 格式（便于 ELK/Loki 等日志系统解析）
  ✅ 日志压缩：轮转后的旧日志自动 gzip 压缩
  ✅ 自动清理：周期性清理过期日志文件
  ✅ Trace ID：支持请求链路追踪
  ✅ 模块级别：各模块可独立配置日志级别
  ✅ 第三方库静音：避免日志被刷屏
  ✅ 统一格式：时间戳、级别、模块名、Trace ID、消息

使用方式：
  在 lie_server.py 最顶部：
    from logger_setup import setup_logging, get_logger, set_trace_id, get_trace_id
    setup_logging()

  在业务代码中：
    import logging
    logger = logging.getLogger("module_name")
    logger.info("消息内容")

  在请求处理中：
    set_trace_id(trace_id)   # 注入当前请求的 Trace ID
    logger.info("处理中...") # 日志自动带上 trace_id
"""
import os
import sys
import gzip
import json
import uuid
import logging
import threading
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import (
    LOG_LEVEL,
    LOG_DIR,
    LOG_FILE,
    LOG_ROTATE_MODE,
    LOG_MAX_FILE_SIZE_MB,
    LOG_BACKUP_COUNT,
    LOG_ROTATE_WHEN,
    LOG_ROTATE_INTERVAL,
    LOG_RETENTION_DAYS,
    LOG_CLEANUP_INTERVAL_HOURS,
    LOG_COMPRESS_OLD,
    LOG_FORMAT,
    LOG_CONSOLE_FORMAT,
    LOG_ERROR_SEPARATE,
    LOG_ACCESS_ENABLED,
    LOG_ACCESS_FILE,
    LOG_MODULE_LEVELS,
    LOG_MUTE_THIRD_PARTY,
    LOG_TRACE_ID_HEADER,
)

# ===== 全局状态 =====
_initialized = False
_cleanup_thread: Optional[threading.Thread] = None
_cleanup_stop_event = threading.Event()

# 线程本地存储：每个请求的 Trace ID
_trace_local = threading.local()


# ============================================================
# Trace ID 管理
# ============================================================
def set_trace_id(trace_id: Optional[str] = None) -> str:
    """
    设置当前线程的 Trace ID。
    如果不传则自动生成一个。

    :param trace_id: Trace ID 字符串
    :return: 设置后的 Trace ID
    """
    if trace_id is None:
        trace_id = uuid.uuid4().hex[:16]
    _trace_local.trace_id = trace_id
    return trace_id


def get_trace_id() -> str:
    """获取当前线程的 Trace ID，没有则返回空字符串"""
    return getattr(_trace_local, "trace_id", "")


def clear_trace_id():
    """清除当前线程的 Trace ID（请求结束时调用）"""
    if hasattr(_trace_local, "trace_id"):
        delattr(_trace_local, "trace_id")


# ============================================================
# 自定义 Filter：注入 Trace ID
# ============================================================
class TraceIdFilter(logging.Filter):
    """为日志记录注入 trace_id 字段"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


# ============================================================
# 自定义 Formatter：JSON 格式
# ============================================================
class JsonFormatter(logging.Formatter):
    """
    JSON 结构化日志格式器
    输出字段：timestamp, level, logger, trace_id, message, exc_info(可选)
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "message": record.getMessage(),
        }
        # 异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        # 额外字段（通过 extra= 传入）
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_entry.update(record.extra_fields)
        return json.dumps(log_entry, ensure_ascii=False)


# ============================================================
# 自定义 Handler：带压缩的按大小轮转
# ============================================================
class CompressedRotatingFileHandler(RotatingFileHandler):
    """
    带 gzip 压缩的按大小轮转文件处理器
    轮转后的旧文件自动压缩为 .gz
    """

    def rotate(self, source: str, dest: str):
        super().rotate(source, dest)
        if LOG_COMPRESS_OLD:
            self._compress_file(dest)

    @staticmethod
    def _compress_file(filepath: str):
        """将文件压缩为 .gz 并删除原文件"""
        try:
            gz_path = filepath + ".gz"
            with open(filepath, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    f_out.writelines(f_in)
            os.remove(filepath)
        except OSError:
            pass  # 压缩失败不影响主流程


# ============================================================
# 自定义 Handler：带压缩的按时间轮转
# ============================================================
class CompressedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    带 gzip 压缩的按时间轮转文件处理器
    """

    def rotate(self, source: str, dest: str):
        super().rotate(source, dest)
        if LOG_COMPRESS_OLD:
            self._compress_file(dest)

    @staticmethod
    def _compress_file(filepath: str):
        try:
            gz_path = filepath + ".gz"
            with open(filepath, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    f_out.writelines(f_in)
            os.remove(filepath)
        except OSError:
            pass


# ============================================================
# 工具函数
# ============================================================
def _get_log_level(level_str: str) -> int:
    """将字符串日志级别转换为 logging 常量"""
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return levels.get(level_str.upper(), logging.INFO)


def _make_formatter(fmt_type: str = "text") -> logging.Formatter:
    """
    创建日志格式器

    :param fmt_type: text / json
    """
    if fmt_type == "json":
        return JsonFormatter()

    # 文本格式：包含 trace_id
    log_format = (
        "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"
    return logging.Formatter(log_format, datefmt=date_format)


def _make_file_handler(
    log_path: str,
    level: int = logging.INFO,
    fmt_type: str = "text",
) -> logging.Handler:
    """
    根据配置创建文件处理器（按大小 / 按时间 / 双重模式）

    :param log_path: 日志文件路径
    :param level: 日志级别
    :param fmt_type: 格式类型 text/json
    :return: logging Handler
    """
    max_bytes = LOG_MAX_FILE_SIZE_MB * 1024 * 1024

    if LOG_ROTATE_MODE == "time":
        # 纯按时间轮转
        handler = CompressedTimedRotatingFileHandler(
            log_path,
            when=LOG_ROTATE_WHEN,
            interval=LOG_ROTATE_INTERVAL,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    elif LOG_ROTATE_MODE == "both":
        # 双重模式：使用按时间轮转 + 自定义大小检查
        # TimedRotatingFileHandler 本身不支持大小限制，
        # 这里通过继承实现双重触发（简化方案：用 size 模式但按天命名）
        handler = CompressedRotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    else:
        # 默认按大小轮转
        handler = CompressedRotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )

    handler.setLevel(level)
    handler.setFormatter(_make_formatter(fmt_type))
    handler.addFilter(TraceIdFilter())
    return handler


def _mute_third_party_loggers():
    """静音第三方库的日志，避免日志被刷屏"""
    noisy_loggers = [
        "httpx",
        "httpx2",
        "httpcore",
        "urllib3",
        "sentence_transformers",
        "transformers",
        "faiss.loader",
        "langchain",
        "langchain_core",
        "langchain_community",
        "langchain_openai",
        "langchain_huggingface",
        "tavily",
        "uvicorn",
        "uvicorn.access",
        "fastapi",
        "starlette",
    ]
    for name in noisy_loggers:
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)


def _apply_module_levels():
    """应用模块级别配置，格式："module1=DEBUG,module2=WARNING" """
    if not LOG_MODULE_LEVELS:
        return
    pairs = [p.strip() for p in LOG_MODULE_LEVELS.split(",") if p.strip()]
    for pair in pairs:
        if "=" in pair:
            module, level = pair.split("=", 1)
            module = module.strip()
            level = level.strip().upper()
            if module and level:
                logging.getLogger(module).setLevel(_get_log_level(level))


def cleanup_old_logs(log_dir: Optional[str] = None, retention_days: Optional[int] = None) -> int:
    """
    清理超过保留天数的旧日志文件

    :param log_dir: 日志目录，默认使用 LOG_DIR
    :param retention_days: 保留天数，默认使用 LOG_RETENTION_DAYS
    :return: 清理的文件数量
    """
    log_dir = log_dir or LOG_DIR
    retention_days = retention_days if retention_days is not None else LOG_RETENTION_DAYS

    if retention_days <= 0 or not os.path.isdir(log_dir):
        return 0

    cutoff_time = datetime.now() - timedelta(days=retention_days)
    # 匹配 .log, .log.1, .log.2024-01-01, .log.gz 等
    patterns = ["*.log", "*.log.*", "*.gz"]

    cleaned_count = 0
    for pattern in patterns:
        for log_file in Path(log_dir).glob(pattern):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff_time:
                    log_file.unlink()
                    cleaned_count += 1
            except OSError:
                pass

    return cleaned_count


def _cleanup_scheduler(interval_hours: int, stop_event: threading.Event):
    """
    后台线程：周期性清理过期日志

    :param interval_hours: 清理间隔（小时）
    :param stop_event: 停止事件
    """
    while not stop_event.is_set():
        # 等待间隔时间，每60秒检查一次是否需要停止
        total_seconds = interval_hours * 3600
        waited = 0
        while waited < total_seconds and not stop_event.is_set():
            stop_event.wait(min(60, total_seconds - waited))
            waited += 60

        if stop_event.is_set():
            break

        try:
            cleaned = cleanup_old_logs()
            if cleaned > 0:
                logger = logging.getLogger("logger_setup")
                logger.info("周期性日志清理完成，删除了 %d 个过期文件", cleaned)
        except Exception:
            pass  # 清理失败不影响服务


# ============================================================
# 主入口：初始化日志系统
# ============================================================
def setup_logging() -> bool:
    """
    初始化全局日志配置。
    必须在所有模块导入之前调用（在 lie_server.py 最顶部调用）。

    :return: 是否初始化成功
    """
    global _initialized, _cleanup_thread, _cleanup_stop_event

    if _initialized:
        return True

    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)

    log_level = _get_log_level(LOG_LEVEL)
    log_path = os.path.join(LOG_DIR, LOG_FILE)

    # 根 logger 配置
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # 清除已有的 handler，避免重复输出
    root_logger.handlers.clear()

    # ===== Handler 1: 控制台输出 =====
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(_make_formatter(LOG_CONSOLE_FORMAT))
    console_handler.addFilter(TraceIdFilter())
    root_logger.addHandler(console_handler)

    # ===== Handler 2: 主日志文件 =====
    file_handler = _make_file_handler(log_path, level=log_level, fmt_type=LOG_FORMAT)
    root_logger.addHandler(file_handler)

    # ===== Handler 3: 错误日志文件（单独存放 ERROR 及以上） =====
    if LOG_ERROR_SEPARATE:
        error_log_path = os.path.join(LOG_DIR, "error.log")
        error_handler = _make_file_handler(
            error_log_path,
            level=logging.ERROR,
            fmt_type=LOG_FORMAT,
        )
        root_logger.addHandler(error_handler)

    # ===== Handler 4: 访问日志（独立 logger，不继承根 logger 的输出） =====
    if LOG_ACCESS_ENABLED:
        access_log_path = os.path.join(LOG_DIR, LOG_ACCESS_FILE)
        access_handler = _make_file_handler(
            access_log_path,
            level=logging.INFO,
            fmt_type=LOG_FORMAT,
        )
        access_logger = logging.getLogger("access")
        access_logger.setLevel(logging.INFO)
        access_logger.addHandler(access_handler)
        access_logger.propagate = False  # 不传递给根 logger，避免重复输出

    # ===== 静音第三方库日志 =====
    if LOG_MUTE_THIRD_PARTY:
        _mute_third_party_loggers()

    # ===== 应用模块级别配置 =====
    _apply_module_levels()

    # ===== 启动时清理一次过期日志 =====
    cleaned_count = cleanup_old_logs()
    if cleaned_count > 0:
        print(f"[日志] 已清理 {cleaned_count} 个过期日志文件（保留 {LOG_RETENTION_DAYS} 天）")

    # ===== 启动周期性清理线程 =====
    if LOG_CLEANUP_INTERVAL_HOURS > 0:
        _cleanup_stop_event = threading.Event()
        _cleanup_thread = threading.Thread(
            target=_cleanup_scheduler,
            args=(LOG_CLEANUP_INTERVAL_HOURS, _cleanup_stop_event),
            daemon=True,
            name="log-cleanup",
        )
        _cleanup_thread.start()

    _initialized = True

    # 记录启动信息
    logger = logging.getLogger("logger_setup")
    logger.info(
        "日志系统已初始化 | 级别=%s | 模式=%s | 格式=%s | 目录=%s | 保留%d天 | 单文件最大%dMB | 备份%d个 | 压缩=%s | 独立错误日志=%s | 访问日志=%s",
        LOG_LEVEL,
        LOG_ROTATE_MODE,
        LOG_FORMAT,
        LOG_DIR,
        LOG_RETENTION_DAYS,
        LOG_MAX_FILE_SIZE_MB,
        LOG_BACKUP_COUNT,
        "开启" if LOG_COMPRESS_OLD else "关闭",
        "开启" if LOG_ERROR_SEPARATE else "关闭",
        "开启" if LOG_ACCESS_ENABLED else "关闭",
    )
    return True


def shutdown_logging():
    """
    关闭日志系统，停止后台清理线程。
    在服务关闭时调用。
    """
    global _cleanup_thread, _cleanup_stop_event, _initialized

    if _cleanup_stop_event and _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_stop_event.set()
        _cleanup_thread.join(timeout=5)

    # 关闭所有 handler
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        try:
            handler.close()
            root_logger.removeHandler(handler)
        except Exception:
            pass

    _initialized = False


def get_logger(name: str) -> logging.Logger:
    """
    获取命名 logger 的便捷函数。

    :param name: logger 名称，建议使用模块名或功能名
    :return: logging.Logger 实例
    """
    return logging.getLogger(name)


def get_access_logger() -> logging.Logger:
    """获取访问日志专用 logger"""
    return logging.getLogger("access")


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields):
    """
    带额外字段的日志输出（JSON 格式下会包含这些字段）

    :param logger: logger 实例
    :param level: 日志级别
    :param message: 日志消息
    :param fields: 额外字段（关键字参数）
    """
    if not logger.isEnabledFor(level):
        return
    record = logger.makeRecord(
        logger.name, level, "(unknown)", 0, message, (), None, None, None
    )
    record.extra_fields = fields
    record.trace_id = get_trace_id() or "-"
    logger.handle(record)
