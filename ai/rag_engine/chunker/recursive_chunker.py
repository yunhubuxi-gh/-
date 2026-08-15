"""
递归字符分块器（兜底策略）

按分隔符优先级递归切分文本，保证 chunk 大小不超过 chunk_size，
同时保留 chunk_overlap 重叠，避免关键信息被切断。
"""
from __future__ import annotations

from typing import List, Tuple

from ai.rag_engine.chunker.base_chunker import BaseChunker, Chunk
from ai.rag_engine.document_parser.base_parser import ParsedDocument
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# 分隔符优先级：段落 -> 换行 -> 句子 -> 逗号/空格 -> 字符
DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", "，", ",", " ", ""]


class RecursiveChunker(BaseChunker):
    """递归字符分块器（带页码溯源）"""

    def __init__(self, chunk_size: int | None = None, chunk_overlap: int | None = None):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def split(self, parsed: ParsedDocument, document_id: str) -> List[Chunk]:
        # 1. 每页文本切成句子/段落片段，并保留页码
        segments: List[Tuple[str, int]] = []
        for page in parsed.pages:
            for seg in self._split_text(page.text, DEFAULT_SEPARATORS):
                seg = seg.strip()
                if seg:
                    segments.append((seg, page.page_number))

        # 2. 按 chunk_size 聚合片段
        chunks: List[Chunk] = []
        buf: List[str] = []
        buf_len = 0
        buf_page = segments[0][1] if segments else 1

        for seg, page in segments:
            if not buf:
                buf, buf_len, buf_page = [seg], len(seg), page
                continue

            if buf_len + len(seg) + 1 <= self.chunk_size:
                buf.append(seg)
                buf_len += len(seg) + 1
            else:
                chunks.append(self._make_chunk(buf, buf_page, document_id, len(chunks)))
                # 重叠：保留上一块末尾片段
                overlap = self._tail_overlap(buf)
                if overlap:
                    buf, buf_len, buf_page = [overlap, seg], len(overlap) + len(seg) + 1, page
                else:
                    buf, buf_len, buf_page = [seg], len(seg), page

        if buf:
            chunks.append(self._make_chunk(buf, buf_page, document_id, len(chunks)))

        logger.debug(
            f"递归分块完成: document_id={document_id}, chunks={len(chunks)}, "
            f"size={self.chunk_size}, overlap={self.chunk_overlap}"
        )
        return chunks

    # ---------- 内部工具 ----------

    @staticmethod
    def _split_text(text: str, separators: List[str]) -> List[str]:
        """递归按分隔符优先级切分，返回不包含空串的片段"""
        if not text:
            return []
        for sep in separators:
            if sep == "":
                return [text]
            if sep in text:
                result: List[str] = []
                next_seps = separators[separators.index(sep) + 1:]
                for part in text.split(sep):
                    result.extend(RecursiveChunker._split_text(part, next_seps))
                return result
        return [text]

    def _tail_overlap(self, buf: List[str]) -> str:
        """取上一块末尾 overlap 长度的文本作为重叠"""
        joined = "\n".join(buf)
        if len(joined) <= self.chunk_overlap:
            return joined
        return joined[-self.chunk_overlap:].lstrip("\n ")

    @staticmethod
    def _make_chunk(buf: List[str], page_number: int, document_id: str, index: int) -> Chunk:
        text = "\n".join(buf).strip()
        return Chunk(
            chunk_id=f"doc_{document_id}:{index}",
            document_id=document_id,
            text=text,
            page_number=page_number,
            chunk_index=index,
            start_char=0,
            end_char=len(text),
        )
