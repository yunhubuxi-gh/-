"""
CRUD 数据访问层

所有数据库操作都封装在此层，业务层通过 CRUD 操作数据库，
不直接写 SQL，便于统一管理与优化。
"""
from db.crud.user_crud import user_crud
from db.crud.kb_crud import kb_crud
from db.crud.document_crud import document_crud
from db.crud.conversation_crud import conversation_crud, message_crud
from db.crud.agent_task_crud import agent_task_crud
from db.crud.audit_log_crud import audit_log_crud

__all__ = [
    "user_crud",
    "kb_crud",
    "document_crud",
    "conversation_crud",
    "message_crud",
    "agent_task_crud",
    "audit_log_crud",
]
