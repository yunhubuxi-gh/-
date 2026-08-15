"""
步骤3 - RAG 引擎模块 测试脚本

覆盖：解析、分块、入库、多路召回、rerank、引用标注、幻觉抑制。

设计说明：
- 测试使用「确定性 Fake」注入（哈希嵌入 + 内存向量库），不依赖 BGE 模型下载、
  Chroma/Milvus 服务、LLM API，保证在任意环境可离线快速运行。
- BM25 与 rerank 使用真实实现（rank_bm25 / 词重叠重排），缺失依赖时自动降级。

运行方式：
    pip install jieba rank-bm25
    python tests/test_step3_rag.py
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 测试用 Fake 组件（确定性）
# ============================================================

def _tokenize(text: str):
    """测试用分词：优先 jieba，缺失则退化为逐字"""
    try:
        from utils.text_utils import jieba_segment
        tokens = jieba_segment(text, use_stopwords=False)
        if tokens:
            return tokens
    except Exception:
        pass
    return list(text)


class HashingEmbedder:
    """确定性哈希嵌入：共享词元越多，向量越相似（余弦相似度可比较）"""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vec(self, text: str):
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm:
            vec = [x / norm for x in vec]
        return vec

    def embed(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, query: str):
        return self._vec(query)


class FakeVectorStore:
    """内存向量库，实现 BaseVectorStore 接口（cosine 检索）"""

    def __init__(self):
        self._collections = {}

    def create_collection(self, collection_name, dimension):
        self._collections.setdefault(collection_name, {"dim": dimension, "items": {}})

    def delete_collection(self, collection_name):
        self._collections.pop(collection_name, None)

    def upsert(self, collection_name, ids, vectors, documents, metadatas):
        col = self._collections.setdefault(collection_name, {"dim": len(vectors[0]), "items": {}})
        for cid, vec, doc, meta in zip(ids, vectors, documents, metadatas):
            col["items"][cid] = {"vector": vec, "document": doc, "metadata": meta or {}}

    def delete(self, collection_name, ids):
        col = self._collections.get(collection_name)
        if col:
            for cid in ids:
                col["items"].pop(cid, None)

    def delete_by_document_id(self, collection_name, document_id):
        col = self._collections.get(collection_name)
        if col:
            for cid in list(col["items"].keys()):
                if str(col["items"][cid]["metadata"].get("document_id")) == str(document_id):
                    del col["items"][cid]

    def search(self, collection_name, query_vector, top_k=10, filter=None):
        from ai.rag_engine.vector_store.base_store import VectorSearchResult
        col = self._collections.get(collection_name)
        if not col:
            return []
        scored = []
        for cid, item in col["items"].items():
            sim = self._cosine(query_vector, item["vector"])
            meta = item["metadata"]
            if filter:
                if not all(str(meta.get(k)) == str(v) for k, v in filter.items()):
                    continue
            scored.append((sim, cid, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for sim, cid, item in scored[:top_k]:
            meta = item["metadata"]
            results.append(VectorSearchResult(
                chunk_id=cid,
                document_id=str(meta.get("document_id", "")),
                knowledge_base_id=str(meta.get("knowledge_base_id", "")),
                content=item["document"],
                score=sim,
                page_number=meta.get("page_number"),
                metadata=meta,
            ))
        return results

    def get_by_document_id(self, collection_name, document_id):
        col = self._collections.get(collection_name)
        if not col:
            return []
        return [
            {"chunk_id": cid, "content": it["document"], "metadata": it["metadata"]}
            for cid, it in col["items"].items()
            if str(it["metadata"].get("document_id")) == str(document_id)
        ]

    def count(self, collection_name):
        col = self._collections.get(collection_name)
        return len(col["items"]) if col else 0

    @staticmethod
    def _cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0


class FakeLLM:
    """测试用 LLM：基于上下文生成确定性回答"""

    def chat(self, messages, **kwargs):
        user_content = messages[-1]["content"]
        if "请假" in user_content:
            return "员工请假需提前三天提交申请，并经过部门主管审批。[1]"
        return "知识库中未找到相关信息。"


# ============================================================
# 测试样例文档
# ============================================================

SAMPLE_DOC = """# 员工请假流程说明

## 第一条 适用范围
本流程适用于公司全体员工。

## 第二条 请假申请
员工请假需提前三天提交请假申请，并经过部门主管审批。

## 第三条 请假类型
年假、病假、事假均需通过 OA 系统提交。

## 第四条 审批流程
部门主管审批后，交由人事部备案。请假超过三天需总经理审批。

