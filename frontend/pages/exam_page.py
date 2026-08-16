"""
试卷页面（课程试卷智能命题校验批改系统）

功能：
- 教师（owner/admin/write）发起试卷生成（双 Agent 出卷，后台异步 + 进度轮询）
- 历史试卷列表 + 详情（题目 / 参考答案 / 双 Agent 完整执行轨迹 / 知识点标签云与雷达图）
- 编辑模式（owner/admin）：单题重出、编辑题目、删除题目、新增自定义试题，实时写入数据库
- 批改详情：客观题错误解析 + 溯源，主观题四维度分项打分 + 分项点评 + 各维度溯源
- 导出 Markdown（含/不含答案）
权限：read 学生隐藏「生成试卷」，且详情不返回参考答案。
"""
from __future__ import annotations

import html
import math
import time
from collections import Counter

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


# ============================================================
# 知识点分布可视化（标签云 + 雷达图，纯 HTML/SVG，零额外依赖）
# ============================================================

_PALETTE = ["#7c3aed", "#3b5bdb", "#0f9d8f", "#e8590c", "#c2255c", "#2f9e44", "#e8930c", "#5b6472"]


def _knowledge_stats(questions) -> list:
    """统计试卷知识点分布 [(知识点, 出现次数)]，按次数降序"""
    c = Counter(
        (str(q.get("knowledge_point") or "未标注").strip() or "未标注")
        for q in (questions or [])
    )
    return c.most_common()


def _tag_cloud_html(stats: list) -> str:
    """知识点标签云：HTML 圆角胶囊，字号与颜色随出现次数变化"""
    if not stats:
        return ""
    max_c = max(c for _, c in stats) or 1
    spans = []
    for i, (kp, cnt) in enumerate(stats):
        size = 0.95 + 1.15 * (cnt / max_c)
        color = _PALETTE[i % len(_PALETTE)]
        spans.append(
            f'<span style="display:inline-block;font-size:{size:.2f}rem;color:{color};'
            f'font-weight:600;padding:0.2rem 0.55rem;margin:0.2rem 0.25rem;'
            f'background:{color}1a;border-radius:999px;white-space:nowrap;">'
            f'{_esc(kp)} <span style="opacity:0.65;font-size:0.78em;">×{cnt}</span></span>'
        )
    return f'<div style="line-height:2;">{"".join(spans)}</div>'


def _radar_svg(labels: list, values: list) -> str:
    """知识点覆盖率雷达图（SVG 多边形）：需 ≥3 个维度，值按最大项归一化"""
    n = len(labels)
    if n < 3:
        return ""
    cx, cy, R = 200, 200, 150
    max_v = max(values) or 1

    def pt(i, r):
        ang = math.radians(-90 + i * 360.0 / n)
        return (cx + r * math.cos(ang), cy + r * math.sin(ang))

    rings = "".join(
        f'<polygon points="{" ".join(f"{pt(i, R*frac)[0]:.1f},{pt(i, R*frac)[1]:.1f}" for i in range(n))}" '
        f'fill="none" stroke="#e5e7eb" stroke-width="1"/>'
        for frac in (0.25, 0.5, 0.75, 1.0)
    )
    axes = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{pt(i, R)[0]:.1f}" y2="{pt(i, R)[1]:.1f}" '
        f'stroke="#e5e7eb" stroke-width="1"/>'
        for i in range(n)
    )
    poly_pts = " ".join(
        f"{pt(i, R * values[i] / max_v)[0]:.1f},{pt(i, R * values[i] / max_v)[1]:.1f}"
        for i in range(n)
    )
    dots = "".join(
        f'<circle cx="{pt(i, R * values[i] / max_v)[0]:.1f}" cy="{pt(i, R * values[i] / max_v)[1]:.1f}" '
        f'r="3" fill="#3b5bdb"/>'
        for i in range(n)
    )
    label_txt = ""
    for i, lab in enumerate(labels):
        x, y = pt(i, R + 34)
        anchor, tx = "middle", x
        if x < cx - R * 0.6:
            anchor, tx = "end", x - 6
        elif x > cx + R * 0.6:
            anchor, tx = "start", x + 6
        label_txt += (
            f'<text x="{tx:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="12" fill="#333">'
            f'{_esc(lab)}</text>'
        )
    return (
        f'<svg viewBox="0 0 400 430" width="100%" style="max-width:430px;" '
        f'xmlns="http://www.w3.org/2000/svg">{rings}{axes}'
        f'<polygon points="{poly_pts}" fill="#3b5bdb33" stroke="#3b5bdb" stroke-width="2"/>'
        f'{dots}{label_txt}</svg>'
    )


