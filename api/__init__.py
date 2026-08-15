"""
API 接口层（FastAPI）

职责：
- 接收 HTTP 请求，校验鉴权（JWT），把参数传给 services 业务服务层，返回统一格式响应
- 不写业务逻辑（只做参数接收、鉴权、调用 service、返回结果）
- 不直接写审计日志：审计写操作入口收敛到 services.write_audit_log（service 层调用），
  ❌ 本层禁止直接调用 utils.log_audit
- service 抛出的自定义业务异常（PermissionException / AuthException 等）不在本层捕获，
  统一交给全局异常处理器（api.handlers）转成标准化 HTTP 返回体

模块划分：
- main.py       FastAPI 实例 + CORS + 中间件 + 路由注册 + 异常处理器
- deps.py       JWT 鉴权依赖（get_current_user）
- middleware.py 请求日志中间件（记录路径 / 用户 / 耗时）
- handlers.py   全局异常处理器（业务异常 / 校验异常 / 系统异常）
- router/       6 个路由模块（auth / kb / document / chat / agent / audit）
"""
from __future__ import annotations
