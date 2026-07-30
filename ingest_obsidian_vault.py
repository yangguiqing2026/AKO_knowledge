# -*- coding: utf-8 -*-
"""
全量向量化 Obsidian vault D:\AKOBUILD\AKO_knowledge_base → ChromaDB → Gbrain 发酵

用法: python ingest_obsidian_vault.py [--dry-run] [--no-ferment]
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

VAULT_ROOT = r"D:\AKOBUILD\AKO_knowledge_base"
EXCLUDED_DIRS = {".obsidian", ".git", ".trash", "_system", ".oak"}
CONFLICT_MARKS = ("冲突", "conflict")


def scan_vault_md(root: str) -> list:
    """扫描 Obsidian vault 中所有 .md 文件"""
    files = []
    for r, dirs, fs in os.walk(root):
        # 原地过滤排除目录
        rel_root = r[len(root):].lstrip(os.sep)
        parts = set(rel_root.split(os.sep))
        if parts & EXCLUDED_DIRS:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        for f in fs:
            if not f.endswith(".md"):
                continue
            name_lower = f.lower()
            if any(m in name_lower for m in CONFLICT_MARKS):
                continue
            full = os.path.join(r, f)
            rel = os.path.relpath(full, root)
            size = os.path.getsize(full)
            if size < 50:
                continue
            files.append((full, rel, size))
    return sorted(files, key=lambda x: x[1])


def chunk_text(text: str, chunk_size: int = 450, overlap: int = 100) -> list:
    """语义分块"""
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
    ap = argparse.ArgumentParser(description="Obsidian vault 全量向量化入库")
    ap.add_argument("--dry-run", action="store_true", help="只扫描不写入")
    ap.add_argument("--no-ferment", action="store_true", help="跳过后置发酵")
    ap.add_argument("--vault", default=VAULT_ROOT, help="vault 根目录")
    args = ap.parse_args()

    vault = args.vault
    if not os.path.isdir(vault):
        print(f"[错误] 路径不存在: {vault}")
        return 1

    # 扫描
    md_files = scan_vault_md(vault)
    print(f"\n{'='*60}")
    print(f"Obsidian Vault 向量化入库")
    print(f"{'='*60}")
    print(f"扫描路径: {vault}")
    print(f"有效 .md 文件: {len(md_files)} 个")
    total_size = sum(s for _, _, s in md_files)
    print(f"总大小: {total_size:,} bytes ({total_size/1024:.1f} KB)")

    if args.dry_run:
        for fp, rel, size in md_files[:20]:
            print(f"  [{size:>7}B] {rel}")
        if len(md_files) > 20:
            print(f"  ... 另有 {len(md_files)-20} 个文件")
        print(f"\n[DRY-RUN] 仅扫描，不写入。")
        return 0

    # 加载配置
    config = get_config()
    client = chromadb.PersistentClient(path=config.db_path)
    collection = client.get_or_create_collection(config.collection_name)

    # 获取已入库 source
    existing_data = collection.get(include=["metadatas"])
    existing_sources = set()
    existing_hashes = set()
    for meta in (existing_data.get("metadatas") or []):
        m = meta or {}
        existing_sources.add(m.get("source", ""))
        existing_hashes.add(m.get("content_hash", ""))

    files_done = 0
    chunks_total = 0
    skipped = 0
    errors = 0
    timestamp = datetime.datetime.now().isoformat()

    from hybrid_retrieval import build_hybrid_metadata
    import ollama

    for full_path, rel_path, size in md_files:
        source_key = rel_path.replace("\\", "/")

        if source_key in existing_sources:
            skipped += 1
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            errors += 1
            print(f"  [READ ERR] {source_key}: {e}")
            continue

        content_hash = compute_content_hash(content)
        if content_hash in existing_hashes:
            skipped += 1
            continue

        chunks = chunk_text(content)
        if not chunks:
            print(f"  [EMPTY] {source_key}")
            continue

        embedded = 0
        for idx, chunk in enumerate(chunks):
            doc_id = f"obs_{content_hash}_{idx}"
            try:
                embed_resp = ollama.embeddings(
                    model=config.embedding_model,
                    prompt=chunk,
                )
                embed = embed_resp["embedding"]
            except Exception as e:
                errors += 1
                print(f"  [EMBED ERR] {source_key} chunk {idx}: {e}")
                continue

            meta = build_hybrid_metadata(chunk)
            meta.update({
                "source": source_key,
                "type": "obsidian_note",
                "chunk_index": idx,
                "chunk_total": len(chunks),
                "timestamp": timestamp,
                "content_hash": content_hash,
                "vault": "AKO_knowledge_base",
            })

            try:
                collection.add(
                    ids=[doc_id],
                    embeddings=[embed],
                    documents=[chunk],
                    metadatas=[meta],
                )
                embedded += 1
            except Exception as e:
                if "already exists" in str(e).lower():
                    continue
                errors += 1

        chunks_total += embedded
        files_done += 1
        status = "[OK]" if embedded > 0 else "[NONE]"
        print(f"  {status} {source_key} → {embedded}/{len(chunks)} chunks")

    # 汇总
    print(f"\n{'='*60}")
    print(f"入库完成: {files_done} 个文件, {chunks_total} 个片段")
    print(f"跳过: {skipped} (已存在), 错误: {errors}")
    print(f"ChromaDB 总计: {collection.count()} 条")
    print(f"{'='*60}")

    # Gbrain 发酵
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
        if graph:
            print(f"  概念图谱: {graph.get('total_concepts', 0)} 概念")
        print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())