def _render_knowledge_vis(questions) -> None:
    """试卷详情页知识点可视化：标签云 + 覆盖率雷达图"""
    stats = _knowledge_stats(questions)
    if not stats:
        return
    st.markdown('<div style="font-weight:600;margin:0.5rem 0 0.2rem 0;">🏷 知识点分布</div>',
                unsafe_allow_html=True)
    c1, c2 = st.columns([1.15, 1])
    with c1:
        st.caption("标签云（字号 = 出现次数）")
        st.markdown(_tag_cloud_html(stats), unsafe_allow_html=True)
    with c2:
        labels = [kp for kp, _ in stats[:6]]
        values = [c for _, c in stats[:6]]
        if len(stats) > 6:
            labels.append("其他")
            values.append(sum(c for _, c in stats[6:]))
        radar = _radar_svg(labels, values)
        st.caption("覆盖率雷达图（各知识点题量分布）")
        if radar:
            st.markdown(radar, unsafe_allow_html=True)
        else:
            st.info("知识点≥3 个时展示雷达图")


# ============================================================
# 试卷编辑（单题重出 / 增删改）
# ============================================================

def _save_paper(paper_id: int, questions: list) -> None:
    """复用现有 ExamPaperUpdate 接口：整卷题目 + 参考答案实时落库"""
    payload = {
        "questions": questions,
        "reference_answers": [
            {"qid": q.get("qid"), "answer": q.get("answer"),
             "knowledge_point": q.get("knowledge_point")}
            for q in questions
        ],
    }
    api.put(f"/api/v1/exam/papers/{paper_id}", json=payload)


