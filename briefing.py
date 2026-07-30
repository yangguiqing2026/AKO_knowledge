"""
AKO_Hub 每日简报生成工具 - briefing 技能

功能:
1. 汇总知识库最近入库的内容
2. 检测即将到期的文档 (基于 metadata timestamp)
3. 统计今日/本周新增量
4. 调用 DeepSeek 生成自然语言简报 (可选)
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

LLM_API_BASE = config.llm_api_base
LLM_API_KEY = config.llm_api_key
LLM_MODEL = config.llm_model


def _get_collection():
    """获取 ChromaDB collection"""
    client = chromadb.PersistentClient(path=config.db_path)
    return client.get_collection(config.collection_name)


def _parse_timestamp(ts_str: str) -> Optional[datetime.datetime]:
    """解析 ISO 格式时间戳"""
    if not ts_str:
        return None
    try:
        return datetime.datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


# ==================== 数据收集 ====================

def get_recent_additions(days: int = 7) -> List[Dict[str, Any]]:
    """
    获取最近 N 天新增的文档

    Returns:
        [{source, type, chunk_count, first_seen, timestamp}]
    """
    col = _get_collection()
    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])

    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=days)

    # 按 source 聚合
    source_info = defaultdict(lambda: {
        "chunks": 0,
        "types": set(),
        "timestamps": [],
        "earliest": None,
    })

    for meta in metas:
        meta = meta or {}
        source = meta.get("source", "未知")
        doc_type = meta.get("type", "未知")
        ts = _parse_timestamp(meta.get("timestamp", ""))

        if ts and ts >= cutoff:
            source_info[source]["chunks"] += 1
            source_info[source]["types"].add(doc_type)
            source_info[source]["timestamps"].append(ts)
            if source_info[source]["earliest"] is None or ts < source_info[source]["earliest"]:
                source_info[source]["earliest"] = ts

    result = []
    for source, info in source_info.items():
        result.append({
            "source": source,
            "type": ", ".join(info["types"]),
            "chunk_count": info["chunks"],
            "first_seen": info["earliest"].isoformat() if info["earliest"] else "",
        })

    result.sort(key=lambda x: x["first_seen"], reverse=True)
    return result


def get_today_stats() -> Dict[str, Any]:
    """
    获取今日统计

    Returns:
        {total_chunks, new_sources, new_chunks, source_breakdown}
    """
    col = _get_collection()
    total = col.count()

    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])

    now = datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - datetime.timedelta(days=7)

    today_chunks = 0
    week_chunks = 0
    today_sources = set()
    week_sources = set()
    type_breakdown = defaultdict(int)

    for meta in metas:
        meta = meta or {}
        ts = _parse_timestamp(meta.get("timestamp", ""))
        source = meta.get("source", "未知")
        doc_type = meta.get("type", "未知")

        if ts:
            if ts >= today_start:
                today_chunks += 1
                today_sources.add(source)
            if ts >= week_start:
                week_chunks += 1
                week_sources.add(source)
            type_breakdown[doc_type] += 1

    return {
        "total_chunks": total,
        "today_chunks": today_chunks,
        "today_sources": len(today_sources),
        "today_source_list": list(today_sources),
        "week_chunks": week_chunks,
        "week_sources": len(week_sources),
        "type_breakdown": dict(type_breakdown),
    }


def get_expiring_soon(days: int = 30) -> List[Dict[str, Any]]:
    """
    获取即将到期 (超过 N 天) 的文档

    Returns:
        [{source, age_days, chunk_count}]
    """
    col = _get_collection()
    all_data = col.get(include=["metadatas"])
    metas = all_data.get("metadatas", [])

    now = datetime.datetime.now()
    threshold = now - datetime.timedelta(days=days)

    expiring = defaultdict(lambda: {"chunks": 0, "oldest": None})

    for meta in metas:
        meta = meta or {}
        source = meta.get("source", "未知")
        ts = _parse_timestamp(meta.get("timestamp", ""))

        if ts and ts < threshold:
            expiring[source]["chunks"] += 1
            if expiring[source]["oldest"] is None or ts < expiring[source]["oldest"]:
                expiring[source]["oldest"] = ts

    result = []
    for source, info in expiring.items():
        age = (now - info["oldest"]).days if info["oldest"] else 0
        result.append({
            "source": source,
            "age_days": age,
            "chunk_count": info["chunks"],
        })

    result.sort(key=lambda x: x["age_days"], reverse=True)
    return result


# ==================== 简报生成 ====================

def generate_briefing_text(
    stats: Dict[str, Any],
    recent: List[Dict[str, Any]],
    expiring: List[Dict[str, Any]],
) -> str:
    """
    生成纯文本简报 (不依赖 LLM)
    """
    now = datetime.datetime.now()
    lines = []
    lines.append(f"📋 AKO 知识库每日简报 - {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 50)

    # 统计概览
    lines.append(f"\n📊 知识库概览:")
    lines.append(f"  总记录数: {stats['total_chunks']}")
    lines.append(f"  今日新增: {stats['today_chunks']} 段 ({stats['today_sources']} 个来源)")
    lines.append(f"  本周新增: {stats['week_chunks']} 段 ({stats['week_sources']} 个来源)")

    if stats["type_breakdown"]:
        lines.append(f"  类型分布: {', '.join(f'{k}:{v}' for k, v in stats['type_breakdown'].items())}")

    # 今日新增来源
    if stats["today_source_list"]:
        lines.append(f"\n📥 今日新入库:")
        for src in stats["today_source_list"][:10]:
            lines.append(f"  • {src}")

    # 最近 7 天
    if recent:
        lines.append(f"\n📰 最近 7 天入库 ({len(recent)} 个来源):")
        for item in recent[:10]:
            lines.append(f"  • {item['source']} ({item['type']}, {item['chunk_count']} 段)")

    # 即将过期
    if expiring:
        lines.append(f"\n⏰ 超过 30 天未更新 ({len(expiring)} 个来源):")
        for item in expiring[:5]:
            lines.append(f"  • {item['source']} - {item['age_days']} 天前")

    # 健康提示
    lines.append(f"\n💡 提示:")
    if stats["today_chunks"] == 0:
        lines.append("  ⚠️ 今日暂无新增内容")
    if len(expiring) > 5:
        lines.append(f"  ⚠️ {len(expiring)} 个来源超过 30 天未更新，建议检查是否需要刷新")

    lines.append("\n" + "=" * 50)
    return "\n".join(lines)


def generate_llm_briefing(
    stats: Dict[str, Any],
    recent: List[Dict[str, Any]],
    expiring: List[Dict[str, Any]],
) -> str:
    """
    调用 DeepSeek 生成自然语言简报
    """
    if not LLM_API_KEY:
        return generate_briefing_text(stats, recent, expiring)

    # 构建 prompt
    context_parts = [
        f"知识库总记录: {stats['total_chunks']}",
        f"今日新增: {stats['today_chunks']} 段, {stats['today_sources']} 个来源",
        f"本周新增: {stats['week_chunks']} 段",
    ]

    if recent:
        context_parts.append("最近入库:")
        for item in recent[:5]:
            context_parts.append(f"  - {item['source']} ({item['type']})")

    if expiring:
        context_parts.append("即将过期:")
        for item in expiring[:3]:
            context_parts.append(f"  - {item['source']} ({item['age_days']} 天)")

    context = "\n".join(context_parts)

    prompt = f"""你是一个知识库管理助手。请根据以下知识库数据生成一份简洁的每日简报。

