"""
审计日志查看页面

功能：分页查询、操作类型筛选、结果筛选、资源类型筛选、表格美化。
只做只读查询，写入由后端 service 层统一完成。
"""
from __future__ import annotations

import html

import streamlit as st

from frontend import styles
from frontend.api_client import api, ApiError
from frontend.components import result_badge, empty_state


ACTION_LABELS = {
    "login": "登录", "logout": "登出", "register": "注册", "token_refresh": "令牌刷新",
    "kb_create": "创建知识库", "kb_update": "更新知识库", "kb_delete": "删除知识库",
    "kb_member_add": "添加成员", "kb_member_remove": "移除成员", "kb_member_update": "更新成员",
    "doc_upload": "上传文档", "doc_delete": "删除文档", "doc_update": "更新文档", "doc_rebuild": "重建索引",
    "chat_question": "问答", "agent_task_create": "Agent任务创建", "agent_task_complete": "Agent任务完成",
    "user_create": "创建用户", "user_update": "更新用户", "user_delete": "删除用户",
}


def _esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def _fmt_time(s) -> str:
    if not s:
        return "—"
    return str(s).replace("T", " ")[:19]


def render() -> None:
    styles.hero("📊 审计日志", "查看系统关键操作记录，只读查询")

    # 筛选区
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    with c1:
        action = st.selectbox("操作类型", ["全部"] + list(ACTION_LABELS.keys()),
                              format_func=lambda a: "全部" if a == "全部" else ACTION_LABELS.get(a, a))
    with c2:
        result = st.selectbox("结果", ["全部", "success", "failed", "permission_denied"],
                              format_func=lambda r: {"全部": "全部", "success": "成功", "failed": "失败", "permission_denied": "越权拒绝"}[r])
    with c3:
        resource_type = st.selectbox("资源类型", ["全部", "user", "kb", "doc", "conv", "agent_task"])
    with c4:
        page = st.number_input("页码", min_value=1, value=1, step=1)

    params = {"page": page, "page_size": 20}
    if action != "全部":
        params["action"] = action
    if result != "全部":
        params["result"] = result
    if resource_type != "全部":
        params["resource_type"] = resource_type

    try:
        with st.spinner("正在加载审计日志…"):
            data = api.get("/api/v1/audit/logs", params=params)
        items = data["items"]
        total = data["total"]
        total_pages = data["total_pages"]
    except ApiError as e:
        st.error(e.message)
        return

    st.markdown(
        f'<div style="color:#555a63;font-size:0.85rem;margin-bottom:0.6rem;">'
        f'共 <b>{total}</b> 条记录 · 第 {page}/{max(total_pages, 1)} 页</div>',
        unsafe_allow_html=True,
    )

    if not items:
        empty_state("📊", "暂无审计日志，系统关键操作记录将在此展示")
        return

    header = (
        '<tr style="background:#f4f6fb;color:#555a63;">'
        '<th style="padding:0.6rem;text-align:left;">时间</th>'
        '<th style="text-align:left;">用户</th>'
        '<th style="text-align:left;">操作</th>'
        '<th style="text-align:left;">结果</th>'
        '<th style="text-align:left;">资源</th>'
        '<th style="text-align:left;">详情</th></tr>'
    )
    rows = []
    for log in items:
        detail = log.get("details")
        detail_str = str(detail)[:60] if detail else "—"
        rows.append(
            f'<tr style="border-top:1px solid #eef1f6;">'
            f'<td style="padding:0.6rem;font-size:0.82rem;color:#555a63;">{_fmt_time(log.get("created_at"))}</td>'
            f'<td style="font-size:0.85rem;">{_esc(log.get("user_id"))}</td>'
            f'<td style="font-size:0.85rem;">{_esc(ACTION_LABELS.get(log.get("action"), log.get("action")))}</td>'
            f'<td>{result_badge(log.get("result"))}</td>'
            f'<td style="font-size:0.85rem;">{_esc(log.get("resource_type"))}/{_esc(log.get("resource_id"))}</td>'
            f'<td style="font-size:0.8rem;color:#555a63;">{_esc(detail_str)}</td></tr>'
        )
    st.markdown(
        '<div style="overflow-x:auto;background:#ffffff;border:1px solid #c8cdd5;border-radius:12px;">'
        '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
        f'<thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )
