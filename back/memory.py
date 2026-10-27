# -*- coding: utf-8 -*-
"""
长时记忆模块 - 基于 SQLite 的对话记忆存储
============================================
功能：
  1. 会话管理（创建/查询/清理会话）
  2. 消息持久化（保存/查询/搜索对话记录）
  3. 可选的 FAISS 语义检索（通过环境变量 MEMORY_USE_FAISS=1 启用）

使用方式（在 lie_server.py 中）：
  from memory import MemoryManager

  # 初始化（只需一次）
  mem = MemoryManager()

  # 保存消息
  mem.save_message(session_id, "user", user_message)
  mem.save_message(session_id, "assistant", assistant_response)

  # 获取对话历史
  history = mem.get_history(session_id, limit=20)

  # 语义搜索（需启用 FAISS）
  results = mem.search_memories(session_id, "之前聊过的谣言话题")
"""

import sqlite3
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# ===== 配置（统一从 config.py 读取） =====
from config import (
    MEMORY_DB_PATH as DB_PATH,
    MEMORY_USE_FAISS as USE_FAISS,
    FAISS_INDEX_PATH,
    SEMANTIC_SEARCH_TOP_K,
    SEMANTIC_SCORE_THRESHOLD,
    MESSAGE_RETENTION_DAYS,
)

# ===== 数据模型 =====
@dataclass
class Message:
    """消息数据类"""
    id: int
    session_id: str
    role: str           # 'user' / 'assistant' / 'system'
    content: str
    created_at: str     # ISO 格式时间字符串

    @property
    def is_user(self) -> bool:
        return self.role == 'user'

    @property
    def is_assistant(self) -> bool:
        return self.role == 'assistant'


@dataclass
class Session:
    """会话数据类"""
    session_id: str
    user_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0


# ===== 数据库层 =====
class MemoryDB:
    """SQLite 数据库操作层"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # 启用 WAL 模式（提升并发性能）
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    user_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                )
            """)

            # 消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                )
            """)

            # 索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(session_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_role ON messages(session_id, role)")

            conn.commit()

    def create_session(self, session_id: str, user_id: Optional[str] = None) -> Session:
        """创建新会话"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, user_id) VALUES (?, ?)",
                (session_id, user_id)
            )
            conn.commit()
            return self.get_session(session_id)

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话信息"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT session_id, user_id, created_at, updated_at, "
                "(SELECT COUNT(*) FROM messages WHERE session_id = s.session_id) as message_count "
                "FROM sessions s WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row is None:
                return None
            return Session(
                session_id=row["session_id"],
                user_id=row["user_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                message_count=row["message_count"]
            )

    def save_message(self, session_id: str, role: str, content: str) -> int:
        """保存一条消息，返回消息 ID"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content)
            )
            # 更新会话的 updated_at
            conn.execute(
                "UPDATE sessions SET updated_at = datetime('now') WHERE session_id = ?",
                (session_id,)
            )
            conn.commit()
            return cursor.lastrowid

    def get_history(self, session_id: str, limit: int = 20) -> List[Message]:
        """获取最近 N 条对话历史（按时间正序）"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (session_id, limit)
            ).fetchall()
            return [
                Message(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]

    def get_recent_assistant(self, session_id: str, n: int = 1) -> List[str]:
        """获取最近 N 条助手回复（纯文本列表，用于构建上下文）"""
        history = self.get_history(session_id, limit=n * 2)  # 多取一些以防角色不匹配
        assistant_msgs = []
        for msg in reversed(history):
            if msg.is_assistant:
                assistant_msgs.append(msg.content)
                if len(assistant_msgs) >= n:
                    break
        return list(reversed(assistant_msgs))

    def search_messages(self, session_id: str, keyword: str, limit: int = 10) -> List[Message]:
        """关键词搜索历史消息"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND content LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, f"%{keyword}%", limit)
            ).fetchall()
            return [
                Message(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]

    def delete_session(self, session_id: str):
        """删除会话及其所有消息"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    def cleanup_old_messages(self, retention_days: int = MESSAGE_RETENTION_DAYS):
        """清理过期消息（保留最近 retention_days 天的数据）"""
        if retention_days <= 0:
            return 0
        with self._get_conn() as conn:
            # 删除过期消息
            conn.execute(
                "DELETE FROM messages WHERE created_at < datetime('now', ?)",
                (f"-{retention_days} days",)
            )
            deleted_messages = conn.total_changes

            # 删除空会话
            conn.execute(
                "DELETE FROM sessions WHERE session_id NOT IN "
                "(SELECT DISTINCT session_id FROM messages)"
            )
            conn.commit()
            return deleted_messages

    def get_stats(self) -> Dict[str, any]:
        """获取记忆库统计信息"""
        with self._get_conn() as conn:
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            today_messages = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE date(created_at) = date('now')"
            ).fetchone()[0]
            return {
                "total_sessions": sessions,
                "total_messages": messages,
                "today_messages": today_messages,
            }


