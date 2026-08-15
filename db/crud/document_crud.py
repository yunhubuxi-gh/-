"""
文档 CRUD
只存元数据，不存文档正文与向量。
"""
from __future__ import annotations

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from db.models import Document, DocumentVersion
from config.constants import DocumentStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class DocumentCRUD:
    """文档 CRUD 封装类"""

    model = Document
    version_model = DocumentVersion

    # ---------- 查询 ----------

    def get_by_id(self, db: Session, doc_id: int) -> Optional[Document]:
        """根据 ID 获取文档"""
        return db.query(Document).filter(
            Document.id == doc_id,
            Document.is_deleted == False,  # noqa: E712
        ).first()

    def get_list_by_kb(
        self,
        db: Session,
        kb_id: int,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        doc_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Document], int]:
        """分页获取知识库下的文档列表"""
        query = db.query(Document).filter(
            Document.knowledge_base_id == kb_id,
            Document.is_deleted == False,  # noqa: E712
        )

        if keyword:
            query = query.filter(Document.title.like(f"%{keyword}%"))
        if status:
            query = query.filter(Document.status == status)
        if doc_type:
            query = query.filter(Document.doc_type == doc_type)

        total = query.count()
        docs = query.order_by(Document.updated_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return docs, total

    def get_by_hash(self, db: Session, kb_id: int, file_hash: str) -> Optional[Document]:
        """根据文件哈希查找（用于去重）"""
        return db.query(Document).filter(
            Document.knowledge_base_id == kb_id,
            Document.file_hash == file_hash,
            Document.is_deleted == False,  # noqa: E712
        ).first()

    def get_ready_docs_count(self, db: Session, kb_id: int) -> int:
        """获取知识库中就绪状态的文档数"""
        return db.query(Document).filter(
            Document.knowledge_base_id == kb_id,
            Document.status == DocumentStatus.READY.value,
            Document.is_deleted == False,  # noqa: E712
        ).count()

    # ---------- 创建 ----------

    def create(
        self,
        db: Session,
        kb_id: int,
        uploader_id: int,
        title: str,
        file_name: str,
        file_path: str,
        file_size: int,
        doc_type: str,
        file_hash: Optional[str] = None,
    ) -> Document:
        """创建文档元数据记录"""
        doc = Document(
            title=title,
            doc_type=doc_type,
            knowledge_base_id=kb_id,
            uploader_id=uploader_id,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_hash=file_hash,
            status=DocumentStatus.UPLOADED.value,
            current_version=1,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        logger.info(
            f"创建文档: id={doc.id}, kb_id={kb_id}, "
            f"title={title[:30]}, size={file_size}"
        )
        return doc

    # ---------- 更新 ----------

    def update_status(
        self,
        db: Session,
        doc_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[Document]:
        """更新文档处理状态"""
        doc = self.get_by_id(db, doc_id)
        if not doc:
            return None
        doc.status = status
        if error_message is not None:
            doc.error_message = error_message
        db.commit()
        db.refresh(doc)
        logger.debug(f"文档状态更新: id={doc_id}, status={status}")
        return doc

    def update_stats(
        self,
        db: Session,
        doc_id: int,
        page_count: Optional[int] = None,
        char_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
    ) -> Optional[Document]:
        """更新文档统计信息"""
        doc = self.get_by_id(db, doc_id)
        if not doc:
            return None
        if page_count is not None:
            doc.page_count = page_count
        if char_count is not None:
            doc.char_count = char_count
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        db.commit()
        db.refresh(doc)
        return doc

    def update_title(self, db: Session, doc_id: int, title: str) -> Optional[Document]:
        """更新文档标题"""
        doc = self.get_by_id(db, doc_id)
        if not doc:
            return None
        doc.title = title
        db.commit()
        db.refresh(doc)
        return doc

    # ---------- 删除 ----------

    def delete(self, db: Session, doc_id: int) -> bool:
        """软删除文档"""
        doc = self.get_by_id(db, doc_id)
        if not doc:
            return False
        doc.is_deleted = True
        db.commit()
        logger.info(f"删除文档: id={doc_id}")
        return True

    # ---------- 版本管理 ----------

    def add_version(
        self,
        db: Session,
        doc_id: int,
        version: int,
        file_path: str,
        file_hash: str,
        file_size: int,
        uploaded_by: int,
        change_log: Optional[str] = None,
    ) -> DocumentVersion:
        """添加新版本"""
        ver = DocumentVersion(
            document_id=doc_id,
            version=version,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            uploaded_by=uploaded_by,
            change_log=change_log,
        )
        db.add(ver)
        db.commit()
        db.refresh(ver)
        logger.info(f"文档新版本: doc_id={doc_id}, version={version}")
        return ver

    def get_version(self, db: Session, doc_id: int, version: int) -> Optional[DocumentVersion]:
        """获取指定版本"""
        return db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version == version,
            DocumentVersion.is_deleted == False,  # noqa: E712
        ).first()

    def list_versions(self, db: Session, doc_id: int) -> List[DocumentVersion]:
        """列出所有版本"""
        return db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.is_deleted == False,  # noqa: E712
        ).order_by(DocumentVersion.version.desc()).all()


# 单例
document_crud = DocumentCRUD()
