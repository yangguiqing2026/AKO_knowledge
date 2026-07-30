#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AKO_knowledge 检索对比：Dense-only vs Hybrid (Dense + Sparse + ColBERT)
跑 6 条覆盖不同检索模式的查询，对比 top-5 排名差异。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chromadb
from hybrid_retrieval import HybridRetriever, build_sparse_features, tokenize


# ── 测试查询 (覆盖关键词/语义/数值/混合四种模式) ────────────────────
QUERIES = [
    # Q1 精确关键词 (产品名)
    "陶粒发泡混凝土大板墙板",
    # Q2 语义性描述 (应用场景)
    "适用于乡村自建房的装配式墙体",
    # Q3 数值型精确 (尺寸)
    "4米跨度 10米高度 墙板",
    # Q4 公司 + 产品混合
    "贵州阿格建筑 防火性能",
    # Q5 规范类 (标准号)
    "GB50016 防火规范 墙体材料",
    # Q6 价格 / 商业信息
    "580万 壹 THE ONE 顶奢",
]

TOP_K = 5
CHROMA_ROOT = "D:/AKO_knowledge"
COLLECTION = "ako_photos"


# ── Baseline: Dense-only (ChromaDB cosine) ─────────────────────
def dense_only_query(col, query: str, top_k: int, hybrid: HybridRetriever):
    """用 HybridRetriever 的 bge-m3 encoder 得到 dense 向量，再直接 col.query 走 cosine"""
    encoded = hybrid.encode_query(query)
    dense_vec = encoded.get("dense_vec")
    if dense_vec is None:
        return None, 0.0
    t0 = time.time()
    res = col.query(
        query_embeddings=[dense_vec],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    elapsed = time.time() - t0
    return res, elapsed


# ── Baseline: Sparse-only (关键词 BM25-style) ──────────────────
def sparse_only_query(col, query: str, top_k: int, retriever=None) -> dict:
    """纯关键词匹配：用 bge-m3 native sparse lexicon (BPE token IDs) 做匹配"""
    # 用 bge-m3 native sparse lexicon 获取 query 的 BPE token IDs
    q_tokens = None
    if retriever is not None:
        encoded = retriever.encode_query(query)
        sparse_lex = encoded.get("sparse_lexicon")
        if isinstance(sparse_lex, dict):
            q_tokens = list(sparse_lex.keys())
    if not q_tokens:
        q_tokens = tokenize(query)  # fallback
    if not q_tokens:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]], "scores": [[]]}, 0.0
    q_set = set(q_tokens)

    t0 = time.time()
    # 多召回一些再排序 (因为没 dense 先召回，只能全库扫)
    data = col.get(include=["documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"]
    metas = data["metadatas"]

    scored = []
    for did, doc, meta in zip(ids, docs, metas or [{}] * len(ids)):
        meta = meta or {}
        sparse_raw = meta.get("sparse_lexicon")
        if not sparse_raw:
            continue
        try:
            doc_lex = json.loads(sparse_raw)
        except Exception:
            continue
        doc_tokens = set(doc_lex.keys())
        if not doc_tokens:
            continue
        inter = q_set & doc_tokens
        if not inter:
            continue
        # 加权匹配：query 中匹配 token 的 lexicon 权重和 / query 总权重
        score = sum(doc_lex.get(t, 0) for t in inter)
        scored.append((score, did, doc, meta))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    elapsed = time.time() - t0

    return {
        "ids": [[t[1] for t in top]],
        "documents": [[t[2] for t in top]],
        "metadatas": [[t[3] for t in top]],
        "distances": [[1.0 - t[0] for t in top]],
        "scores": [[t[0] for t in top]],
    }, elapsed


# ── Hybrid (Dense + Sparse + ColBERT) ─────────────────────────
def hybrid_query(col, query: str, top_k: int):
    hr = HybridRetriever(collection=col)
    t0 = time.time()
    res = hr.search(query=query, top_k=top_k)
    elapsed = time.time() - t0
    return res, elapsed


# ── 打印与对比 ─────────────────────────────────────────────────
def short_preview(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text[:n] + ("…" if len(text) > n else "")


def source_tag(meta: dict) -> str:
    src = meta.get("source", "") or meta.get("type", "")
    return f"[{src[:30]}]" if src else ""


def print_block(name: str, res: dict, elapsed: float):
    ids = res["ids"][0]
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    scores = res.get("scores")
    dists = res.get("distances", [[]])[0]
    print(f"  ── {name}  ({elapsed*1000:.0f} ms, hits={len(ids)}) ──")
    if not ids:
        print("    (no results)")
        return
    for i, (did, doc, meta) in enumerate(zip(ids, docs, metas), 1):
        s = f"{scores[0][i-1]:.4f}" if scores else "—"
        d = f"{dists[i-1]:.4f}" if i-1 < len(dists) else "—"
        print(f"    {i}. [{did[:8]}] score={s} dist={d} {source_tag(meta)}")
        print(f"       {short_preview(doc)}")


def main():
    client = chromadb.PersistentClient(path=CHROMA_ROOT)
    col = client.get_collection(name=COLLECTION)
    print(f"📚 {COLLECTION}: {col.count()} docs (dim=1024 bge-m3)")
    print(f"🔬 {len(QUERIES)} 条查询 × 3 种模式 (Dense-only / Sparse-only / Hybrid)\n")

    # 共享的 HybridRetriever 实例 (复用 encoder)
    shared_hr = HybridRetriever(collection=col)

    stats = []
    for qi, q in enumerate(QUERIES, 1):
        print(f"{'='*80}")
        print(f"Q{qi}: {q!r}")
        print(f"{'='*80}")

        dense_res, dense_t = dense_only_query(col, q, TOP_K, shared_hr)
        sparse_res, sparse_t = sparse_only_query(col, q, TOP_K, retriever=shared_hr)
        hybrid_res, hybrid_t = hybrid_query(col, q, TOP_K)

        print_block("Dense-only  (ChromaDB cosine, 单向量)", dense_res, dense_t)
        print_block("Sparse-only (关键词 BM25-style)", sparse_res, sparse_t)
        print_block("Hybrid      (Dense + Sparse + ColBERT, 三向量融合)", hybrid_res, hybrid_t)

        # 排名对比：Dense vs Hybrid 的 top-1 id 是否一致
        d_top1 = dense_res["ids"][0][0] if dense_res["ids"][0] else None
        h_top1 = hybrid_res["ids"][0][0] if hybrid_res["ids"][0] else None
        rerank_happened = d_top1 != h_top1
        d_set = set(dense_res["ids"][0])
        h_set = set(hybrid_res["ids"][0])
        overlap = len(d_set & h_set)

        print(f"\n  📊 对比: top-1 {'🔄 被 rerank' if rerank_happened else '✅ 一致'}  |  "
              f"top-5 集合重叠 {overlap}/{TOP_K}")
        stats.append({
            "query": q,
            "dense_ms": round(dense_t*1000, 1),
            "sparse_ms": round(sparse_t*1000, 1),
            "hybrid_ms": round(hybrid_t*1000, 1),
            "top1_reranked": rerank_happened,
            "top5_overlap": overlap,
        })
        print()

    # 汇总
    print("=" * 80)
    print("📈 汇总")
    print("=" * 80)
    avg_dense = sum(s["dense_ms"] for s in stats) / len(stats)
    avg_sparse = sum(s["sparse_ms"] for s in stats) / len(stats)
    avg_hybrid = sum(s["hybrid_ms"] for s in stats) / len(stats)
    rerank_n = sum(1 for s in stats if s["top1_reranked"])
    overlap_n = sum(s["top5_overlap"] for s in stats) / len(stats)
    print(f"  平均耗时:  Dense {avg_dense:.0f} ms  |  Sparse {avg_sparse:.0f} ms  |  Hybrid {avg_hybrid:.0f} ms")
    print(f"  Hybrid vs Dense-only:")
    print(f"    - top-1 排名被 rerank 的 query: {rerank_n}/{len(stats)}  ← 说明 sparse/colbert 真的改变了排序")
    print(f"    - top-5 集合平均重叠: {overlap_n:.1f}/{TOP_K}  ← 5 说明只是重排，<5 说明召回了 dense 没找到的新 doc")

    # 保存详细 JSON 报告
    report_path = HERE / "compare_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump({"queries": QUERIES, "stats": stats}, f, ensure_ascii=False, indent=2)
    print(f"\n📄 详细报告: {report_path}")


if __name__ == "__main__":
    main()
