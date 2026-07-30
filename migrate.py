"""
AKO_Hub 知识库迁移工具 - migrate 技能

支持从以下来源导入:
1. Obsidian vault (Markdown + YAML frontmatter + [[wikilinks]])
2. 通用 Markdown 文件夹
3. 纯文本文件夹

功能:
- 解析 YAML frontmatter (tags, title, date 等)
- 处理 [[wikilinks]] 交叉引用 → 转为可读文本
- 保留原始来源信息到 metadata
- 自动分块 + 嵌入入库
"""
import os
import re
import uuid
import json
import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

import chromadb
from config_loader import get_config

# ==================== 加载配置 ====================
config = get_config()

CHUNK_SIZE = config.chunk_size
OVERLAP = config.overlap
BATCH_SIZE = config.batch_size
EMBEDDING_MODEL = config.embedding_model


def _get_collection():
    """获取 ChromaDB collection"""
    db_path = config.db_path
    client = chromadb.PersistentClient(path=db_path)
    return client.get_collection(config.collection_name)


# ==================== Markdown 解析 ====================

def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    解析 YAML frontmatter

    Args:
        content: 原始 Markdown 内容

    Returns:
        (frontmatter_dict, body_text)
    """
    frontmatter = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()

            current_key = None
            current_list = None

            for line in fm_text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue

                # 列表项 (- item)
                if stripped.startswith("- ") and current_key:
                    if current_list is None:
                        current_list = []
                    current_list.append(stripped[2:].strip().strip("'\""))
                    frontmatter[current_key] = current_list
                    continue

                # key: value
                if ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    current_key = key
                    current_list = None

                    if val:
                        frontmatter[key] = val
                    else:
                        # 可能是列表的开头
                        frontmatter[key] = ""

    return frontmatter, body


def convert_wikilinks(text: str) -> str:
    """
    将 Obsidian [[wikilinks]] 转为可读文本

    [[page]] → page
    [[page|alias]] → alias
    [[page#heading]] → page > heading
    """
    def replace_wikilink(match):
        content = match.group(1)
        if "|" in content:
            return content.split("|")[1]
        if "#" in content:
            parts = content.split("#")
            return f"{parts[0]} > {parts[1]}"
        return content

    return re.sub(r"\[\[([^\]]+)\]\]", replace_wikilink, text)


def clean_markdown(text: str) -> str:
    """
    清理 Markdown 格式 (保留语义内容)

    - 移除图片链接 ![alt](url)
    - 转换链接 [text](url) → text
    - 转换 wikilinks
    - 移除 HTML 标签
    - 规范化空白
    """
    # 先处理 wikilinks
    text = convert_wikilinks(text)

    # 移除图片
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)

    # 转换链接为纯文本
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # 移除 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)

    # 移除 Markdown 格式符号 (保留文字)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # 标题
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # 粗体
    text = re.sub(r"\*([^*]+)\*", r"\1", text)  # 斜体
    text = re.sub(r"`([^`]+)`", r"\1", text)  # 行内代码
    text = re.sub(r"^[-*+]\s+", "• ", text, flags=re.MULTILINE)  # 列表

    # 规范化空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# ==================== 文件扫描 ====================

def scan_obsidian_vault(vault_path: str) -> List[Dict[str, Any]]:
    """
    扫描 Obsidian Vault 目录

    Args:
        vault_path: Obsidian vault 根目录

    Returns:
        文件信息列表 [{path, filename, frontmatter, body, wikilinks}]
    """
    if not os.path.exists(vault_path):
        raise FileNotFoundError(f"Vault 路径不存在: {vault_path}")

    files = []
    for root, dirs, filenames in os.walk(vault_path):
        # 跳过 Obsidian 系统目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for fn in filenames:
            if not fn.endswith((".md", ".markdown")):
                continue

            fp = os.path.join(root, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read()

                frontmatter, body = parse_frontmatter(content)
                wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
                cleaned_body = clean_markdown(body)

                if cleaned_body and len(cleaned_body) > 20:
                    files.append({
                        "path": fp,
                        "filename": fn,
                        "relative_path": os.path.relpath(fp, vault_path),
                        "frontmatter": frontmatter,
                        "body": cleaned_body,
                        "wikilinks": wikilinks,
                        "source_type": "obsidian",
                    })
            except Exception as e:
                print(f"  [警告] 读取 {fp} 失败: {e}")
                continue

    return files


def scan_markdown_folder(folder_path: str) -> List[Dict[str, Any]]:
    """
    扫描通用 Markdown 文件夹

    Returns:
        文件信息列表
    """
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    files = []
    for fn in os.listdir(folder_path):
        if not fn.endswith((".md", ".markdown", ".txt")):
            continue

        fp = os.path.join(folder_path, fn)
        if not os.path.isfile(fp):
            continue

        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()

            frontmatter, body = parse_frontmatter(content)
            cleaned_body = clean_markdown(body)

            if cleaned_body and len(cleaned_body) > 20:
                files.append({
                    "path": fp,
                    "filename": fn,
                    "frontmatter": frontmatter,
                    "body": cleaned_body,
                    "wikilinks": [],
                    "source_type": "markdown",
                })
        except Exception as e:
            print(f"  [警告] 读取 {fp} 失败: {e}")
            continue

    return files


# ==================== 分块 + 入库 ====================

def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """递归式文本分块"""
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if overlap is None:
        overlap = OVERLAP

    if not text or len(text) < 50:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks


def migrate_files(
    files: List[Dict[str, Any]],
    collection_name: str = None,
    skip_existing: bool = True,
) -> Dict[str, Any]:
    """
    将扫描到的文件迁移入库

    Args:
        files: scan_obsidian_vault 或 scan_markdown_folder 返回的文件列表
        collection_name: 目标 collection (默认使用配置)
        skip_existing: 是否跳过已入库的文档

    Returns:
        迁移报告 {files_processed, chunks_added, skipped, errors}
    """
    import ollama

    if collection_name is None:
        collection_name = config.collection_name

    col = _get_collection()
    timestamp = datetime.datetime.now().isoformat()

    report = {
        "files_processed": 0,
        "chunks_added": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    for file_idx, file_info in enumerate(files, 1):
        source_name = file_info["frontmatter"].get("title", file_info["filename"])
        source_type = file_info.get("source_type", "markdown")
        print(f"\n[{file_idx}/{len(files)}] 处理: {file_info['filename']}")

        # 检查是否已入库
        if skip_existing:
            existing = col.get(where={"source": source_name})
            if existing["ids"]:
                report["skipped"] += 1
                report["details"].append({
                    "file": file_info["filename"],
                    "status": "skipped",
                    "reason": "已存在",
                })
                continue

        body = file_info["body"]
        chunks = chunk_text(body)
        if not chunks:
            report["skipped"] += 1
            continue

        # 构建交叉引用信息
        cross_refs = ""
        if file_info.get("wikilinks"):
            cross_refs = f"\n[交叉引用: {', '.join(file_info['wikilinks'][:10])}]"

        added = 0
        for idx, chunk in enumerate(chunks):
            try:
                doc_id = str(uuid.uuid4())

                # 嵌入
                safe_text = chunk[:450]
                embed = ollama.embeddings(model=EMBEDDING_MODEL, prompt=safe_text)["embedding"]

                # metadata
                meta = {
                    "source": source_name,
                    "type": source_type,
                    "chunk_index": idx,
                    "timestamp": timestamp,
                    "original_file": file_info["filename"],
                    "original_path": file_info.get("relative_path", file_info["path"]),
                }

                # 添加 frontmatter 中的标签
                tags = file_info["frontmatter"].get("tags", [])
                if isinstance(tags, list):
                    meta["tags"] = ",".join(tags)
                elif tags:
                    meta["tags"] = str(tags)

                # 添加日期
                date_val = file_info["frontmatter"].get("date", "")
                if date_val:
                    meta["source_date"] = str(date_val)

                col.add(
                    ids=[doc_id],
                    embeddings=[embed],
                    documents=[chunk + cross_refs],
                    metadatas=[meta],
                )
                added += 1

            except Exception as e:
                print(f"  [错误] {file_info['filename']} chunk {idx}: {e}")
                report["errors"] += 1

        report["files_processed"] += 1
        report["chunks_added"] += added
        report["details"].append({
            "file": file_info["filename"],
            "status": "ok",
            "chunks": added,
        })
        print(f"  [OK] {file_info['filename']} -> {added} 段")

    return report


# ==================== 便捷入口 ====================

def migrate_from_obsidian(vault_path: str, skip_existing: bool = True) -> Dict[str, Any]:
    """从 Obsidian Vault 迁移"""
    print(f"\n[扫描] Obsidian Vault: {vault_path}")
    files = scan_obsidian_vault(vault_path)
    print(f"  发现 {len(files)} 个 Markdown 文件")

    if not files:
        return {"files_processed": 0, "chunks_added": 0, "message": "未发现可导入的文件"}

    print(f"\n[入库] 开始迁移入库...")
    report = migrate_files(files, skip_existing=skip_existing)
    report["message"] = (
        f"迁移完成: {report['files_processed']} 个文件, "
        f"{report['chunks_added']} 段入库, "
        f"{report['skipped']} 个跳过"
    )
    return report


def migrate_from_folder(folder_path: str, skip_existing: bool = True) -> Dict[str, Any]:
    """从 Markdown 文件夹迁移"""
    print(f"\n[扫描] 扫描文件夹: {folder_path}")
    files = scan_markdown_folder(folder_path)
    print(f"  发现 {len(files)} 个文件")

    if not files:
        return {"files_processed": 0, "chunks_added": 0, "message": "未发现可导入的文件"}

    print(f"\n[入库] 开始迁移入库...")
    report = migrate_files(files, skip_existing=skip_existing)
    report["message"] = (
        f"迁移完成: {report['files_processed']} 个文件, "
        f"{report['chunks_added']} 段入库"
    )
    return report


# ==================== 命令行入口 ====================
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python migrate.py obsidian <vault_path>  - 从 Obsidian 导入")
        print("  python migrate.py folder <folder_path>   - 从 Markdown 文件夹导入")
        sys.exit(1)

    mode = sys.argv[1].lower()
    path = sys.argv[2] if len(sys.argv) > 2 else ""

    if mode == "obsidian":
        if not path:
            path = input("请输入 Obsidian Vault 路径: ").strip()
        result = migrate_from_obsidian(path)
    elif mode == "folder":
        if not path:
            path = input("请输入 Markdown 文件夹路径: ").strip()
        result = migrate_from_folder(path)
    else:
        print(f"未知模式: {mode}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"迁移结果: {result.get('message', '完成')}")
    print(f"{'=' * 60}")
