"""
文档服务（document_service）

职责：
- 文档上传：文件校验（类型/大小/路径安全）→ SHA256 去重 → 存文件系统 → 建元数据记录 → 建版本记录
- 向量化入库：通过 utils.async_task 提交后台任务（大文档不阻塞业务方法），
  后台任务内解析（rag_engine.parse_document）→ RagPipeline.ingest_document（分块/嵌入/写向量库+BM25）
- 文档删除：软删除记录 + 清理向量库/BM25 索引（rag_engine.version_manager）+ 更新知识库统计
- 版本管理：每次上传新建 document_versions 版本记录，支持查看历史版本
- 权限：上传/编辑/删除需 write+，查看/下载需 read+

存储边界铁则（严格遵守）：
- 原始文件二进制 -> 文件系统（settings.upload_dir / kb_{kb_id} / uuid.ext）
- chunk 文本 + 向量 -> 向量库（RagPipeline 内部处理）
- PG 只存元数据（documents / document_versions 表）

依赖：
- db.crud.document_crud / kb_crud：元数据操作（不写原生 SQL）
- ai.rag_engine：parse_document + RagPipeline（不重写解析/召回）
- utils.file_utils：文件安全（路径遍历防护 / 类型大小校验 / 哈希）
- utils.async_task：异步任务抽象（后台线程执行，业务不阻塞）
- 审计：上传/编辑/删除/重建全部走 services.write_audit_log
"""
from __future__ import annotations

import hashlib
import os

from typing import Dict, Any, Optional, List

from config.settings import settings
from config.constants import KBUserRole, DocumentStatus, DocumentType, AuditAction, AuditResult
from db.models import Document
from db.crud import document_crud, kb_crud
from db.schemas import DocumentQuery
from utils.file_utils import (
    validate_file,
    get_upload_path,
    generate_unique_filename,
    safe_join_path,
    sanitize_filename,
)
from utils.async_task import submit_task
from utils.permission import has_permission
from utils.exceptions import (
    ResourceNotFoundException,
    ValidationException,
    PermissionException,
    FileOperationException,
)
from utils.error_codes import (
    KB_NOT_FOUND,
    KB_NO_PERMISSION,
    DOC_NOT_FOUND,
    DOC_UPLOAD_FAILED,
    RESOURCE_ALREADY_EXISTS,
)
from utils.response import page_result
from utils.logger import get_logger
from services import write_audit_log

logger = get_logger(__name__)


