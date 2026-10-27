# -*- coding: utf-8 -*-
"""
多智能体协作系统
=================
包含三个智能体 + 一个路由分发器：

  1. intent_agent  —— 意图识别智能体（判断用户要干嘛）
  2. rumor_agent   —— 谣言分析智能体（原有的分析逻辑）
  3. chat_agent    —— 闲聊智能体（日常对话、打招呼、引导）
  4. route_request —— 路由分发函数（根据意图调用对应智能体）
"""
import logging
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import List, Optional

from schemas import AnswerInfo
from tools import web_search, local_kb_search
from llm import model

logger = logging.getLogger("agents")


# ============================================================
# 1. 谣言分析智能体（原有的，改个名）
# ============================================================
_rumor_system_prompt = (
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
)

rumor_agent = create_agent(
    model=model,
    tools=[local_kb_search, web_search],
    system_prompt=_rumor_system_prompt,
    response_format=ToolStrategy(AnswerInfo, handle_errors=True),
)


# ============================================================
# 2. 意图识别智能体
# ============================================================
class IntentResult(BaseModel):
    """意图识别结果"""
    intent: str = Field(description="用户意图分类：rumor（谣言分析）/ chat（闲聊对话）/ unclear（不确定）")
    confidence: float = Field(description="意图识别置信度，0.0~1.0")
    reason: str = Field(description="判断理由，一句话说明为什么归类为该意图")
    extracted_rumor: str = Field(description="如果是谣言分析意图，提取出需要核实的传闻原文；如果不是则填空字符串")


_intent_system_prompt = """你是一个专业的意图识别助手。请分析用户输入的消息，判断用户的意图属于哪一类：

【意图分类】
1. rumor（谣言分析）：用户在询问某条传闻/说法/消息是否真实，或者要求验证某个说法的真假。
   典型特征：包含"是真的吗"、"真的假的"、"辟谣"、"是不是谣言"、"可信吗"、"靠谱吗"等疑问词；
   或者用户直接抛出一条传闻希望得到核实。

2. chat（闲聊对话）：用户在打招呼、问候、闲聊、问问题（非谣言类）、表达情绪、
   或者进行日常交流。例如："你好"、"你是谁"、"你能做什么"、"今天天气怎么样"、
   "讲个笑话"、"谢谢"、"再见"等。

3. unclear（不确定）：用户输入太模糊、太短、无法判断意图，或者内容有歧义。

【输出要求】
- 严格按照 IntentResult 格式输出
- intent 只能是 rumor / chat / unclear 三者之一
- confidence 给出你判断的把握程度
- reason 用一句话说明判断理由
- 如果是 rumor 意图，extracted_rumor 填写用户需要核实的传闻原文（去掉疑问词）

【示例】
用户：你好
→ intent=chat, confidence=0.98, reason="用户在打招呼"

用户：吃头孢喝酒真的会死吗
→ intent=rumor, confidence=0.95, reason="用户在询问说法的真实性", extracted_rumor="吃头孢喝酒会死"

用户：你能帮我做什么
→ intent=chat, confidence=0.9, reason="用户询问能力范围，属于日常对话"

用户：今天听说
→ intent=unclear, confidence=0.3, reason="用户输入不完整，无法判断具体意图"
"""

intent_agent = create_agent(
    model=model,
    tools=[],
    system_prompt=_intent_system_prompt,
    response_format=ToolStrategy(IntentResult, handle_errors=True),
)


# ============================================================
# 3. 闲聊智能体
# ============================================================
_chat_system_prompt = """你是一个专业且友好的 AI 助手，名字叫「谣言终结者」。
你的主要职责是和用户进行日常对话交流，并在合适的时候引导用户使用谣言分析功能。

【性格特点】
- 专业可靠，同时亲切自然
- 幽默风趣，但不过分
- 回答简洁明了，不啰嗦

【能力范围】
- 日常打招呼、问候、告别
- 回答关于你自己的问题（你是谁、你能做什么）
- 简单的闲聊和互动
- 适当地引导用户尝试谣言分析功能

【引导话术】
当用户问你能做什么、或者对话内容涉及到传闻/说法/真假时，
你可以自然地介绍："我是谣言终结者，可以帮你鉴别各类谣言！你把听到的传闻发给我，我来帮你核查真假~"

【注意事项】
- 不要编造事实，不知道就说不知道
- 不要进行谣言分析（那是另一个智能体的工作）
- 保持对话的轻松愉快氛围
- 回答控制在 2-3 句话以内，除非用户需要更详细的回答
"""

# 闲聊智能体用简单的 model.invoke 即可，不需要工具
chat_model = model


# ============================================================
# 4. 路由分发函数
# ============================================================
def recognize_intent(user_message: str) -> IntentResult:
    """
    识别用户消息的意图

    :param user_message: 用户输入的消息
    :return: IntentResult
    """
    try:
        response = intent_agent.invoke(
            {"messages": [HumanMessage(content=user_message)]},
        )
        result = response.get("structured_response")
        if result is None:
            for msg in reversed(response.get("messages", [])):
                if hasattr(msg, "structured_output") and msg.structured_output:
                    result = msg.structured_output
                    break
        if result:
            logger.info(
                "[意图识别] intent=%s | confidence=%.2f | reason=%s",
                result.intent, result.confidence, result.reason,
            )
            return result
    except Exception as e:
        logger.error("[意图识别] 失败: %s", e)

    # 兜底：默认按 chat 处理
    return IntentResult(
        intent="chat",
        confidence=0.5,
        reason="意图识别异常，默认按闲聊处理",
        extracted_rumor="",
    )


def chat_with_agent(user_message: str, history: Optional[list] = None) -> str:
    """
    调用闲聊智能体进行对话

    :param user_message: 用户消息
    :param history: 历史消息列表（HumanMessage/AIMessage）
    :return: 回复文本
    """
    messages = [SystemMessage(content=_chat_system_prompt)]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=user_message))

    try:
        response = chat_model.invoke(messages)
        reply = response.content
        logger.info("[闲聊] 回复完成，长度: %d", len(reply))
        return reply
    except Exception as e:
        logger.error("[闲聊] 调用失败: %s", e)
        return "抱歉，我有点走神了，能再说一遍吗？😊"


def analyze_rumor_with_agent(
    rumor_text: str,
    callbacks: Optional[list] = None,
    memory_context: str = "",
) -> dict:
    """
    调用谣言分析智能体

    :param rumor_text: 需要分析的传闻文本
    :param callbacks: 回调列表（监控用）
    :param memory_context: 记忆上下文
    :return: 结构化结果 dict
    """
    messages = []
    if memory_context:
        context_msg = HumanMessage(
            content=f"[系统提示：以下是你之前在此会话中讨论过的内容，供参考但不必须重复回答]\n{memory_context}"
        )
        messages.append(context_msg)
    messages.append(HumanMessage(content=rumor_text))

    response = rumor_agent.invoke(
        {"messages": messages},
        config={"callbacks": callbacks} if callbacks else {},
    )

    raw_data = response.get("structured_response")
    if raw_data is None:
        for msg in reversed(response.get("messages", [])):
            if hasattr(msg, "structured_output") and msg.structured_output:
                raw_data = msg.structured_output
                break

    return raw_data


# 兼容旧代码：保持 agent 变量可用
agent = rumor_agent
_base_system_prompt = _rumor_system_prompt
