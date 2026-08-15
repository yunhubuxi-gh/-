"""
可复用 UI 组件

- 状态 / 角色徽章（彩色胶囊）
- 聊天气泡 + 引用来源卡片 + 打字机流式动画
- 空状态占位 + 空状态引导（大卡片 + 引导按钮）
- 卡片 / 统计卡 / 通知 / 导航切换
"""
from __future__ import annotations

import html
import time

import streamlit as st


def _escape(text) -> str:
    return html.escape(str(text)).replace("\n", "<br>")


# ============================================================
# 徽章
# ============================================================

def pill(text: str, color: str, bg: str) -> str:
    """通用彩色胶囊徽章"""
    return (
        f'<span class="pill" style="color:{color};background:{bg};">'
        f'<span class="pill-dot"></span>{_escape(text)}</span>'
    )


def role_badge(role: str) -> str:
    """知识库权限角色徽章"""
    m = {
        "owner": ("所有者", "#7c3aed", "#f2edfd"),
        "admin": ("管理员", "#3b5bdb", "#e9edfc"),
        "write": ("编辑", "#0f9d8f", "#e6f7f5"),
        "read": ("只读", "#5b6472", "#f1f3f7"),
    }
    label, color, bg = m.get(role, (role, "#5b6472", "#f1f3f7"))
    return pill(label, color, bg)


def doc_status_badge(status: str) -> str:
    """文档处理状态徽章"""
    m = {
        "uploaded": ("待解析", "#e8930c", "#fff4e0"),
        "parsing": ("解析中", "#3b5bdb", "#e9edfc"),
        "extracting_images": ("提取图片中", "#3b5bdb", "#e9edfc"),
        "ocr": ("OCR 识别中", "#3b5bdb", "#e9edfc"),
        "parsed": ("已解析", "#3b5bdb", "#e9edfc"),
        "embedding": ("文本向量化中", "#3b5bdb", "#e9edfc"),
        "image_preprocess": ("图片预处理中", "#e8930c", "#fff4e0"),
        "image_embedding": ("图片向量化中", "#3b5bdb", "#e9edfc"),
        "ready": ("就绪", "#2f9e44", "#ebf7ee"),
        "failed": ("失败", "#e03131", "#fdeeee"),
        "archived": ("已归档", "#5b6472", "#f1f3f7"),
    }
    label, color, bg = m.get(status, (status, "#5b6472", "#f1f3f7"))
    return pill(label, color, bg)


def agent_status_badge(status: str) -> str:
    """Agent 任务状态徽章"""
    m = {
        "pending": ("等待", "#5b6472", "#f1f3f7"),
        "planning": ("规划中", "#3b5bdb", "#e9edfc"),
        "executing": ("执行中", "#3b5bdb", "#e9edfc"),
        "reflecting": ("反思中", "#e8930c", "#fff4e0"),
        "success": ("成功", "#2f9e44", "#ebf7ee"),
        "failed": ("失败", "#e03131", "#fdeeee"),
        "cancelled": ("已取消", "#5b6472", "#f1f3f7"),
    }
    label, color, bg = m.get(status, (status, "#5b6472", "#f1f3f7"))
    return pill(label, color, bg)


def result_badge(result: str) -> str:
    """审计结果徽章"""
    m = {
        "success": ("成功", "#2f9e44", "#ebf7ee"),
        "failed": ("失败", "#e03131", "#fdeeee"),
        "permission_denied": ("越权拒绝", "#e8930c", "#fff4e0"),
    }
    label, color, bg = m.get(result, (result, "#5b6472", "#f1f3f7"))
    return pill(label, color, bg)


# ============================================================
# 卡片 / 空状态
# ============================================================

def card(inner_html: str) -> None:
    """卡片容器（包裹自定义 HTML）"""
    st.markdown(f'<div class="stCard">{inner_html}</div>', unsafe_allow_html=True)


def empty_state(icon: str, message: str) -> None:
    """空状态占位"""
    st.markdown(
        f'<div class="empty-box"><div class="empty-icon">{icon}</div>'
        f'<div>{_escape(message)}</div></div>',
        unsafe_allow_html=True,
    )


def empty_guide(icon: str, title: str, message: str, button_label: str, key: str) -> bool:
    """空状态引导：大卡片 + 图标 + 标题 + 描述 + 居中主按钮，返回按钮是否被点击"""
    st.markdown(
        f'<div class="empty-guide">'
        f'<div class="empty-icon">{icon}</div>'
        f'<div class="empty-guide-title">{_escape(title)}</div>'
        f'<div class="empty-guide-msg">{_escape(message)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        return st.button(button_label, key=key, type="primary", use_container_width=True)


def navigate(page_key: str) -> None:
    """切换侧边栏导航页（写入 session_state 后重跑）"""
    st.session_state["nav_page"] = page_key
    st.rerun()


def stat_card(num, label: str) -> None:
    """统计卡片"""
    st.markdown(
        f'<div class="stat-card"><div class="stat-num">{_escape(num)}</div>'
        f'<div class="stat-label">{_escape(label)}</div></div>',
        unsafe_allow_html=True,
    )


# ============================================================
# 聊天气泡
# ============================================================

def chat_bubble_html(role: str, content: str) -> str:
    """生成单条聊天气泡 HTML"""
    return (
        f'<div class="chat-row {role}">'
        f'<div class="chat-bubble {role}">{_escape(content)}</div></div>'
    )


def citations_html(citations) -> str:
    """生成引用来源卡片 HTML"""
    if not citations:
        return ""
    items = []
    for c in citations:
        idx = c.get("index", "?")
        name = c.get("document_name") or f"文档{c.get('document_id')}"
        page = c.get("page_number") or 0
        chunk = (c.get("chunk_index") or 0) + 1
        items.append(
            f'<div class="ref-item"><b>[{idx}]</b> {_escape(name)} · 第{page}页 · 块{chunk}</div>'
        )
    return f'<div class="ref-card">{"".join(items)}</div>'


def typewriter(placeholder, role: str, text: str, sleep: float = 0.006) -> None:
    """客户端侧流式打字动画（后端一次性返回全文时，用打字机效果呈现流式观感）"""
    step = 1 if len(text) < 200 else 3
    displayed = ""
    for i in range(0, len(text), step):
        displayed = text[: i + step]
        placeholder.markdown(chat_bubble_html(role, displayed), unsafe_allow_html=True)
        time.sleep(sleep)
    placeholder.markdown(chat_bubble_html(role, text), unsafe_allow_html=True)


# ============================================================
# 通知
# ============================================================

def notify_success(message: str) -> None:
    st.toast(message, icon="✅")


def notify_error(message: str) -> None:
    st.toast(message, icon="⚠️")
