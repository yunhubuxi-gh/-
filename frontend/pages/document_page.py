"""
文档管理页面

功能：文档上传（异步向量化 + 实时进度）、文档列表、版本查看、下载、删除、重建索引。
上传后立即拿到 task_id，前端轮询文档状态（uploaded→parsing→embedding→ready）展示进度。
无知识库时：醒目引导 + 跳转创建。
"""
from __future__ import annotations

import html
import time

import streamlit as st

from frontend import styles, config
from frontend.api_client import api, ApiError
from frontend.components import doc_status_badge, notify_success, notify_error, empty_state, empty_guide, navigate


def _esc(s) -> str:
    return html.escape(str(s))


def _list_kb_options():
    try:
        return api.get("/api/v1/kb", params={"page_size": 100})["items"]
    except ApiError:
        return []


def _upload_block(kb_id: int) -> None:
    """文档上传 + 异步进度轮询"""
    with st.container(border=True):
        with st.form("doc_upload_form", clear_on_submit=True):
            st.markdown('<div style="font-weight:600;margin-bottom:0.4rem;">上传文档</div>', unsafe_allow_html=True)
            file = st.file_uploader("选择文件（pdf/docx/md/txt/png/jpg）", type=["pdf", "docx", "md", "txt", "png", "jpg", "jpeg"])
            submitted = st.form_submit_button("上传并向量化", type="primary", use_container_width=True)

        if submitted and file is not None:
            try:
                with st.spinner("正在上传…"):
                    data = api.upload(
                        f"/api/v1/kb/{kb_id}/documents",
                        files={"file": (file.name, file.getvalue(), file.type or "application/octet-stream")},
                    )
                doc_id = data["document_id"]
                task_id = data["task_id"]
                notify_success(f"上传成功，开始向量化（task_id: {task_id}）")

                status_bar = st.progress(0, text="正在向量化…")
                deadline = time.time() + config.POLL_MAX_WAIT_SECONDS
                status_map = {
                    "uploaded": 0.08, "parsing": 0.25, "extracting_images": 0.4, "ocr": 0.5,
                    "parsed": 0.55, "embedding": 0.7, "image_embedding": 0.9, "ready": 1.0, "failed": 1.0,
                }
                while time.time() < deadline:
                    try:
                        doc = api.get(f"/api/v1/documents/{doc_id}")
                    except ApiError:
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue
                    s = doc.get("status")
                    status_bar.progress(min(status_map.get(s, 0.1), 0.9), text=f"状态：{s}")
                    if s in ("ready", "failed"):
                        if s == "ready":
                            status_bar.progress(1.0, text="向量化完成 ✅")
                            notify_success("文档已就绪，可检索")
                        else:
                            status_bar.empty()
                            notify_error(f"向量化失败：{doc.get('error_message') or '未知错误'}")
                        break
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                else:
                    status_bar.empty()
                    notify_error("处理超时，请稍后刷新查看")
                st.rerun()
            except ApiError as e:
                notify_error(e.message)


