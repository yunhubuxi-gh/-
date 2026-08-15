"""
RAG 流水线总控（对外统一入口）

职责编排：
- 文档入库：解析 → 分块 → 嵌入 → 写向量库 + BM25
- 检索召回：多路混合召回（BM25 + 向量 → 融合 → 重排）
- 问答生成：检索上下文 → 构建 Prompt → LLM 生成 → 幻觉抑制 → 引用标注

对外统一入口：
- retrieve(query, knowledge_base_ids, top_k) -> List[RetrievedChunk]
- answer(query, knowledge_base_ids, top_k) -> RagAnswer

存储边界：chunk 文本 + 向量存向量库，原始文档读 file_path，PG 只存元数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from ai.rag_engine.hybrid_retriever import HybridRetriever, RetrievedChunk
from ai.rag_engine.hallucination_detector import HallucinationDetector
from ai.rag_engine.doc_version_manager import DocVersionManager
from ai.rag_engine.citation_formatter import (
    Citation,
    build_citations,
    annotate_answer,
)
from ai.rag_engine.document_parser import parse_document, ParsedDocument
from config.settings import settings
from utils.logger import get_logger
from utils.exceptions import RAGException
from utils.error_codes import CHAT_NO_RELEVANT_DOCS

logger = get_logger(__name__)

# 生成阶段提示词
_SYSTEM_PROMPT = (
    "你是企业私有知识库智能助手。请严格遵循以下规则：\n"
    "1. 只依据下方提供的【检索上下文】回答问题，禁止使用外部知识或编造内容；\n"
    "2. 若检索上下文中没有相关信息，请明确回答「知识库中未找到相关信息」，不要猜测；\n"
    "3. 回答时在关键结论后用 [编号] 标注引用来源；\n"
    "4. 回答应简洁、准确、条理清晰。"
)


@dataclass
class RagAnswer:
    """RAG 问答结果"""
    answer: str
    citations: List[Citation] = field(default_factory=list)
    context_chunks: List[RetrievedChunk] = field(default_factory=list)
    grounded: bool = True
    no_answer: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "grounded": self.grounded,
            "no_answer": self.no_answer,
            "warnings": self.warnings,
        }


class RagPipeline:
    """
    RAG 流水线总控。

    依赖通过构造器注入（测试可注入 Fake），缺省时从工厂懒加载。
    """

    def __init__(
        self,
        vector_store=None,
        bm25_engine=None,
        embedding_client=None,
        reranker=None,
        llm_client=None,
        chunker=None,
    ):
        self.retriever = HybridRetriever(
            vector_store=vector_store,
            bm25_engine=bm25_engine,
            embedding_client=embedding_client,
            reranker=reranker,
        )
        self.version_manager = DocVersionManager(
            vector_store=vector_store,
            bm25_engine=bm25_engine,
            embedding_client=embedding_client,
        )
        self.embedding_client = embedding_client
        self.llm_client = llm_client
        self.chunker = chunker
        self.hallucination_detector = HallucinationDetector()

    # ---------- 懒加载 ----------

    def _get_chunker(self):
        if self.chunker is None:
            from ai.rag_engine.chunker import SemanticChunker
            # 语义分块复用同一嵌入客户端，避免重复加载模型
            self.chunker = SemanticChunker(embedding_client=self.embedding_client)
        return self.chunker

    def _get_llm(self):
        if self.llm_client is None:
            from utils.llm_client import get_llm_client
            self.llm_client = get_llm_client()
        return self.llm_client

    # ---------- 文档入库 ----------

    def ingest_document(
        self,
        knowledge_base_id: Any,
        document_id: Any,
        document_name: str,
        file_path: Optional[str] = None,
        parsed: Optional[ParsedDocument] = None,
    ) -> int:
        """
        文档入库：解析（可选）→ 分块 → 嵌入 → 写向量库 + BM25。

        Args:
            knowledge_base_id: 知识库 ID
            document_id: 文档 ID（DB 中的 document id）
            document_name: 文档名（用于引用展示）
            file_path: 磁盘文件路径（未传 parsed 时必填）
            parsed: 已解析文档（跳过解析步骤）

        Returns:
            写入的块数量
        """
        doc_id = str(document_id)
        kb_id = str(knowledge_base_id)

        if parsed is None:
            if not file_path:
                raise RAGException(CHAT_NO_RELEVANT_DOCS, "缺少 file_path 或 parsed 参数")
            parsed = parse_document(file_path)

        chunks = self._get_chunker().split(parsed, doc_id)
        if not chunks:
            logger.warning(f"文档分块结果为空: doc_id={doc_id}")
            return 0

        # 将文档名写入块元数据，保证引用溯源
        for chunk in chunks:
            chunk.metadata["document_name"] = document_name

        collection_name = f"kb_{kb_id}"
        count = self.version_manager.index_chunks(collection_name, chunks, kb_id)
        logger.info(
            f"文档入库完成: kb={kb_id}, doc={doc_id}, name={document_name}, chunks={count}"
        )
        return count

    def ingest_images(
        self,
        knowledge_base_id: Any,
        document_id: Any,
        document_name: str,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        图片多模态向量化入库（加法式扩展，不影响文本 ingest_document）。

        Args:
            knowledge_base_id: 知识库 ID
            document_id: 文档 ID
            document_name: 文档名
            images: [{image_path, page_number, index, ext}]，空则返回 0

        Returns:
            写入的图片数量（开关关闭/模型不可用时返回 0）
        """
        if not images:
            return 0
        from ai.rag_engine.image_retriever import get_image_retriever
        return get_image_retriever().index_images(
            knowledge_base_id, document_id, document_name, images,
        )

    # ---------- 检索召回 ----------

    def retrieve(
        self,
        query: str,
        knowledge_base_ids: Optional[List[Any]] = None,
        top_k: int = 5,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """
        统一检索入口：多路混合召回 + 重排 + （可选）图片跨模态召回。

        Args:
            query: 用户查询
            knowledge_base_ids: 知识库 ID 列表
            top_k: 返回条数

        Returns:
            RetrievedChunk 列表（含 chunk 文本 + 文档名/页码/块号等引用元数据；
            图片片段携带 chunk_type=image / image_path）
        """
        chunks = self.retriever.retrieve(
            query=query,
            knowledge_base_ids=knowledge_base_ids,
            top_k=top_k,
            **kwargs,
        )

        # 加法式图片召回：原有文本混合检索结果完全不动，仅在末尾追加图片结果
        try:
            from ai.rag_engine.image_retriever import get_image_retriever
            image_chunks = get_image_retriever().retrieve_images(
                query, knowledge_base_ids=knowledge_base_ids, top_k=top_k,
            )
        except Exception as e:
            logger.warning(f"图片检索失败，仅返回文本结果: {e}")
            image_chunks = []

        return chunks + image_chunks

    # ---------- 问答生成 ----------

    def answer(
        self,
        query: str,
        knowledge_base_ids: Optional[List[Any]] = None,
        top_k: int = 5,
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> RagAnswer:
        """
        统一问答入口：检索 → 生成 → 幻觉抑制 → 引用标注。

        Args:
            query: 用户问题
            knowledge_base_ids: 知识库 ID 列表
            top_k: 检索上下文条数
            history: 历史消息 [{"role": "user"/"assistant", "content": "..."}]

        Returns:
            RagAnswer（含回答、引用、上下文、幻觉检测结果）
        """
        # 1. 检索
        context_chunks = self.retrieve(query, knowledge_base_ids=knowledge_base_ids, top_k=top_k)

        # 2. 无上下文 → 明确告知，禁止编造
        if not context_chunks:
            return RagAnswer(
                answer="知识库中未找到相关信息，无法回答该问题。",
                context_chunks=[],
                grounded=False,
                no_answer=True,
                warnings=["检索上下文为空"],
            )

        # 3. 构建 Prompt
        citations = build_citations(context_chunks)
        context_text = self._build_context_text(context_chunks)
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        if history:
            messages.extend(history[-10:])
        messages.append({
            "role": "user",
            "content": f"【检索上下文】\n{context_text}\n\n【问题】\n{query}",
        })

        # 4. LLM 生成
        try:
            llm = self._get_llm()
            answer_text = llm.chat(messages, **kwargs)
        except Exception as e:
            raise RAGException(CHAT_NO_RELEVANT_DOCS, f"大模型调用失败: {e}") from e

        # 5. 幻觉抑制
        check = self.hallucination_detector.check(
            answer=answer_text,
            contexts=[c.content for c in context_chunks],
            context_scores=[c.score for c in context_chunks],
        )

        # 若判定无答案，返回明确提示
        if check.no_answer and not check.has_context:
            answer_text = "知识库中未找到相关信息，无法回答该问题。"

        # 6. 引用标注
        final_answer = annotate_answer(answer_text, citations)

        return RagAnswer(
            answer=final_answer,
            citations=citations,
            context_chunks=context_chunks,
            grounded=check.grounded,
            no_answer=check.no_answer,
            warnings=check.warnings,
        )

    # ---------- 内部工具 ----------

    @staticmethod
    def _build_context_text(chunks: List[RetrievedChunk]) -> str:
        """构建带编号的上下文文本，供 LLM 引用"""
        lines: List[str] = []
        for i, chunk in enumerate(chunks):
            doc_name = chunk.document_name or f"文档{chunk.document_id}"
            page = f"第{chunk.page_number}页" if chunk.page_number else "无页码"
            lines.append(f"[{i + 1}] ({doc_name} · {page} · 块{chunk.chunk_index + 1})\n{chunk.content}")
        return "\n\n".join(lines)
