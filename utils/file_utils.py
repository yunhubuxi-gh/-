"""
文件处理工具
- 文件格式检测与校验
- 安全文件名处理
- 路径安全校验（防止路径遍历攻击）
- 文件大小校验
"""
from __future__ import annotations

import os
import re
import uuid
import hashlib
from pathlib import Path
from typing import Optional, Tuple

from config.settings import settings
from config.constants import SUPPORTED_EXTENSIONS, DocumentType
from utils.logger import get_logger
from utils.exceptions import ValidationException
from utils.error_codes import (
    DOC_UNSUPPORTED_TYPE,
    DOC_FILE_TOO_LARGE,
    INVALID_PARAMS,
)

logger = get_logger(__name__)


# ==================== 文件名与路径安全 ====================


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除不安全字符。

    Args:
        filename: 原始文件名

    Returns:
        安全的文件名
    """
    # 移除路径分隔符与危险字符
    filename = os.path.basename(filename)
    # 只保留字母、数字、中文、下划线、点、中划线
    filename = re.sub(r"[^\w一-龥.\-]", "_", filename)
    # 去掉开头的点（隐藏文件）
    filename = filename.lstrip(".")
    # 限制长度
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:196] + ext
    return filename or "unnamed"


def generate_unique_filename(original_name: str) -> str:
    """
    生成唯一文件名（UUID + 原始扩展名），避免同名覆盖。

    Args:
        original_name: 原始文件名

    Returns:
        唯一文件名
    """
    _, ext = os.path.splitext(original_name)
    unique_name = f"{uuid.uuid4().hex}{ext.lower()}"
    return unique_name


def safe_join_path(base_dir: str | Path, *paths: str) -> Path:
    """
    安全拼接路径，防止路径遍历攻击（如 ../../etc/passwd）。

    Args:
        base_dir: 基础目录
        *paths: 要拼接的路径段

    Returns:
        安全的绝对路径

    Raises:
        ValidationException: 路径越界时抛出
    """
    base = Path(base_dir).resolve()
    target = (base / Path(*paths)).resolve()
    try:
        target.relative_to(base)
    except ValueError as e:
        raise ValidationException(INVALID_PARAMS, "非法路径") from e
    return target


# ==================== 文件格式检测 ====================


def get_file_extension(filename: str) -> str:
    """获取小写文件扩展名（带点，如 '.pdf'）"""
    return Path(filename).suffix.lower()


def detect_document_type(filename: str) -> Optional[DocumentType]:
    """
    根据文件名检测文档类型。

    Args:
        filename: 文件名

    Returns:
        DocumentType 枚举，不支持的类型返回 None
    """
    ext = get_file_extension(filename)
    return SUPPORTED_EXTENSIONS.get(ext)


def is_supported_file(filename: str) -> bool:
    """判断文件类型是否受支持"""
    return detect_document_type(filename) is not None


def validate_file(filename: str, file_size: int) -> Tuple[DocumentType, str]:
    """
    校验上传文件的类型与大小。

    Args:
        filename: 文件名
        file_size: 文件大小（字节）

    Returns:
        (文档类型, 安全文件名)

    Raises:
        ValidationException: 类型不支持或文件过大
    """
    doc_type = detect_document_type(filename)
    if doc_type is None:
        raise ValidationException(
            DOC_UNSUPPORTED_TYPE,
            f"不支持的文件类型: {get_file_extension(filename)}，"
            f"支持类型: {', '.join(SUPPORTED_EXTENSIONS.keys())}",
        )

    max_size = settings.max_file_size_mb * 1024 * 1024
    if file_size > max_size:
        raise ValidationException(
            DOC_FILE_TOO_LARGE,
            f"文件大小 {file_size / 1024 / 1024:.2f}MB，"
            f"超过限制 {settings.max_file_size_mb}MB",
        )

    safe_name = sanitize_filename(filename)
    return doc_type, safe_name


# ==================== 文件哈希 ====================


def compute_file_hash(file_path: str | Path, algorithm: str = "sha256") -> str:
    """
    计算文件哈希值，用于文件去重与版本识别。

    Args:
        file_path: 文件路径
        algorithm: 哈希算法（md5 / sha1 / sha256）

    Returns:
        十六进制哈希字符串
    """
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ==================== 目录管理 ====================


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在，不存在则创建"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_upload_path(knowledge_base_id: str = "default") -> Path:
    """
    获取知识库的上传目录路径。

    Args:
        knowledge_base_id: 知识库 ID

    Returns:
        上传目录路径
    """
    path = Path(settings.upload_dir) / knowledge_base_id
    ensure_dir(path)
    return path


def get_export_path() -> Path:
    """获取导出文件目录"""
    path = Path(settings.export_dir)
    ensure_dir(path)
    return path


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读形式"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f}MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f}GB"