# ===== FAISS 语义检索层（可选） =====
class MemoryVectorStore:
    """基于 FAISS 的记忆语义检索（可选组件）"""

    def __init__(self, index_path: str = FAISS_INDEX_PATH):
        self.index_path = index_path
        self._faiss = None
        self._embeddings = None
        self._docmap: Dict[int, Tuple[str, str]] = {}  # doc_id -> (session_id, content)
        self._load_or_create()

    def _load_or_create(self):
        """加载已有索引或创建新索引"""
        try:
            from langchain_community.vectorstores import FAISS
            import os as _os

            if _os.path.exists(self.index_path):
                self._faiss = FAISS.load_local(
                    self.index_path,
                    self._get_embeddings(),
                    allow_dangerous_deserialization=True
                )
                # 重建 docmap（FAISS 不持久化 metadata）
                self._docmap = {}
                for i, doc in enumerate(self._faiss.docstore._dict.values()):
                    meta = doc.metadata if hasattr(doc, 'metadata') else {}
                    self._docmap[i] = (meta.get("session_id", ""), doc.page_content)
                print(f"[MemoryVectorStore] 加载已有索引，共 {len(self._docmap)} 条记忆")
            else:
                self._faiss = FAISS.from_documents([], self._get_embeddings())
                print(f"[MemoryVectorStore] 创建新索引，路径: {self.index_path}")
        except ImportError:
            print("[MemoryVectorStore] langchain_community 未安装，语义检索功能不可用")
            self._faiss = None
        except Exception as e:
            print(f"[MemoryVectorStore] 初始化失败: {e}，语义检索功能不可用")
            self._faiss = None

    def _get_embeddings(self):
        """获取 embedding 实例（复用 lie_server 的配置）"""
        if self._embeddings is not None:
            return self._embeddings

        # 尝试本地 BGE
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            bge_dir = os.getenv("BGE_LOCAL_DIR", "")
            model_name = bge_dir if bge_dir and os.path.isdir(bge_dir) else os.getenv(
                "BGE_MODEL_NAME", "BAAI/bge-small-zh-v1.5"
            )
            self._embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": os.getenv("BGE_DEVICE", "cpu")},
                encode_kwargs={"normalize_embeddings": True},
            )
            return self._embeddings
        except Exception:
            pass

        # 回退 DashScope
        try:
            from langchain_openai import OpenAIEmbeddings
            self._embeddings = OpenAIEmbeddings(
                model="text-embedding-v3",
                base_url=os.getenv("DASHSCOPE_BASE_URL"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                check_embedding_ctx_length=False,
            )
            return self._embeddings
        except Exception as e:
            print(f"[MemoryVectorStore] 无法初始化 embedding: {e}")
            return None

    def add_message(self, session_id: str, message_id: int, content: str):
        """将一条消息加入向量索引"""
        if self._faiss is None or self._embeddings is None:
            return
        from langchain_community.docstore.document import Document
        doc = Document(
            page_content=content,
            metadata={"session_id": session_id, "message_id": message_id}
        )
        self._faiss.add_documents([doc])
        self._docmap[len(self._docmap)] = (session_id, content)

    def search(self, session_id: str, query: str, top_k: int = SEMANTIC_SEARCH_TOP_K) -> List[Dict]:
        """语义搜索相关记忆"""
        if self._faiss is None:
            return []

        results = self._faiss.similarity_search_with_score(query, k=top_k * 2)
        # 过滤同一会话的旧消息（排除当前查询的那条）
        filtered = []
        for doc, score in results:
            meta = doc.metadata if hasattr(doc, 'metadata') else {}
            doc_session = meta.get("session_id", "")
            # 只返回相关度>=阈值的
            if score >= SEMANTIC_SCORE_THRESHOLD:
                filtered.append({
                    "session_id": doc_session,
                    "content": doc.page_content,
                    "score": round(score, 3),
                })
        return filtered[:top_k]

    def save_index(self):
        """持久化索引到磁盘"""
        if self._faiss is not None:
            self._faiss.save_local(self.index_path)
            print(f"[MemoryVectorStore] 索引已保存: {self.index_path}")


# ===== 统一管理器 =====
class MemoryManager:
    """长时记忆统一管理器 - 对外暴露的 API"""

    def __init__(self, db_path: str = DB_PATH, enable_vector: bool = USE_FAISS):
        self.db = MemoryDB(db_path)
        self.vector_store: Optional[MemoryVectorStore] = None
        self._enabled_vector = enable_vector

        if self._enabled_vector:
            try:
                self.vector_store = MemoryVectorStore()
            except Exception as e:
                print(f"[MemoryManager] 向量检索初始化失败: {e}，将仅使用 SQLite")
                self.vector_store = None

        # 启动时清理过期数据
        self.db.cleanup_old_messages()
        print(f"[MemoryManager] 已初始化 (SQLite={db_path}, FAISS={self._enabled_vector})")

    def ensure_session(self, session_id: str, user_id: Optional[str] = None) -> Session:
        """确保会话存在，不存在则创建"""
        session = self.db.get_session(session_id)
        if session is None:
            session = self.db.create_session(session_id, user_id)
        return session

    def save_turn(self, session_id: str, user_message: str, assistant_message: str):
        """保存一轮完整对话（用户消息 + 助手回复）"""
        # 1. 存 SQLite
        msg_id_user = self.db.save_message(session_id, "user", user_message)
        msg_id_ai = self.db.save_message(session_id, "assistant", assistant_message)

        # 2. 存向量索引（异步感，不阻塞）
        if self.vector_store is not None:
            try:
                self.vector_store.add_message(session_id, msg_id_user, user_message)
                self.vector_store.add_message(session_id, msg_id_ai, assistant_message)
            except Exception as e:
                print(f"[MemoryManager] 向量索引写入失败: {e}")

        return msg_id_user, msg_id_ai

    def get_history(self, session_id: str, limit: int = 20) -> List[Message]:
        """获取对话历史"""
        return self.db.get_history(session_id, limit)

    def get_context_messages(self, session_id: str, limit: int = 20) -> List[Dict]:
        """获取适合传入 LLM 的上下文消息列表（dict 格式）"""
        history = self.get_history(session_id, limit)
        return [
            {"role": msg.role, "content": msg.content}
            for msg in history
        ]

    def search_memories(self, session_id: str, query: str) -> List[Dict]:
        """语义搜索相关记忆"""
        if self.vector_store is not None:
            return self.vector_store.search(session_id, query)
        # 降级到关键词搜索
        return self.db.search_messages(session_id, query)

    def cleanup(self):
        """清理过期数据"""
        deleted = self.db.cleanup_old_messages()
        if self.vector_store is not None:
            try:
                self.vector_store.save_index()
            except Exception as e:
                print(f"[MemoryManager] 向量索引保存失败: {e}")
        return deleted

    def get_stats(self) -> Dict[str, any]:
        """获取统计信息"""
        stats = self.db.get_stats()
        if self.vector_store is not None:
            stats["vector_index_size"] = len(self.vector_store._docmap) if self.vector_store._docmap else 0
        return stats

    def shutdown(self):
        """优雅关闭"""
        if self.vector_store is not None:
            try:
                self.vector_store.save_index()
            except Exception as e:
                print(f"[MemoryManager] 关闭时保存索引失败: {e}")


# ===== 模块级单例（方便直接导入使用） =====
_memory_instance: Optional[MemoryManager] = None


def get_memory(db_path: str = DB_PATH, enable_vector: bool = USE_FAISS) -> MemoryManager:
    """获取记忆管理器单例"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = MemoryManager(db_path=db_path, enable_vector=enable_vector)
    return _memory_instance


# 直接导入时的便捷初始化
try:
    memory = get_memory()
except Exception as e:
    print(f"[Memory] 初始化警告: {e}，请确保 SQLite 可写")
    memory = None