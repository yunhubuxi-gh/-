"""
会话与问答服务（chat_service）

职责：
- 会话管理：创建/列表/详情/删除会话、读取消息
- RAG 问答：read 权限校验 → 取历史 → 调用 rag_engine.answer（统一入口，不重写检索/生成）
  → 保存用户/助手消息（含引用 JSON）→ 审计
- 权限：问答/查看需 read+

依赖：
- db.crud.conversation_crud / message_crud：会话与消息
- ai.rag_engine.RagPipeline.answer：问答统一入口
- config.settings：检索条数等配置（无魔法数字）
- 审计：问答（chat_question）走 services.write_audit_log
"""
from __future__ import annotations

from typing import Dict, Any, Optional

from config.settings import settings
from config.constants import (
    ConversationType,
    MessageRole,
    KBUserRole,
    AuditAction,
    AuditResult,
)
from db.schemas import ConversationCreate, ChatRequest
from db.crud import conversation_crud, message_crud, kb_crud
from utils.permission import has_permission
from utils.exceptions import (
    ResourceNotFoundException,
    ValidationException,
    PermissionException,
)
from utils.error_codes import (
    KB_NOT_FOUND,
    KB_NO_PERMISSION,
    CHAT_CONVERSATION_NOT_FOUND,
)
from utils.response import page_result
from utils.logger import get_logger
from services import write_audit_log

logger = get_logger(__name__)

# 历史消息窗口大小（config 驱动，无魔法数字）
_HISTORY_WINDOW = getattr(settings, "agent_short_term_memory_window", 10)


