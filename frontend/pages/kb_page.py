"""
知识库管理页面

功能：知识库列表卡片展示、创建、删除、成员权限管理。
权限：owner 可删除，admin+ 可管理成员，越权由后端拦截并友好提示。
无知识库时：醒目引导卡片 + 一键创建。
"""
from __future__ import annotations

import html

import streamlit as st

from frontend import styles
from frontend.api_client import api, ApiError
from frontend.components import role_badge, pill, notify_success, notify_error, empty_guide


def _esc(s) -> str:
    return html.escape(str(s))


def _create_kb() -> None:
    with st.form("kb_create_form", clear_on_submit=True):
        st.markdown('<div style="font-weight:600;margin-bottom:0.5rem;">新建课程库</div>', unsafe_allow_html=True)
        name = st.text_input("课程名称", placeholder="如：数据结构")
        description = st.text_input("课程描述（可选）")
        tags_input = st.text_input("课程标签（可选，逗号分隔）", placeholder="如：算法,图论")
        submitted = st.form_submit_button("创建", type="primary")

    if submitted:
        if not name:
            notify_error("请输入课程库名称")
            return
        tags = [t.strip() for t in tags_input.replace("，", ",").split(",") if t.strip()] or None
        try:
            api.post("/api/v1/kb", json={"name": name, "description": description or None, "tags": tags})
            notify_success("课程库创建成功")
            st.session_state.pop("kb_show_create", None)
            st.rerun()
        except ApiError as e:
            notify_error(e.message)


def _member_manage(kb: dict) -> None:
    """成员管理面板（admin+）"""
    kb_id = kb["id"]
    st.markdown('<div style="font-weight:600;margin:0.6rem 0 0.4rem 0;">成员管理</div>', unsafe_allow_html=True)
    try:
        members = api.get(f"/api/v1/kb/{kb_id}/members")["items"]
    except ApiError as e:
        st.warning(e.message)
        return

    for m in members:
        u = m.get("user") or {}
        uname = u.get("username") or f"用户{m['user_id']}"
        nick = u.get("nickname") or uname
        c1, c2, c3 = st.columns([2, 1, 1])
        c1.markdown(f'<div style="padding-top:0.5rem;font-weight:500;">{_esc(nick)}</div>', unsafe_allow_html=True)
        c2.markdown(role_badge(m["role"]), unsafe_allow_html=True)
        if m["role"] != "owner":
            if c3.button("移除", key=f"rm_{m['user_id']}", use_container_width=True):
                try:
                    api.delete(f"/api/v1/kb/{kb_id}/members/{m['user_id']}")
                    notify_success("成员已移除")
                    st.rerun()
                except ApiError as e:
                    notify_error(e.message)
        else:
            c3.markdown('<div style="color:#666666;padding-top:0.5rem;font-size:0.8rem;">—</div>', unsafe_allow_html=True)

    st.markdown('<div style="font-weight:600;margin-top:0.6rem;">添加成员</div>', unsafe_allow_html=True)
    with st.form(f"kb_add_member_{kb_id}", clear_on_submit=True):
        cc1, cc2, cc3 = st.columns([2, 1, 1])
        user_id = cc1.text_input("用户ID", key=f"uid_{kb_id}")
        role = cc2.selectbox("角色", ["read", "write", "admin"],
                             format_func=lambda r: {"read": "只读", "write": "编辑", "admin": "管理员"}[r],
                             key=f"role_{kb_id}")
        sub = cc3.form_submit_button("添加", use_container_width=True)
    if sub:
        if not user_id:
            notify_error("请输入用户ID")
            return
        try:
            api.post(f"/api/v1/kb/{kb_id}/members", json={"user_id": int(user_id), "role": role})
            notify_success("成员已添加")
            st.rerun()
        except (ApiError, ValueError) as e:
            notify_error(str(e))


