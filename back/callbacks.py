import time
import logging
from langchain_core.callbacks.base import BaseCallbackHandler

logger = logging.getLogger("agent_monitor")


class AgentMonitor(BaseCallbackHandler):
    """全链路监控：记录耗时、Token、工具调用"""

    def __init__(self):
        self.llm_start_time = None
        self.total_tokens = 0
        self.llm_call_count = 0          # 新增：统计 LLM 调用次数
        self.tool_calls = []

    def on_llm_start(self, serialized, prompts, **kwargs):
        self.llm_start_time = time.time()
        self.llm_call_count += 1         # 新增：计数
        logger.info(
            "[LLM] 开始调用 | 第%d次 | prompt长度: %d",
            self.llm_call_count,
            len(prompts[0]) if prompts else 0,
        )

    def on_llm_end(self, response, **kwargs):
        duration = time.time() - (self.llm_start_time or time.time())
        # 安全取值，兼容不同模型提供商的返回结构
        token_usage = {}
        if response:
            llm_output = getattr(response, "llm_output", None) or {}
            usage = getattr(response, "usage_metadata", None)
            if llm_output and isinstance(llm_output, dict):
                token_usage = llm_output.get("token_usage", {}) or {}
            # 兜底：OpenAI 新版 SDK 有时把用量放在 usage_metadata 上
            if not token_usage and usage:
                token_usage = {
                    "prompt_tokens": getattr(usage, "input_tokens", 0),
                    "completion_tokens": getattr(usage, "output_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                }
        tokens = token_usage.get("total_tokens", 0)
        self.total_tokens += tokens
        logger.info(
            "[LLM] 完成 | 耗时: %.2fs | Token: %d | 累计: %d",
            duration,
            tokens,
            self.total_tokens,
        )

    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get("name", "unknown") if isinstance(serialized, dict) else str(serialized)
        self.tool_calls.append({"tool": tool_name, "input": str(input_str)[:200], "status": "start"})
        logger.info("[Tool] 调用: %s | 入参: %s", tool_name, str(input_str)[:100])

    def on_tool_end(self, output, **kwargs):
        logger.info("[Tool] 返回: %s", str(output)[:200])

    def on_tool_error(self, error, **kwargs):
        logger.error("[Tool] 异常: %s", error)