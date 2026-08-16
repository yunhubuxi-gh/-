"""
登录 / 注册页面（未登录态）

- 清爽稳重的蓝灰教育风背景（浅色渐变）
- 居中独立白色卡片（圆角 + 阴影 + 留白，不铺满屏幕）
- 登录 / 注册双标签页，输入框边框、背景、文字清晰可见
- 登录成功后默认跳转【课程库】页面

说明：本页仅负责前端渲染展示；登录鉴权、session 状态、后端接口逻辑
（api.post / set_auth / nav_page / st.rerun）与原实现完全一致，未做任何改动。
"""
from __future__ import annotations

import streamlit as st

from frontend.api_client import api, ApiError
from frontend.auth import set_auth
from frontend.components import notify_success, notify_error

# 登录页专属背景：浅蓝灰渐变（教育风，清爽稳重，不花哨）
_AUTH_PAGE_CSS = """
<style>
.stApp {
    background: linear-gradient(160deg, #eef3fa 0%, #e6ecf7 45%, #dfe8f4 100%) !important;
}
.block-container { max-width: 640px !important; }

/* 登录卡片顶部品牌区 */
.auth-brand {
    text-align: center;
    margin-bottom: 0.4rem;
}
.auth-logo {
    width: 56px; height: 56px; border-radius: 16px;
    background: linear-gradient(135deg, #3b5bdb, #6b8afd);
    display: inline-flex; align-items: center; justify-content: center;
    color: #fff; font-size: 1.7rem; font-weight: 700;
    box-shadow: 0 8px 20px rgba(59, 91, 219, 0.30);
    margin-bottom: 0.9rem;
}
.auth-title {
    font-size: 1.45rem; font-weight: 700; color: #111111;
    letter-spacing: 0.01em; line-height: 1.35;
}
.auth-subtitle {
    font-size: 0.85rem; color: #555a63;
    margin-top: 0.5rem; line-height: 1.6;
}

/* 系统能力简介小字（卡片底部） */
.auth-intro {
    margin-top: 1.1rem; padding-top: 0.9rem;
    border-top: 1px dashed #c8cdd5;
    text-align: center;
}
.auth-intro-label {
    font-size: 0.76rem; color: #666666; margin-bottom: 0.55rem;
}
.auth-features {
    display: flex; flex-wrap: wrap; gap: 0.45rem; justify-content: center;
}
.auth-feature {
    display: inline-flex; align-items: center;
    padding: 0.28rem 0.7rem; border-radius: 999px;
    background: #f4f6fb; border: 1px solid #e3e7f0;
    font-size: 0.74rem; color: #3b5bdb; font-weight: 500;
    white-space: nowrap;
}
</style>
"""


def _brand_block() -> None:
    """试卷命题系统品牌区：logo + 大标题 + 副标题标语"""
    st.markdown(
        '<div class="auth-brand">'
        '<div class="auth-logo">卷</div>'
        '<div class="auth-title">课程试卷智能命题校验批改系统</div>'
        '<div class="auth-subtitle">基于多模态 RAG 的习题文档解析、智能命题、'
        '试卷校验与自动批改平台</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _intro_block() -> None:
    """系统能力简介小字（卡片底部）"""
    st.markdown(
        '<div class="auth-intro">'
        '<div class="auth-intro-label">系统能力</div>'
        '<div class="auth-features">'
        '<span class="auth-feature">📄 PDF / Word 习题文档解析</span>'
        '<span class="auth-feature">🖼️ 多模态图片向量化</span>'
        '<span class="auth-feature">📝 自动生成试卷</span>'
        '<span class="auth-feature">✅ 校验批改试题</span>'
        '</div>'
        '</div>',
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
            # 登录成功后默认进入【课程库】页面
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
    """渲染登录 / 注册页（浅蓝灰背景 + 居中白色卡片 + 系统能力简介）"""
    st.markdown(_AUTH_PAGE_CSS, unsafe_allow_html=True)
    st.markdown('<div style="height:5vh"></div>', unsafe_allow_html=True)

    left, center, right = st.columns([1, 2.2, 1])
    with center:
        with st.container(border=True):
            _brand_block()
            tab_login, tab_register = st.tabs(["登 录", "注 册"])
            with tab_login:
                _login_tab()
            with tab_register:
                _register_tab()
            _intro_block()
