# -*- coding: utf-8 -*-
"""
全量向量化 D:\AKO_Hub 中所有 .md 文件 → ChromaDB → Gbrain 发酵

用法: python ingest_hub_all.py [--dry-run] [--no-ferment]
"""
import os
import sys
import hashlib
import datetime
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chromadb
from config_loader import get_config

# ── 扫描 AKO_Hub ──
HUB_ROOT = r"D:\AKO_Hub"
EXCLUDED_DIRS = {".git", ".obsidian", "__pycache__", "backups", ".venv",
                 "site-packages", ".pytest_cache", ".gradio", ".streamlit"}

def scan_hub_md(root: str) -> list:
    """扫描 AKO_Hub 中有价值的 .md 文件"""
    files = []
    for r, dirs, fs in os.walk(root):
        # 原地过滤，跳过排除目录
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        parts = set(r.split(os.sep))
        if parts & EXCLUDED_DIRS:
            continue
        for f in fs:
            if f.endswith(".md"):
                full = os.path.join(r, f)
                rel = os.path.relpath(full, root)
                size = os.path.getsize(full)
                # 跳过空文件 (<50 bytes)
                if size < 50:
                    continue
                files.append((full, rel, size))
    return sorted(files, key=lambda x: x[1])


def chunk_text(text: str, chunk_size: int = 450, overlap: int = 100) -> list:
    """递归语义分块"""
    if not text or len(text) < 50:
        return []
    if len(text) <= chunk_size:
        return [text.strip()]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def compute_content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser(description="AKO_Hub .md 全量向量化入库")
    ap.add_argument("--dry-run", action="store_true", help="只扫描不写入")
    ap.add_argument("--no-ferment", action="store_true", help="跳过后置发酵")
    ap.add_argument("--vault", default=HUB_ROOT, help="vault 根目录")
    args = ap.parse_args()

    vault = args.vault
    if not os.path.isdir(vault):
        print(f"[错误] 路径不存在: {vault}")
        return 1

    # ── 扫描 ──
    md_files = scan_hub_md(vault)
    print(f"\n{'='*60}")
    print(f"AKO_Hub 向量化入库")
    print(f"{'='*60}")
    print(f"扫描路径: {vault}")
    print(f"有效 .md 文件: {len(md_files)} 个")

    for fp, rel, size in md_files:
        print(f"  [{size:>7}B] {rel}")

    if args.dry_run:
        print(f"\n[DRY-RUN] 仅扫描，不写入。")
        return 0

    # ── 加载配置 ──
    config = get_config()
    client = chromadb.PersistentClient(path=config.db_path)
    collection = client.get_or_create_collection(config.collection_name)

    # ── 获取已入库 source 集合 ──
    existing_data = collection.get(include=["metadatas"])
    existing_sources = set()
    existing_hashes = set()
    for meta in (existing_data.get("metadatas") or []):
        s = (meta or {}).get("source", "")
        h = (meta or {}).get("content_hash", "")
        if s:
            existing_sources.add(s)
        if h:
            existing_hashes.add(h)

    # ── 逐文件入库 ──
    files_done = 0
    chunks_total = 0
    skipped = 0
    timestamp = datetime.datetime.now().isoformat()

    for full_path, rel_path, size in md_files:
        # 以 rel_path 作为 source
        source_key = rel_path.replace("\\", "/")

        # 检查是否已入库
        if source_key in existing_sources:
            skipped += 1
            print(f"  [SKIP] {source_key} (已入库)")
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            print(f"  [ERROR] 读取失败 {source_key}: {e}")
            continue

        content_hash = compute_content_hash(content)
        if content_hash in existing_hashes:
            skipped += 1
            print(f"  [SKIP] {source_key} (内容已存在)")
            continue

        chunks = chunk_text(content)
        if not chunks:
            print(f"  [EMPTY] {source_key}")
            continue

        # 向量化 + 入库 (逐块处理，避免大文件 OOM)
        from hybrid_retrieval import build_hybrid_metadata
        import ollama

        for idx, chunk in enumerate(chunks):
            doc_id = f"hub_{content_hash}_{idx}"
            try:
                embed_resp = ollama.embeddings(
                    model=config.embedding_model,
                    prompt=chunk,
                )
                embed = embed_resp["embedding"]
            except Exception as e:
                print(f"  [EMBED ERROR] {source_key} chunk {idx}: {e}")
                continue

            meta = build_hybrid_metadata(chunk)
            meta.update({
                "source": source_key,
                "type": "markdown",
                "chunk_index": idx,
                "chunk_total": len(chunks),
                "timestamp": timestamp,
                "content_hash": content_hash,
                "source_path": source_key,
            })

            try:
                collection.add(
                    ids=[doc_id],
                    embeddings=[embed],
                    documents=[chunk],
                    metadatas=[meta],
                )
            except Exception as e:
                print(f"  [DB ERROR] {source_key} chunk {idx}: {e}")
                # 如果 ID 冲突则跳过
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    continue
                raise

        chunks_total += len(chunks)
        files_done += 1
        print(f"  [OK] {source_key} → {len(chunks)} chunks")

    # ── 汇总 ──
    print(f"\n{'='*60}")
    print(f"入库完成: {files_done} 个文件, {chunks_total} 个片段, 跳过 {skipped}")
    print(f"ChromaDB 总计: {collection.count()} 条")
    print(f"{'='*60}")

    # ── Gbrain 发酵 ──
    if not args.no_ferment and files_done > 0:
        print(f"\n{'='*60}")
        print("触发 Gbrain 发酵...")
        print(f"{'='*60}")
        from gbrain_ferment import create_engine
        engine = create_engine(
            db_path=config.db_path,
            collection_name=config.collection_name,
            vault_root=vault,
        )
        report = engine.ferment(full_graph=True)
        print(f"发酵完成:")
        print(f"  新建 stubs: {report['stubs_created']}")
        print(f"  升级 basic: {report['upgrades_basic']}")
        print(f"  升级 full: {report['upgrades_full']}")
        print(f"  富化 basic: {report['enriched_basic']}")
        print(f"  富化 full: {report['enriched_full']}")
        print(f"  总概念页: {report['total_pages']}")
        graph = report.get("graph_stats", {})
        print(f"  概念图谱: {graph.get('total_concepts', 0)} 概念, "
              f"{graph.get('total_edges', 0)} 边")
        print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())