{context}

要求:
1. 用简洁的中文总结知识库动态
2. 突出重要变化 (新增内容、过期风险)
3. 给出 1-2 条管理建议
4. 控制在 200 字以内"""

    try:
        import httpx
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{LLM_API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            llm_text = data["choices"][0]["message"]["content"]

            # 拼接基础统计 + LLM 总结
            text_briefing = generate_briefing_text(stats, recent, expiring)
            return f"{text_briefing}\n\n🤖 AI 总结:\n{llm_text}"

    except Exception as e:
        # 降级到纯文本
        text = generate_briefing_text(stats, recent, expiring)
        return f"{text}\n\n(LLM 简报生成失败: {e})"


# ==================== 主入口 ====================

def generate_briefing(use_llm: bool = True, days: int = 7) -> Dict[str, Any]:
    """
    生成每日简报

    Args:
        use_llm: 是否使用 DeepSeek 生成 AI 总结
        days: 回溯天数

    Returns:
        {
            "date": str,
            "stats": dict,
            "recent": list,
            "expiring": list,
            "briefing_text": str,
        }
    """
    stats = get_today_stats()
    recent = get_recent_additions(days=days)
    expiring = get_expiring_soon(days=30)

    if use_llm and LLM_API_KEY:
        briefing_text = generate_llm_briefing(stats, recent, expiring)
    else:
        briefing_text = generate_briefing_text(stats, recent, expiring)

    return {
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stats": stats,
        "recent": recent,
        "expiring": expiring,
        "briefing_text": briefing_text,
    }


# ==================== 命令行入口 ====================
if __name__ == "__main__":
    import sys

    use_llm = "--no-llm" not in sys.argv

    print("正在生成简报...")
    report = generate_briefing(use_llm=use_llm)
    print(report["briefing_text"])
