"""
试卷服务（exam_service）

职责：
- 试卷生成：校验课程库 write+ 权限 → 建试卷记录 → 后台异步执行双 Agent 出卷闭环
- 试卷管理：列表 / 详情 / 复用修改 / 删除 / 导出 Markdown
- 权限落地：owner/admin/write 可出卷，read 只读（禁止生成试卷）
- 审计：生成/修改/删除均走 services.write_audit_log

依赖：
- ai.agent_langgraph.exam.ExamManager：双 Agent 统一执行入口（不重写工作流）
- db.crud.exam_crud：试卷表（复用）
- utils.async_task.submit_task：后台异步（大模型出卷不阻塞 HTTP）
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from config.constants import (
    KBUserRole, ExamPaperStatus, ExamQuestionType, AnswerSheetStatus,
    AuditAction, AuditResult, DEFAULT_QUESTION_SCORE,
)
from db.schemas import ExamPaperCreate, ExamPaperUpdate, AnswerSheetSubmit
from db.crud import exam_paper_crud, answer_sheet_crud, kb_crud, user_crud
from utils.permission import has_permission
from utils.exceptions import (
    ResourceNotFoundException,
    ValidationException,
    PermissionException,
)
from utils.error_codes import (
    KB_NOT_FOUND,
    KB_NO_PERMISSION,
    EXAM_PAPER_NOT_FOUND,
    EXAM_GENERATE_FAILED,
    EXAM_NO_QUESTION,
    EXAM_ANSWER_NOT_FOUND,
    EXAM_GRADE_FAILED,
    OPERATION_NOT_ALLOWED,
    PERMISSION_DENIED,
)
from utils.async_task import submit_task
from utils.response import page_result
from utils.logger import get_logger
from services import write_audit_log

logger = get_logger(__name__)


class ExamService:
    """试卷服务"""

    def __init__(self, exam_manager=None, grade_manager=None):
        # 可注入（测试用 Fake），缺省懒加载真实 ExamManager / GradeManager
        self.exam_manager = exam_manager
        self.grade_manager = grade_manager

    def _get_manager(self):
        if self.exam_manager is None:
            from ai.agent_langgraph.exam import ExamManager
            self.exam_manager = ExamManager()
        return self.exam_manager

    def _get_grade_manager(self):
        if self.grade_manager is None:
            from ai.agent_langgraph.exam import GradeManager
            self.grade_manager = GradeManager()
        return self.grade_manager

    # ============================================================
    # 试卷生成
    # ============================================================

    def generate(self, db, user_id: int, data: ExamPaperCreate) -> Dict[str, Any]:
        """发起试卷生成任务（write+ 权限），后台执行双 Agent 出卷"""
        # 1. 课程库存在 + write 权限（read 学生禁止生成试卷）
        kb = self._get_kb(db, data.knowledge_base_id)
        self._check_permission(db, data.knowledge_base_id, user_id, KBUserRole.WRITE,
                               "exam_generate", AuditAction.EXAM_GENERATE.value)

        # 2. 题型配置校验（至少一题）
        cfg = data.question_config.model_dump()
        total = sum(int(cfg.get(t, 0)) for t in ("choice", "fill", "short"))
        if total <= 0:
            raise ValidationException(EXAM_NO_QUESTION, "至少配置一道题")

        # 3. 生成标题（缺省：课程名-难度-时间）
        title = data.title or self._auto_title(kb.name, data.difficulty)

        # 4. 建试卷记录（status=generating）
        paper = exam_paper_crud.create(db, data, user_id, title)

        # 5. 后台异步执行双 Agent 出卷
        task_id = submit_task(
            self._generate_task, paper.id, data.knowledge_base_id, cfg, data.difficulty,
        )

        # 6. 审计
        write_audit_log(
            db, user_id, AuditAction.EXAM_GENERATE.value,
            resource_type="exam", resource_id=paper.id,
            details={"kb_id": data.knowledge_base_id, "question_config": cfg,
                     "difficulty": data.difficulty, "task_id": task_id},
        )
        logger.info(f"试卷生成任务提交: paper={paper.id}, kb={data.knowledge_base_id}, task={task_id}")
        return {"paper_id": paper.id, "task_id": task_id, "status": paper.status}

    def _generate_task(self, paper_id: int, kb_id: int, question_config: dict, difficulty: str) -> None:
        """后台任务：执行双 Agent 出卷闭环，回填题目/轨迹/状态"""
        from db.session import SyncSessionLocal
        db = SyncSessionLocal()
        try:
            manager = self._get_manager()
            result = manager.execute(kb_id, question_config, difficulty)

            if result.get("success"):
                exam_paper_crud.set_questions(
                    db, paper_id,
                    questions=result["questions"],
                    reference_answers=result["reference_answers"],
                    trace=result["trace"],
                    iterate_count=result["iterate_count"],
                    total_score=result["total_score"],
                )
                if result.get("warning"):
                    logger.warning(f"试卷 {paper_id} 生成告警: {result['warning']}")
            else:
                exam_paper_crud.update_status(
                    db, paper_id, ExamPaperStatus.FAILED.value,
                    result.get("error") or "试卷生成失败",
                )
                logger.error(f"试卷生成失败: paper={paper_id}, err={result.get('error')}")
        except Exception as e:
            logger.error(f"试卷生成任务异常: paper={paper_id}, err={e}")
            try:
                exam_paper_crud.update_status(
                    db, paper_id, ExamPaperStatus.FAILED.value, str(e),
                )
            except Exception:
                pass
        finally:
            db.close()

    # ============================================================
    # 试卷查询 / 管理
    # ============================================================

    def list(
        self, db, user_id: int, kb_id: Optional[int] = None,
        status: Optional[str] = None, page: int = 1, page_size: int = 20,
    ) -> Dict[str, Any]:
        """试卷列表（read+）。未指定 kb_id 时返回用户有权限课程库下的全部试卷"""
        if kb_id is not None:
            self._check_permission(db, kb_id, user_id, KBUserRole.READ, "exam_list", audit_on_deny=False)
            papers, total = exam_paper_crud.list_by_kb(db, kb_id, status, page, page_size)
        else:
            # 跨课程库：遍历用户有权限的课程库
            kbs, _ = kb_crud.get_list_by_user(db, user_id, page=1, page_size=1000)
            items: List[Dict[str, Any]] = []
            for kb in kbs:
                plist, _ = exam_paper_crud.list_by_kb(db, kb.id, status, 1, 1000)
                items.extend(self._to_paper_dict(p) for p in plist)
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            total = len(items)
            start = (page - 1) * page_size
            return page_result(items[start:start + page_size], total, page, page_size)

        return page_result([self._to_paper_dict(p) for p in papers], total, page, page_size)

    def get(self, db, user_id: int, paper_id: int) -> Dict[str, Any]:
        """试卷详情（read+，含题目 + 参考答案 + 双 Agent 轨迹）。学生（read）隐藏参考答案"""
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.READ,
                               "exam_get", audit_on_deny=False)
        role = kb_crud.get_user_role(db, paper.knowledge_base_id, user_id)
        hide_answer = role == KBUserRole.READ.value
        return self._to_paper_detail(paper, hide_answer=hide_answer)

    def update(self, db, user_id: int, paper_id: int, data: ExamPaperUpdate) -> Dict[str, Any]:
        """编辑试卷（admin+）：标题/难度/题目/参考答案。

        试卷编辑（增删改、单题重出落库）统一走本接口：当提交 questions 时，
        服务端自动规范化题目、重算参考答案 / 总分 / 题型配置，保证标签云与雷达图数据一致。
        """
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.ADMIN,
                               "exam_update", AuditAction.EXAM_UPDATE.value)
        update_data = data.model_dump(exclude_unset=True)
        questions = update_data.get("questions")
        if questions is not None:
            questions = self._sanitize_questions(questions)
            update_data["questions"] = questions
            update_data["reference_answers"] = [
                {"qid": q.get("qid"), "answer": q.get("answer"),
                 "knowledge_point": q.get("knowledge_point")}
                for q in questions
            ]
            update_data["total_score"] = sum(int(q.get("score") or 0) for q in questions)
            cfg = {"choice": 0, "fill": 0, "short": 0}
            for q in questions:
                t = q.get("type")
                if t in cfg:
                    cfg[t] += 1
            update_data["question_config"] = cfg
        paper = exam_paper_crud.update(db, paper_id, ExamPaperUpdate(**update_data))
        write_audit_log(
            db, user_id, AuditAction.EXAM_UPDATE.value,
            resource_type="exam", resource_id=paper_id,
            details={"kb_id": paper.knowledge_base_id, "question_count": len(questions) if questions is not None else None},
        )
        return self._to_paper_detail(paper)

    def regenerate_question(self, db, user_id: int, paper_id: int, qid: int) -> Dict[str, Any]:
        """试卷编辑「单题重出」（admin+）：仅针对该题调用命题 Agent 重出一题，不动其它题。

        复用 ExamManager 双 Agent 图（命题 → 校验自动复核），重出结果实时写入试卷。
        """
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.ADMIN,
                               "exam_regenerate", AuditAction.EXAM_UPDATE.value)
        if paper.status != ExamPaperStatus.READY.value:
            raise ValidationException(OPERATION_NOT_ALLOWED, "试卷尚未就绪，无法重出题目")

        questions = paper.questions or []
        idx = next((i for i, q in enumerate(questions) if q.get("qid") == qid), None)
        if idx is None:
            raise ResourceNotFoundException(EXAM_PAPER_NOT_FOUND, f"试卷中不存在第 {qid} 题")

        manager = self._get_manager()
        res = manager.regenerate_question(paper.knowledge_base_id, questions[idx], paper.difficulty)
        if not res.get("success"):
            raise ValidationException(EXAM_GENERATE_FAILED, res.get("error") or "单题重出失败")

        questions[idx] = res["question"]
        questions = self._sanitize_questions(questions)
        update_data = {
            "questions": questions,
            "reference_answers": [
                {"qid": q.get("qid"), "answer": q.get("answer"),
                 "knowledge_point": q.get("knowledge_point")}
                for q in questions
            ],
            "total_score": sum(int(q.get("score") or 0) for q in questions),
        }
        paper = exam_paper_crud.update(db, paper_id, ExamPaperUpdate(**update_data))
        write_audit_log(
            db, user_id, AuditAction.EXAM_UPDATE.value,
            resource_type="exam", resource_id=paper_id,
            details={"kb_id": paper.knowledge_base_id, "op": "regenerate", "qid": qid,
                     "warning": res.get("warning")},
        )
        detail = self._to_paper_detail(paper)
        if res.get("warning"):
            detail["warning"] = res["warning"]
        return detail

    def delete(self, db, user_id: int, paper_id: int) -> bool:
        """删除试卷（owner）"""
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.OWNER,
                               "exam_delete", AuditAction.EXAM_DELETE.value)
        exam_paper_crud.delete(db, paper_id)
        write_audit_log(
            db, user_id, AuditAction.EXAM_DELETE.value,
            resource_type="exam", resource_id=paper_id,
            details={"kb_id": paper.knowledge_base_id},
        )
        return True

    # ============================================================
    # 导出
    # ============================================================

    def export_markdown(self, db, user_id: int, paper_id: int, with_answer: bool = True) -> str:
        """导出试卷为 Markdown（题目与参考答案可分开导出）"""
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.READ,
                               "exam_export", audit_on_deny=False)
        # 学生（read）导出不附带参考答案，避免答案泄露
        role = kb_crud.get_user_role(db, paper.knowledge_base_id, user_id)
        if role == KBUserRole.READ.value:
            with_answer = False
        questions = paper.questions or []
        answers = paper.reference_answers or []

        lines = [f"# {paper.title}", "", f"难度：{paper.difficulty}　总分：{paper.total_score}",
                 f"迭代次数：{paper.iterate_count}", ""]
        type_label = {
            ExamQuestionType.CHOICE.value: "单选题",
            ExamQuestionType.FILL.value: "填空题",
            ExamQuestionType.SHORT.value: "简答题",
        }
        for q in questions:
            qid = q.get("qid")
            label = type_label.get(q.get("type"), "题目")
            score = q.get("score", 0)
            lines.append(f"## 第{qid}题（{label}，{score} 分）")
            lines.append(q.get("stem", ""))
            if q.get("options"):
                for opt in q["options"]:
                    lines.append(f"- {opt}")
            lines.append("")

        if with_answer and answers:
            lines.append("---")
            lines.append("")
            lines.append("# 参考答案")
            lines.append("")
            for a in answers:
                lines.append(f"## 第{a.get('qid')}题")
                lines.append(a.get("answer", ""))
                if a.get("knowledge_point"):
                    lines.append(f"*知识点：{a['knowledge_point']}*")
                lines.append("")
        return "\n".join(lines)

    # ============================================================
    # 答卷提交 / 批改（阶段2）
    # ============================================================

    @staticmethod
    def _norm_answer(s) -> str:
        """答案归一化：去空白、转小写，用于客观题规则判分"""
        return re.sub(r"\s+", "", str(s or "")).lower()

    @staticmethod
    def _grade_objective(question: Dict[str, Any], student_answer) -> int:
        """客观题规则判分（不调 LLM）。

        - 单选题：字母精确匹配（取首字母，忽略大小写）
        - 填空题：去空白精确匹配 → 否则按关键词命中比例给分
        """
        qtype = question.get("type")
        max_score = int(question.get("score") or 0)
        ref = str(question.get("answer") or "").strip()
        stu = str(student_answer or "").strip()

        if qtype == ExamQuestionType.CHOICE.value:
            r = (ref[:1] or "").upper()
            s = (stu[:1] or "").upper()
            return max_score if (r and s and r == s) else 0

        if qtype == ExamQuestionType.FILL.value:
            r = ExamService._norm_answer(ref)
            s = ExamService._norm_answer(stu)
            if not s:
                return 0
            if r == s:
                return max_score
            terms = [t for t in re.split(r"[，,、;；/｜|]+", r) if t]
            if not terms:
                terms = [r]
            matched = sum(1 for t in terms if t in s)
            if not matched:
                return 0
            return max(0, round(max_score * matched / len(terms)))

        return 0  # 主观题不在此判分

    def _grade_objective_all(self, questions: list, answers: list) -> tuple:
        """客观题判分，返回 (判分明细, 客观题总分)。

        只处理客观题（选择/填空），主观题由后台 _grade_task 单独批改后追加，
        避免出现重复的判分明细项。
        """
        ans_map = {a.get("qid"): a.get("answer") for a in answers if isinstance(a, dict)}
        details: List[Dict[str, Any]] = []
        objective_score = 0
        for q in questions:
            qid = q.get("qid")
            qtype = q.get("type")
            max_score = int(q.get("score") or 0)
            if qtype in (ExamQuestionType.CHOICE.value, ExamQuestionType.FILL.value):
                s = self._grade_objective(q, ans_map.get(qid, ""))
                objective_score += s
                details.append({
                    "qid": qid, "type": qtype, "score": s, "max_score": max_score,
                    "objective": True, "correct": s == max_score,
                })
        return details, objective_score

    def submit_answer(self, db, user_id: int, paper_id: int, data: AnswerSheetSubmit) -> Dict[str, Any]:
        """学生提交答卷（read 亦可）。客观题同步规则判分，主观题后台溯源批改"""
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.READ,
                               "exam_submit", AuditAction.EXAM_SUBMIT.value)

        if paper.status != ExamPaperStatus.READY.value:
            raise ValidationException(OPERATION_NOT_ALLOWED, "试卷尚未生成完成，无法作答")

        questions = paper.questions or []
        if not questions:
            raise ValidationException(EXAM_NO_QUESTION, "试卷无题目，无法作答")

        answers = data.answers or []
        has_short = any(q.get("type") == ExamQuestionType.SHORT.value for q in questions)

        # 客观题规则判分（同步，只用于快速返回客观分；完整明细 + 错误解析在后台批改任务完成）
        _, objective_score = self._grade_objective_all(questions, answers)

        # 统一走后台批改任务：客观题答错生成「错误解析」、主观题四维度分项溯源批改，
        # 全部在后台完成，提交接口快速返回，前端轮询批改状态。
        sheet = answer_sheet_crud.create(
            db, paper_id, user_id, answers,
            objective_score=objective_score,
            status=AnswerSheetStatus.GRADING.value,
        )
        task_id = submit_task(self._grade_task, sheet.id)

        write_audit_log(
            db, user_id, AuditAction.EXAM_SUBMIT.value,
            resource_type="exam", resource_id=paper_id,
            details={"answer_id": sheet.id, "objective_score": objective_score,
                     "has_subjective": has_short},
        )
        logger.info(f"答卷提交: answer={sheet.id}, paper={paper_id}, student={user_id}, "
                    f"objective={objective_score}, subjective_pending={has_short}")
        return {
            "answer_id": sheet.id,
            "task_id": task_id,
            "status": sheet.status,
            "objective_score": objective_score,
        }

    def _grade_task(self, answer_id: int) -> None:
        """后台任务：主观题溯源批改（RAG 检索课件 + LLM 判分），回填得分与来源引用"""
        from db.session import SyncSessionLocal
        db = SyncSessionLocal()
        try:
            sheet = answer_sheet_crud.get_by_id(db, answer_id)
            if not sheet:
                return
            paper = exam_paper_crud.get_by_id(db, sheet.exam_paper_id)
            if not paper:
                answer_sheet_crud.update_status(
                    db, answer_id, AnswerSheetStatus.FAILED.value, "试卷不存在",
                )
                return

            kb_id = paper.knowledge_base_id
            questions = paper.questions or []
            answers = sheet.answers or []
            ans_map = {a.get("qid"): a.get("answer") for a in answers if isinstance(a, dict)}

            # 客观题规则判分（重算，不调 LLM）
            objective_details, objective_score = self._grade_objective_all(questions, answers)

            # 精细化溯源批改：主观题四维度分项打分；客观题答错生成错误解析
            grader = self._get_grade_manager()
            subjective_score = 0
            for q in questions:
                qtype = q.get("type")
                qid = q.get("qid")
                if qtype == ExamQuestionType.SHORT.value:
                    res = grader.grade_subjective(kb_id, q, ans_map.get(qid, ""))
                    subjective_score += res["score"]
                    objective_details.append({
                        "qid": qid, "type": qtype,
                        "score": res["score"], "max_score": res["max_score"],
                        "strengths": res["strengths"], "missing": res["missing"],
                        "source_refs": res["source_refs"],
                        "dimensions": res.get("dimensions") or [],
                        "objective": False, "error": res.get("error"),
                    })
                elif qtype in (ExamQuestionType.CHOICE.value, ExamQuestionType.FILL.value):
                    # 客观题答错：补充「错误选项解析 + 考察知识点 + 课件溯源片段」
                    d = next((x for x in objective_details if x.get("qid") == qid), None)
                    if d is not None and not d.get("correct"):
                        detail_res = grader.grade_objective_detail(
                            kb_id, q, ans_map.get(qid, ""), d.get("score", 0),
                        )
                        d["analysis"] = detail_res.get("analysis")
                        d["knowledge_point"] = detail_res.get("knowledge_point") or q.get("knowledge_point")
                        refs = list(dict.fromkeys(
                            (d.get("source_refs") or []) + detail_res.get("source_refs", [])
                        ))
                        d["source_refs"] = refs
                        d["analysis_error"] = detail_res.get("error")
                        d["objective_explain"] = True

            total = objective_score + subjective_score
            answer_sheet_crud.set_result(
                db, answer_id, objective_details, objective_score, subjective_score, total,
            )
            write_audit_log(
                db, sheet.student_id, AuditAction.EXAM_GRADE.value,
                resource_type="exam", resource_id=sheet.exam_paper_id,
                details={"answer_id": answer_id, "objective_score": objective_score,
                         "subjective_score": subjective_score, "total_score": total},
            )
            logger.info(f"答卷批改完成: answer={answer_id}, objective={objective_score}, "
                        f"subjective={subjective_score}, total={total}")
        except Exception as e:
            logger.error(f"答卷批改任务异常: answer={answer_id}, err={e}")
            try:
                answer_sheet_crud.update_status(
                    db, answer_id, AnswerSheetStatus.FAILED.value, str(e),
                )
            except Exception:
                pass
        finally:
            db.close()

    def list_answers(self, db, user_id: int, paper_id: int, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """教师（write+）查看某试卷全班答卷"""
        paper = self._get_paper(db, paper_id)
        self._check_permission(db, paper.knowledge_base_id, user_id, KBUserRole.WRITE,
                               "exam_list_answers", audit_on_deny=False)
        sheets, total = answer_sheet_crud.list_by_paper(db, paper_id, page, page_size)
        return page_result([self._to_sheet_dict(db, s) for s in sheets], total, page, page_size)

    def get_answer(self, db, user_id: int, answer_id: int) -> Dict[str, Any]:
        """答卷详情：学生仅能看自己的答卷，教师（write+）可看全班任一答卷"""
        sheet = answer_sheet_crud.get_by_id(db, answer_id)
        if not sheet:
            raise ResourceNotFoundException(EXAM_ANSWER_NOT_FOUND, f"答卷 {answer_id} 不存在")
        paper = exam_paper_crud.get_by_id(db, sheet.exam_paper_id)
        role = kb_crud.get_user_role(db, paper.knowledge_base_id, user_id) if paper else None
        is_teacher = bool(role and has_permission(role, KBUserRole.WRITE))
        if sheet.student_id != user_id and not is_teacher:
            raise PermissionException(PERMISSION_DENIED, "无权限查看该答卷", {"answer_id": answer_id})
        return self._to_sheet_dict(db, sheet, with_detail=True)

    def _to_sheet_dict(self, db, sheet, with_detail: bool = False) -> Dict[str, Any]:
        """答卷序列化：附带学生昵称/用户名，列表缺省不返回批改明细"""
        d = sheet.to_dict()
        student = user_crud.get_by_id(db, sheet.student_id) if sheet.student_id else None
        d["student_name"] = (student.nickname or student.username) if student else None
        if not with_detail:
            d.pop("answers", None)
            d.pop("grading_details", None)
        return d

    # ============================================================
    # 内部工具
    # ============================================================

    def _get_manager_for_task(self):
        return self._get_manager()

    def _get_kb(self, db, kb_id: int):
        kb = kb_crud.get_by_id(db, kb_id)
        if not kb:
            raise ResourceNotFoundException(KB_NOT_FOUND, f"课程库 {kb_id} 不存在")
        return kb

    def _get_paper(self, db, paper_id: int):
        paper = exam_paper_crud.get_by_id(db, paper_id)
        if not paper:
            raise ResourceNotFoundException(EXAM_PAPER_NOT_FOUND, f"试卷 {paper_id} 不存在")
        return paper

    def _check_permission(
        self, db, kb_id: int, user_id: int,
        required_role: KBUserRole, resource: str,
        action: str = AuditAction.EXAM_GENERATE.value,
        audit_on_deny: bool = True,
    ) -> None:
        """课程库权限校验，越权抛 PermissionException 并写审计（permission_denied）"""
        role = kb_crud.get_user_role(db, kb_id, user_id)
        if role is None:
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": resource, "user_role": None, "required": required_role.value},
                )
            raise PermissionException(KB_NO_PERMISSION, "无该课程库访问权限", {"resource": f"kb_{kb_id}"})
        if not has_permission(role, required_role):
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": resource, "user_role": role, "required": required_role.value},
                )
            raise PermissionException(
                KB_NO_PERMISSION, f"需要 {required_role.value} 权限", {"resource": f"kb_{kb_id}"},
            )

    @staticmethod
    def _auto_title(kb_name: str, difficulty: str) -> str:
        """自动生成试卷标题"""
        diff_label = {"easy": "易", "medium": "中", "hard": "难"}.get(difficulty, difficulty)
        now = datetime.now().strftime("%Y%m%d")
        return f"{kb_name}试卷-{diff_label}等-{now}"

    @staticmethod
    def _sanitize_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """规范化试卷编辑提交的题目：过滤无效项、重新编号 qid、补齐字段、确保选择题选项合法"""
        valid_types = {t.value for t in ExamQuestionType}
        clean: List[Dict[str, Any]] = []
        for q in questions or []:
            if not isinstance(q, dict):
                continue
            qtype = str(q.get("type") or "").strip().lower()
            if qtype not in valid_types:
                continue
            stem = str(q.get("stem") or "").strip()
            if not stem:
                continue
            item = {
                "type": qtype,
                "stem": stem,
                "answer": str(q.get("answer") or "").strip(),
                "knowledge_point": str(q.get("knowledge_point") or "").strip(),
                "source_refs": [str(r).strip() for r in (q.get("source_refs") or [])
                                if str(r).strip()],
                "score": max(0, int(q.get("score") or 0)),
            }
            if qtype == ExamQuestionType.CHOICE.value:
                options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
                if len(options) < 2:
                    continue
                item["options"] = options
            clean.append(item)
        for i, q in enumerate(clean):
            q["qid"] = i + 1
        return clean

    @staticmethod
    def _to_paper_dict(paper) -> Dict[str, Any]:
        d = paper.to_dict()
        # 列表接口不返回题目明细与轨迹，减小响应体
        d.pop("questions", None)
        d.pop("reference_answers", None)
        d.pop("trace", None)
        return d

    @staticmethod
    def _to_paper_detail(paper, hide_answer: bool = False) -> Dict[str, Any]:
        d = paper.to_dict()
        for key in ("questions", "reference_answers", "trace"):
            d[key] = getattr(paper, key, None)
        # 学生（read）隐藏参考答案：题目里去掉 answer，参考答案置空
        if hide_answer:
            d["reference_answers"] = None
            questions = d.get("questions") or []
            d["questions"] = [
                {k: v for k, v in q.items() if k != "answer"}
                for q in questions
            ]
        return d


# 单例
exam_service = ExamService()
