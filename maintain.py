"""
AKO_Hub 知识库健康检查工具 - maintain 技能

检测项:
1. 过期内容检测 - 基于 timestamp 判断文档是否超过有效期
2. 死链接检测 - 检查 metadata 中 source 文件是否仍存在于磁盘
3. 孤儿页检测 - 找 chunk_index 不连续的片段 (中间缺失)
4. 矛盾检测 - 同 source 不同 chunk 间语义冲突 (需 LLM)
5. 统计报告 - 知识库整体健康概览
"""
import os
import json
import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict

import chromadb
from config_loader import get_config

# ==================== 加载配置 ====================
config = get_config()

# 过期阈值 (天) — 从 config.json 读取 maintain_settings（config_loader 暂无此属性）
_MAINTAIN_CONFIG = {}
try:
    _config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(_config_file, "r", encoding="utf-8") as _f:
        _MAINTAIN_CONFIG = json.load(_f).get("maintain_settings", {})
except Exception:
    pass
EXPIRE_DAYS = _MAINTAIN_CONFIG.get("expire_days", 180)

# 文档源文件夹 (用于死链检测) — 通过 config_loader
_SOURCE_FOLDERS = []
for folder in (config.pdf_folder, config.word_folder, config.ppt_folder, config.img_folder):
    if folder and os.path.exists(folder):
        _SOURCE_FOLDERS.append(folder)

# Inbox 文件夹
_INBOX_FOLDER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    _raw_cfg.get("inbox_folder", "Inbox"),
)


def _get_collection():
    """获取 ChromaDB collection"""
    client = chromadb.PersistentClient(path=config.db_path)
    return client.get_collection(config.collection_name)


def get_stats() -> Dict[str, Any]:
    """
    知识库统计概览
    """
    col = _get_collection()
    total = col.count()

    # 获取所有 metadata
    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])

    # 按 source 统计
    source_counts = defaultdict(int)
    type_counts = defaultdict(int)
    timestamps = []

    for meta in metas:
        meta = meta or {}
        source = meta.get("source", "未知")
        doc_type = meta.get("type", "未知")
        ts = meta.get("timestamp", "")

        source_counts[source] += 1
        type_counts[doc_type] += 1
        if ts:
            timestamps.append(ts)

    # 时间范围
    oldest = min(timestamps) if timestamps else "N/A"
    newest = max(timestamps) if timestamps else "N/A"

    return {
        "total_chunks": total,
        "unique_sources": len(source_counts),
        "source_breakdown": dict(source_counts),
        "type_breakdown": dict(type_counts),
        "oldest_record": oldest,
        "newest_record": newest,
    }


def check_expired(expire_days: int = None) -> List[Dict[str, Any]]:
    """
    过期内容检测 - 找出超过有效期的文档

    Args:
        expire_days: 过期天数阈值，默认使用配置

    Returns:
        过期文档列表 [{source, timestamp, age_days, chunk_count}]
    """
    if expire_days is None:
        expire_days = EXPIRE_DAYS

    col = _get_collection()
    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])
    ids = all_data.get("ids", [])

    now = datetime.datetime.now()
    expired = defaultdict(lambda: {"timestamps": [], "chunks": 0})

    for doc_id, meta in zip(ids, metas):
        meta = meta or {}
        source = meta.get("source", "未知")
        ts_str = meta.get("timestamp", "")
        if not ts_str:
            continue

        try:
            ts = datetime.datetime.fromisoformat(ts_str)
            age_days = (now - ts).days
            if age_days > expire_days:
                expired[source]["timestamps"].append(ts_str)
                expired[source]["chunks"] += 1
                expired[source]["age_days"] = age_days
        except (ValueError, TypeError):
            continue

    result = []
    for source, info in expired.items():
        result.append({
            "source": source,
            "oldest_timestamp": min(info["timestamps"]),
            "age_days": info["age_days"],
            "chunk_count": info["chunks"],
        })

    result.sort(key=lambda x: x["age_days"], reverse=True)
    return result


