"""
会话与问答路由（chat_router）

端点（全部受 JWT 保护）：
- POST /conversations                创建会话
- GET  /conversations                会话列表
- GET  /conversations/{conv_id}/messages   会话消息列表
- POST /ask                          知识库问答（普通 RAG）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import ConversationCreate, ChatRequest
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import chat_service

router = APIRouter()


@router.post("/conversations")
def create_conversation(
    data: ConversationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(chat_service.create_conversation(db, user.id, data), "会话创建成功")


@router.get("/conversations")
def list_conversations(
    kb_id: Optional[int] = None,
    conv_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(
        chat_service.list_conversations(db, user.id, kb_id, conv_type, page, page_size),
    )


@router.get("/conversations/{conv_id}/messages")
def get_messages(
    conv_id: int,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(chat_service.get_messages(db, user.id, conv_id, limit))


@router.post("/ask")
def ask(
    data: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(chat_service.ask(db, user.id, data))
