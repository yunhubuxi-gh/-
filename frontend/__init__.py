"""
前端 UI 层（Streamlit）

定位：
- 只负责页面渲染、接收用户输入、发起 HTTP 请求调用 FastAPI 后端接口
- ❌ 禁止直接操作数据库、禁止直接调用 rag_engine / agent_langgraph / services / utils
- 所有功能、数据、业务逻辑一律通过后端 API 完成

模块划分：
- config.py      前端网络配置（API base_url / 超时，统一读取全局 config，禁止硬编码）
- styles.py      全局自定义 CSS（高颜值主题、卡片化、阴影、圆角、hover 动画）
- api_client.py  HTTP 请求封装（统一鉴权头、异常友好提示、401 自动登出）
- auth.py        登录态管理（session_state 保持 + 未登录拦截）
- components.py  可复用 UI 组件（徽章、状态胶囊、气泡、类型打字动画、卡片）
- pages/         6 大页面（登录注册 / 知识库 / 文档 / 问答 / Agent / 审计）
- app.py         主入口（登录拦截 + 侧边栏导航 + 页面路由）
"""
from __future__ import annotations
