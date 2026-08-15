"""
知识库路由（kb_router）

端点（全部受 JWT 保护）：
- POST   ""                   创建知识库
- GET    ""                   我的知识库列表
- GET    /{kb_id}             知识库详情
- PUT    /{kb_id}             修改知识库（admin+）
- DELETE /{kb_id}             删除知识库（owner）
- GET    /{kb_id}/members     成员列表
- POST   /{kb_id}/members     添加成员（admin+）
- PUT    /{kb_id}/members/{member_user_id}   更新成员权限（admin+）
- DELETE /{kb_id}/members/{member_user_id}   移除成员（admin+）

权限拦截在 service 层落地，本层只透传参数。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import KBCreate, KBUpdate, KBMemberAdd, KBMemberUpdate
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import kb_service

router = APIRouter()


@router.post("")
def create_kb(
    data: KBCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(kb_service.create(db, user.id, data), "知识库创建成功")


@router.get("")
def list_my(
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(kb_service.list_my(db, user.id, keyword, page, page_size))


@router.get("/{kb_id}")
def get_kb(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(kb_service.get(db, user.id, kb_id))


@router.put("/{kb_id}")
def update_kb(
    kb_id: int,
    data: KBUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(kb_service.update(db, user.id, kb_id, data), "知识库更新成功")


@router.delete("/{kb_id}")
def delete_kb(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kb_service.delete(db, user.id, kb_id)
    return success_response(None, "知识库删除成功")


@router.get("/{kb_id}/members")
def list_members(
    kb_id: int,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(kb_service.list_members(db, user.id, kb_id, page, page_size))


@router.post("/{kb_id}/members")
def add_member(
    kb_id: int,
    data: KBMemberAdd,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(kb_service.add_member(db, user.id, kb_id, data), "成员添加成功")


@router.put("/{kb_id}/members/{member_user_id}")
def update_member_role(
    kb_id: int,
    member_user_id: int,
    data: KBMemberUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(
        kb_service.update_member_role(db, user.id, kb_id, member_user_id, data),
        "成员权限更新成功",
    )


@router.delete("/{kb_id}/members/{member_user_id}")
def remove_member(
    kb_id: int,
    member_user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kb_service.remove_member(db, user.id, kb_id, member_user_id)
    return success_response(None, "成员移除成功")
