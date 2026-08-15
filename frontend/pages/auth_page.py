"""
登录 / 注册页面（未登录态）

- 全屏渐变深色背景（页面背景 ≠ 卡片背景）
- 居中独立大卡片（白色 #ffffff + 阴影 + 圆角）
- 登录 / 注册双标签页，输入框边框、背景、文字清晰可见
- 登录成功后默认跳转【知识库管理】页面
"""
from __future__ import annotations

import streamlit as st

from frontend.api_client import api, ApiError
from frontend.auth import set_auth
from frontend.components import notify_success, notify_error

# 登录页专属背景：全屏渐变深色
_AUTH_PAGE_CSS = """
<style>
.stApp {
    background: linear-gradient(135deg, #1d2745 0%, #2c3d6e 45%, #3b5bdb 100%) !important;
}
.block-container { max-width: 720px !important; }
</style>
"""


def _brand_block() -> None:
    st.markdown(
        '<div style="display:flex;align-items:center;justify-content:center;gap:0.7rem;margin-bottom:0.4rem;">'
        '<div class="sidebar-logo">企</div>'
        '<div style="font-size:1.4rem;font-weight:700;color:#111111;">企业私有知识库智能助手</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="text-align:center;font-size:0.84rem;color:#666666;margin-bottom:1.4rem;">'
        '企业级 · 私有化 · RAG 检索增强生成平台</div>',
        unsafe_allow_html=True,
    )


def _login_tab() -> None:
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登 录", type="primary", use_container_width=True)

    if submitted:
        if not username or not password:
            notify_error("请输入用户名和密码")
            return
        try:
            data = api.post("/api/v1/auth/login", json={"username": username, "password": password}, auth=False)
            set_auth(data["access_token"], data["refresh_token"], data["user"])
            notify_success(f"欢迎回来，{data['user'].get('nickname') or data['user']['username']}")
            # 登录成功后默认进入【知识库管理】页面（而非问答页）
            st.session_state["nav_page"] = "kb"
            st.rerun()
        except ApiError as e:
            notify_error(e.message)


def _register_tab() -> None:
    with st.form("register_form", clear_on_submit=False):
        username = st.text_input("用户名", placeholder="3-64 位字母/数字/下划线")
        nickname = st.text_input("昵称（可选）")
        email = st.text_input("邮箱（可选）")
        password = st.text_input("密码", type="password", placeholder="至少 6 位")
        password2 = st.text_input("确认密码", type="password", placeholder="请再次输入密码")
        submitted = st.form_submit_button("注 册", type="primary", use_container_width=True)

    if submitted:
        if not username or not password:
            notify_error("请输入用户名和密码")
            return
        if password != password2:
            notify_error("两次输入的密码不一致")
            return
        try:
            payload = {"username": username, "password": password}
            if nickname:
                payload["nickname"] = nickname
            if email:
                payload["email"] = email
            api.post("/api/v1/auth/register", json=payload, auth=False)
            notify_success("注册成功，请登录")
        except ApiError as e:
            notify_error(e.message)


def render() -> None:
    """渲染登录 / 注册页（全屏深色背景 + 居中白色大卡片）"""
    st.markdown(_AUTH_PAGE_CSS, unsafe_allow_html=True)
    st.markdown('<div style="height:3vh"></div>', unsafe_allow_html=True)

    left, center, right = st.columns([1, 1.6, 1])
    with center:
        with st.container(border=True):
            _brand_block()
            tab_login, tab_register = st.tabs(["登 录", "注 册"])
            with tab_login:
                _login_tab()
            with tab_register:
                _register_tab()
