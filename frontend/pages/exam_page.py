"""
试卷页面（课程试卷智能命题校验批改系统）

功能：
- 教师（owner/admin/write）发起试卷生成（双 Agent 出卷，后台异步 + 进度轮询）
- 历史试卷列表 + 详情（题目 / 参考答案 / 双 Agent 完整执行轨迹）
- 导出 Markdown（含/不含答案）
权限：read 学生隐藏「生成试卷」，且详情不返回参考答案。
"""
from __future__ import annotations

import html
import time

import streamlit as st

from frontend import styles, config
from frontend.api_client import api, ApiError
from frontend.components import notify_success, notify_error, empty_state, empty_guide, navigate, pill


def _esc(s) -> str:
    return html.escape(str(s))


def _list_kb_options():
    try:
        return api.get("/api/v1/kb", params={"page_size": 100})["items"]
    except ApiError:
        return []


_DIFF_LABEL = {"easy": "易", "medium": "中", "hard": "难"}
_TYPE_LABEL = {"choice": "单选题", "fill": "填空题", "short": "简答题"}


def _generate_block() -> None:
    kbs = _list_kb_options()
    if not kbs:
        if empty_guide("📚", "还没有课程库",
                       "创建课程库并上传课件后，即可生成试卷",
                       "去创建课程库", key="exam_empty_kb"):
            navigate("kb")
        return

    with st.container(border=True):
        with st.form("exam_generate_form", clear_on_submit=True):
            kb_options = {f'{kb["name"]} (ID {kb["id"]})': kb for kb in kbs}
            chosen = st.selectbox("选择课程库", list(kb_options.keys()))
            kb = kb_options[chosen]
            kb_id = kb["id"]
            role = kb.get("user_role") or "read"

            c1, c2, c3 = st.columns(3)
            choice = c1.number_input("单选题数", 0, 50, 5, step=1)
            fill = c2.number_input("填空题数", 0, 50, 3, step=1)
            short = c3.number_input("简答题数", 0, 20, 2, step=1)
            title = st.text_input("试卷标题（可选）", placeholder="留空自动生成")
            difficulty = st.selectbox(
                "难度", ["easy", "medium", "hard"],
                format_func=lambda d: {"easy": "易", "medium": "中", "hard": "难"}[d],
            )
            submitted = st.form_submit_button("生成试卷", type="primary", use_container_width=True)

        if not submitted:
            return
        if role not in ("owner", "admin", "write"):
            notify_error("你为只读成员，无生成试卷权限")
            return
        if choice + fill + short <= 0:
            notify_error("至少配置一道题")
            return

        try:
            payload = {
                "knowledge_base_id": kb_id,
                "difficulty": difficulty,
                "question_config": {"choice": int(choice), "fill": int(fill), "short": int(short)},
            }
            if title:
                payload["title"] = title
            with st.spinner("正在提交生成任务…"):
                data = api.post("/api/v1/exam/papers", json=payload)
            paper_id = data["paper_id"]
            notify_success(f"试卷生成任务已提交（ID {paper_id}）")

            # 轮询生成状态（双 Agent 出卷较慢，放宽轮询上限）
            status_bar = st.progress(0, text="双 Agent 出卷中（命题 → 逐题校验 → 重生成）…")
            deadline = time.time() + max(config.POLL_MAX_WAIT_SECONDS, 600)
            status_map = {"generating": 0.5, "ready": 1.0, "failed": 1.0}
            while time.time() < deadline:
                try:
                    paper = api.get(f"/api/v1/exam/papers/{paper_id}")
                except ApiError:
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                    continue
                s = paper.get("status")
                status_bar.progress(min(status_map.get(s, 0.1), 0.9), text=f"出卷状态：{s}")
                if s in ("ready", "failed"):
                    if s == "ready":
                        status_bar.progress(1.0, text="试卷生成完成 ✅")
                        notify_success(f"试卷「{paper.get('title')}」已生成")
                    else:
                        status_bar.empty()
                        notify_error(f"生成失败：{paper.get('error_message') or '未知错误'}")
                    break
                time.sleep(config.POLL_INTERVAL_SECONDS)
            else:
                status_bar.empty()
                notify_error("生成耗时较长，已提交后台，请稍后刷新查看")
            st.rerun()
        except ApiError as e:
            notify_error(e.message)


