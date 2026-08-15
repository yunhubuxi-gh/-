"""
试卷 / 答卷 CRUD（课程试卷智能命题校验批改系统）

- ExamPaperCRUD：试卷元数据 + 题目/答案/双Agent执行轨迹的读写
- AnswerSheetCRUD：学生答卷 + 客观题/主观题得分 + 溯源批改详情

数据访问层约定：不写原生 SQL，全部走 SQLAlchemy ORM；
试卷题目/答案/轨迹均为结构化 JSON，不存文件（遵循「三者分离」原则）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session

from db.models import ExamPaper, AnswerSheet
from db.schemas import ExamPaperCreate, ExamPaperUpdate
from config.constants import ExamPaperStatus, AnswerSheetStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class ExamPaperCRUD:
    """试卷 CRUD"""

    model = ExamPaper

    def get_by_id(self, db: Session, paper_id: int) -> Optional[ExamPaper]:
        return db.query(ExamPaper).filter(
            ExamPaper.id == paper_id,
            ExamPaper.is_deleted == False,  # noqa: E712
        ).first()

    def create(
        self,
        db: Session,
        obj_in: ExamPaperCreate,
        creator_id: int,
        title: str,
    ) -> ExamPaper:
        """创建试卷记录（status=generating），供后台双 Agent 任务回填题目与轨迹"""
        data = obj_in.model_dump()
        data["creator_id"] = creator_id
        data["title"] = title
        data["status"] = ExamPaperStatus.GENERATING.value
        paper = ExamPaper(**data)
        db.add(paper)
        db.commit()
        db.refresh(paper)
        logger.info(f"创建试卷: id={paper.id}, kb={paper.knowledge_base_id}, title={title}")
        return paper

    def update(self, db: Session, paper_id: int, obj_in: ExamPaperUpdate) -> Optional[ExamPaper]:
        """复用旧试卷修改（标题/难度/题目/答案）"""
        paper = self.get_by_id(db, paper_id)
        if not paper:
            return None
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None and hasattr(paper, field):
                setattr(paper, field, value)
        db.commit()
        db.refresh(paper)
        logger.info(f"更新试卷: id={paper_id}")
        return paper

    def update_status(
        self,
        db: Session,
        paper_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[ExamPaper]:
        """更新生成状态（generating/ready/failed）"""
        paper = self.get_by_id(db, paper_id)
        if not paper:
            return None
        paper.status = status
        if error_message is not None:
            paper.error_message = error_message
        db.commit()
        db.refresh(paper)
        return paper

    def update_trace(self, db: Session, paper_id: int, trace: list) -> Optional[ExamPaper]:
        """更新双 Agent 执行轨迹（前端可视化完整执行过程）"""
        paper = self.get_by_id(db, paper_id)
        if not paper:
            return None
        paper.trace = trace
        db.commit()
        db.refresh(paper)
        return paper

    def set_questions(
        self,
        db: Session,
        paper_id: int,
        questions: list,
        reference_answers: list,
        trace: list,
        iterate_count: int,
        total_score: int,
    ) -> Optional[ExamPaper]:
        """写入最终试卷题目/答案/轨迹，并置为 ready"""
        paper = self.get_by_id(db, paper_id)
        if not paper:
            return None
        paper.questions = questions
        paper.reference_answers = reference_answers
        paper.trace = trace
        paper.iterate_count = iterate_count
        paper.total_score = total_score
        paper.status = ExamPaperStatus.READY.value
        db.commit()
        db.refresh(paper)
        return paper

    def list_by_kb(
        self,
        db: Session,
        kb_id: int,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ExamPaper], int]:
        """列出课程库下的试卷（按创建时间倒序）"""
        query = db.query(ExamPaper).filter(
            ExamPaper.knowledge_base_id == kb_id,
            ExamPaper.is_deleted == False,  # noqa: E712
        )
        if status:
            query = query.filter(ExamPaper.status == status)
        total = query.count()
        papers = query.order_by(ExamPaper.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return papers, total

    def delete(self, db: Session, paper_id: int) -> bool:
        """软删除试卷"""
        paper = self.get_by_id(db, paper_id)
        if not paper:
            return False
        paper.is_deleted = True
        db.commit()
        logger.info(f"删除试卷: id={paper_id}")
        return True


class AnswerSheetCRUD:
    """答卷 CRUD"""

    model = AnswerSheet

    def get_by_id(self, db: Session, answer_id: int) -> Optional[AnswerSheet]:
        return db.query(AnswerSheet).filter(
            AnswerSheet.id == answer_id,
            AnswerSheet.is_deleted == False,  # noqa: E712
        ).first()

    def create(
        self,
        db: Session,
        exam_paper_id: int,
        student_id: int,
        answers: list,
        objective_score: int = 0,
        status: Optional[str] = None,
    ) -> AnswerSheet:
        """创建答卷（缺省 status=submitted，可预置客观题得分与批改状态）"""
        sheet = AnswerSheet(
            exam_paper_id=exam_paper_id,
            student_id=student_id,
            answers=answers,
            objective_score=objective_score,
            status=status or AnswerSheetStatus.SUBMITTED.value,
            submitted_at=datetime.now(),
        )
        db.add(sheet)
        db.commit()
        db.refresh(sheet)
        logger.info(f"创建答卷: id={sheet.id}, paper={exam_paper_id}, student={student_id}")
        return sheet

    def update_status(
        self,
        db: Session,
        answer_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[AnswerSheet]:
        sheet = self.get_by_id(db, answer_id)
        if not sheet:
            return None
        sheet.status = status
        if error_message is not None:
            sheet.error_message = error_message
        db.commit()
        db.refresh(sheet)
        return sheet

    def set_result(
        self,
        db: Session,
        answer_id: int,
        grading_details: list,
        objective_score: int,
        subjective_score: int,
        total_score: int,
    ) -> Optional[AnswerSheet]:
        """写入批改结果并置为 graded"""
        sheet = self.get_by_id(db, answer_id)
        if not sheet:
            return None
        sheet.grading_details = grading_details
        sheet.objective_score = objective_score
        sheet.subjective_score = subjective_score
        sheet.total_score = total_score
        sheet.status = AnswerSheetStatus.GRADED.value
        db.commit()
        db.refresh(sheet)
        return sheet

    def list_by_paper(
        self,
        db: Session,
        exam_paper_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AnswerSheet], int]:
        """列出某试卷下的全部答卷（教师查看全班）"""
        query = db.query(AnswerSheet).filter(
            AnswerSheet.exam_paper_id == exam_paper_id,
            AnswerSheet.is_deleted == False,  # noqa: E712
        )
        total = query.count()
        sheets = query.order_by(AnswerSheet.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return sheets, total


# 单例
exam_paper_crud = ExamPaperCRUD()
answer_sheet_crud = AnswerSheetCRUD()
