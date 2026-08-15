"""
会话 + 消息 CRUD
"""
from __future__ import annotations

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from datetime import datetime

from db.models import Conversation, Message
from db.schemas import ConversationCreate, ConversationUpdate
from config.constants import ConversationType, MessageRole
from utils.logger import get_logger

logger = get_logger(__name__)


class ConversationCRUD:
    """会话 CRUD"""

    model = Conversation

    def get_by_id(self, db: Session, conv_id: int) -> Optional[Conversation]:
        return db.query(Conversation).filter(
            Conversation.id == conv_id,
            Conversation.is_deleted == False,  # noqa: E712
        ).first()

    def get_list_by_user(
        self,
        db: Session,
        user_id: int,
        kb_id: Optional[int] = None,
        type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Conversation], int]:
        query = db.query(Conversation).filter(
            Conversation.user_id == user_id,
            Conversation.is_deleted == False,  # noqa: E712
        )
        if kb_id:
            query = query.filter(Conversation.knowledge_base_id == kb_id)
        if type:
            query = query.filter(Conversation.type == type)

        total = query.count()
        convs = query.order_by(Conversation.last_message_at.desc().nullslast(),
                               Conversation.updated_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return convs, total

    def create(self, db: Session, user_id: int, obj_in: ConversationCreate) -> Conversation:
        data = obj_in.model_dump()
        data["user_id"] = user_id
        conv = Conversation(**data)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        logger.info(f"创建会话: id={conv.id}, user_id={user_id}")
        return conv

    def update(self, db: Session, conv_id: int, obj_in: ConversationUpdate | dict) -> Optional[Conversation]:
        conv = self.get_by_id(db, conv_id)
        if not conv:
            return None
        update_data = obj_in.model_dump(exclude_unset=True) if hasattr(obj_in, "model_dump") else obj_in
        for field, value in update_data.items():
            if hasattr(conv, field) and value is not None:
                setattr(conv, field, value)
        db.commit()
        db.refresh(conv)
        return conv

    def delete(self, db: Session, conv_id: int) -> bool:
        conv = self.get_by_id(db, conv_id)
        if not conv:
            return False
        conv.is_deleted = True
        db.commit()
        return True

    def touch_last_message(self, db: Session, conv_id: int) -> None:
        """更新最后消息时间与消息计数"""
        conv = self.get_by_id(db, conv_id)
        if not conv:
            return
        conv.last_message_at = datetime.utcnow()
        conv.message_count = (conv.message_count or 0) + 1
        db.commit()


class MessageCRUD:
    """消息 CRUD"""

    model = Message

    def get_by_id(self, db: Session, msg_id: int) -> Optional[Message]:
        return db.query(Message).filter(
            Message.id == msg_id,
            Message.is_deleted == False,  # noqa: E712
        ).first()

    def get_by_conversation(
        self,
        db: Session,
        conv_id: int,
        limit: int = 50,
        before_id: Optional[int] = None,
    ) -> List[Message]:
        """获取会话的消息列表（按时间正序）"""
        query = db.query(Message).filter(
            Message.conversation_id == conv_id,
            Message.is_deleted == False,  # noqa: E712
        )
        if before_id:
            query = query.filter(Message.id < before_id)
        return query.order_by(Message.id.desc()).limit(limit)[::-1]  # 倒序取最新，再反转成正序

    def create(
        self,
        db: Session,
        conv_id: int,
        role: str,
        content: str,
        citations: Optional[list] = None,
        meta_info: Optional[dict] = None,
    ) -> Message:
        msg = Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            citations=citations,
            meta_info=meta_info,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        # 更新会话统计
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv:
            conv.last_message_at = datetime.utcnow()
            conv.message_count = (conv.message_count or 0) + 1
            db.commit()
        return msg

    def delete(self, db: Session, msg_id: int) -> bool:
        msg = self.get_by_id(db, msg_id)
        if not msg:
            return False
        msg.is_deleted = True
        db.commit()
        return True


# 单例
conversation_crud = ConversationCRUD()
message_crud = MessageCRUD()