def _render_questions(paper: dict) -> None:
    """渲染题目列表"""
    questions = paper.get("questions") or []
    answers = {a.get("qid"): a for a in (paper.get("reference_answers") or [])}
    if not questions:
        st.info("暂无题目")
        return
    for q in questions:
        qid = q.get("qid")
        label = _TYPE_LABEL.get(q.get("type"), "题目")
        score = q.get("score", 0)
        st.markdown(
            f'<div class="stCard" style="padding:0.7rem 1rem;margin:0.4rem 0;">'
            f'<div style="font-weight:700;font-size:0.95rem;">第{qid}题 · {label} · {score} 分</div>'
            f'<div style="margin-top:0.4rem;">{_esc(q.get("stem", ""))}</div>',
            unsafe_allow_html=True,
        )
        if q.get("options"):
            opts = "".join(f'<div style="margin:0.15rem 0;">{_esc(o)}</div>' for o in q["options"])
            st.markdown(f'<div style="color:#444;font-size:0.9rem;margin:0.3rem 0 0 1rem;">{opts}</div>',
                        unsafe_allow_html=True)
        # 答案（学生端已由后端隐藏 answer 字段）
        if q.get("answer"):
            st.markdown(f'<div style="color:#2f9e44;font-size:0.85rem;margin-top:0.4rem;">'
                        f'<b>答案：</b>{_esc(q["answer"])}</div>', unsafe_allow_html=True)
        if q.get("knowledge_point"):
            st.markdown(f'<div style="color:#555a63;font-size:0.8rem;">知识点：{_esc(q["knowledge_point"])}</div>',
                        unsafe_allow_html=True)
        if q.get("source_refs"):
            st.markdown(f'<div style="color:#7c3aed;font-size:0.8rem;margin-top:0.2rem;">'
                        f'📖 来源引用：{_esc("；".join(q["source_refs"][:2]))}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_trace(trace: list) -> None:
    """渲染双 Agent 完整执行轨迹（命题 → 逐题校验 → 重生成）"""
    if not trace:
        return
    st.markdown('<div style="font-weight:600;margin-top:0.5rem;">🔄 双 Agent 执行轨迹</div>', unsafe_allow_html=True)
    for i, entry in enumerate(trace):
        phase = entry.get("phase")
        iteration = entry.get("iteration")
        if phase == "generation":
            rag_queries = entry.get("rag_queries") or []
            query_text = "；".join(
                f'{r.get("query")}({r.get("count")}条)' for r in rag_queries
            )
            st.markdown(
                f'<div class="stCard" style="padding:0.5rem 0.8rem;margin:0.3rem 0;font-size:0.82rem;'
                f'border-left:3px solid #3b5bdb;">'
                f'<b>第{iteration}轮 · 命题 Agent</b> · {_esc(entry.get("detail") or "")} · '
                f'出题 {entry.get("question_count", 0)} 道</div>',
                unsafe_allow_html=True,
            )
            if query_text:
                st.markdown(f'<div style="font-size:0.78rem;color:#555a63;margin:0 0 0.4rem 1rem;">'
                            f'RAG 检索：{_esc(query_text)}</div>', unsafe_allow_html=True)
        elif phase == "validation":
            st.markdown(
                f'<div class="stCard" style="padding:0.5rem 0.8rem;margin:0.3rem 0;font-size:0.82rem;'
                f'border-left:3px solid #e8930c;">'
                f'<b>第{iteration}轮 · 校验评审 Agent</b> · {_esc(entry.get("detail") or "")}</div>',
                unsafe_allow_html=True,
            )
            per_question = entry.get("per_question") or []
            for v in per_question:
                ok = v.get("verdict") == "pass"
                color = "#2f9e44" if ok else "#e03131"
                mark = "✅ 合格" if ok else "❌ 不合格"
                st.markdown(
                    f'<div style="font-size:0.8rem;margin:0.2rem 0 0.2rem 1rem;">'
                    f'<span style="color:{color};font-weight:600;">第{v.get("qid")}题 {mark}</span>'
                    f' · {_esc(v.get("reason") or "")}</div>',
                    unsafe_allow_html=True,
                )


def _paper_history() -> None:
    try:
        data = api.get("/api/v1/exam/papers", params={"page_size": 100})
        papers = data["items"]
    except ApiError as e:
        st.warning(e.message)
        return

    if not papers:
        empty_state("📝", "暂无试卷，生成后将在此展示")
        return

    st.markdown('<div style="font-weight:600;margin:0.6rem 0 0.4rem 0;">历史试卷</div>', unsafe_allow_html=True)
    for p in papers:
        status = p.get("status")
        status_label = {"generating": "生成中", "ready": "就绪", "failed": "失败"}.get(status, status)
        with st.expander(f'{p.get("title") or "试卷"} · {_esc(status_label)} · 总分 {p.get("total_score", 0)}'):
            st.markdown(
                f'<div style="color:#555a63;font-size:0.85rem;margin-bottom:0.5rem;">'
                f'ID {p.get("id")} · 难度 {_DIFF_LABEL.get(p.get("difficulty"), p.get("difficulty"))} · '
                f'迭代 {p.get("iterate_count", 0)} 轮</div>',
                unsafe_allow_html=True,
            )
            if p.get("error_message"):
                st.markdown(f'<div style="color:#e03131;font-size:0.85rem;">失败原因：{_esc(p["error_message"])}</div>',
                            unsafe_allow_html=True)

            # 导出按钮
            try:
                md = api.get_bytes(f"/api/v1/exam/papers/{p['id']}/export?with_answer=true")
                st.download_button(
                    "⬇️ 导出 Markdown（含答案）", md,
                    file_name=f"exam_{p['id']}.md", mime="text/markdown",
                    key=f"dl_{p['id']}",
                )
            except ApiError as e:
                st.warning(e.message)

            # 详情（题目 + 轨迹）
            try:
                detail = api.get(f"/api/v1/exam/papers/{p['id']}")
            except ApiError:
                detail = None
            if detail:
                _render_questions(detail)
                _render_trace(detail.get("trace"))


_SHEET_STATUS_LABEL = {"submitted": "待批改", "grading": "批改中", "graded": "已批改", "failed": "批改失败"}


def _list_ready_papers() -> list:
    try:
        data = api.get("/api/v1/exam/papers", params={"status": "ready", "page_size": 100})
        return data["items"]
    except ApiError:
        return []


def _render_grading_detail(sheet: dict) -> None:
    """渲染答卷批改详情（得分 + 优缺点 + 课件原文溯源引用）"""
    obj = sheet.get("objective_score", 0)
    subj = sheet.get("subjective_score", 0)
    total = sheet.get("total_score", 0)
    st.markdown(
        f'<div style="font-size:0.9rem;margin:0.3rem 0;">'
        f'客观 {obj} 分 + 主观 {subj} 分 = <b>总分 {total} 分</b></div>',
        unsafe_allow_html=True,
    )
    if sheet.get("error_message"):
        st.markdown(f'<div style="color:#e03131;font-size:0.85rem;">批改异常：{_esc(sheet["error_message"])}</div>',
                    unsafe_allow_html=True)
    details = sheet.get("grading_details") or []
    for d in details:
        qid = d.get("qid")
        score = d.get("score", 0)
        max_score = d.get("max_score", 0)
        st.markdown(
            f'<div class="stCard" style="padding:0.5rem 0.8rem;margin:0.4rem 0;">'
            f'<b>第{qid}题</b>（{_TYPE_LABEL.get(d.get("type"), "题目")}）· '
            f'{score}/{max_score} 分'
            + (' · ✅ 正确' if d.get("correct") else '')
            + '</div>',
            unsafe_allow_html=True,
        )
        strengths = d.get("strengths") or []
        missing = d.get("missing") or []
        refs = d.get("source_refs") or []
        if strengths:
            st.markdown(f'<div style="font-size:0.82rem;color:#2f9e44;">✅ 优点：{_esc("；".join(strengths))}</div>',
                        unsafe_allow_html=True)
        if missing:
            st.markdown(f'<div style="font-size:0.82rem;color:#e03131;">❌ 缺失/不足：{_esc("；".join(missing))}</div>',
                        unsafe_allow_html=True)
        if d.get("error"):
            st.markdown(f'<div style="font-size:0.8rem;color:#e8930c;">⚠️ {_esc(d["error"])}</div>',
                        unsafe_allow_html=True)
        if refs:
            st.markdown(f'<div style="font-size:0.8rem;color:#7c3aed;margin-top:0.2rem;">'
                        f'📖 课件原文溯源：{_esc("；".join(refs[:3]))}</div>', unsafe_allow_html=True)


def _answer_block() -> None:
    """学生在线答题（read 亦可）：选择已发布试卷 → 作答 → 提交 → 查看批改结果"""
    papers = _list_ready_papers()
    if not papers:
        empty_state("✍️", "暂无可作答的试卷", "等待教师生成并发布试卷后即可在线作答")
        return

    options = {f'{p.get("title") or "试卷"} (ID {p.get("id")})': p for p in papers}
    chosen = st.selectbox("选择要作答的试卷", list(options.keys()))
    paper = options[chosen]

    try:
        detail = api.get(f"/api/v1/exam/papers/{paper['id']}")
    except ApiError as e:
        st.error(e.message)
        return
    questions = detail.get("questions") or []
    if not questions:
        st.info("该试卷暂无题目")
        return

    st.markdown(f'<div style="font-weight:600;margin:0.5rem 0;">📋 {_esc(paper.get("title"))} · '
                f'总分 {paper.get("total_score", 0)}</div>', unsafe_allow_html=True)
    qmap = {q.get("qid"): q for q in questions}

    with st.form("answer_submit_form", clear_on_submit=False):
        answers = {}
        for q in questions:
            qid = q.get("qid")
            qtype = q.get("type")
            score = q.get("score", 0)
            st.markdown(
                f'<div style="margin-top:0.7rem;"><b>第{qid}题</b>'
                f'（{_TYPE_LABEL.get(qtype, qtype)}，{score} 分）</div>',
                unsafe_allow_html=True,
            )
            st.markdown(q.get("stem", ""))
            opts = q.get("options") or []
            if qtype == "choice" and opts:
                answers[qid] = st.radio("", opts, key=f"ans_c_{qid}", label_visibility="collapsed")
            elif qtype == "fill":
                answers[qid] = st.text_input("", key=f"ans_f_{qid}", placeholder="填写答案")
            else:
                answers[qid] = st.text_area("", key=f"ans_s_{qid}", height=120, placeholder="简答题作答…")
        submitted = st.form_submit_button("提交答卷", type="primary", use_container_width=True)

    if not submitted:
        return

    payload_answers = []
    for qid, val in answers.items():
        q = qmap.get(qid)
        if not q:
            continue
        v = val
        if q.get("type") == "choice":
            v = (str(val or "")[:1]).upper()
        payload_answers.append({"qid": qid, "answer": v})

    try:
        with st.spinner("正在提交答卷…"):
            data = api.post(f"/api/v1/exam/papers/{paper['id']}/submit", json={"answers": payload_answers})
    except ApiError as e:
        notify_error(e.message)
        return
    answer_id = data.get("answer_id")
    status = data.get("status")
    notify_success(f"答卷已提交（ID {answer_id}），客观题得分 {data.get('objective_score', 0)}")

    if status == "graded":
        st.rerun()

    # 主观题后台批改中：轮询
    status_bar = st.progress(0, text="主观题溯源批改中（RAG 检索课件 + 判分）…")
    deadline = time.time() + max(config.POLL_MAX_WAIT_SECONDS, 300)
    while time.time() < deadline:
        try:
            sheet = api.get(f"/api/v1/exam/answers/{answer_id}")
        except ApiError:
            time.sleep(config.POLL_INTERVAL_SECONDS)
            continue
        s = sheet.get("status")
        status_bar.progress(0.6, text=f"批改状态：{_SHEET_STATUS_LABEL.get(s, s)}")
        if s in ("graded", "failed"):
            status_bar.empty()
            if s == "graded":
                notify_success(f"批改完成，总分 {sheet.get('total_score', 0)}")
            else:
                notify_error(f"批改失败：{sheet.get('error_message') or '未知错误'}")
            st.rerun()
            break
        time.sleep(config.POLL_INTERVAL_SECONDS)
    else:
        status_bar.empty()
        notify_error("批改耗时较长，已提交后台，请稍后刷新查看")


def _grading_view() -> None:
    """教师（write+）查看全班答卷 + 单份批改详情（溯源引用）"""
    try:
        papers = api.get("/api/v1/exam/papers", params={"page_size": 100})["items"]
    except ApiError as e:
        st.warning(e.message)
        return
    ready = [p for p in papers if p.get("status") == "ready"]
    if not ready:
        empty_state("📊", "暂无已就绪的试卷")
        return

    options = {f'{p.get("title") or "试卷"} (ID {p.get("id")})': p for p in ready}
    chosen = st.selectbox("选择要查看的试卷", list(options.keys()), key="grade_paper_sel")
    paper = options[chosen]

    try:
        data = api.get(f"/api/v1/exam/papers/{paper['id']}/answers", params={"page_size": 100})
        sheets = data["items"]
    except ApiError as e:
        st.warning(e.message)
        return

    if not sheets:
        st.info("暂无学生提交答卷")
        return

    st.markdown(f'<div style="font-weight:600;margin:0.5rem 0;">共 {len(sheets)} 份答卷</div>',
                unsafe_allow_html=True)
    for s in sheets:
        status = s.get("status")
        status_label = _SHEET_STATUS_LABEL.get(status, status)
        with st.expander(f'{s.get("student_name") or "学生"} · 总分 {s.get("total_score", 0)} · {status_label}'):
            try:
                detail = api.get(f"/api/v1/exam/answers/{s['id']}")
                _render_grading_detail(detail)
            except ApiError as e:
                st.warning(e.message)


def render() -> None:
    styles.hero("📝 试卷中心", "双 Agent 智能命题 · 在线答题 · 课件溯源批改")

    tab_manage, tab_answer, tab_grade = st.tabs(["📝 试卷管理", "✍️ 在线答题", "📊 批改与成绩"])
    with tab_manage:
        _generate_block()
        st.markdown("---")
        _paper_history()
    with tab_answer:
        _answer_block()
    with tab_grade:
        _grading_view()