def check_dead_links() -> List[Dict[str, Any]]:
    """
    死链接检测 - 检查 metadata 中 source 文件是否仍存在于磁盘

    Returns:
        死链列表 [{source, original_file, exists}]
    """
    col = _get_collection()
    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])

    # 收集所有唯一的 source 文件名
    sources = set()
    for meta in metas:
        meta = meta or {}
        source = meta.get("source", "")
        original_file = meta.get("original_file", "")
        if source and source != "api" and source != "未知":
            sources.add((source, original_file))

    # 构建已有文件集合
    existing_files = set()
    for folder in _SOURCE_FOLDERS:
        try:
            for f in os.listdir(folder):
                existing_files.add(f.lower())
        except Exception:
            continue

    # Inbox 文件夹
    if os.path.exists(_INBOX_FOLDER):
        for f in os.listdir(_INBOX_FOLDER):
            existing_files.add(f.lower())

    dead_links = []
    for source, original_file in sources:
        # 检查 source 文件名是否在磁盘上存在
        source_lower = source.lower()
        found = source_lower in existing_files

        # 也检查 original_file
        if not found and original_file:
            found = original_file.lower() in existing_files

        if not found:
            dead_links.append({
                "source": source,
                "original_file": original_file,
                "searched_folders": _SOURCE_FOLDERS + [_INBOX_FOLDER],
            })

    return dead_links


def check_orphan_chunks() -> List[Dict[str, Any]]:
    """
    孤儿页检测 - 找 chunk_index 不连续的文档 (中间有缺失)

    Returns:
        不连续的文档列表 [{source, expected_indices, missing_indices}]
    """
    col = _get_collection()
    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])

    # 按 source 分组收集 chunk_index
    source_indices = defaultdict(set)
    for meta in metas:
        meta = meta or {}
        source = meta.get("source", "未知")
        chunk_idx = meta.get("chunk_index")
        if chunk_idx is not None:
            source_indices[source].add(int(chunk_idx))

    orphans = []
    for source, indices in source_indices.items():
        if len(indices) <= 1:
            continue

        sorted_idx = sorted(indices)
        expected = set(range(sorted_idx[0], sorted_idx[-1] + 1))
        missing = expected - set(sorted_idx)

        if missing:
            orphans.append({
                "source": source,
                "total_chunks": len(indices),
                "expected_range": f"{sorted_idx[0]}-{sorted_idx[-1]}",
                "missing_indices": sorted(missing),
                "missing_count": len(missing),
            })

    orphans.sort(key=lambda x: x["missing_count"], reverse=True)
    return orphans


def run_full_check() -> Dict[str, Any]:
    """
    运行完整健康检查

    Returns:
        {
            "stats": {...},
            "expired": [...],
            "dead_links": [...],
            "orphans": [...],
            "health_score": float,
            "summary": str,
        }
    """
    stats = get_stats()
    expired = check_expired()
    dead_links = check_dead_links()
    orphans = check_orphan_chunks()

    # 计算健康分数 (0-100)
    total = stats["total_chunks"] or 1
    issues = 0
    issues += len(expired) * 5       # 每个过期来源扣 5 分
    issues += len(dead_links) * 3    # 每个死链扣 3 分
    issues += len(orphans) * 2       # 每个孤儿扣 2 分
    health_score = max(0, 100 - issues)

    # 生成摘要
    summary_parts = [f"知识库共 {stats['total_chunks']} 条记录"]
    if expired:
        summary_parts.append(f"{len(expired)} 个来源已过期")
    if dead_links:
        summary_parts.append(f"{len(dead_links)} 个死链接")
    if orphans:
        summary_parts.append(f"{len(orphans)} 个文档存在碎片缺失")
    if not expired and not dead_links and not orphans:
        summary_parts.append("一切正常!")

    return {
        "stats": stats,
        "expired": expired,
        "dead_links": dead_links,
        "orphans": orphans,
        "health_score": health_score,
        "summary": " | ".join(summary_parts),
    }


# ==================== 命令行入口 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("AKO 知识库健康检查")
    print("=" * 60)

    report = run_full_check()

    print(f"\n📊 统计概览:")
    print(f"  总记录数: {report['stats']['total_chunks']}")
    print(f"  来源数量: {report['stats']['unique_sources']}")
    print(f"  类型分布: {report['stats']['type_breakdown']}")
    print(f"  时间范围: {report['stats']['oldest_record']} ~ {report['stats']['newest_record']}")

    print(f"\n🏥 健康评分: {report['health_score']}/100")
    print(f"  {report['summary']}")

    if report["expired"]:
        print(f"\n⏰ 过期内容 ({len(report['expired'])} 个来源):")
        for item in report["expired"][:10]:
            print(f"  - {item['source']}: {item['age_days']} 天前 ({item['chunk_count']} 段)")

    if report["dead_links"]:
        print(f"\n🔗 死链接 ({len(report['dead_links'])} 个):")
        for item in report["dead_links"][:10]:
            print(f"  - {item['source']}")

    if report["orphans"]:
        print(f"\n📄 碎片缺失 ({len(report['orphans'])} 个文档):")
        for item in report["orphans"][:10]:
            print(f"  - {item['source']}: 缺失 {item['missing_count']} 段 "
                  f"(范围 {item['expected_range']})")

    print("\n" + "=" * 60)
