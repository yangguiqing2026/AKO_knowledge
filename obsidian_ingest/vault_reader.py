# -*- coding: utf-8 -*-
"""N0 VaultReader: 只读扫描 Obsidian vault, 产出 NoteRecord 列表。

铁律: 对 vault 全程只读, 一个字节都不写。
排除规则(任一命中即跳过):
  - 相对路径任意一级为 .obsidian / .trash / .git / .smart-env
  - 首层目录为 _system
  - 文件名含 "冲突" 或 "conflict"(不区分大小写)
  - 扩展名非 .md(PDF/HTML 留给 Phase 2 附件管道)
注意: AKO_knowledge_base 是嵌套 vault(自带 .obsidian/.git), 其中 .md 正常收录。
"""
import hashlib
import time
from pathlib import Path

from .models import NoteRecord

EXCLUDED_DIRS = {".obsidian", ".trash", ".git", ".smart-env"}
EXCLUDED_TOP = {"_system"}
CONFLICT_MARKS = ("冲突", "conflict")
ROOT_LABEL = "(root)"


def _sha256_file(path: Path, bufsize: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(bufsize)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _is_excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDED_DIRS for p in parts):
        return True
    if len(parts) > 1 and parts[0] in EXCLUDED_TOP:
        return True
    name = rel.name.lower()
    if any(m in name for m in CONFLICT_MARKS):
        return True
    return False


def scan_vault(vault_root: Path) -> list[NoteRecord]:
    """遍历 vault, 返回全部合格 .md 笔记的 NoteRecord(按 rel_path 排序)。"""
    vault_root = Path(vault_root)
    notes: list[NoteRecord] = []
    for p in sorted(vault_root.rglob("*.md")):
        if not p.is_file():
            continue
        rel = p.relative_to(vault_root)
        if _is_excluded(rel):
            continue
        rel_posix = rel.as_posix()
        top = rel.parts[0] if len(rel.parts) > 1 else ROOT_LABEL
        st = p.stat()
        notes.append(NoteRecord(
            rel_path=rel_posix,
            abs_path=p,
            top_folder=top,
            sha256=_sha256_file(p),
            mtime=st.st_mtime,
            size=st.st_size,
        ))
    return notes


def read_note_text(abs_path: Path, retries: int = 3) -> str:
    """以 utf-8 读取笔记全文; 占用/锁定时按 1s/3s/10s 重试, 仍失败抛异常。"""
    delays = [1, 3, 10]
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError as ex:  # 网盘/编辑器占用等瞬态错误
            last = ex
            if attempt < retries - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
    raise last if last else RuntimeError(f"读取失败: {abs_path}")