def _doc_table(kb_id: int) -> None:
    """文档列表表格"""
    try:
        data = api.get(f"/api/v1/kb/{kb_id}/documents", params={"page_size": 200})
        docs = data["items"]
    except ApiError as e:
        st.warning(e.message)
        return

    if not docs:
        empty_state("📄", "该知识库暂无文档，请上传文档")
        return

    st.markdown('<div style="font-weight:600;margin:0.4rem 0;">文档列表</div>', unsafe_allow_html=True)
    html_rows = []
    for d in docs:
        size_kb = (d.get("file_size") or 0) / 1024
        html_rows.append(
            f'<tr style="border-top:1px solid #eef1f6;">'
            f'<td style="padding:0.6rem;font-size:0.85rem;color:#555a63;">{d["id"]}</td>'
            f'<td style="font-size:0.85rem;">{_esc(d.get("title"))}</td>'
            f'<td style="font-size:0.85rem;">{_esc(d.get("doc_type"))}</td>'
            f'<td style="font-size:0.85rem;color:#555a63;">{size_kb:.1f} KB</td>'
            f'<td>{doc_status_badge(d.get("status"))}</td>'
            f'<td style="font-size:0.85rem;">{d.get("chunk_count", 0)}</td>'
            f'<td style="font-size:0.85rem;">v{d.get("current_version", 1)}</td></tr>'
        )
    st.markdown(
        '<div style="overflow-x:auto;background:#ffffff;border:1px solid #c8cdd5;border-radius:12px;">'
        '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
        '<thead><tr style="background:#f4f6fb;color:#555a63;">'
        '<th style="padding:0.6rem;text-align:left;">ID</th><th style="text-align:left;">标题</th>'
        '<th style="text-align:left;">类型</th><th style="text-align:left;">大小</th>'
        '<th style="text-align:left;">状态</th><th style="text-align:left;">分块</th>'
        '<th style="text-align:left;">版本</th></tr></thead>'
        f'<tbody>{"".join(html_rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _doc_detail(kb_id: int) -> None:
    """选中文档的详情：版本查看 + 删除 + 重建"""
    try:
        docs = api.get(f"/api/v1/kb/{kb_id}/documents", params={"page_size": 200})["items"]
    except ApiError:
        docs = []
    if not docs:
        return
    options = {f'{d["title"]} (ID {d["id"]})': d for d in docs}
    chosen = st.selectbox("选择文档", list(options.keys()))
    doc = options[chosen]
    doc_id = doc["id"]

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("查看版本", use_container_width=True):
            st.session_state[f"versions_{doc_id}"] = True
    with c2:
        if st.button("重建索引", use_container_width=True):
            try:
                with st.spinner("正在提交重建任务…"):
                    r = api.post(f"/api/v1/documents/{doc_id}/reindex")
                notify_success(f"重建任务已提交：{r.get('task_id')}")
            except ApiError as e:
                notify_error(e.message)
    with c3:
        if st.button("删除文档", use_container_width=True):
            try:
                with st.spinner("正在删除…"):
                    api.delete(f"/api/v1/documents/{doc_id}")
                notify_success("文档已删除")
                st.rerun()
            except ApiError as e:
                notify_error(e.message)

    if st.session_state.get(f"versions_{doc_id}"):
        try:
            versions = api.get(f"/api/v1/documents/{doc_id}/versions")
            st.markdown('<div style="font-weight:600;margin:0.6rem 0 0.3rem 0;">历史版本</div>', unsafe_allow_html=True)
            for v in versions:
                st.markdown(
                    f'<div class="stCard" style="padding:0.6rem 0.9rem;margin:0.3rem 0;">'
                    f'<b>v{v["version"]}</b> · {_esc(v.get("change_log") or "—")} · '
                    f'{(v.get("file_size") or 0) // 1024} KB</div>',
                    unsafe_allow_html=True,
                )
        except ApiError as e:
            st.warning(e.message)


def render() -> None:
    styles.hero("📄 文档管理", "上传文档、实时查看向量化进度、管理版本")

    kbs = _list_kb_options()
    if not kbs:
        if empty_guide("📚", "还没有知识库",
                       "创建知识库后，即可上传文档并自动向量化",
                       "去创建知识库", key="doc_empty_kb"):
            navigate("kb")
        return

    options = {f'{kb["name"]} (ID {kb["id"]})': kb for kb in kbs}
    chosen = st.selectbox("选择知识库", list(options.keys()))
    kb = options[chosen]
    kb_id = kb["id"]
    role = kb.get("user_role") or "read"

    # 上传（write+）
    if role in ("owner", "admin", "write"):
        _upload_block(kb_id)
    else:
        st.info("你当前为只读成员，无上传文档权限")

    st.markdown("---")
    _doc_table(kb_id)
    _doc_detail(kb_id)