def _render_kb_cards(kbs: list) -> None:
    """课程库卡片栅格展示"""
    cols = st.columns(2, gap="medium")
    for i, kb in enumerate(kbs):
        with cols[i % 2]:
            role = kb.get("user_role") or "read"
            tags = kb.get("tags") or []
            tags_html = "".join(
                f'<span style="display:inline-block;background:#f1f3f7;color:#555a63;'
                f'border-radius:10px;padding:0.1rem 0.6rem;font-size:0.72rem;margin-right:0.3rem;">'
                f'{_esc(t)}</span>'
                for t in tags
            )
            st.markdown(
                '<div class="stCard" style="margin-bottom:0.9rem;">'
                f'<div style="display:flex;align-items:flex-start;justify-content:space-between;">'
                f'<div style="font-size:1.05rem;font-weight:700;color:#111111;">{_esc(kb.get("name"))}</div>'
                f'{role_badge(role)}'
                f'</div>'
                f'<div style="font-size:0.82rem;color:#555a63;margin:0.4rem 0 0.4rem 0;min-height:2rem;">'
                f'{_esc(kb.get("description") or "暂无描述")}</div>'
                f'<div style="margin-bottom:0.8rem;min-height:1.2rem;">{tags_html}</div>'
                f'<div style="display:flex;gap:1.2rem;font-size:0.78rem;color:#666666;">'
                f'<span>📄 {kb.get("doc_count", 0)} 文档</span>'
                f'<span>🧩 {kb.get("chunk_count", 0)} 分块</span>'
                f'<span>{pill(kb.get("status", "active"), "#3b5bdb", "#e9edfc")}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def render() -> None:
    styles.hero("📚 课程库管理", "创建、管理你的课程库（上传课件、生成试卷）与成员权限")

    try:
        data = api.get("/api/v1/kb", params={"page_size": 100})
        kbs = data["items"]
    except ApiError as e:
        st.error(e.message)
        return

    # 无课程库：醒目引导 + 创建表单
    if not kbs:
        if not st.session_state.get("kb_show_create", False):
            if empty_guide(
                "📚", "还没有课程库",
                "创建课程库后，即可上传课件、进行智能问答、生成试卷",
                "＋ 新建第一个课程库", key="kb_empty_create",
            ):
                st.session_state["kb_show_create"] = True
                st.rerun()
            return
        st.markdown("---")
        st.markdown('<div class="section-title" style="font-size:1.1rem;">🏗️ 新建课程库</div>',
                    unsafe_allow_html=True)
        _create_kb()
        return

    # 有课程库：左侧卡片列表 + 右侧新建
    head_l, head_r = st.columns([3, 1])
    with head_l:
        _render_kb_cards(kbs)
    with head_r:
        with st.container(border=True):
            _create_kb()

    # 选中课程库 → 详情 + 成员管理
    st.markdown("---")
    st.markdown('<div class="section-title" style="font-size:1.1rem;">🔧 课程库详情与成员</div>',
                unsafe_allow_html=True)
    options = {f'{kb["name"]} (ID {kb["id"]})': kb for kb in kbs}
    chosen = st.selectbox("选择课程库", list(options.keys()))
    kb = options[chosen]
    role = kb.get("user_role") or "read"

    c1, c2 = st.columns(2)
    with c1:
        tags = kb.get("tags") or []
        tags_text = "、".join(tags) if tags else "无"
        st.markdown(
            f'<div class="stCard"><div style="font-weight:700;">{_esc(kb["name"])}</div>'
            f'<div style="color:#555a63;font-size:0.85rem;margin-top:0.3rem;">{_esc(kb.get("description") or "暂无描述")}</div>'
            f'<div style="color:#555a63;font-size:0.8rem;margin-top:0.3rem;">标签：{_esc(tags_text)}</div>'
            f'<div style="margin-top:0.6rem;">{role_badge(role)}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        if role in ("owner", "admin"):
            _member_manage(kb)
        else:
            st.info("你当前为只读成员，无成员管理权限")

    # 危险操作：删除（owner）
    if role == "owner":
        st.markdown("---")
        with st.expander("⚠️ 删除课程库（不可恢复）"):
            if st.button("确认删除该课程库", type="primary"):
                try:
                    api.delete(f"/api/v1/kb/{kb['id']}")
                    notify_success("课程库已删除")
                    st.rerun()
                except ApiError as e:
                    notify_error(e.message)
