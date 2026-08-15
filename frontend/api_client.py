"""
HTTP 请求封装（统一后端 API 调用入口）

职责：
- 统一拼接 base_url、附加 JWT 鉴权头、超时控制
- 统一解析后端返回体 {code, message, data, timestamp}，code != 0 时抛 ApiError
- 401 自动清除登录态并跳转登录页
- 403 权限不足友好提示
- 所有网络异常统一为 ApiError，由页面层友好提示

禁止：本模块不直接访问数据库 / rag_engine / services / utils，只走 HTTP。
"""
from __future__ import annotations

from typing import Optional

import requests
import streamlit as st

from frontend import config


class ApiError(Exception):
    """后端接口调用异常（携带业务错误码与 HTTP 状态码）"""

    def __init__(self, message: str, code: Optional[int] = None, status: Optional[int] = None):
        self.message = message
        self.code = code
        self.status = status
        super().__init__(message)


class ApiClient:
    """后端 API 客户端（单例）"""

    def __init__(self):
        self.base_url = config.API_BASE_URL
        self.timeout = config.TIMEOUT

    # ---------- 基础 ----------

    def _token(self) -> Optional[str]:
        return st.session_state.get("token")

    def _headers(self, auth: bool = True, json_body: bool = True):
        h = {"Content-Type": "application/json"} if json_body else {}
        if auth and self._token():
            h["Authorization"] = f"Bearer {self._token()}"
        return h

    def _handle(self, resp: requests.Response):
        # 401 -> 清除登录态并立即跳转登录页
        if resp.status_code == 401:
            from frontend.auth import logout
            logout()
            st.toast("登录已过期，请重新登录", icon="🔒")
            st.rerun()

        try:
            body = resp.json()
        except ValueError:
            body = {}

        # 403 -> 权限不足，友好提示
        if resp.status_code == 403:
            raise ApiError(
                f"权限不足：{body.get('message') or '你无权执行该操作'}",
                code=body.get("code"), status=403,
            )

        if resp.status_code >= 400:
            raise ApiError(
                body.get("message", f"请求失败（HTTP {resp.status_code}）"),
                code=body.get("code"), status=resp.status_code,
            )

        if body.get("code") != 0:
            raise ApiError(
                body.get("message", "请求失败"),
                code=body.get("code"), status=resp.status_code,
            )
        return body.get("data")

    def _request(self, method: str, path: str, **kwargs):
        url = self.base_url + path
        try:
            resp = requests.request(method, url, timeout=self.timeout, **kwargs)
        except requests.exceptions.ConnectionError:
            raise ApiError(f"无法连接后端服务（{url}），请确认后端已启动")
        except requests.exceptions.Timeout:
            raise ApiError("请求超时，请稍后重试")
        except requests.exceptions.RequestException as e:
            raise ApiError(f"网络请求异常：{e}")
        return self._handle(resp)

    # ---------- 常用方法 ----------

    def get(self, path: str, params: Optional[dict] = None, auth: bool = True):
        return self._request("GET", path, params=params, headers=self._headers(auth))

    def post(self, path: str, json: Optional[dict] = None, auth: bool = True):
        return self._request("POST", path, json=json, headers=self._headers(auth))

    def put(self, path: str, json: Optional[dict] = None, auth: bool = True):
        return self._request("PUT", path, json=json, headers=self._headers(auth))

    def delete(self, path: str, auth: bool = True):
        return self._request("DELETE", path, headers=self._headers(auth))

    def upload(self, path: str, files: dict, auth: bool = True):
        """文件上传（multipart，不手动设置 Content-Type）"""
        return self._request("POST", path, files=files, headers=self._headers(auth, json_body=False))

    def get_bytes(self, path: str, auth: bool = True) -> bytes:
        """下载二进制资源（如图片），返回原始字节"""
        url = self.base_url + path
        try:
            resp = requests.get(url, timeout=self.timeout, headers=self._headers(auth, json_body=False))
        except requests.exceptions.RequestException as e:
            raise ApiError(f"网络请求异常：{e}")

        if resp.status_code == 401:
            from frontend.auth import logout
            logout()
            st.toast("登录已过期，请重新登录", icon="🔒")
            st.rerun()
        if resp.status_code >= 400:
            raise ApiError(f"资源获取失败（HTTP {resp.status_code}）", status=resp.status_code)
        return resp.content


# 全局单例
api = ApiClient()
