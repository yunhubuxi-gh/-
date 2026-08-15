"""
RAG 优化自测脚本（一次性，非交付物）

流程：
1. 登录 admin
2. 向指定知识库上传 demo_docs/ 下 4 个文档
3. 轮询文档状态直到 ready
4. 针对文档内知识点提问，打印回答 + 引用（验证召回）
5. 重复提问，验证缓存命中（响应应显著变快，且后端日志出现「缓存命中」）
"""
from __future__ import annotations

import glob
import os
import sys
import time

import requests

BASE = "http://localhost:8000/api/v1"
DEMO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo_docs")


def login(username: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
    return r.json()["data"]["access_token"]


def upload(header: dict, kb_id: int, path: str) -> int:
    name = os.path.basename(path)
    with open(path, "rb") as f:
        files = {"file": (name, f.read(), "application/octet-stream")}
        r = requests.post(f"{BASE}/kb/{kb_id}/documents", files=files, headers=header, timeout=60)
    return r.json()["data"]["document_id"]


def wait_ready(header: dict, kb_id: int, doc_id: int, timeout: float = 120.0) -> str:
    deadline = time.time() + timeout
    status = "uploaded"
    while time.time() < deadline:
        r = requests.get(f"{BASE}/documents/{doc_id}", headers=header, timeout=30)
        d = r.json()["data"]
        status = d.get("status")
        print(f"    doc={doc_id} status={status} chunks={d.get('chunk_count')}")
        if status in ("ready", "failed"):
            break
        time.sleep(2)
    return status


def ask(header: dict, kb_id: int, query: str) -> dict:
    r = requests.post(
        f"{BASE}/chat/ask",
        json={"knowledge_base_id": kb_id, "query": query},
        headers=header,
        timeout=120,
    )
    return r.json()["data"]


def main():
    kb_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    header = {"Authorization": f"Bearer {login('admin', 'admin123456')}"}

    docs = sorted(glob.glob(os.path.join(DEMO_DIR, "*")))
    docs = [d for d in docs if d.lower().endswith((".md", ".txt"))]
    print(f"\n=== 上传 {len(docs)} 个 demo 文档到知识库 {kb_id} ===")
    for path in docs:
        doc_id = upload(header, kb_id, path)
        print(f"  上传 {os.path.basename(path)} -> doc_id={doc_id}")
        wait_ready(header, kb_id, doc_id)

    # 知识点提问（对应 demo_docs 内容）
    queries = [
        "什么是混合检索？",
        "LangGraph Agent 的工作流程是怎样的？",
    ]
    print("\n=== 提问验证召回 ===")
    for q in queries:
        print(f"\n[提问] {q}")
        t0 = time.time()
        data = ask(header, kb_id, q)
        dt = time.time() - t0
        print(f"  耗时 {dt:.2f}s")
        print(f"  回答: {(data.get('answer') or '')[:120]}")
        cites = data.get("citations") or []
        print(f"  引用 {len(cites)} 条: {[c.get('document_name') for c in cites[:5]]}")

    # 重复提问验证缓存
    q = queries[0]
    print(f"\n=== 重复提问验证缓存: 「{q}」连续 3 次 ===")
    for i in range(3):
        t0 = time.time()
        ask(header, kb_id, q)
        dt = time.time() - t0
        print(f"  第{i + 1}次 耗时 {dt:.2f}s")

    print("\n自测流程执行完毕，请查看后端日志中的 [RAG调试] 输出。")


if __name__ == "__main__":
    main()
