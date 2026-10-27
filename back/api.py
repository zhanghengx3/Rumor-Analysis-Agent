# -*- coding: utf-8 -*-
"""FastAPI 路由定义"""
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import List
import fastapi_cdn_host
import logging
import time

from schemas import (
    QueryRequest, QueryResponse, KeyEntitiesResp,
    KeyEntities, Reference, AnswerInfo,
    ChatRequest, ChatResponse, IntentInfo, MonitorInfo,
)
from agent import (
    agent, _base_system_prompt,
    recognize_intent, chat_with_agent, analyze_rumor_with_agent,
)
from session import _get_session_id, _build_memory_context
from memory import get_memory
from tools import calculate_confidence
from knowledge_base import search_with_scores
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel
from config import (
    MEMORY_DB_PATH, MEMORY_USE_FAISS,
    LOG_TRACE_ID_HEADER, LOG_ACCESS_ENABLED,
    AGENT_MAX_RETRIES,
)
from callbacks import AgentMonitor
from logger_setup import set_trace_id, clear_trace_id, get_access_logger, get_trace_id

# ===== 日志配置 =====
logger = logging.getLogger("api")

# ===== 创建 App =====
app = FastAPI(title="谣言分析智能体 API (带长时记忆)", version="3.0.0")
fastapi_cdn_host.patch_docs(app)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ===== Trace ID & 访问日志中间件 =====
class TraceIdAccessMiddleware(BaseHTTPMiddleware):
    """
    请求中间件：
      1. 从请求头提取 Trace ID（没有则生成）
      2. 注入到线程本地存储，所有日志自动带上
      3. 记录访问日志（请求路径、方法、耗时、状态码、客户端IP）
    """

    # 跳过访问日志的路径（健康检查、静态资源等）
    SKIP_PATHS = {"/health", "/favicon.ico", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        # 1. 获取或生成 Trace ID
        trace_id = request.headers.get(LOG_TRACE_ID_HEADER)
        trace_id = set_trace_id(trace_id)

        # 2. 记录请求开始
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        # 跳过某些路径的访问日志
        skip_access = path in self.SKIP_PATHS or path.startswith("/docs") or path.startswith("/openapi")

        try:
            # 3. 处理请求
            response: Response = await call_next(request)

            # 4. 设置响应头中的 Trace ID
            response.headers[LOG_TRACE_ID_HEADER] = trace_id

            # 5. 计算耗时并记录访问日志
            duration_ms = (time.time() - start_time) * 1000
            status_code = response.status_code

            if LOG_ACCESS_ENABLED and not skip_access:
                access_logger = get_access_logger()
                access_logger.info(
                    '%s %s %s %d %.2fms ip=%s',
                    method, path, trace_id, status_code, duration_ms, client_ip,
                )

            return response

        except Exception as e:
            # 异常情况下也记录
            duration_ms = (time.time() - start_time) * 1000
            if LOG_ACCESS_ENABLED and not skip_access:
                access_logger = get_access_logger()
                access_logger.error(
                    '%s %s %s 500 %.2fms ip=%s error=%s',
                    method, path, trace_id, duration_ms, client_ip, str(e),
                )
            raise
        finally:
            # 6. 清理线程本地存储（防止线程复用导致 Trace ID 泄漏）
            clear_trace_id()


app.add_middleware(TraceIdAccessMiddleware)

# ===== 记忆管理器（全局单例） =====
memory = get_memory(db_path=MEMORY_DB_PATH, enable_vector=MEMORY_USE_FAISS)
logger.info("长时记忆已启用: SQLite=%s, FAISS语义检索=%s", MEMORY_DB_PATH, MEMORY_USE_FAISS)


# ===== 主分析接口 =====
def _build_agent_messages(session_id: str, question: str):
    """构建 Agent 的消息列表（含记忆上下文）"""
    memory_context = _build_memory_context(session_id)
    has_memory = len(memory_context.strip()) > 0

    messages = []
    if has_memory:
        # 将历史对话转为 LangChain 消息对象
        for msg in memory.get_history(session_id, limit=10):
            if msg.is_user:
                messages.append(HumanMessage(content=msg.content))
            elif msg.is_assistant:
                messages.append(AIMessage(content=msg.content))

        # 注入记忆上下文作为系统参考
        context_message = HumanMessage(
            content=f"[系统提示：以下是你之前在此会话中讨论过的内容，供参考但不必须重复回答]\n{memory_context}"
        )
        messages.insert(0, context_message)

    messages.append(HumanMessage(content=question))
    return messages, has_memory


def _invoke_agent_with_retry(messages: list, max_retries: int = 2):
    """
    调用 Agent，失败时自动重试。

    :param messages: 消息列表
    :param max_retries: 最大重试次数
    :return: (response, monitor, success, retry_count)
    """
    last_error = None
    for attempt in range(max_retries + 1):
        monitor = AgentMonitor()
        try:
            response = agent.invoke(
                {"messages": messages},
                config={"callbacks": [monitor]},
            )
            return response, monitor, True, attempt
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(
                    "[Agent] 第 %d 次调用失败: %s，准备重试（剩余 %d 次）",
                    attempt + 1, str(e)[:100], max_retries - attempt,
                )
            else:
                logger.error(
                    "[Agent] 已重试 %d 次全部失败: %s",
                    max_retries, str(e)[:200],
                )
    return last_error, None, False, max_retries


@app.post("/api/analyze", response_model=QueryResponse)
async def analyze_rumor(req: QueryRequest, request: Request):
    # ---- 会话管理 ----
    if req.session_id:
        session_id = req.session_id
    else:
        session_id = _get_session_id(request)

    # 确保会话在数据库中
    memory.ensure_session(session_id)

    # ---- 构建消息（含记忆上下文） ----
    messages, has_memory = _build_agent_messages(session_id, req.question)

    # ---- 调用 Agent（带重试） ----
    start_time = time.time()
    response, monitor, success, retries = _invoke_agent_with_retry(
        messages, max_retries=AGENT_MAX_RETRIES,
    )
    duration = time.time() - start_time

    if not success:
        error_msg = str(response) if response else "未知错误"
        logger.error(
            "[Agent失败] session=%s | 重试%d次后仍失败 | 耗时=%.2fs | error=%s",
            session_id, retries, duration, error_msg[:200],
        )
        raise HTTPException(status_code=500, detail=f"Agent 调用失败：{error_msg[:200]}")

    logger.info(
        "[Agent完成] session=%s | 耗时=%.2fs | LLM调用次数=%d | 总Token=%d | 重试=%d次",
        session_id, duration, monitor.llm_call_count, monitor.total_tokens, retries,
    )

    try:
        # ---- 提取结构化结果 ----
        raw_data = response.get("structured_response")
        if raw_data is None:
            for msg in reversed(response.get("messages", [])):
                if hasattr(msg, "structured_output") and msg.structured_output:
                    raw_data = msg.structured_output
                    break
        if raw_data is None:
            raise HTTPException(status_code=500, detail="Agent 未返回结构化结果")

        # ---- 置信度重写 ----
        results = search_with_scores(req.question, top_k=4)
        local_hits = [(d, s) for d, s in results if s >= 0.3]

        web_refs = raw_data.reference
        calc_conf = calculate_confidence(local_hits, web_refs, raw_data.verdict)
        raw_data.confidence = calc_conf

        # ---- 保存到长时记忆 ----
        assistant_reply = raw_data.conclusion if hasattr(raw_data, "conclusion") else str(raw_data)
        memory.save_turn(session_id, req.question, assistant_reply)

        # ---- 返回结果 ----
        result = raw_data.model_dump() if isinstance(raw_data, BaseModel) else raw_data
        result["memory_used"] = has_memory
        result["history_count"] = len(memory.get_history(session_id, limit=10))
        result["monitor"] = {
            "duration_seconds": round(duration, 3),
            "llm_call_count": monitor.llm_call_count,
            "total_tokens": monitor.total_tokens,
            "retry_count": retries,
        }
        return QueryResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[处理异常] session=%s | error=%s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== 简易调试接口（可选） =====
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


@app.post("/chat")
def chat(request: ChatRequest):
    """
    简易聊天入口，用于快速验证 AgentMonitor 和回调链路。
    正式业务建议继续走 /api/analyze。
    """
    monitor = AgentMonitor()
    start_time = time.time()

    response = agent.invoke(
        {"messages": [HumanMessage(content=request.message)]},
        config={"callbacks": [monitor]},
    )

    duration = time.time() - start_time
    logger.info(
        "[/chat完成] session=%s | 耗时=%.2fs | LLM调用=%d | Token=%d",
        request.session_id,
        duration,
        monitor.llm_call_count,
        monitor.total_tokens,
    )

    return {
        "session_id": request.session_id,
        "duration_seconds": round(duration, 3),
        "llm_call_count": monitor.llm_call_count,
        "total_tokens": monitor.total_tokens,
        "response": response,
    }


# ===== 统一对话接口（多智能体协作） =====
@app.post("/api/chat", response_model=ChatResponse)
async def unified_chat(req: ChatRequest, request: Request):
    """
    统一对话入口：自动识别用户意图，路由到对应智能体
    - 谣言分析意图 → 调用谣言分析智能体
    - 闲聊意图 → 调用闲聊智能体
    - 不确定 → 按闲聊处理，引导用户澄清
    """
    # ---- 会话管理 ----
    if req.session_id:
        session_id = req.session_id
    else:
        session_id = _get_session_id(request)
    memory.ensure_session(session_id)

    total_start = time.time()
    total_llm_calls = 0
    total_tokens = 0

    try:
        # ---- 第一步：意图识别 ----
        logger.info("[对话] 收到消息 | session=%s | 内容: %s", session_id, req.message[:50])
        intent_result = recognize_intent(req.message)
        total_llm_calls += 1  # 意图识别也算一次 LLM 调用

        intent_info = IntentInfo(
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            reason=intent_result.reason,
            extracted_rumor=intent_result.extracted_rumor,
        )

        # ---- 第二步：根据意图路由 ----
        # 情况 1：谣言分析意图
        if intent_result.intent == "rumor" and intent_result.extracted_rumor:
            rumor_text = intent_result.extracted_rumor
            logger.info("[路由] 谣言分析 | 传闻: %s", rumor_text[:50])

            # 构建记忆上下文
            memory_context = _build_memory_context(session_id)
            has_memory = len(memory_context.strip()) > 0

            # 调用谣言分析智能体（带重试）
            response, monitor, success, retries = _invoke_agent_with_retry(
                _build_rumor_messages(rumor_text, memory_context),
                max_retries=AGENT_MAX_RETRIES,
            )

            if not success:
                error_msg = str(response) if response else "未知错误"
                logger.error("[谣言分析] 失败: %s", error_msg[:100])
                raise HTTPException(status_code=500, detail=f"分析失败：{error_msg[:200]}")

            total_llm_calls += monitor.llm_call_count
            total_tokens += monitor.total_tokens

            # 提取结构化结果
            raw_data = response.get("structured_response")
            if raw_data is None:
                for msg in reversed(response.get("messages", [])):
                    if hasattr(msg, "structured_output") and msg.structured_output:
                        raw_data = msg.structured_output
                        break
            if raw_data is None:
                raise HTTPException(status_code=500, detail="Agent 未返回结构化结果")

            # 置信度重写
            results = search_with_scores(rumor_text, top_k=4)
            local_hits = [(d, s) for d, s in results if s >= 0.3]
            calc_conf = calculate_confidence(local_hits, raw_data.reference, raw_data.verdict)
            raw_data.confidence = calc_conf

            # 保存到长时记忆
            assistant_reply = raw_data.conclusion if hasattr(raw_data, "conclusion") else str(raw_data)
            memory.save_turn(session_id, req.message, assistant_reply)

            # 组装结果
            result_dict = raw_data.model_dump() if isinstance(raw_data, BaseModel) else raw_data
            result_dict["memory_used"] = has_memory
            result_dict["history_count"] = len(memory.get_history(session_id, limit=10))

            total_duration = time.time() - total_start
            logger.info(
                "[对话完成] 谣言分析 | session=%s | 耗时=%.2fs | LLM=%d | Token=%d",
                session_id, total_duration, total_llm_calls, total_tokens,
            )

            return ChatResponse(
                type="rumor",
                content="",
                rumor_result=result_dict,
                intent=intent_info,
                monitor=MonitorInfo(
                    duration_seconds=round(total_duration, 3),
                    llm_call_count=total_llm_calls,
                    total_tokens=total_tokens,
                    retry_count=retries,
                ),
                session_id=session_id,
            )

        # 情况 2：闲聊 / 不确定
        else:
            if intent_result.intent == "unclear":
                logger.info("[路由] 意图不确定，按闲聊处理")
            else:
                logger.info("[路由] 闲聊对话")

            # 从记忆中构建历史消息（用于上下文）
            history_msgs = []
            history = memory.get_history(session_id, limit=6)
            for msg in history:
                if msg.is_user:
                    history_msgs.append(HumanMessage(content=msg.content))
                elif msg.is_assistant:
                    history_msgs.append(AIMessage(content=msg.content))

            # 调用闲聊智能体
            reply = chat_with_agent(req.message, history=history_msgs)
            total_llm_calls += 1

            # 保存到长时记忆
            memory.save_turn(session_id, req.message, reply)

            total_duration = time.time() - total_start
            logger.info(
                "[对话完成] 闲聊 | session=%s | 耗时=%.2fs | LLM=%d",
                session_id, total_duration, total_llm_calls,
            )

            return ChatResponse(
                type="text",
                content=reply,
                rumor_result=None,
                intent=intent_info,
                monitor=MonitorInfo(
                    duration_seconds=round(total_duration, 3),
                    llm_call_count=total_llm_calls,
                    total_tokens=total_tokens,
                ),
                session_id=session_id,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[对话异常] session=%s | error=%s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _build_rumor_messages(rumor_text: str, memory_context: str) -> list:
    """构建谣言分析的消息列表"""
    messages = []
    if memory_context:
        context_msg = HumanMessage(
            content=f"[系统提示：以下是你之前在此会话中讨论过的内容，供参考但不必须重复回答]\n{memory_context}"
        )
        messages.append(context_msg)
    messages.append(HumanMessage(content=rumor_text))
    return messages


# ===== 记忆管理接口（调试/运维用） =====
@app.get("/api/memory/stats")
def memory_stats():
    """获取记忆库统计信息"""
    stats = memory.get_stats()
    return stats


@app.get("/api/memory/history/{session_id}")
def get_memory_history(session_id: str, limit: int = 20):
    """获取某会话的记忆历史"""
    history = memory.get_history(session_id, limit)
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in history
        ],
    }


@app.delete("/api/memory/session/{session_id}")
def delete_memory_session(session_id: str):
    """删除某会话的记忆"""
    memory.db.delete_session(session_id)
    return {"status": "ok", "session_id": session_id}


@app.get("/health")
def health():
    stats = memory.get_stats()
    return {
        "status": "ok",
        "service": "谣言分析智能体(带长时记忆)",
        "memory": stats,
    }