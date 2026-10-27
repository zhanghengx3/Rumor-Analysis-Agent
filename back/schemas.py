# -*- coding: utf-8 -*-
"""Pydantic 数据模型"""
from pydantic import BaseModel as PydanticBaseModel, Field
from typing import List, Optional, Dict, Any


# ============================================================
# 谣言分析相关
# ============================================================
class KeyEntities(PydanticBaseModel):
    subject: str = Field(description="传闻涉及的主体/对象，如某种食物、药品、人物、机构；无法确定填'未提及'")
    time: str = Field(description="传闻涉及的时间或时段；未提及填'未提及'")
    location: str = Field(description="传闻涉及的地点或范围；未提及填'未提及'")
    event: str = Field(description="用一句话概括传闻的核心论断/事件")


class Reference(PydanticBaseModel):
    source: str = Field(description="证据来源说明，例如'本地辟谣知识库'或联网检索到的网页标题")
    url: str = Field(description="网页的真实URL。本地证据留空，联网证据必须从 web_search 返回的真实来源网址中提取，严禁捏造。")


class AnswerInfo(PydanticBaseModel):
    key_entities: KeyEntities = Field(description="从用户传闻中自动抽取的关键信息")
    verdict: str = Field(description="判断结果：真实、虚假或存疑")
    confidence: float = Field(description="置信度：0.0到1.0")
    basis: List[str] = Field(description="推理依据，分条列出，每条写明证据内容及其来源(本地/联网)")
    conflict_analysis: str = Field(
        description="多源证据冲突分析：明确指出本地证据与联网证据(若有)之间是否存在冲突、"
                    "冲突点是什么、以及最终采信哪一方及理由；若来源一致或仅有单一来源，也要明确说明。"
    )
    conclusion: str = Field(description="最终结论的总结性陈述")
    reference: list[Reference] = Field(description="引用的来源列表")


class QueryRequest(PydanticBaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, description="客户端会话ID，不传则自动生成")


class KeyEntitiesResp(PydanticBaseModel):
    subject: str
    time: str
    location: str
    event: str


class QueryResponse(PydanticBaseModel):
    key_entities: KeyEntitiesResp
    verdict: str
    confidence: float
    basis: List[str]
    conflict_analysis: str
    conclusion: str
    reference: List[dict]
    memory_used: bool = Field(False, description="是否使用了长时记忆上下文")
    history_count: int = Field(0, description="本次使用的历史对话条数")


# ============================================================
# 多智能体对话相关
# ============================================================
class ChatRequest(PydanticBaseModel):
    """统一对话请求"""
    message: str = Field(..., min_length=1, max_length=2000, description="用户输入的消息")
    session_id: Optional[str] = Field(None, description="客户端会话ID，不传则自动生成")


class IntentInfo(PydanticBaseModel):
    """意图识别信息"""
    intent: str = Field(description="rumor / chat / unclear")
    confidence: float = Field(description="置信度 0~1")
    reason: str = Field(description="判断理由")
    extracted_rumor: str = Field(description="提取的传闻原文（仅 rumor 意图有值）")


class MonitorInfo(PydanticBaseModel):
    """监控指标"""
    duration_seconds: float = Field(0, description="总耗时（秒）")
    llm_call_count: int = Field(0, description="LLM 调用次数")
    total_tokens: int = Field(0, description="总 Token 消耗")
    retry_count: int = Field(0, description="重试次数")


class ChatResponse(PydanticBaseModel):
    """统一对话响应"""
    # 消息类型：text（纯文本闲聊） / rumor（谣言分析结果）
    type: str = Field(description="消息类型：text / rumor")
    # 文本内容（type=text 时有值）
    content: str = Field("", description="文本回复内容")
    # 谣言分析结果（type=rumor 时有值）
    rumor_result: Optional[Dict[str, Any]] = Field(None, description="谣言分析结构化结果")
    # 意图识别信息
    intent: IntentInfo = Field(description="意图识别结果")
    # 监控信息
    monitor: MonitorInfo = Field(default_factory=MonitorInfo, description="性能监控指标")
    # 会话信息
    session_id: str = Field(description="会话ID")
