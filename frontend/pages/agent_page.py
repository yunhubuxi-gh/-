"""
Agent 智能任务页面

功能：任务提交、任务进度实时刷新、任务历史记录、执行轨迹（规划/执行日志/反思）展示。
前置条件：必须先有知识库；无知识库时给出引导。
"""
from __future__ import annotations

import html
import time

import streamlit as st

from frontend import styles, config
from frontend.api_client import api, ApiError
from frontend.components import agent_status_badge, notify_success, notify_error, empty_state, empty_guide, navigate


def _esc(s) -> str:
    return html.escape(str(s))


def _list_kb_options():
    try:
        return api.get("/api/v1/kb", params={"page_size": 100})["items"]
    except ApiError:
        return []


def _submit_block() -> None:
    kbs = _list_kb_options()
    if not kbs:
        if empty_guide("📚", "还没有知识库",
                       "创建知识库后，即可提交 Agent 智能任务",
                       "去创建知识库", key="agent_empty_kb"):
            navigate("kb")
        return

    with st.container(border=True):
        with st.form("agent_submit_form", clear_on_submit=True):
            kb_options = {f'{kb["name"]} (ID {kb["id"]})': kb for kb in kbs}
            chosen = st.selectbox("选择知识库", list(kb_options.keys()))
            kb_id = kb_options[chosen]["id"]
            title = st.text_input("任务标题（可选）", placeholder="如：总结请假流程")
            task_input = st.text_area("任务描述", placeholder="例如：查询知识库中关于请假的制度，并总结成要点", height=100)
            submitted = st.form_submit_button("提交 Agent 任务", type="primary", use_container_width=True)

        if submitted:
            if not task_input:
                notify_error("请输入任务描述")
                return
            try:
                with st.spinner("正在提交任务…"):
                    payload = {"knowledge_base_id": kb_id, "task_input": task_input}
                    if title:
                        payload["title"] = title
                    data = api.post("/api/v1/agent/tasks", json=payload)
                task_id = data["task_id"]
                notify_success(f"任务已提交：{task_id}")

                status_bar = st.progress(0, text="任务执行中…")
                deadline = time.time() + config.POLL_MAX_WAIT_SECONDS
                status_map = {"pending": 0.05, "planning": 0.25, "executing": 0.5,
                              "reflecting": 0.7, "success": 1.0, "failed": 1.0}
                while time.time() < deadline:
                    try:
                        task = api.get(f"/api/v1/agent/tasks/{task_id}")
                    except ApiError:
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue
                    s = task.get("status")
                    status_bar.progress(min(status_map.get(s, 0.05), 0.9), text=f"任务状态：{s}")
                    if s in ("success", "failed"):
                        if s == "success":
                            status_bar.progress(1.0, text="任务完成 ✅")
                        else:
                            status_bar.empty()
                            notify_error(f"任务失败：{task.get('error_message') or '未知错误'}")
                        break
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                else:
                    status_bar.empty()
                    notify_error("任务执行超时")
                st.rerun()
            except ApiError as e:
                notify_error(e.message)


def _render_trace(detail: dict) -> None:
    """执行轨迹展示：规划 → 执行步骤 → 反思记录"""
    if detail.get("plan"):
        st.markdown('<div style="font-weight:600;margin-top:0.5rem;">📋 任务规划</div>', unsafe_allow_html=True)
        for step in detail["plan"]:
            st.markdown(
                f'<div class="stCard" style="padding:0.5rem 0.8rem;margin:0.25rem 0;font-size:0.85rem;">'
                f'<b>步骤 {step.get("step")}</b> · 工具 {step.get("tool")} · '
                f'{_esc(step.get("description") or "")}</div>',
                unsafe_allow_html=True,
            )

    if detail.get("execution_log"):
        st.markdown('<div style="font-weight:600;margin-top:0.5rem;">⚙️ 执行日志</div>', unsafe_allow_html=True)
        for e in detail["execution_log"]:
            color = "#2f9e44" if e.get("status") == "success" else "#e03131"
            st.markdown(
                f'<div class="stCard" style="padding:0.5rem 0.8rem;margin:0.25rem 0;font-size:0.82rem;'
                f'border-left:3px solid {color};">'
                f'<b>{e.get("tool")}</b> · {e.get("status")} · {e.get("duration_ms", 0)}ms</div>',
                unsafe_allow_html=True,
            )

    if detail.get("reflection_log"):
        st.markdown('<div style="font-weight:600;margin-top:0.5rem;">🔁 反思记录</div>', unsafe_allow_html=True)
        for r in detail["reflection_log"]:
            st.markdown(
                f'<div class="stCard" style="padding:0.5rem 0.8rem;margin:0.25rem 0;font-size:0.82rem;">'
                f'第 {r.get("retry")} 次重试 · {_esc(r.get("issue") or "")} → {_esc(r.get("strategy") or "")}</div>',
                unsafe_allow_html=True,
            )


def _task_history() -> None:
    try:
        data = api.get("/api/v1/agent/tasks", params={"page_size": 100})
        tasks = data["items"]
    except ApiError as e:
        st.warning(e.message)
        return

    if not tasks:
        empty_state("🤖", "暂无任务记录，提交任务后将在此展示")
        return

    st.markdown('<div style="font-weight:600;margin:0.6rem 0 0.4rem 0;">任务历史</div>', unsafe_allow_html=True)
    for t in tasks:
        with st.expander(f'{t.get("title") or "任务"} · {agent_status_badge(t.get("status"))} · retry={t.get("retry_count", 0)}'):
            st.markdown(
                f'<div style="color:#555a63;font-size:0.85rem;margin-bottom:0.5rem;">'
                f'任务ID：{t.get("task_id")} · 耗时 {t.get("duration_ms", 0)}ms</div>',
                unsafe_allow_html=True,
            )
            if t.get("task_input"):
                st.markdown(f'<div style="font-size:0.9rem;"><b>任务描述：</b>{_esc(t["task_input"])}</div>', unsafe_allow_html=True)
            if t.get("result"):
                st.markdown('<div style="font-weight:600;margin-top:0.5rem;">执行结果</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="stCard" style="padding:0.8rem 1rem;margin:0.3rem 0;">{_esc(t["result"])}</div>',
                    unsafe_allow_html=True,
                )

            detail = None
            try:
                detail = api.get(f"/api/v1/agent/tasks/{t['task_id']}")
            except ApiError:
                pass
            if detail:
                _render_trace(detail)


def render() -> None:
    styles.hero("🤖 Agent 智能任务", "让 AI 智能体拆解任务、调用工具、反思重试")

    _submit_block()
    st.markdown("---")
    _task_history()
