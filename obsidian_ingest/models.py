# -*- coding: utf-8 -*-
"""Pydantic v2 数据模型: NoteRecord / ChunkRecord / IngestReport。"""
from pathlib import Path

from pydantic import BaseModel, Field


class NoteRecord(BaseModel):
    """vault 中一篇 .md 笔记的扫描记录(增量判据载体)。"""

    rel_path: str            # vault 相对路径, POSIX 风格, 如 "AKO_inbox/xxx.md"
    abs_path: Path
    top_folder: str          # 首层目录名; 根目录文件记 "(root)"
    sha256: str              # 全文哈希, 增量判据
    mtime: float
    size: int


class ChunkRecord(BaseModel):
    """一个待入库的文本块。"""

    chunk_id: str            # f"{rel_path}#{seq:03d}"
    rel_path: str
    seq: int
    text: str
    metadata: dict           # 见 md_parser.CHUNK_METADATA 契约


class IngestReport(BaseModel):
    """一次入库运行的统计报告。"""

    scanned: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0         # tombstone 处理的文件数
    chunks_written: int = 0
    errors: list[str] = Field(default_factory=list)

    def table(self) -> str:
        rows = [
            ("scanned", self.scanned),
            ("new", self.new),
            ("updated", self.updated),
            ("unchanged", self.unchanged),
            ("deleted(tombstone)", self.deleted),
            ("chunks_written", self.chunks_written),
            ("errors", len(self.errors)),
        ]
        width = max(len(k) for k, _ in rows)
        lines = [f"  {k:<{width}} : {v}" for k, v in rows]
        out = "IngestReport\n" + "\n".join(lines)
        if self.errors:
            out += "\n  --- errors ---\n" + "\n".join(f"  * {e}" for e in self.errors)
        return out
