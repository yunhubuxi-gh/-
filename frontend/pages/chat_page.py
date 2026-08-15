"""
智能对话 RAG 问答页面

功能：聊天气泡界面、引用来源展示、流式打字动画、会话管理（新建/切换）。
前置条件：必须先有知识库；无知识库时禁止展示聊天输入框，仅展示引导按钮。
"""
from __future__ import annotations

import streamlit as st

from frontend import styles
from frontend.api_client import api, ApiError
from frontend.components import (
    chat_bubble_html, citations_html, typewriter, notify_error, empty_guide, navigate,
)


def _list_kb_options():
    try:
        return api.get("/api/v1/kb", params={"page_size": 100})["items"]
    except ApiError:
        return []


def _load_conversations():
    try:
        return api.get("/api/v1/chat/conversations", params={"page_size": 50})["items"]
    except ApiError:
        return []


def _render_messages(msgs: list) -> None:
    """渲染历史消息气泡"""
    for m in msgs:
        role = "user" if m["role"] == "user" else "assistant"
        st.markdown(chat_bubble_html(role, m.get("content") or ""), unsafe_allow_html=True)
        if role == "assistant" and m.get("citations"):
            st.markdown(citations_html(m["citations"]), unsafe_allow_html=True)
            _render_citation_images(m["citations"])


def _render_citation_images(citations) -> None:
    """渲染检索结果中的图片片段（content_type==image，通过后端接口取图）"""
    for c in citations or []:
        ctype = c.get("content_type") or c.get("chunk_type")
        if ctype != "image":
            continue
        doc_id = c.get("document_id")
        page = c.get("page_number") or 1
        idx = c.get("chunk_index") or 0
        if doc_id is None:
            continue
        try:
            raw = api.get_bytes(f"/api/v1/documents/{doc_id}/images/{page}/{idx}")
            st.image(raw, caption=f"📎 {c.get('document_name') or ''} 第{page}页",
                     use_container_width=True)
        except ApiError:
            continue


def _chat_interface() -> None:
    """会话选择 + 聊天主区 + 输入框（前置检测知识库）"""
    kbs = _list_kb_options()
    if not kbs:
        if empty_guide("📚", "还没有知识库",
                       "创建知识库后，即可上传文档并进行智能问答",
                       "去创建知识库", key="chat_empty_kb"):
            navigate("kb")
        return

    # 顶部控制：知识库 + 会话
    c1, c2 = st.columns([2, 2])
    with c1:
        kb_options = {f'{kb["name"]} (ID {kb["id"]})': kb for kb in kbs}
        chosen = st.selectbox("选择知识库", list(kb_options.keys()))
        kb = kb_options[chosen]
        kb_id = kb["id"]
    with c2:
        convs = _load_conversations()
        conv_options = {"＋ 新建会话": None}
        for c in convs:
            conv_options[f'{c.get("title") or "会话"} (ID {c["id"]})'] = c["id"]
        conv_chosen = st.selectbox("选择会话", list(conv_options.keys()))
        conv_id = conv_options[conv_chosen]

    # 所选知识库无文档：友好提示 + 引导上传
    if (kb.get("doc_count") or 0) == 0:
        h_l, h_r = st.columns([3, 1])
        with h_l:
            st.info("📭 该知识库暂无文档，问答可能无结果，建议先上传文档")
        with h_r:
            if st.button("去上传文档", key="chat_go_doc", use_container_width=True):
                navigate("document")

    # 聊天消息历史
    if conv_id is not None:
        try:
            msgs = api.get(f"/api/v1/chat/conversations/{conv_id}/messages")
        except ApiError as e:
            msgs = []
            st.warning(e.message)
        _render_messages(msgs)

    st.markdown("---")

    # 输入框（已确保有知识库）
    query = st.chat_input("请输入你的问题，回车发送…")
    if query:
        st.markdown(chat_bubble_html("user", query), unsafe_allow_html=True)
        placeholder = st.empty()

        try:
            with st.spinner("正在检索并生成回答…"):
                payload = {"knowledge_base_id": kb_id, "query": query}
                if conv_id is not None:
                    payload["conversation_id"] = conv_id
                data = api.post("/api/v1/chat/ask", json=payload)

            answer = data.get("answer") or ""
            typewriter(placeholder, "assistant", answer)
            if data.get("citations"):
                st.markdown(citations_html(data["citations"]), unsafe_allow_html=True)
                _render_citation_images(data["citations"])
        except ApiError as e:
            placeholder.empty()
            notify_error(e.message)
        st.rerun()


def render() -> None:
    styles.hero("💬 智能问答", "基于 RAG 检索增强生成的企业知识库问答")
    _chat_interface()