def _render_editor(paper_id: int, detail: dict) -> None:
    """试卷编辑模式：每道题支持单题重出 / 编辑 / 删除，底部可新增自定义试题"""
    questions = detail.get("questions") or []
    st.markdown("---")
    st.markdown('<div style="font-weight:600;color:#3b5bdb;">✏️ 编辑模式</div>', unsafe_allow_html=True)
    st.caption("单题重出 / 编辑 / 删除 / 新增均实时写入数据库，并自动刷新上方知识点标签云与雷达图。")

    for q in questions:
        qid = q.get("qid")
        row = st.columns([3, 1, 1, 1])
        with row[0]:
            st.markdown(f"**第{qid}题** · {_TYPE_LABEL.get(q.get('type'), q.get('type'))}"
                        f" · {q.get('score', 0)} 分")
        with row[1]:
            b_reg = st.button("🔁 重出", key=f"reg_{paper_id}_{qid}", use_container_width=True)
        with row[2]:
            b_edit = st.button("✏️ 编辑", key=f"edit_{paper_id}_{qid}", use_container_width=True)
        with row[3]:
            b_del = st.button("🗑 删除", key=f"del_{paper_id}_{qid}", use_container_width=True)

        if b_reg:
            with st.spinner(f"命题 Agent 正在重出第 {qid} 题…"):
                try:
                    detail2 = api.post(f"/api/v1/exam/papers/{paper_id}/regenerate/{qid}")
                    if detail2.get("warning"):
                        notify_error(detail2["warning"])
                    else:
                        notify_success(f"第 {qid} 题已重出")
                except ApiError as e:
                    notify_error(e.message)
            st.rerun()
        if b_del:
            new_q = [x for x in questions if x.get("qid") != qid]
            try:
                _save_paper(paper_id, new_q)
                notify_success("题目已删除")
            except ApiError as e:
                notify_error(e.message)
            st.rerun()
        if b_edit:
            st.session_state[f"exam_editing_{paper_id}_{qid}"] = True

        # 编辑表单
        if st.session_state.get(f"exam_editing_{paper_id}_{qid}"):
            with st.form(f"edit_form_{paper_id}_{qid}", border=True):
                stem = st.text_area("题干", value=q.get("stem", ""), key=f"es_{paper_id}_{qid}")
                if q.get("type") == "choice":
                    opts = (q.get("options") or []) + [""] * (4 - len(q.get("options") or []))
                    ca, cb = st.columns(2)
                    cc, cd = st.columns(2)
                    opt_a = ca.text_input("选项 A", value=opts[0], key=f"eo1_{paper_id}_{qid}")
                    opt_b = cb.text_input("选项 B", value=opts[1], key=f"eo2_{paper_id}_{qid}")
                    opt_c = cc.text_input("选项 C", value=opts[2], key=f"eo3_{paper_id}_{qid}")
                    opt_d = cd.text_input("选项 D", value=opts[3], key=f"eo4_{paper_id}_{qid}")
                else:
                    opt_a = opt_b = opt_c = opt_d = ""
                answer = st.text_input("参考答案", value=q.get("answer", ""), key=f"ea_{paper_id}_{qid}")
                kp = st.text_input("知识点", value=q.get("knowledge_point", ""), key=f"ek_{paper_id}_{qid}")
                score = st.number_input("分值", 1, 100, int(q.get("score") or 5), key=f"esc_{paper_id}_{qid}")
                fc = st.columns([1, 1, 6])
                saved = fc[0].form_submit_button("保存")
                cancelled = fc[1].form_submit_button("取消")
                if cancelled:
                    st.session_state.pop(f"exam_editing_{paper_id}_{qid}", None)
                    st.rerun()
                if saved:
                    updated = dict(q)
                    updated["stem"] = stem.strip()
                    updated["answer"] = answer.strip()
                    updated["knowledge_point"] = kp.strip()
                    updated["score"] = int(score)
                    if q.get("type") == "choice":
                        updated["options"] = [o for o in (opt_a, opt_b, opt_c, opt_d) if o.strip()]
                    new_q = [updated if x.get("qid") == qid else x for x in questions]
                    try:
                        _save_paper(paper_id, new_q)
                        notify_success("题目已更新")
                    except ApiError as e:
                        notify_error(e.message)
                    st.session_state.pop(f"exam_editing_{paper_id}_{qid}", None)
                    st.rerun()

    # 新增自定义试题
    with st.expander("➕ 新增自定义试题", expanded=False):
        with st.form(f"add_form_{paper_id}"):
            qtype = st.selectbox(
                "题型", ["choice", "fill", "short"],
                format_func=lambda t: _TYPE_LABEL.get(t, t), key=f"at_{paper_id}",
            )
            stem = st.text_area("题干", key=f"ast_{paper_id}")
            if qtype == "choice":
                ca, cb = st.columns(2)
                cc, cd = st.columns(2)
                opt_a = ca.text_input("选项 A", key=f"ao1_{paper_id}")
                opt_b = cb.text_input("选项 B", key=f"ao2_{paper_id}")
                opt_c = cc.text_input("选项 C", key=f"ao3_{paper_id}")
                opt_d = cd.text_input("选项 D", key=f"ao4_{paper_id}")
            else:
                opt_a = opt_b = opt_c = opt_d = ""
            answer = st.text_input("参考答案", key=f"aans_{paper_id}")
            kp = st.text_input("知识点", key=f"akp_{paper_id}")
            score = st.number_input("分值", 1, 100, 5, key=f"asc_{paper_id}")
            add_clicked = st.form_submit_button("添加题目", type="primary")
        if add_clicked:
            new_q = {"type": qtype, "stem": stem.strip(), "answer": answer.strip(),
                     "knowledge_point": kp.strip(), "score": int(score), "source_refs": []}
            if qtype == "choice":
                new_q["options"] = [o for o in (opt_a, opt_b, opt_c, opt_d) if o.strip()]
            if not new_q["stem"]:
                notify_error("题干不能为空")
            elif qtype == "choice" and len(new_q.get("options", [])) < 2:
                notify_error("选择题至少需要两个选项")
            else:
                try:
                    _save_paper(paper_id, questions + [new_q])
                    notify_success("题目已添加")
                except ApiError as e:
                    notify_error(e.message)
                st.rerun()


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

    # 课程库角色映射（决定是否展示编辑入口：owner/admin 可编辑）
    role_map = {}
    try:
        role_map = {kb["id"]: kb.get("user_role") for kb in api.get("/api/v1/kb", params={"page_size": 100})["items"]}
    except ApiError:
        pass

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

            # 详情（知识点可视化 + 题目 + 轨迹）
            try:
                detail = api.get(f"/api/v1/exam/papers/{p['id']}")
            except ApiError:
                detail = None
            if detail:
                _render_knowledge_vis(detail.get("questions"))
                _render_questions(detail)
                _render_trace(detail.get("trace"))

                # 编辑模式（owner/admin，且试卷就绪）
                can_edit = (role_map.get(p.get("knowledge_base_id")) in ("owner", "admin"))
                if can_edit and status == "ready":
                    edit_on = st.toggle("✏️ 编辑模式", key=f"edit_mode_{p['id']}")
                    if edit_on:
                        _render_editor(p["id"], detail)


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

        # 主观题：四维度分项打分（得分 / 点评 / 各维度溯源）
        dims = d.get("dimensions") or []
        if dims:
            st.markdown('<div style="font-size:0.84rem;color:#3b5bdb;font-weight:600;margin-top:0.3rem;">'
                        '📐 四维度分项打分</div>', unsafe_allow_html=True)
            for dim in dims:
                label = dim.get("label") or dim.get("key")
                ds = dim.get("score", 0)
                dm = dim.get("max_score", 0)
                st.markdown(
                    f'<div style="font-size:0.82rem;margin:0.2rem 0 0 0.5rem;">'
                    f'<b>{_esc(label)}</b>：{ds}/{dm} 分</div>',
                    unsafe_allow_html=True,
                )
                if dim.get("comment"):
                    st.markdown(
                        f'<div style="font-size:0.8rem;color:#444;margin-left:1rem;">{_esc(dim["comment"])}</div>',
                        unsafe_allow_html=True,
                    )
                for r in (dim.get("source_refs") or [])[:2]:
                    st.markdown(
                        f'<div style="font-size:0.76rem;color:#7c3aed;margin-left:1rem;">📖 {_esc(r)}</div>',
                        unsafe_allow_html=True,
                    )

        # 客观题答错：错误解析 + 考察知识点（溯源片段见下方「课件原文溯源」）
        if d.get("analysis"):
            st.markdown(
                f'<div style="font-size:0.84rem;color:#e03131;margin-top:0.3rem;">'
                f'❌ 错误解析：{_esc(d["analysis"])}</div>',
                unsafe_allow_html=True,
            )
        if d.get("knowledge_point") and d.get("objective_explain"):
            st.markdown(
                f'<div style="font-size:0.8rem;color:#555a63;margin-top:0.15rem;">'
                f'🎯 本题考察知识点：{_esc(d["knowledge_point"])}</div>',
                unsafe_allow_html=True,
            )
        if d.get("analysis_error"):
            st.markdown(
                f'<div style="font-size:0.8rem;color:#e8930c;">⚠️ 错误解析生成失败：{_esc(d["analysis_error"])}</div>',
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
