"""
前端主入口

职责：
- 未登录自动拦截，跳转登录 / 注册页
- 已登录渲染侧边栏（品牌 + 用户信息 + 导航 + 修改密码 + 退出登录）
- 根据导航切换 6 大页面，统一加载动画

启动：
    streamlit run frontend/app.py
"""
from __future__ import annotations

import html
import os
import sys

# 把项目根目录加入 sys.path，使 frontend 能 import 全局 config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402

from frontend import styles  # noqa: E402
from frontend.auth import is_authenticated, get_user, logout  # noqa: E402
from frontend.api_client import api, ApiError  # noqa: E402
from frontend.components import notify_success, notify_error  # noqa: E402
from frontend.pages import (  # noqa: E402
    auth_page, kb_page, document_page, chat_page, agent_page, audit_page,
)

# 页面注册表（知识库管理居首，登录后默认落地页）
PAGES = {
    "kb": ("📚 知识库管理", kb_page),
    "document": ("📄 文档管理", document_page),
    "chat": ("💬 智能问答", chat_page),
    "agent": ("🤖 Agent 任务", agent_page),
    "audit": ("📊 审计日志", audit_page),
}


def _esc(s) -> str:
    return html.escape(str(s))


def _page_config() -> None:
    st.set_page_config(
        page_title="企业私有知识库智能助手",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    styles.inject_global_css()


def _render_sidebar() -> str:
    """侧边栏：品牌 + 用户卡片 + 导航 + 修改密码 + 退出"""
    user = get_user()
    nickname = user.get("nickname") or user.get("username") or "用户"
    role_label = {"admin": "管理员", "normal": "普通用户", "guest": "访客"}.get(user.get("role"), "用户")

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">'
            '<div class="sidebar-logo">企</div>'
            '<div><div class="sidebar-title">私有知识库助手</div>'
            '<div class="sidebar-sub">Enterprise KB Assistant</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # 用户卡片（顶部显示当前登录用户名 + 角色）
        initial = (nickname[0] if nickname else "U").upper()
        st.markdown(
            f'<div class="user-card">'
            f'<div class="user-avatar">{initial}</div>'
            f'<div><div class="user-name">{_esc(nickname)}</div>'
            f'<div class="user-role">{role_label}</div></div></div>',
            unsafe_allow_html=True,
        )

        # 导航
        labels = [label for label, _ in PAGES.values()]
        keys = list(PAGES.keys())
        current = st.session_state.get("nav_page", "kb")
        idx = keys.index(current) if current in keys else 0
        chosen_label = st.radio("导航", labels, index=idx, label_visibility="collapsed")
        nav_page = keys[labels.index(chosen_label)]
        st.session_state["nav_page"] = nav_page

        st.markdown("---")

        # 修改密码
        with st.expander("🔑 修改密码"):
            with st.form("change_pwd_form", clear_on_submit=True):
                old = st.text_input("原密码", type="password")
                new = st.text_input("新密码", type="password")
                if st.form_submit_button("确认修改", type="primary", use_container_width=True):
                    if not old or not new:
                        notify_error("请填写完整")
                    else:
                        try:
                            with st.spinner("正在修改…"):
                                api.post("/api/v1/auth/change-password",
                                         json={"old_password": old, "new_password": new})
                            notify_success("密码修改成功")
                        except ApiError as e:
                            notify_error(e.message)

        # 退出登录
        if st.button("🚪 退出登录", use_container_width=True):
            logout()
            st.rerun()

    return nav_page


def main() -> None:
    _page_config()

    # 未登录 → 登录/注册页
    if not is_authenticated():
        auth_page.render()
        st.stop()

    # 已登录 → 侧边栏导航 + 页面渲染（统一加载动画）
    nav_page = _render_sidebar()
    page = PAGES[nav_page][1]
    with st.spinner("加载中…"):
        page.render()


if __name__ == "__main__":
    main()
