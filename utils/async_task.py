"""
异步任务封装模块
提供统一的异步任务调度接口，开发环境使用 FastAPI BackgroundTasks，
生产环境可切换为 Celery，业务层通过配置项 async_task_engine 控制。

设计目的：大文档上传、向量化等耗时操作不阻塞 HTTP 响应。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Any, Optional
from enum import Enum

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class AsyncTaskEngine(ABC):
    """异步任务引擎抽象基类"""

    @abstractmethod
    def submit(self, func: Callable, *args, **kwargs) -> str:
        """提交任务，返回任务 ID"""
        ...

    @abstractmethod
    def get_status(self, task_id: str) -> TaskStatus:
        """获取任务状态"""
        ...

    @abstractmethod
    def get_result(self, task_id: str) -> Optional[Any]:
        """获取任务结果（如果已完成）"""
        ...


# ==================== BackgroundTasks 引擎（开发/轻量场景）====================
class BackgroundTasksEngine(AsyncTaskEngine):
    """
    基于内存字典的简单异步任务引擎。
    适用于开发环境和单机部署，使用线程执行后台任务。
    """

    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._task_counter = 0

    def submit(self, func: Callable, *args, **kwargs) -> str:
        import threading
        self._task_counter += 1
        task_id = f"bg_task_{self._task_counter}"
        self._tasks[task_id] = {
            "status": TaskStatus.PENDING,
            "result": None,
            "error": None,
        }

        def _run():
            try:
                self._tasks[task_id]["status"] = TaskStatus.RUNNING
                result = func(*args, **kwargs)
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["status"] = TaskStatus.SUCCESS
                logger.info(f"后台任务 {task_id} 执行成功")
            except Exception as e:
                self._tasks[task_id]["error"] = str(e)
                self._tasks[task_id]["status"] = TaskStatus.FAILED
                logger.error(f"后台任务 {task_id} 执行失败: {str(e)}")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        logger.debug(f"提交后台任务: {task_id}")
        return task_id

    def get_status(self, task_id: str) -> TaskStatus:
        task = self._tasks.get(task_id)
        if not task:
            return TaskStatus.PENDING
        return task["status"]

    def get_result(self, task_id: str) -> Optional[Any]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return task.get("result")


# ==================== Celery 引擎（生产环境）====================
class CeleryEngine(AsyncTaskEngine):
    """
    Celery 异步任务引擎。
    生产环境使用，支持分布式、任务持久化、重试机制。
    实际使用时需要在 worker/tasks.py 中定义具体 Celery 任务。
    """

    def __init__(self):
        try:
            from celery import Celery
        except ImportError:
                raise ImportError(
                    "Celery 未安装，请执行 pip install celery redis"
                )
        self.app = Celery(
            "kb_assistant",
            broker=settings.celery_broker_url,
            backend=settings.celery_result_backend,
        )
        logger.info("Celery 异步任务引擎初始化完成")

    def submit(self, func: Callable, *args, **kwargs) -> str:
        # Celery 通过任务名分发，此处假设 func 必须是已注册的 Celery 任务
        # 生产环境建议直接调用 celery_task.delay()
        if hasattr(func, "delay"):
            result = func.delay(*args, **kwargs)
            return result.id
        else:
            # 如果不是 Celery 任务，尝试用 apply_async
            task = self.app.task(func)
            result = task.apply_async(args=args, kwargs=kwargs)
            return result.id

    def get_status(self, task_id: str) -> TaskStatus:
        from celery.result import AsyncResult
        result = AsyncResult(task_id, app=self.app)
        state_map = {
            "PENDING": TaskStatus.PENDING,
            "STARTED": TaskStatus.RUNNING,
            "SUCCESS": TaskStatus.SUCCESS,
            "FAILURE": TaskStatus.FAILED,
        }
        return state_map.get(result.state, TaskStatus.PENDING)

    def get_result(self, task_id: str) -> Optional[Any]:
        from celery.result import AsyncResult
        result = AsyncResult(task_id, app=self.app)
        if result.successful():
            return result.result
        return None


# ==================== 工厂函数 ====================
_engine: Optional[AsyncTaskEngine] = None


def get_task_engine() -> AsyncTaskEngine:
    """
    根据配置获取异步任务引擎单例"""
    global _engine
    if _engine is None:
        if settings.async_task_engine == "celery":
            _engine = CeleryEngine()
        else:
            _engine = BackgroundTasksEngine()
        logger.info(f"使用异步任务引擎: {settings.async_task_engine}")
    return _engine


def submit_task(func: Callable, *args, **kwargs) -> str:
    """
    便捷函数：提交异步任务

    Args:
        func: 要执行的函数
        *args, **kwargs: 函数参数

    Returns:
        任务 ID
    """
    engine = get_task_engine()
    return engine.submit(func, *args, **kwargs)


def get_task_status(task_id: str) -> TaskStatus:
    """便捷函数：获取任务状态"""
    engine = get_task_engine()
    return engine.get_status(task_id)