class DocumentService:
    """文档服务"""

    def __init__(self, rag_pipeline=None):
        # 可注入（测试用 Fake），缺省懒加载真实 RagPipeline
        self.rag_pipeline = rag_pipeline

    # ============================================================
    # 上传
    # ============================================================

    def upload(
        self, db, user_id: int, kb_id: int, filename: str, file_content: bytes,
    ) -> Dict[str, Any]:
        """上传文档：校验 → 去重 → 存盘 → 建记录 → 异步向量化"""
        # 1. 知识库存在 + write 权限
        kb = self._get_kb(db, kb_id)
        self._check_permission(db, kb_id, user_id, KBUserRole.WRITE, "doc_upload",
                               AuditAction.DOC_UPLOAD.value)

        # 2. 文件类型/大小校验 + 内容非空
        if not file_content:
            raise ValidationException(DOC_UPLOAD_FAILED, "文件内容为空")
        doc_type, _ = validate_file(filename, len(file_content))
        file_hash = hashlib.sha256(file_content).hexdigest()

        # 3. 同知识库下哈希去重
        existing = document_crud.get_by_hash(db, kb_id, file_hash)
        if existing:
            raise ValidationException(
                RESOURCE_ALREADY_EXISTS,
                f"该文件已存在（文档ID {existing.id}，标题 {existing.title}）",
            )

        # 4. 存文件系统（UUID 文件名 + 路径安全拼接，防止路径遍历）
        upload_dir = get_upload_path(f"kb_{kb_id}")
        unique_name = generate_unique_filename(filename)
        target_path = safe_join_path(upload_dir, unique_name)
        try:
            with open(target_path, "wb") as f:
                f.write(file_content)
        except OSError as e:
            raise FileOperationException(DOC_UPLOAD_FAILED, f"文件保存失败: {e}") from e

        # 5. 建元数据记录 + 版本记录（v1）
        safe_name = sanitize_filename(filename)
        doc = document_crud.create(
            db, kb_id, user_id,
            title=safe_name,
            file_name=filename,
            file_path=str(target_path),
            file_size=len(file_content),
            doc_type=doc_type.value,
            file_hash=file_hash,
        )
        document_crud.add_version(
            db, doc.id, version=1,
            file_path=str(target_path), file_hash=file_hash,
            file_size=len(file_content), uploaded_by=user_id,
        )

        # 6. 异步向量化（走 utils 异步任务抽象，不阻塞业务方法）
        task_id = submit_task(
            self._process_document, doc.id, kb_id, str(target_path), filename,
        )

        # 7. 审计
        write_audit_log(
            db, user_id, AuditAction.DOC_UPLOAD.value,
            resource_type="doc", resource_id=doc.id,
            details={
                "kb_id": kb_id, "file_name": filename,
                "size": len(file_content), "task_id": task_id,
            },
        )
        logger.info(f"文档上传: doc_id={doc.id}, kb_id={kb_id}, name={filename}")
        return {
            "document_id": doc.id,
            "title": safe_name,
            "file_name": filename,
            "file_size": len(file_content),
            "status": doc.status,
            "task_id": task_id,
        }

    def _process_document(self, document_id: int, kb_id: int, file_path: str, file_name: str) -> int:
        """后台任务：解析 → 提取图片 → OCR → 文本向量化 → 图片向量化 → 状态流转"""
        from db.session import SyncSessionLocal
        db = SyncSessionLocal()
        try:
            # 0. 清理旧的图片向量（重建场景避免孤儿；首次上传为空操作）
            self._clear_image_vectors(kb_id, document_id)

            # 1. 解析文件
            document_crud.update_status(db, document_id, DocumentStatus.PARSING.value)
            parsed = self._parse(file_path)
            document_crud.update_stats(
                db, document_id, page_count=parsed.page_count, char_count=parsed.char_count,
            )

            # 2. 提取图片（PDF 内嵌图）→ 落盘；图片文件则直接复用其自身
            image_items: List[Dict[str, Any]] = []
            if self._image_embed_enabled():
                document_crud.update_status(db, document_id, DocumentStatus.EXTRACTING_IMAGES.value)
                image_items = self._collect_images(document_id, kb_id, file_path, parsed)

            # 3. 文本分块 & 文本向量化（原有文本 RAG 链路，完全不动）
            document_crud.update_status(db, document_id, DocumentStatus.EMBEDDING.value)
            pipeline = self._get_pipeline()
            chunk_count = pipeline.ingest_document(
                kb_id, document_id, file_name, parsed=parsed,
            )

            # 4. 图片多模态 Embedding 向量化（写入独立集合）
            image_count = 0
            if image_items:
                document_crud.update_status(db, document_id, DocumentStatus.IMAGE_EMBEDDING.value)
                image_count = pipeline.ingest_images(kb_id, document_id, file_name, image_items)

            # 5. 完成
            document_crud.update_stats(db, document_id, chunk_count=chunk_count)
            document_crud.update_status(db, document_id, DocumentStatus.READY.value)
            kb_crud.update_stats(db, kb_id, doc_delta=1, chunk_delta=chunk_count)
            logger.info(
                f"文档处理完成: doc={document_id}, chunks={chunk_count}, images={image_count}"
            )
            return chunk_count
        except Exception as e:
            logger.error(f"文档处理失败: doc={document_id}, err={e}")
            try:
                document_crud.update_status(
                    db, document_id, DocumentStatus.FAILED.value, str(e),
                )
            except Exception:
                pass
            return 0
        finally:
            db.close()

    # ============================================================
    # 图片多模态辅助（加法式，开关关闭时完全跳过）
    # ============================================================

    @staticmethod
    def _image_embed_enabled() -> bool:
        """图片向量化开关 + 多模态客户端可用性双重判断"""
        if not settings.enable_image_embed:
            return False
        try:
            from utils.multimodal_embedding_client import get_multimodal_client
            return get_multimodal_client() is not None
        except Exception:
            return False

    @staticmethod
    def _clear_image_vectors(kb_id: int, document_id: int) -> None:
        """清理文档旧的图片向量（删除/重建时避免孤儿向量），失败静默"""
        try:
            from ai.rag_engine.image_retriever import get_image_retriever
            get_image_retriever().clear_document_images(kb_id, document_id)
        except Exception as e:
            logger.warning(f"清理图片向量失败: kb={kb_id}, doc={document_id}, err={e}")

    def _collect_images(
        self, document_id: int, kb_id: int, file_path: str, parsed,
    ) -> List[Dict[str, Any]]:
        """
        收集待向量化的图片：
        - 图片文件（png/jpg）：文件本身即图片，直接复用 file_path
        - PDF：将 parsed.images（内存态字节）落盘到上传目录，返回磁盘路径
        """
        items: List[Dict[str, Any]] = []
        fmt = (parsed.metadata or {}).get("format", "")

        if fmt == "image":
            ext = os.path.splitext(file_path)[1].lstrip(".").lower() or "png"
            try:
                with open(file_path, "rb") as f:
                    raw = f.read()
            except OSError:
                raw = b""
            # 复制到标准图片目录，保证前端可通过 doc_id+页码+序号 统一取图
            saved = self._save_image_bytes(kb_id, document_id, 1, 0, ext, raw) if raw else None
            if saved:
                items.append({
                    "image_path": saved,
                    "page_number": 1,
                    "index": 0,
                    "ext": ext,
                })
            return items

        # PDF 等：落盘内嵌图片
        for img in (parsed.images or []):
            saved = self._save_image_bytes(kb_id, document_id, img.page_number, img.index,
                                           img.ext, img.image_bytes)
            if saved:
                items.append({
                    "image_path": saved,
                    "page_number": img.page_number,
                    "index": img.index,
                    "ext": img.ext,
                })
        return items

    @staticmethod
    def _save_image_bytes(
        kb_id: int, document_id: int, page_number: int, index: int, ext: str, image_bytes: bytes,
    ) -> Optional[str]:
        """把提取出的图片字节写入上传目录，返回磁盘路径（失败返回 None）"""
        try:
            from utils.file_utils import get_upload_path
            ext = (ext or "png").lower().lstrip(".")
            if ext not in ("png", "jpg", "jpeg"):
                ext = "png"
            img_dir = get_upload_path(f"kb_{kb_id}") / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            name = f"doc_{document_id}_p{page_number}_{index}.{ext}"
            target = img_dir / name
            with open(target, "wb") as f:
                f.write(image_bytes)
            return str(target.resolve())
        except Exception as e:
            logger.warning(f"图片落盘失败: {e}")
            return None

    @staticmethod
    def _parse(file_path: str):
        """解析文档（复用 rag_engine 统一入口，不重写解析逻辑）"""
        from ai.rag_engine.document_parser import parse_document
        return parse_document(file_path)

    # ============================================================
    # 查询
    # ============================================================

    def list(self, db, user_id: int, query: DocumentQuery) -> Dict[str, Any]:
        """文档列表（read+）"""
        self._check_permission(db, query.knowledge_base_id, user_id, KBUserRole.READ,
                               "doc_list", audit_on_deny=False)
        docs, total = document_crud.get_list_by_kb(
            db, query.knowledge_base_id, query.keyword, query.status,
            query.doc_type, query.page, query.page_size,
        )
        items = [self._to_doc_dict(d) for d in docs]
        return page_result(items, total, query.page, query.page_size)

    def get(self, db, user_id: int, doc_id: int) -> Dict[str, Any]:
        """文档详情（read+）"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.READ,
                               "doc_get", audit_on_deny=False)
        return self._to_doc_dict(doc)

    def list_versions(self, db, user_id: int, doc_id: int) -> list:
        """文档版本列表（read+）"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.READ,
                               "doc_versions", audit_on_deny=False)
        versions = document_crud.list_versions(db, doc_id)
        return [v.to_dict() for v in versions]

    def get_file_content(self, db, user_id: int, doc_id: int) -> Optional[bytes]:
        """读取文档原始文件内容（read+，通过 db.file_path 读取，供下载/预览）"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.READ,
                               "doc_download", audit_on_deny=False)
        try:
            with open(doc.file_path, "rb") as f:
                return f.read()
        except OSError as e:
            raise FileOperationException(DOC_NOT_FOUND, f"文件读取失败: {e}") from e

    def get_image_content(
        self, db, user_id: int, doc_id: int, page_number: int, index: int,
    ) -> tuple[bytes, str]:
        """读取文档内嵌图片字节（read+），供前端渲染检索到的图片片段"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.READ,
                               "doc_image", audit_on_deny=False)
        img_dir = get_upload_path(f"kb_{doc.knowledge_base_id}") / "images"
        matches = sorted(img_dir.glob(f"doc_{doc_id}_p{page_number}_{index}.*"))
        if not matches:
            raise ResourceNotFoundException(DOC_NOT_FOUND, "图片不存在")
        path = matches[0]
        ext = path.suffix.lstrip(".").lower()
        media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
            ext, "application/octet-stream"
        )
        try:
            return path.read_bytes(), media
        except OSError as e:
            raise FileOperationException(DOC_NOT_FOUND, f"图片读取失败: {e}") from e

    # ============================================================
    # 编辑 / 删除 / 重建
    # ============================================================

    def update_title(self, db, user_id: int, doc_id: int, title: str) -> Dict[str, Any]:
        """修改文档标题（write+）"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.WRITE,
                               "doc_update", AuditAction.DOC_UPDATE.value)
        doc = document_crud.update_title(db, doc_id, title)
        write_audit_log(
            db, user_id, AuditAction.DOC_UPDATE.value,
            resource_type="doc", resource_id=doc_id,
            details={"kb_id": doc.knowledge_base_id, "title": title},
        )
        return self._to_doc_dict(doc)

    def delete(self, db, user_id: int, doc_id: int) -> bool:
        """删除文档（write+）：软删除 + 清理向量/BM25 索引 + 更新知识库统计"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.WRITE,
                               "doc_delete", AuditAction.DOC_DELETE.value)
        kb_id = doc.knowledge_base_id
        old_chunk_count = doc.chunk_count or 0

        # 清理向量库 / BM25 索引（复用 rag_engine 版本管理原语）
        try:
            pipeline = self._get_pipeline()
            pipeline.version_manager.clear_document_chunks(f"kb_{kb_id}", str(doc_id))
        except Exception as e:
            logger.warning(f"清理文档索引失败（继续删除）: {e}")

        # 清理图片向量（多模态集合 kb_{id}_img）
        self._clear_image_vectors(kb_id, doc_id)

        document_crud.delete(db, doc_id)
        kb_crud.update_stats(db, kb_id, doc_delta=-1, chunk_delta=-old_chunk_count)

        write_audit_log(
            db, user_id, AuditAction.DOC_DELETE.value,
            resource_type="doc", resource_id=doc_id,
            details={"kb_id": kb_id, "file_name": doc.file_name},
        )
        return True

    def reindex(self, db, user_id: int, doc_id: int) -> Dict[str, Any]:
        """重建文档索引（write+）：清理旧索引后重新解析当前版本文件并入库"""
        doc = self._get_doc(db, doc_id)
        self._check_permission(db, doc.knowledge_base_id, user_id, KBUserRole.WRITE,
                               "doc_rebuild", AuditAction.DOC_REBUILD.value)
        if doc.status == DocumentStatus.READY.value:
            try:
                self._get_pipeline().version_manager.clear_document_chunks(
                    f"kb_{doc.knowledge_base_id}", str(doc_id),
                )
            except Exception as e:
                logger.warning(f"清理旧索引失败: {e}")
        task_id = submit_task(
            self._process_document, doc.id, doc.knowledge_base_id, doc.file_path, doc.file_name,
        )
        write_audit_log(
            db, user_id, AuditAction.DOC_REBUILD.value,
            resource_type="doc", resource_id=doc_id,
            details={"kb_id": doc.knowledge_base_id, "task_id": task_id},
        )
        return {"document_id": doc.id, "status": "rebuilding", "task_id": task_id}

    # ============================================================
    # 内部工具
    # ============================================================

    def _get_pipeline(self):
        if self.rag_pipeline is None:
            from ai.rag_engine.rag_pipeline import RagPipeline
            self.rag_pipeline = RagPipeline()
        return self.rag_pipeline

    def _get_kb(self, db, kb_id: int):
        kb = kb_crud.get_by_id(db, kb_id)
        if not kb:
            raise ResourceNotFoundException(KB_NOT_FOUND, f"知识库 {kb_id} 不存在")
        return kb

    def _get_doc(self, db, doc_id: int) -> Document:
        doc = document_crud.get_by_id(db, doc_id)
        if not doc:
            raise ResourceNotFoundException(DOC_NOT_FOUND, f"文档 {doc_id} 不存在")
        return doc

    def _check_permission(
        self, db, kb_id: int, user_id: int,
        required_role: KBUserRole, resource: str,
        action: str = AuditAction.DOC_UPDATE.value,
        audit_on_deny: bool = True,
    ) -> None:
        """知识库权限校验，越权抛 PermissionException 并写审计（permission_denied）"""
        role = kb_crud.get_user_role(db, kb_id, user_id)
        if role is None:
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": resource, "user_role": None, "required": required_role.value},
                )
            raise PermissionException(
                KB_NO_PERMISSION, "无该知识库访问权限", {"resource": f"kb_{kb_id}"},
            )
        if not has_permission(role, required_role):
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": resource, "user_role": role, "required": required_role.value},
                )
            raise PermissionException(
                KB_NO_PERMISSION, f"需要 {required_role.value} 权限", {"resource": f"kb_{kb_id}"},
            )

    @staticmethod
    def _to_doc_dict(doc: Document) -> Dict[str, Any]:
        return doc.to_dict()


# 单例
document_service = DocumentService()
