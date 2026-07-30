# -*- coding: utf-8 -*-
"""CLI 入口: Obsidian vault 增量入库。

用法(在 D:\\AKO_knowledge 下):
  python -m obsidian_ingest.ingest_obsidian [--vault D:\\AKOBUILD] [--dry-run] [--full]

  --dry-run  只扫描+对账, 打印 IngestReport, 不写库
  --full     无视台账全量重建(先清空目标 collection 中 type=obsidian_note 的块)

退出码: 0 全部成功; 1 有 errors; 2 Ollama 不可达。
"""
import argparse
import json
import sys
from pathlib import Path

import chromadb

_KB_ROOT = Path(__file__).resolve().parent.parent
if str(_KB_ROOT) not in sys.path:
    sys.path.insert(0, str(_KB_ROOT))

from config_loader import get_config  # noqa: E402

from .embedder import (BgeM3Embedder, OllamaUnavailable, delete_file_chunks,  # noqa: E402
                       purge_obsidian_chunks, write_chunks)
from .manifest import Manifest  # noqa: E402
from .md_parser import chunk_note, parse_note  # noqa: E402
from .models import IngestReport  # noqa: E402
from .vault_reader import read_note_text, scan_vault  # noqa: E402
from .vault_router import load_router, route_file  # noqa: E402

DEFAULT_VAULT = r"D:\AKOBUILD"

# 每批嵌入+落盘的块数; 粗分块(1200字)单块约4-7s, 10块/批约1分钟可稳过5分钟执行窗口
EMBED_GROUP = 10
PROGRESS_FILE = Path(__file__).parent / ".embed_progress.json"


def load_progress() -> dict:
    """读取批级嵌入断点 {rel_path: 下一待嵌 seq(1 起始)}。"""
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 文件缺失/损坏均视为无断点
        return {}


def save_progress(progress: dict) -> None:
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Obsidian vault 增量入库(只读 vault)")
    ap.add_argument("--vault", default=DEFAULT_VAULT, help="vault 根目录")
    ap.add_argument("--dry-run", action="store_true", help="只扫描+对账, 不写库")
    ap.add_argument("--full", action="store_true", help="无视台账全量重建")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"[错误] vault 不存在: {vault}")
        return 1

    cfg = get_config()
    router = load_router(Path(__file__).parent / "vault_router.yaml")
    report = IngestReport()

    # N0 扫描
    notes = scan_vault(vault)
    report.scanned = len(notes)

    manifest = Manifest(Path(__file__).parent / "manifest.db")

    # 本地 Chroma(cfg.db_path 即 D:\AKO_knowledge)
    local_client = chromadb.PersistentClient(path=cfg.db_path)

    # Hub 双写客户端(可选; 本地为主 Hub 为副本)
    # 注意: 不用 cfg.hub_chroma_root 属性 —— 它会优先取 AKO_Hub hub.yaml 的 sync_root
    # (当前指向失效的 E: 网盘路径), 这里以本模块已验证的 config.json 值为准
    hub_cfg = cfg.config.get("hub_integration", {})
    dual = bool(cfg.hub_enabled and hub_cfg.get("dual_write", False))
    hub_client = None
    if dual:
        try:
            hub_client = chromadb.PersistentClient(path=hub_cfg["hub_chroma_root"])
        except Exception as ex:  # noqa: BLE001
            report.errors.append(f"Hub 客户端初始化失败(仅影响副本): {ex}")
            hub_client = None

    collections = {route_file(n.rel_path, n.top_folder, router)[0] for n in notes}
    collections.add(router.get("default"))

    if args.full:
        for name in collections:
            purge_obsidian_chunks(local_client, name)
            if hub_client is not None:
                try:
                    purge_obsidian_chunks(hub_client, name)
                except Exception as ex:  # noqa: BLE001
                    report.errors.append(f"Hub purge 失败 {name}: {ex}")
        manifest.clear()
        PROGRESS_FILE.unlink(missing_ok=True)  # 全量重建时批级断点一并作废
        new, changed, unchanged, deleted = notes, [], [], []
    else:
        new, changed, unchanged, deleted = manifest.diff(notes)

    report.new = len(new)
    report.updated = len(changed)
    report.unchanged = len(unchanged)
    report.deleted = len(deleted)

    if args.dry_run:
        manifest.close()
        print(report.table())
        return 0 if not report.errors else 1

    embedder = BgeM3Embedder(model=cfg.embedding_model, batch=4)

    # N3 墓碑清理
    for rp in deleted:
        old = manifest.get(rp) or {}
        col_name = old.get("collection", router.get("default"))
        delete_file_chunks(local_client, col_name, rp, old.get("chunk_count", 0))
        if hub_client is not None:
            try:
                delete_file_chunks(hub_client, col_name, rp, old.get("chunk_count", 0))
            except Exception as ex:  # noqa: BLE001
                report.errors.append(f"Hub 墓碑失败 {rp}: {ex}")
        manifest.remove(rp)

    # N1+N3 处理新增/变更(按 EMBED_GROUP 分组落盘+存档进度, 支持 5 分钟窗口断点续跑)
    progress = load_progress()
    try:
        for note in new + changed:
            col_name, cs, ov = route_file(note.rel_path, note.top_folder, router)
            try:
                raw = read_note_text(note.abs_path)
                fm, body, links = parse_note(note, raw)
                chunks = chunk_note(note, body, fm, links,
                                    cs or cfg.chunk_size, ov or cfg.overlap)
                if not chunks:
                    report.errors.append(f"空笔记跳过: {note.rel_path}")
                    continue

                if note in changed:
                    old = manifest.get(note.rel_path) or {}
                    delete_file_chunks(local_client, col_name, note.rel_path,
                                       old.get("chunk_count", 0))
                    if hub_client is not None:
                        try:
                            delete_file_chunks(hub_client, col_name, note.rel_path,
                                               old.get("chunk_count", 0))
                        except Exception as ex:  # noqa: BLE001
                            report.errors.append(f"Hub 更新清理失败 {note.rel_path}: {ex}")

                # 断点: 上次窗口已写出的分组直接跳过(chunk_id 幂等, 不重嵌)
                start_seq = progress.get(note.rel_path, 1)
                pending = [c for c in chunks if c.seq >= start_seq]
                for gi in range(0, len(pending), EMBED_GROUP):
                    group = pending[gi:gi + EMBED_GROUP]
                    vectors = embedder.embed([c.text for c in group])
                    write_chunks(local_client, col_name, group, vectors)
                    if hub_client is not None:
                        try:
                            write_chunks(hub_client, col_name, group, vectors)
                        except Exception as ex:  # noqa: BLE001
                            report.errors.append(f"Hub 双写失败 {note.rel_path}: {ex}")
                    progress[note.rel_path] = group[-1].seq + 1
                    save_progress(progress)
                    report.chunks_written += len(group)

                progress.pop(note.rel_path, None)
                save_progress(progress)
                manifest.upsert(note, col_name, len(chunks))
            except OllamaUnavailable:
                raise
            except Exception as ex:  # noqa: BLE001
                report.errors.append(f"{note.rel_path}: {ex}")
    except OllamaUnavailable as ex:
        manifest.close()
        print(f"[错误] {ex}")
        return 2

    manifest.close()
    print(report.table())
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