class ChatService:
    """会话与问答服务"""

    def __init__(self, rag_pipeline=None):
        # 可注入（测试用 Fake），缺省懒加载真实 RagPipeline
        self.rag_pipeline = rag_pipeline

    # ============================================================
    # 会话管理
    # ============================================================

    def create_conversation(self, db, user_id: int, data: ConversationCreate) -> Dict[str, Any]:
        """创建会话（关联知识库时校验 read 权限）"""
        if data.knowledge_base_id:
            self._check_read(db, data.knowledge_base_id, user_id, audit_on_deny=False)
        conv = conversation_crud.create(db, user_id, data)
        return conv.to_dict()

    def list_conversations(
        self, db, user_id: int, kb_id: Optional[int] = None,
        type: Optional[str] = None, page: int = 1, page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出当前用户的会话"""
        convs, total = conversation_crud.get_list_by_user(
            db, user_id, kb_id, type, page, page_size,
        )
        return page_result([c.to_dict() for c in convs], total, page, page_size)

    def get_conversation(self, db, user_id: int, conv_id: int) -> Dict[str, Any]:
        """会话详情（归属 + read 校验）"""
        conv = self._get_conv(db, user_id, conv_id)
        if conv.knowledge_base_id:
            self._check_read(db, conv.knowledge_base_id, user_id, audit_on_deny=False)
        return conv.to_dict()

    def get_messages(
        self, db, user_id: int, conv_id: int, limit: int = 50,
    ) -> list:
        """读取会话消息（归属 + read 校验）"""
        conv = self._get_conv(db, user_id, conv_id)
        if conv.knowledge_base_id:
            self._check_read(db, conv.knowledge_base_id, user_id, audit_on_deny=False)
        msgs = message_crud.get_by_conversation(db, conv_id, limit)
        return [m.to_dict() for m in msgs]

    def delete_conversation(self, db, user_id: int, conv_id: int) -> bool:
        """删除会话（仅归属用户本人）"""
        self._get_conv(db, user_id, conv_id)
        return conversation_crud.delete(db, conv_id)

    # ============================================================
    # RAG 问答
    # ============================================================

    def ask(self, db, user_id: int, data: ChatRequest) -> Dict[str, Any]:
        """
        知识库问答：检索 → LLM 生成 → 幻觉抑制 → 引用标注（全部由 rag_engine 完成）。
        本服务只做：权限校验、历史装配、消息持久化、审计。
        """
        # 1. read 权限
        self._check_read(db, data.knowledge_base_id, user_id,
                         AuditAction.CHAT_QUESTION.value)

        # 2. 会话：复用已有（须归属本人且知识库匹配）或新建
        conv_id = data.conversation_id
        if conv_id:
            conv = self._get_conv(db, user_id, conv_id)
            if conv.knowledge_base_id and conv.knowledge_base_id != data.knowledge_base_id:
                raise ValidationException(
                    CHAT_CONVERSATION_NOT_FOUND, "会话与知识库不匹配",
                )
        else:
            conv = conversation_crud.create(
                db, user_id,
                ConversationCreate(
                    title=data.query[:30],
                    knowledge_base_id=data.knowledge_base_id,
                    type=ConversationType.CHAT.value,
                ),
            )
            conv_id = conv.id

        # 3. 保存用户消息
        message_crud.create(db, conv_id, MessageRole.USER.value, data.query)

        # 4. 历史装配（user/assistant 角色，供 RAG 上下文）
        history = self._build_history(db, conv_id)

        # 5. 问答（复用 rag_engine 统一入口）
        top_k = getattr(settings, "vector_top_k", 5)
        result = self._get_pipeline().answer(
            data.query, [data.knowledge_base_id], top_k=top_k, history=history,
        )
        citations = [c.to_dict() for c in result.citations]

        # 6. 保存助手消息（引用 JSON 单独存 citations 字段）
        message_crud.create(
            db, conv_id, MessageRole.ASSISTANT.value, result.answer,
            citations=citations,
            meta_info={
                "grounded": result.grounded,
                "no_answer": result.no_answer,
                "warnings": result.warnings,
            },
        )

        # 7. 审计
        write_audit_log(
            db, user_id, AuditAction.CHAT_QUESTION.value,
            resource_type="conv", resource_id=conv_id,
            details={
                "kb_id": data.knowledge_base_id,
                "query": data.query[:100],
                "grounded": result.grounded,
            },
        )
        return {
            "conversation_id": conv_id,
            "answer": result.answer,
            "citations": citations,
            "grounded": result.grounded,
            "no_answer": result.no_answer,
            "warnings": result.warnings,
        }

    # ============================================================
    # 内部工具
    # ============================================================

    def _get_pipeline(self):
        if self.rag_pipeline is None:
            from ai.rag_engine.rag_pipeline import RagPipeline
            self.rag_pipeline = RagPipeline()
        return self.rag_pipeline

    def _get_conv(self, db, user_id: int, conv_id: int):
        conv = conversation_crud.get_by_id(db, conv_id)
        if not conv or conv.is_deleted:
            raise ResourceNotFoundException(
                CHAT_CONVERSATION_NOT_FOUND, f"会话 {conv_id} 不存在",
            )
        if conv.user_id != user_id:
            raise PermissionException(
                KB_NO_PERMISSION, "无权访问该会话", {"resource": f"conv_{conv_id}"},
            )
        return conv

    def _build_history(self, db, conv_id: int) -> list:
        """装配最近 N 条 user/assistant 历史消息"""
        msgs = message_crud.get_by_conversation(db, conv_id, limit=_HISTORY_WINDOW)
        history = [
            {"role": m.role, "content": m.content}
            for m in msgs
            if m.role in (MessageRole.USER.value, MessageRole.ASSISTANT.value)
        ]
        return history[-_HISTORY_WINDOW:]

    def _check_read(
        self, db, kb_id: int, user_id: int,
        action: str = AuditAction.CHAT_QUESTION.value,
        audit_on_deny: bool = True,
    ) -> None:
        """校验知识库 read 权限，越权抛 PermissionException 并写审计"""
        if not kb_crud.get_by_id(db, kb_id):
            raise ResourceNotFoundException(KB_NOT_FOUND, f"知识库 {kb_id} 不存在")
        role = kb_crud.get_user_role(db, kb_id, user_id)
        if role is None or not has_permission(role, KBUserRole.READ):
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": "chat_read", "user_role": role, "required": "read"},
                )
            raise PermissionException(
                KB_NO_PERMISSION, "无该知识库访问权限", {"resource": f"kb_{kb_id}"},
            )


# 单例
chat_service = ChatService()
