"""
登录态管理

- 通过 st.session_state 保持全局登录态（access_token / refresh_token / user）
- app.py 入口调用 is_authenticated 判断，未登录自动跳转登录页
- 提供 set_auth / logout / get_token / get_user 便捷访问
"""
from __future__ import annotations

import streamlit as st

_TOKEN_KEY = "token"
_REFRESH_KEY = "refresh_token"
_USER_KEY = "user"
_NAV_KEY = "nav_page"


def is_authenticated() -> bool:
    """是否已登录"""
    return bool(st.session_state.get(_TOKEN_KEY))


def get_token() -> str | None:
    return st.session_state.get(_TOKEN_KEY)


def get_refresh_token() -> str | None:
    return st.session_state.get(_REFRESH_KEY)


def get_user() -> dict:
    return st.session_state.get(_USER_KEY) or {}


def set_auth(access_token: str, refresh_token: str, user: dict) -> None:
    """登录 / 注册成功写入会话状态"""
    st.session_state[_TOKEN_KEY] = access_token
    st.session_state[_REFRESH_KEY] = refresh_token
    st.session_state[_USER_KEY] = user


def logout() -> None:
    """清除登录态，并重置导航（下次登录回到知识库页）"""
    for k in (_TOKEN_KEY, _REFRESH_KEY, _USER_KEY, _NAV_KEY):
        st.session_state.pop(k, None)
