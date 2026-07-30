# -*- coding: utf-8 -*-
"""N2 VaultRouter: 首层目录 -> collection 路由, 配置只读 vault_router.yaml。"""
from pathlib import Path

import yaml

DEFAULT_COLLECTION = "ako_taoli_general_arch"


def load_router(yaml_path: Path) -> dict:
    """读取路由配置; 文件缺失时返回仅含 default 的安全配置。"""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return {"default": DEFAULT_COLLECTION, "routes": {}, "file_rules": []}
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    data.setdefault("default", DEFAULT_COLLECTION)
    data.setdefault("routes", {})
    data.setdefault("file_rules", [])
    return data


def route_collection(top_folder: str, router: dict) -> str:
    """未命中走 default; 新增 collection 只改 yaml, 不动代码。"""
    return router.get("routes", {}).get(top_folder, router.get("default", DEFAULT_COLLECTION))


def route_file(rel_path: str, top_folder: str, router: dict) -> tuple[str, int | None, int | None]:
    """文件级规则优先于目录路由; 返回 (collection, chunk_size|None, overlap|None)。

    chunk_size/overlap 为 None 表示沿用 config.json common_settings。
    超大资料(如整本标准)在此单独指定专库与粗分块, 只改 yaml 不动代码。
    """
    for rule in router.get("file_rules") or []:
        if rule.get("match") == rel_path:
            return (rule.get("collection") or route_collection(top_folder, router),
                    rule.get("chunk_size"), rule.get("overlap"))
    return route_collection(top_folder, router), None, None
