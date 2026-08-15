"""
双 Agent 工作流 JSON 解析工具

LLM 输出不稳定，解析逻辑做多格式兜底：
- 剥离 markdown code fence（```json ... ```）
- 从首个 { / [ 截取到最后一个 } / ]
- json.loads 失败时逐行/关键词兜底
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional


def _strip_fence(text: str) -> str:
    """剥离 markdown code fence 与首尾空白"""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return text


def extract_json_object(text: str) -> Optional[dict]:
    """从 LLM 输出中提取单个 JSON 对象（字典）"""
    text = _strip_fence(text)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def extract_json_array(text: str) -> Optional[list]:
    """从 LLM 输出中提取 JSON 数组"""
    text = _strip_fence(text)
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, list):
                return data
        except Exception:
            return None
    return None


def extract_questions(raw: str) -> list:
    """
    从命题 Agent 输出中提取题目列表。
    兼容 {"questions": [...]} 或直接 [...] 两种格式。
    """
    obj = extract_json_object(raw)
    if isinstance(obj, dict) and isinstance(obj.get("questions"), list):
        return obj["questions"]
    arr = extract_json_array(raw)
    return arr or []