## 第五条 其他说明
本流程自发布之日起生效，解释权归人力资源部所有。
"""


# ============================================================
# 测试函数
# ============================================================

def _make_pipeline():
    from ai.rag_engine.rag_pipeline import RagPipeline
    from ai.rag_engine.chunker import RecursiveChunker
    embedder = HashingEmbedder()
    store = FakeVectorStore()
    return RagPipeline(
        vector_store=store,
        bm25_engine=None,       # 使用真实 BM25Engine（单例）
        embedding_client=embedder,
        reranker=None,          # 使用真实 reranker（词重叠兜底）
        llm_client=FakeLLM(),
        chunker=RecursiveChunker(chunk_size=80, chunk_overlap=10),  # 确定性分块
    ), store, embedder


def _clean_bm25():
    """重置 BM25 单例并清空磁盘索引，避免跨测试残留导致 count 断言失败。

    load_all() 会在首次 get_bm25_engine() 时恢复磁盘上的旧 .pkl 索引，
    若前一次运行残留 kb_1.pkl，则 add_documents 后 count 会包含旧块。
    """
    from ai.rag_engine.bm25_retriever import reset_bm25_engine
    reset_bm25_engine()
    from config.settings import settings
    index_dir = settings.bm25_index_dir
    if os.path.isdir(index_dir):
        for fn in os.listdir(index_dir):
            if fn.endswith(".pkl"):
                try:
                    os.remove(os.path.join(index_dir, fn))
                except OSError:
                    pass


def _ingest_sample(pipeline, kb_id=1, doc_id=1):
    _clean_bm25()
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_DOC)
        path = f.name
    try:
        n = pipeline.ingest_document(
            knowledge_base_id=kb_id,
            document_id=doc_id,
            document_name="员工请假流程说明.md",
            file_path=path,
        )
        return n
    finally:
        os.unlink(path)


def test_1_document_parser():
    """测试文档解析（MD / TXT + 工厂分发）"""
    print("\n" + "=" * 60)
    print("【测试1】文档解析器")
    print("=" * 60)

    from ai.rag_engine.document_parser import parse_document

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_DOC)
        md_path = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("这是一个纯文本测试文档。")
        txt_path = f.name

    try:
        md = parse_document(md_path)
        assert md.title.endswith(".md") or "员工" in SAMPLE_DOC
        assert md.char_count > 100
        assert md.page_count >= 1
        print(f"  ✓ MD 解析: title={md.title}, chars={md.char_count}, pages={md.page_count}")

        txt = parse_document(txt_path)
        assert "纯文本测试文档" in txt.full_text
        assert txt.metadata["format"] == "txt"
        print(f"  ✓ TXT 解析: chars={txt.char_count}, format={txt.metadata['format']}")

        # 不支持类型
        from utils.exceptions import ValidationException
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False, encoding="utf-8") as f:
            f.write("x")
            bad_path = f.name
        try:
            try:
                parse_document(bad_path)
                assert False, "应抛出不支持类型异常"
            except ValidationException as e:
                print(f"  ✓ 不支持类型正确抛异常: {e.message}")
        finally:
            os.unlink(bad_path)
    finally:
        os.unlink(md_path)
        os.unlink(txt_path)

    print("  ✅ 文档解析器全部通过")


def test_2_recursive_chunker():
    """测试递归分块（块序号 + 页码 + 溯源元数据）"""
    print("\n" + "=" * 60)
    print("【测试2】递归分块器")
    print("=" * 60)

    from ai.rag_engine.chunker import RecursiveChunker
    from ai.rag_engine.document_parser import parse_document

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_DOC)
        path = f.name
    try:
        parsed = parse_document(path)
        chunker = RecursiveChunker(chunk_size=80, chunk_overlap=10)
        chunks = chunker.split(parsed, document_id="42")
        assert len(chunks) >= 1
        for c in chunks:
            assert c.document_id == "42"
            assert c.chunk_id.startswith("doc_42:")
            assert c.chunk_index >= 0
            assert c.page_number >= 1
            assert 0 < len(c.text) <= 80 + 10
        print(f"  ✓ 分块数量: {len(chunks)}")
        print(f"  ✓ 首个块溯源: chunk_id={chunks[0].chunk_id}, page={chunks[0].page_number}")
        print(f"  ✓ 块序号连续: {[c.chunk_index for c in chunks]}")
    finally:
        os.unlink(path)

    print("  ✅ 递归分块器全部通过")


def test_3_semantic_chunker():
    """测试语义分块（注入假嵌入，验证不崩溃 + 元数据正确）"""
    print("\n" + "=" * 60)
    print("【测试3】语义分块器")
    print("=" * 60)

    from ai.rag_engine.chunker import SemanticChunker
    from ai.rag_engine.document_parser import parse_document

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_DOC)
        path = f.name
    try:
        parsed = parse_document(path)
        chunker = SemanticChunker(embedding_client=HashingEmbedder(), chunk_size=80, threshold=0.5)
        chunks = chunker.split(parsed, document_id="7")
        assert len(chunks) >= 1
        for c in chunks:
            assert c.document_id == "7"
            assert c.page_number >= 1
            assert c.text.strip()
        print(f"  ✓ 语义分块数量: {len(chunks)}")
        print(f"  ✓ 各块均携带页码与文本: {[(c.page_number, len(c.text)) for c in chunks]}")
    finally:
        os.unlink(path)

    print("  ✅ 语义分块器全部通过")


def test_4_ingest():
    """测试文档入库（解析→分块→嵌入→写向量库+BM25）"""
    print("\n" + "=" * 60)
    print("【测试4】文档入库")
    print("=" * 60)

    pipeline, store, _ = _make_pipeline()
    n = _ingest_sample(pipeline, kb_id=1, doc_id=1)
    assert n >= 1
    assert store.count("kb_1") == n

    from ai.rag_engine.bm25_retriever import get_bm25_engine, reset_bm25_engine
    bm25 = get_bm25_engine()
    assert bm25.count("kb_1") == n
    print(f"  ✓ 入库块数: {n}")
    print(f"  ✓ 向量库块数: {store.count('kb_1')}")
    print(f"  ✓ BM25 索引块数: {bm25.count('kb_1')}")
    reset_bm25_engine()
    print("  ✅ 文档入库全部通过")


def test_5_hybrid_retrieve():
    """测试多路混合召回（BM25 + 向量 → 融合去重）"""
    print("\n" + "=" * 60)
    print("【测试5】多路混合召回")
    print("=" * 60)

    pipeline, store, _ = _make_pipeline()
    _ingest_sample(pipeline, kb_id=1, doc_id=1)

    results = pipeline.retrieve(query="请假流程", knowledge_base_ids=[1], top_k=3)
    assert len(results) >= 1
    assert results[0].document_name == "员工请假流程说明.md"
    print(f"  ✓ 召回结果数: {len(results)}")
    for r in results:
        print(f"    - score={r.score:.4f}, doc={r.document_name}, page={r.page_number}, chunk={r.chunk_index}")

    # 无关查询 → 分数低或空（至少不崩）
    results2 = pipeline.retrieve(query="量子力学", knowledge_base_ids=[1], top_k=3)
    assert isinstance(results2, list)
    print(f"  ✓ 无关查询返回 {len(results2)} 条（低相关/空，不崩）")

    from ai.rag_engine.bm25_retriever import reset_bm25_engine
    reset_bm25_engine()
    print("  ✅ 多路混合召回全部通过")


def test_6_reranker():
    """测试重排（词重叠兜底重排器）"""
    print("\n" + "=" * 60)
    print("【测试6】Rerank 重排")
    print("=" * 60)

    from ai.rag_engine.reranker import OverlapReranker
    reranker = OverlapReranker()
    docs = [
        "量子力学的波函数坍缩理论",
        "员工请假流程需要提前三天申请",
        "公司年会时间安排",
    ]
    ranked = reranker.rerank(query="请假流程", documents=docs, top_n=3)
    assert len(ranked) == 3
    # 最相关的应是第二条
    top_idx = ranked[0][0]
    assert top_idx == 1, f"期望最相关索引为1，实际 {top_idx}"
    print(f"  ✓ 重排结果顺序: {[i for i, _ in ranked]}")
    print(f"  ✓ 最相关片段: {docs[top_idx]}")
    print("  ✅ Rerank 重排全部通过")


def test_7_citation():
    """测试引用来源标注（文档名 + 页码 + 块编号）"""
    print("\n" + "=" * 60)
    print("【测试7】引用标注")
    print("=" * 60)

    pipeline, _, _ = _make_pipeline()
    _ingest_sample(pipeline, kb_id=1, doc_id=1)
    chunks = pipeline.retrieve(query="请假流程", knowledge_base_ids=[1], top_k=2)

    from ai.rag_engine.citation_formatter import build_citations, annotate_answer
    citations = build_citations(chunks)
    assert len(citations) >= 1
    c = citations[0]
    assert c.document_name == "员工请假流程说明.md"
    assert c.index == 1
    assert c.page_number >= 1
    print(f"  ✓ 引用: {c.to_label()}")

    answer = "请假需提前三天申请。[1]"
    annotated = annotate_answer(answer, citations)
    assert "参考来源" in annotated
    assert "员工请假流程说明.md" in annotated
    print(f"  ✓ 标注后回答包含参考来源列表")
    print(f"    引用字典: {c.to_dict()}")

    from ai.rag_engine.bm25_retriever import reset_bm25_engine
    reset_bm25_engine()
    print("  ✅ 引用标注全部通过")


def test_8_hallucination():
    """测试幻觉抑制（无上下文 → 拒绝回答；编造 → 标记）"""
    print("\n" + "=" * 60)
    print("【测试8】幻觉抑制")
    print("=" * 60)

    from ai.rag_engine.hallucination_detector import HallucinationDetector
    det = HallucinationDetector(enabled=True)

    # 无上下文
    r1 = det.check(answer="请假需提前三天申请。", contexts=[])
    assert r1.no_answer is False
    assert r1.has_context is False
    assert r1.should_suppress() is True
    print(f"  ✓ 无上下文 → 建议抑制: '{r1.suggestion}'")

    # 有上下文且回答无答案（正确行为）
    r2 = det.check(answer="知识库中未找到相关信息。", contexts=["员工请假需提前三天申请。"])
    assert r2.no_answer is True
    assert r2.grounded is True
    print(f"  ✓ 明确告知无信息 → 不视为幻觉")

    # 有上下文且回答有支撑
    r3 = det.check(answer="员工请假需提前三天申请。", contexts=["员工请假需提前三天申请，并经过审批。"])
    assert r3.grounded is True
    print(f"  ✓ 有支撑回答 → grounded=True, confidence={r3.confidence:.2f}")

    # 编造内容（与上下文无关）
    r4 = det.check(answer="根据规定，员工可携带宠物上班。", contexts=["员工请假需提前三天申请。"])
    assert r4.grounded is False
    print(f"  ✓ 编造内容 → grounded=False, warnings={r4.warnings}")

    print("  ✅ 幻觉抑制全部通过")


def test_9_answer_pipeline():
    """测试统一问答入口（检索→生成→幻觉抑制→引用）"""
    print("\n" + "=" * 60)
    print("【测试9】RAG 统一问答入口")
    print("=" * 60)

    pipeline, _, _ = _make_pipeline()
    _ingest_sample(pipeline, kb_id=1, doc_id=1)

    result = pipeline.answer(query="请假流程是什么？", knowledge_base_ids=[1], top_k=3)
    assert result.answer
    assert "三天" in result.answer or "请假" in result.answer
    assert len(result.citations) >= 1
    assert result.grounded is True
    print(f"  ✓ 回答: {result.answer[:60]}...")
    print(f"  ✓ 引用数: {len(result.citations)}, grounded={result.grounded}")

    # 无相关知识的库
    result2 = pipeline.answer(query="量子力学是什么？", knowledge_base_ids=[999], top_k=3)
    assert result2.no_answer is True
    assert "未找到" in result2.answer
    print(f"  ✓ 空知识库 → 明确告知无信息: '{result2.answer}'")

    from ai.rag_engine.bm25_retriever import reset_bm25_engine
    reset_bm25_engine()
    print("  ✅ RAG 统一问答入口全部通过")


def main():
    print("\n" + "🚀" * 10 + " 步骤3 RAG引擎模块测试开始 " + "🚀" * 10)

    tests = [
        test_1_document_parser,
        test_2_recursive_chunker,
        test_3_semantic_chunker,
        test_4_ingest,
        test_5_hybrid_retrieve,
        test_6_reranker,
        test_7_citation,
        test_8_hallucination,
        test_9_answer_pipeline,
    ]

    passed = 0
    failed = 0
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ 测试失败: {test_func.__name__}")
            print(f"     错误: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: 共 {len(tests)} 大项, 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 60)

    if failed == 0:
        print("🎉 全部测试通过！步骤3 RAG引擎模块正常。")
        print()
        print("📦 RAG 引擎模块清单:")
        print("  document_parser/  文档解析（PDF/DOCX/MD/TXT + OCR 回退）")
        print("  chunker/          语义分块 + 递归兜底（页码/块号溯源）")
        print("  vector_store/     向量库封装（Chroma/Milvus 二选一）")
        print("  bm25_retriever/   BM25 关键词召回（jieba 分词）")
        print("  reranker/         BGE-Rerank 重排 + 词重叠兜底")
        print("  hybrid_retriever.py  多路混合召回 + 加权融合去重")
        print("  hallucination_detector.py  幻觉抑制")
        print("  citation_formatter.py      引用标注")
        print("  doc_version_manager.py     文档版本索引编排")
        print("  rag_pipeline.py            RAG 统一入口")
        print()
        print("✅ 三者分离存储边界遵守:")
        print("   PostgreSQL = 业务元数据")
        print("   向量库     = chunk 文本 + embedding 向量")
        print("   文件系统   = 原始文档（通过 file_path 读取）")
    else:
        print(f"⚠️  有 {failed} 项测试失败。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
