"""
试卷路由（exam_router）

端点（全部受 JWT 保护）：
- POST   /papers                    发起试卷生成（双 Agent 出卷，后台异步）
- GET    /papers                    试卷列表（可指定课程库）
- GET    /papers/{paper_id}         试卷详情（含题目 + 参考答案 + 双 Agent 轨迹）
- PUT    /papers/{paper_id}         复用旧试卷修改（admin+）
- DELETE /papers/{paper_id}         删除试卷（owner）
- GET    /papers/{paper_id}/export  导出 Markdown（题目与参考答案可分开）
- POST   /papers/{paper_id}/submit  学生提交答卷（客观题规则判分 + 主观题后台批改）
- GET    /papers/{paper_id}/answers 教师查看全班答卷
- GET    /answers/{answer_id}       答卷批改详情（含溯源引用）

权限拦截在 service 层落地，本层只透传参数。
"""
from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import ExamPaperCreate, ExamPaperUpdate, AnswerSheetSubmit
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import exam_service

router = APIRouter()


@router.post("/papers")
def generate_paper(
    data: ExamPaperCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.generate(db, user.id, data), "试卷生成任务已提交")


@router.get("/papers")
def list_papers(
    kb_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.list(db, user.id, kb_id, status, page, page_size))


@router.get("/papers/{paper_id}")
def get_paper(
    paper_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.get(db, user.id, paper_id))


@router.put("/papers/{paper_id}")
def update_paper(
    paper_id: int,
    data: ExamPaperUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.update(db, user.id, paper_id, data), "试卷更新成功")


@router.delete("/papers/{paper_id}")
def delete_paper(
    paper_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam_service.delete(db, user.id, paper_id)
    return success_response(None, "试卷删除成功")


@router.get("/papers/{paper_id}/export")
def export_paper(
    paper_id: int,
    with_answer: bool = True,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    md = exam_service.export_markdown(db, user.id, paper_id, with_answer)
    filename = f"exam_{paper_id}.md"
    return StreamingResponse(
        io.BytesIO(md.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/papers/{paper_id}/submit")
def submit_answer(
    paper_id: int,
    data: AnswerSheetSubmit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.submit_answer(db, user.id, paper_id, data), "答卷已提交")


@router.get("/papers/{paper_id}/answers")
def list_answers(
    paper_id: int,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.list_answers(db, user.id, paper_id, page, page_size))


@router.get("/answers/{answer_id}")
def get_answer(
    answer_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(exam_service.get_answer(db, user.id, answer_id))
