# -*- coding: utf-8 -*-
"""会话管理辅助函数"""
import uuid
from fastapi import Request
from memory import get_memory


def _get_session_id(request: Request, cookie_name: str = "agent_session") -> str:
    """获取或生成会话ID"""
    # 1. 优先从 cookie 读取
    session_id = request.cookies.get(cookie_name)
    if session_id and len(session_id) > 0:
        return session_id

    # 2. 从自定义 header 读取
    session_id = request.headers.get("X-Session-ID")
    if session_id and len(session_id) > 0:
        return session_id

    # 3. 基于 IP + UA 生成（首次访问）
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "")[:100]
    session_id = f"session_{uuid.uuid4().hex[:12]}"
    return session_id


def _build_memory_context(session_id: str) -> str:
    """从长时记忆中构建上下文提示"""
    memory = get_memory()
    history = memory.get_history(session_id, limit=10)
    if not history:
        return ""

    context_lines = ["【历史对话参考】以下是在此会话中之前讨论过的内容，供参考：\n"]
    for msg in history:
        role_label = "用户" if msg.is_user else "助手"
        # 截断过长的消息
        content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
        context_lines.append(f"[{role_label}] {content}\n")

    context_lines.append("【结束历史对话】\n")
    return "\n".join(context_lines)