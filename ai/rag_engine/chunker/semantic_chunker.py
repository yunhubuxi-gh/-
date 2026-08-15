"""
语义分块器

核心思想：不是简单按固定长度切割，而是通过嵌入向量的语义相似度检测「主题边界」。
- 将文档拆为句子，逐句计算与当前缓冲块的语义相似度
- 相似度低于阈值 → 判定为语义边界，切分新块
- 嵌入模型不可用时，优雅降级为递归分块器

参数全部读取 config（chunk_size / chunk_overlap / semantic_chunk_threshold）。
"""
from __future__ import annotations

from typing import List, Tuple, Optional

from ai.rag_engine.chunker.base_chunker import BaseChunker, Chunk
from ai.rag_engine.chunker.recursive_chunker import RecursiveChunker
from ai.rag_engine.document_parser.base_parser import ParsedDocument
from config.settings import settings
from utils.text_utils import cosine_similarity
from utils.logger import get_logger

logger = get_logger(__name__)

# 中文句子切分符号
_SENTENCE_END = "。！？!?；;\n"


class SemanticChunker(BaseChunker):
    """
    语义分块器（嵌入相似度边界检测 + 递归兜底）
    """

    def __init__(
        self,
        embedding_client=None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        threshold: float | None = None,
    ):
        """
        Args:
            embedding_client: 嵌入客户端（需实现 embed(texts) -> List[List[float]]），
                              缺省时懒加载 utils.embedding_client.get_embedding_client()
            chunk_size: 块最大字符数
            chunk_overlap: 相邻块重叠字符数
            threshold: 语义切分相似度阈值，低于则切分
        """
        self._embedding_client = embedding_client
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.threshold = threshold or settings.semantic_chunk_threshold
        self._fallback = RecursiveChunker(self.chunk_size, self.chunk_overlap)

    def _get_embedding_client(self):
        if self._embedding_client is None:
            try:
                from utils.embedding_client import get_embedding_client
                self._embedding_client = get_embedding_client()
            except Exception as e:
                logger.warning(f"嵌入模型初始化失败，语义分块降级为递归分块: {e}")
                return None
        return self._embedding_client

    def split(self, parsed: ParsedDocument, document_id: str) -> List[Chunk]:
        client = self._get_embedding_client()
        if client is None or not hasattr(client, "embed"):
            logger.debug("嵌入客户端不可用，使用递归分块器")
            return self._fallback.split(parsed, document_id)

        # 逐句切分并保留页码
        sentences: List[Tuple[str, int]] = []
        for page in parsed.pages:
            for sent in self._split_sentences(page.text):
                sent = sent.strip()
                if sent:
                    sentences.append((sent, page.page_number))

        if not sentences:
            return []

        try:
            embeddings = client.embed([s for s, _ in sentences])
        except Exception as e:
            logger.warning(f"嵌入失败，语义分块降级为递归分块: {e}")
            return self._fallback.split(parsed, document_id)

        # 基于语义相似度聚合句子
        chunks: List[Chunk] = []
        buf: List[Tuple[str, int]] = [sentences[0]]
        buf_emb = embeddings[0]
        buf_len = len(sentences[0][0])

        for (sent, page), emb in zip(sentences[1:], embeddings[1:]):
            if buf_len + len(sent) + 1 > self.chunk_size:
                # 达到长度上限，切分（重叠：保留上一句）
                chunks.append(self._make_chunk(buf, document_id, len(chunks)))
                overlap = self._tail_overlap_sentence(buf)
                if overlap:
                    buf, buf_len = [overlap], len(overlap[0])
                    buf_emb = self._embed_one(client, overlap[0]) or emb
                else:
                    buf, buf_len = [], 0
                    buf_emb = None

            # 语义边界检测
            if buf_emb is not None and cosine_similarity(buf_emb, emb) < self.threshold:
                chunks.append(self._make_chunk(buf, document_id, len(chunks)))
                buf, buf_len, buf_emb = [(sent, page)], len(sent), emb
            else:
                if not buf:
                    buf, buf_len = [(sent, page)], len(sent)
                    buf_emb = emb
                else:
                    buf.append((sent, page))
                    buf_emb = self._avg_embeddings([buf_emb, emb])
                    buf_len += len(sent) + 1

        if buf:
            chunks.append(self._make_chunk(buf, document_id, len(chunks)))

        logger.debug(
            f"语义分块完成: document_id={document_id}, chunks={len(chunks)}, "
            f"threshold={self.threshold}"
        )
        return chunks

    # ---------- 内部工具 ----------

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """按句末标点切分句子，保留标点"""
        result: List[str] = []
        start = 0
        for i, ch in enumerate(text):
            if ch in _SENTENCE_END:
                result.append(text[start:i + 1])
                start = i + 1
        if start < len(text):
            result.append(text[start:])
        return [s for s in result if s.strip()]

    def _tail_overlap_sentence(self, buf: List[Tuple[str, int]]) -> Optional[Tuple[str, int]]:
        """取上一块末尾句子作为重叠"""
        return buf[-1] if buf else None

    def _embed_one(self, client, text: str) -> Optional[List[float]]:
        try:
            return client.embed([text])[0]
        except Exception:
            return None

    @staticmethod
    def _avg_embeddings(emb_list: List[List[float]]) -> List[float]:
        n = len(emb_list)
        dim = len(emb_list[0])
        return [sum(emb[i] for emb in emb_list) / n for i in range(dim)]

    @staticmethod
    def _make_chunk(buf: List[Tuple[str, int]], document_id: str, index: int) -> Chunk:
        text = "\n".join(s for s, _ in buf).strip()
        page_number = buf[0][1]
        return Chunk(
            chunk_id=f"doc_{document_id}:{index}",
            document_id=document_id,
            text=text,
            page_number=page_number,
            chunk_index=index,
            start_char=0,
            end_char=len(text),
        )
