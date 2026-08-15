"""
文档路由（document_router）

端点（全部受 JWT 保护）：
- POST   /kb/{kb_id}/documents         上传文档（异步向量化，立即返回 task_id）
- GET    /kb/{kb_id}/documents         文档列表
- GET    /documents/{doc_id}           文档详情
- GET    /documents/{doc_id}/versions  版本列表
- GET    /documents/{doc_id}/download  下载原始文件
- DELETE /documents/{doc_id}           删除文档
- POST   /documents/{doc_id}/reindex   重建向量化任务

大文档上传调用 service 后立即返回 task_id，不阻塞 HTTP 请求。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import DocumentQuery
from db.crud import document_crud
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import document_service

router = APIRouter()


@router.post("/kb/{kb_id}/documents")
def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = file.file.read()
    result = document_service.upload(db, user.id, kb_id, file.filename or "unnamed", content)
    return success_response(result, "文档上传成功")


@router.get("/kb/{kb_id}/documents")
def list_documents(
    kb_id: int,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = DocumentQuery(
        knowledge_base_id=kb_id, keyword=keyword, status=status,
        doc_type=doc_type, page=page, page_size=page_size,
    )
    return success_response(document_service.list(db, user.id, query))


@router.get("/documents/{doc_id}")
def get_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(document_service.get(db, user.id, doc_id))


@router.get("/documents/{doc_id}/versions")
def list_versions(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(document_service.list_versions(db, user.id, doc_id))


@router.get("/documents/{doc_id}/download")
def download_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = document_service.get_file_content(db, user.id, doc_id)
    doc = document_crud.get_by_id(db, doc_id)
    filename = doc.file_name if doc else f"document_{doc_id}"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/documents/{doc_id}/images/{page_number}/{index}")
def get_document_image(
    doc_id: int,
    page_number: int,
    index: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取文档内嵌图片（供前端渲染多模态检索到的图片片段）"""
    content, media_type = document_service.get_image_content(
        db, user.id, doc_id, page_number, index,
    )
    return Response(content=content, media_type=media_type)


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document_service.delete(db, user.id, doc_id)
    return success_response(None, "文档删除成功")


@router.post("/documents/{doc_id}/reindex")
def reindex_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = document_service.reindex(db, user.id, doc_id)
    return success_response(result, "重建任务已提交")
