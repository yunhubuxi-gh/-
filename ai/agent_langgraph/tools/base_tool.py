"""
Agent 工具基类
定义所有工具的统一接口、元数据规范，以及工具分类枚举。

工具分为两大类：
1. INTERNAL_RAG  — 内部 RAG 检索工具（如知识库搜索）
2. EXTERNAL_BIZ  — 外部业务工具（如文档摘要、导出CSV、周报生成）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Type, Any, Dict
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger(__name__)


class ToolCategory(str, Enum):
    """
    工具分类枚举
    Agent 在规划阶段可以根据分类选择工具，也便于前端展示与权限控制
    """
    INTERNAL_RAG = "internal_rag"   # 内部 RAG 检索工具
    EXTERNAL_BIZ = "external_biz"   # 外部业务工具


class BaseTool(ABC):
    """
    Agent 工具抽象基类

    所有自定义工具需继承此类并实现：
    - name: 工具唯一标识（英文小写下划线）
    - display_name: 展示名称（中文）
    - category: 工具分类
    - description: 工具功能描述（供 LLM 理解）
    - args_schema: 输入参数的 Pydantic 模型
    - result_schema: 输出结果的 Pydantic 模型
    - _execute(): 实际执行逻辑
    """

    # 工具元数据（子类必须覆盖）
    name: str = ""
    display_name: str = ""
    category: ToolCategory = ToolCategory.EXTERNAL_BIZ
    description: str = ""

    # 输入/输出 Schema（子类必须覆盖）
    args_schema: Type[BaseModel] = BaseModel
    result_schema: Type[BaseModel] = BaseModel

    def __init__(self, **kwargs):
        if not self.name:
            raise ValueError("工具必须定义 name 属性")
        if not self.description:
            raise ValueError("工具必须定义 description 属性")

    def run(self, **kwargs) -> Dict[str, Any]:
        """
        工具执行入口（供 Agent 调用）

        Args:
            **kwargs: 工具参数

        Returns:
            执行结果字典（含 status, data, error 字段）
        """
        try:
            # 参数校验
            input_data = self.args_schema(**kwargs)
            logger.debug(f"执行工具 {self.name}, 参数: {input_data.model_dump()}")

            # 调用具体实现
            result = self._execute(input_data)

            # 结果校验
            if isinstance(result, self.result_schema):
                output = result.model_dump()
            elif isinstance(result, dict):
                output = result
            else:
                raise ValueError(f"工具 {self.name} 返回值类型错误")

            logger.debug(f"工具 {self.name} 执行成功")
            return {"status": "success", "data": output, "error": None}

        except Exception as e:
            logger.error(f"工具 {self.name} 执行失败: {str(e)}")
            return {"status": "failed", "data": None, "error": str(e)}

    @abstractmethod
    def _execute(self, input_data: BaseModel) -> BaseModel:
        """
        工具实际执行逻辑（子类必须实现）

        Args:
            input_data: 已校验的输入参数

        Returns:
            工具执行结果
        """
        ...

    def to_openai_tool(self) -> Dict[str, Any]:
        """
        转换为 OpenAI Function Calling 格式的工具定义，
        供 LangGraph / LLM 工具调用使用。

        Returns:
            OpenAI 函数定义字典
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            },
        }

    @classmethod
    def get_tool_info(cls) -> Dict[str, Any]:
        """获取工具基本信息（用于工具列表展示）"""
        return {
            "name": cls.name,
            "display_name": cls.display_name,
            "category": cls.category.value if isinstance(cls.category, ToolCategory) else cls.category,
            "description": cls.description,
        }
