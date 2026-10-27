# -*- coding: utf-8 -*-
"""
工具定义 - 联网搜索、知识库检索、置信度计算
============================================
容错机制：
  - web_search：指数退避重试 + 最终兜底返回
  - local_kb_search：本地 FAISS 检索，异常时返回空结果
  - calculate_confidence：置信度量化算法
"""
import time
import logging
from langchain.tools import tool
from langchain_tavily import TavilySearch
from knowledge_base import search_with_scores
from config import (
    LOCAL_SCORE_THRESHOLD,
    WEB_SEARCH_MAX_RETRIES,
    WEB_SEARCH_RETRY_DELAY,
)

logger = logging.getLogger("tools")

tavily = TavilySearch(max_results=3, topic="general", include_answer=True)


def _retry_with_backoff(func, max_retries: int, base_delay: float, *args, **kwargs):
    """
    通用重试函数：指数退避重试

    :param func: 要执行的函数
    :param max_retries: 最大重试次数
    :param base_delay: 基础延迟（秒），第 n 次延迟 = base_delay * 2^(n-1)
    :return: (结果, 是否成功, 重试次数)
    """
    last_error = None
    for attempt in range(max_retries + 1):  # 第一次是初始调用，不算重试
        try:
            result = func(*args, **kwargs)
            return result, True, attempt
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)  # 指数退避：1s, 2s, 4s...
                logger.warning(
                    "[web_search] 第 %d 次调用失败: %s，%.1f 秒后重试（剩余 %d 次）",
                    attempt + 1, str(e)[:100], delay, max_retries - attempt,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "[web_search] 已重试 %d 次全部失败: %s",
                    max_retries, str(e)[:200],
                )
    return last_error, False, max_retries


@tool
def web_search(query: str):
    """
    联网检索最新信息。即使本地知识库已命中，也必须调用此工具进行事实核查，提供权威依据。

    支持自动重试（指数退避），全部失败后返回兜底提示，不抛出异常阻断 Agent 流程。
    """
    def _do_search():
        return tavily.invoke(query)

    result, success, retries = _retry_with_backoff(
        _do_search,
        max_retries=WEB_SEARCH_MAX_RETRIES,
        base_delay=WEB_SEARCH_RETRY_DELAY,
    )

    if not success:
        # 兜底：返回结构化的失败提示，让 Agent 知道联网搜索失败了
        error_msg = str(result) if result else "未知错误"
        logger.warning("[web_search] 联网搜索失败，返回兜底结果: %s", error_msg[:100])
        return (
            "【联网搜索失败】由于网络或服务问题，本次联网搜索未能成功获取结果。\n"
            "请基于本地知识库的证据进行分析，并在结论中说明「联网核查暂不可用，判断仅基于本地知识库」。\n"
            f"失败原因：{error_msg[:200]}"
        )

    # 成功：正常格式化结果
    if isinstance(result, dict):
        ai_summary = result.get("answer", "无总结")
        urls = []
        if result.get("results"):
            for item in result.get("results"):
                title = item.get("title", "")
                url = item.get("url", "")
                if url:
                    urls.append(f"- 来源：{title} | 链接：{url}")

        urls_str = "\n".join(urls) if urls else "无有效来源网址"
        retry_info = f"（重试 {retries} 次后成功）" if retries > 0 else ""
        return f"【AI总结】{ai_summary}{retry_info}\n\n【真实来源网址】\n{urls_str}"

    return str(result)


def calculate_confidence(local_hits: list, web_refs: list, verdict: str) -> float:
    """
    基于客观信号计算置信度 (0.0 ~ 1.0)

    :param local_hits: [(document, score), ...] 本地命中列表
    :param web_refs: list[Reference] 联网引用来源列表
    :param verdict: 判断结果（真实/虚假/存疑）
    """
    local_score = 0.0
    if local_hits:
        local_score = max([s for _, s in local_hits])

    base_score = local_score * 0.5

    web_score = 0.0
    web_count = len(web_refs) if web_refs else 0
    if web_count > 0:
        # 联网来源中，排除本地来源后计算
        remote_count = sum(1 for ref in web_refs if getattr(ref, 'url', '') or (isinstance(ref, dict) and ref.get('url', '')))
        web_score = 0.3 * min(1.0, remote_count / 3)

    penalty = 0.0
    if "存疑" in verdict:
        penalty = 0.2
    elif local_hits and web_count == 0:
        penalty = 0.1

    final_confidence = min(1.0, max(0.1, base_score + web_score - penalty))
    return round(final_confidence, 2)


@tool
def local_kb_search(query: str):
    """在本地辟谣知识库中检索证据。"""
    try:
        results = search_with_scores(query, top_k=4)
        hits = [(d, s) for d, s in results if s >= LOCAL_SCORE_THRESHOLD]
        if not hits:
            return "本地知识库未命中，请改用 web_search 联网检索。"
        context_str = ""
        for d, s in hits:
            content = d.page_content if isinstance(d.page_content, str) else str(d.page_content)
            context_str += f"[本地证据 相关度{s:.2f}] {content}\n\n"
        return context_str
    except Exception as e:
        logger.error("[local_kb_search] 本地知识库检索失败: %s", e)
        return f"本地知识库检索异常（{str(e)[:100]}），请改用 web_search 联网检索。"
