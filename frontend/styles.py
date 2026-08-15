"""
全局自定义 CSS（彻底覆盖 Streamlit 原生控件样式）

设计目标：企业级产品质感、低饱和高级配色、卡片化布局。
- 页面背景 #eef1f6 / 卡片 #ffffff / 主色 #3b5bdb
- 输入框背景 #f7f8fa / 文字 #111111 / 提示 #666666 / 边框 #c8cdd5
- 大量使用 !important 强制覆盖 Streamlit 原生控件，根治「白底白字」显示 BUG

禁止依赖 config.toml 主题，所有颜色写死在本 CSS 中。
"""
from __future__ import annotations

import streamlit as st

# 统一色板（与用户要求一一对应）
C_BG = "#eef1f6"
C_CARD = "#ffffff"
C_PRIMARY = "#3b5bdb"
C_PRIMARY_DARK = "#2f4ab8"
C_INPUT_BG = "#f7f8fa"
C_TEXT = "#111111"
C_TEXT_2 = "#555a63"
C_MUTED = "#666666"
C_BORDER = "#c8cdd5"

GLOBAL_CSS = f"""
<style>
/* ============================================================
   1. 全局基础 & 隐藏原生 chrome
============================================================ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
    --primary: {C_PRIMARY};
    --primary-dark: {C_PRIMARY_DARK};
    --primary-soft: #e9edfc;
    --bg: {C_BG};
    --card: {C_CARD};
    --text: {C_TEXT};
    --text-2: {C_TEXT_2};
    --muted: {C_MUTED};
    --border: {C_BORDER};
    --danger: #e03131;
    --danger-soft: #fdeeee;
    --success: #2f9e44;
    --success-soft: #ebf7ee;
    --warning: #e8930c;
    --warning-soft: #fff4e0;
}}

html, body, [class*="css"] {{
    font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', -apple-system,
        BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: {C_TEXT};
}}

.stApp {{
    background: {C_BG};
    background-attachment: fixed;
}}

/* 隐藏 Streamlit 默认 chrome：顶部菜单、footer 水印、装饰条、工具栏 */
#MainMenu {{ visibility: hidden !important; }}
footer {{ visibility: hidden !important; }}
header[data-testid="stHeader"] {{ visibility: hidden !important; height: 0 !important; }}
div[data-testid="stToolbar"] {{ visibility: hidden !important; }}
div[data-testid="stDecoration"] {{ visibility: hidden !important; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden !important; }}
div[data-testid="stAppViewBlockContainer"] {{ padding-top: 1.6rem !important; padding-bottom: 2.5rem !important; }}

/* 主内容区留白 */
.block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1180px;
}}

/* 滚动条 */
::-webkit-scrollbar {{ width: 8px; height: 8px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: #c9d0dc; border-radius: 8px; }}
::-webkit-scrollbar-thumb:hover {{ background: #aab3c4; }}

/* ============================================================
   2. 侧边栏
============================================================ */
[data-testid="stSidebar"] {{
    background: #ffffff;
    border-right: 1px solid {C_BORDER};
    box-shadow: 4px 0 24px rgba(17, 24, 39, 0.05);
}}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.4rem; }}

.sidebar-brand {{
    display: flex; align-items: center; gap: 0.7rem;
    padding: 0.4rem 0.2rem 1rem 0.2rem;
    border-bottom: 1px solid {C_BORDER}; margin-bottom: 1rem;
}}
.sidebar-logo {{
    width: 42px; height: 42px; border-radius: 12px;
    background: linear-gradient(135deg, {C_PRIMARY}, #6b8afd);
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-size: 1.2rem; font-weight: 700;
    box-shadow: 0 6px 16px rgba(59, 91, 219, 0.32);
}}
.sidebar-title {{ font-size: 1.02rem; font-weight: 700; color: {C_TEXT}; line-height: 1.25; }}
.sidebar-sub {{ font-size: 0.72rem; color: {C_MUTED}; }}

.user-card {{
    display: flex; align-items: center; gap: 0.7rem;
    background: #f4f6fb; border: 1px solid #e3e7f0;
    border-radius: 14px; padding: 0.65rem 0.8rem; margin: 0.6rem 0 1rem 0;
}}
.user-avatar {{
    width: 36px; height: 36px; border-radius: 50%;
    background: linear-gradient(135deg, {C_PRIMARY}, #4fa3a1);
    color: #fff; display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 0.95rem; flex-shrink: 0;
}}
.user-name {{ font-weight: 600; color: {C_TEXT}; font-size: 0.9rem; }}
.user-role {{ font-size: 0.72rem; color: {C_TEXT_2}; }}

/* 侧边栏导航 radio */
[data-testid="stSidebar"] [role="radiogroup"] label {{
    border-radius: 10px !important; margin: 0.1rem 0 !important;
    padding: 0.55rem 0.7rem !important; transition: all 0.18s ease !important;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
    background: var(--primary-soft) !important;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
    background: linear-gradient(135deg, {C_PRIMARY}, #6b8afd) !important;
    box-shadow: 0 4px 12px rgba(59, 91, 219, 0.28) !important;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
    color: #fff !important; font-weight: 600 !important;
}}

/* ============================================================
   3. 标题 / 文本
============================================================ */
h1, h2, h3, h4, h5, h6 {{ color: #111111 !important; letter-spacing: -0.01em; }}

/* 全局字体强制黑色：正文 / 标题 / 标签 / 表格 / 列表 / tab / 所有 markdown 文本 */
.stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stApp label, .stApp li, .stApp td, .stApp th, .stApp caption, .stApp blockquote,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] div,
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] span {{
    color: #111111 !important;
}}
.stTabs [data-baseweb="tab"], .stTabs [aria-selected="true"] {{
    color: #111111 !important;
}}
.stTabs [data-baseweb="tab"]::after,
.stTabs [aria-selected="true"]::after {{
    background-color: #111111 !important;
}}

/* 例外1：主按钮（蓝底）保持白字，避免蓝底黑字看不清 */
.stButton button[kind="primary"] p,
.stFormSubmitButton button[kind="primary"] p {{
    color: #ffffff !important;
}}
/* 例外2：用户聊天气泡（蓝底）保持白字 */
.chat-bubble.user, .chat-bubble.user p {{ color: #ffffff !important; }}

.section-title {{
    font-size: 1.5rem; font-weight: 700; color: #111111;
    display: flex; align-items: center; gap: 0.55rem; margin-bottom: 0.2rem;
}}
.section-subtitle {{ font-size: 0.86rem; color: #111111; margin-bottom: 1.2rem; }}

/* ============================================================
   4. 卡片（含 st.container(border=True) 与自定义 .stCard）
============================================================ */
.stCard, div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {C_CARD} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 16px !important;
    box-shadow: 0 2px 10px rgba(17, 24, 39, 0.05) !important;
}}
.stCard {{
    padding: 1.2rem 1.3rem;
    transition: box-shadow 0.22s ease, transform 0.22s ease;
}}
.stCard:hover {{
    box-shadow: 0 10px 30px rgba(17, 24, 39, 0.09) !important;
    transform: translateY(-2px);
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {{
    padding: 1.2rem 1.4rem !important;
}}

/* ============================================================
   5. 按钮
============================================================ */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {{
    border-radius: 9px !important;
    border: 1px solid {C_BORDER} !important;
    background: #ffffff !important; color: {C_TEXT} !important;
    font-weight: 600 !important; padding: 0.5rem 1.1rem !important;
    transition: all 0.18s ease !important;
    box-shadow: 0 1px 2px rgba(17,24,39,0.05) !important;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover,
.stDownloadButton > button:hover {{
    border-color: {C_PRIMARY} !important; color: {C_PRIMARY} !important;
    background: var(--primary-soft) !important;
    box-shadow: 0 6px 16px rgba(59,91,219,0.16) !important;
    transform: translateY(-1px);
}}
/* 主按钮 */
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
    background: linear-gradient(135deg, {C_PRIMARY}, #5c7cf0) !important;
    color: #fff !important; border: none !important;
    box-shadow: 0 6px 16px rgba(59,91,219,0.28) !important;
}}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {{
    box-shadow: 0 10px 24px rgba(59,91,219,0.36) !important;
    color: #fff !important;
    background: linear-gradient(135deg, {C_PRIMARY_DARK}, #4a6bea) !important;
}}

/* ============================================================
   6. 输入控件 —— 彻底根治「白底白字」BUG（硬性要求）
   背景 #f7f8fa（非白）/ 边框 #c8cdd5（可见深色）/ 文字 #111111 / 提示 #666666
============================================================ */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input {{
    background-color: {C_INPUT_BG} !important;
    color: {C_TEXT} !important;
    border: 1.5px solid {C_BORDER} !important;
    border-radius: 9px !important;
    box-shadow: 0 1px 2px rgba(17,24,39,0.04) !important;
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stNumberInput"] input:focus {{
    border-color: {C_PRIMARY} !important;
    box-shadow: 0 0 0 3px rgba(59,91,219,0.14) !important;
    background-color: #ffffff !important;
}}
/* placeholder 提示文字 #666666 */
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {{
    color: {C_MUTED} !important;
    opacity: 1 !important;
}}

/* 下拉选择 / 多选 */
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
    background-color: {C_INPUT_BG} !important;
    border: 1.5px solid {C_BORDER} !important;
    border-radius: 9px !important;
}}
[data-testid="stSelectbox"] div[data-baseweb="select"] span,
[data-testid="stMultiSelect"] div[data-baseweb="select"] span {{
    color: {C_TEXT} !important;
}}

/* 文件上传拖拽区 */
[data-testid="stFileUploaderDropzone"] {{
    border: 1.5px dashed {C_BORDER} !important;
    border-radius: 12px !important;
    background: {C_INPUT_BG} !important;
}}
[data-testid="stFileUploaderDropzone"]:hover {{
    border-color: {C_PRIMARY} !important;
    background: var(--primary-soft) !important;
}}
[data-testid="stFileUploaderDropzone"] span {{
    color: {C_TEXT} !important;
}}

/* 聊天输入框 */
[data-testid="stChatInput"] {{
    border: 1.5px solid {C_BORDER} !important;
    border-radius: 12px !important;
    background: #ffffff !important;
    box-shadow: 0 2px 8px rgba(17,24,39,0.05) !important;
}}
[data-testid="stChatInput"]:focus-within {{
    border-color: {C_PRIMARY} !important;
    box-shadow: 0 0 0 3px rgba(59,91,219,0.14) !important;
}}
[data-testid="stChatInput"] textarea {{
    color: {C_TEXT} !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{
    color: {C_MUTED} !important; opacity: 1 !important;
}}

/* 标签页 */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0.4rem; border-bottom: 1px solid {C_BORDER};
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 10px 10px 0 0; padding: 0.5rem 1.1rem;
    color: {C_TEXT_2}; font-weight: 600;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: {C_PRIMARY} !important; }}
.stTabs [aria-selected="true"] {{ color: {C_PRIMARY} !important; }}

/* 表单提交按钮的输入框间距统一 */
.stForm > div > div {{ gap: 0.5rem; }}

/* ============================================================
   7. 徽章 / 状态胶囊
============================================================ */
.pill {{
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.18rem 0.65rem; border-radius: 999px;
    font-size: 0.74rem; font-weight: 600; line-height: 1.5;
}}
.pill-dot {{ width: 6px; height: 6px; border-radius: 50%; background: currentColor; }}

/* ============================================================
   8. 聊天气泡 + 引用来源卡片
============================================================ */
.chat-row {{ display: flex; margin: 0.4rem 0; }}
.chat-row.user {{ justify-content: flex-end; }}
.chat-row.assistant {{ justify-content: flex-start; }}
.chat-bubble {{
    max-width: 82%; padding: 0.75rem 1rem;
    border-radius: 16px; line-height: 1.65; font-size: 0.94rem;
    box-shadow: 0 2px 8px rgba(17,24,39,0.05);
    word-break: break-word; color: {C_TEXT};
}}
.chat-bubble.user {{
    background: linear-gradient(135deg, {C_PRIMARY}, #5c7cf0); color: #fff;
    border-bottom-right-radius: 5px;
}}
.chat-bubble.assistant {{
    background: #ffffff; color: {C_TEXT};
    border: 1px solid {C_BORDER}; border-bottom-left-radius: 5px;
}}
.ref-card {{
    max-width: 82%; margin: 0.2rem 0 0.8rem 0; padding: 0.6rem 0.85rem;
    background: #f7f9fc; border: 1px dashed {C_BORDER}; border-radius: 12px;
}}
.ref-item {{ font-size: 0.78rem; color: {C_TEXT_2}; line-height: 1.7; }}
.ref-item b {{ color: {C_PRIMARY}; }}

/* ============================================================
   9. 提示框 / 通知
============================================================ */
[data-testid="stAlert"] {{
    border-radius: 12px !important; border: none !important;
    padding: 0.85rem 1rem !important;
}}
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {{
    color: {C_TEXT} !important;
}}

/* ============================================================
   10. 加载动画
============================================================ */
.loading-dots {{ display: inline-flex; gap: 5px; align-items: center; }}
.loading-dots span {{
    width: 8px; height: 8px; border-radius: 50%;
    background: {C_PRIMARY}; animation: blink 1.2s infinite ease-in-out;
}}
.loading-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
.loading-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
@keyframes blink {{
    0%,80%,100% {{ opacity: 0.25; transform: scale(0.8);}}
    40% {{ opacity: 1; transform: scale(1);}}
}}

/* ============================================================
   11. 空状态
============================================================ */
.empty-box {{
    text-align: center; padding: 2.6rem 1rem; color: {C_MUTED};
    border: 1.5px dashed {C_BORDER}; border-radius: 16px; background: #ffffff;
}}
.empty-icon {{ font-size: 2.2rem; margin-bottom: 0.5rem; }}
.empty-guide {{
    text-align: center; padding: 3rem 1.5rem;
    background: #ffffff; border: 1.5px dashed {C_BORDER}; border-radius: 18px;
    box-shadow: 0 2px 10px rgba(17,24,39,0.04);
}}
.empty-guide .empty-icon {{ font-size: 3rem; margin-bottom: 0.6rem; }}
.empty-guide-title {{ font-size: 1.25rem; font-weight: 700; color: {C_TEXT}; margin-bottom: 0.4rem; }}
.empty-guide-msg {{ font-size: 0.88rem; color: {C_TEXT_2}; margin-bottom: 0.2rem; line-height: 1.7; }}

/* ============================================================
   12. 统计卡 / 表格 / 展开面板
============================================================ */
.stat-card {{
    background: #ffffff; border: 1px solid {C_BORDER}; border-radius: 14px;
    padding: 1rem 1.2rem; box-shadow: 0 2px 8px rgba(17,24,39,0.04);
}}
.stat-num {{ font-size: 1.6rem; font-weight: 700; color: {C_PRIMARY}; }}
.stat-label {{ font-size: 0.78rem; color: {C_TEXT_2}; }}

[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
[data-testid="stExpander"] {{
    background: #ffffff; border: 1px solid {C_BORDER}; border-radius: 12px;
}}
</style>
"""


def inject_global_css() -> None:
    """注入全局 CSS（每个脚本运行开头调用一次）"""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "") -> None:
    """渲染统一的页面标题区"""
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="section-subtitle">{subtitle}</div>', unsafe_allow_html=True)
