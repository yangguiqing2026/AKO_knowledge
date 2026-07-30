# -*- coding: utf-8 -*-
"""增量对账台账(sqlite): rel_path -> sha256/mtime/collection/chunk_count。

台账存于 D:\\AKO_knowledge\\obsidian_ingest\\manifest.db, 只写本地, 不进 vault。
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import NoteRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_map(
  rel_path TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  mtime REAL NOT NULL,
  collection TEXT NOT NULL,
  chunk_count INTEGER NOT NULL,
  ingested_at TEXT NOT NULL
);
"""


class Manifest:
    """文件级增量台账; diff 判据: rel_path 存在性 + sha256。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def diff(self, notes: list[NoteRecord]) -> tuple[list[NoteRecord], list[NoteRecord], list[NoteRecord], list[str]]:
        """对比扫描结果与台账 -> (new, changed, unchanged, deleted_rel_paths)。"""
        known = {r[0]: r[1] for r in self._conn.execute("SELECT rel_path, sha256 FROM file_map")}
        new, changed, unchanged = [], [], []
        seen: set[str] = set()
        for n in notes:
            seen.add(n.rel_path)
            old = known.get(n.rel_path)
            if old is None:
                new.append(n)
            elif old != n.sha256:
                changed.append(n)
            else:
                unchanged.append(n)
        deleted = [rp for rp in known if rp not in seen]
        return new, changed, unchanged, deleted

    def upsert(self, note: NoteRecord, collection: str, chunk_count: int) -> None:
        self._conn.execute(
            "INSERT INTO file_map(rel_path, sha256, mtime, collection, chunk_count, ingested_at)"
            " VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(rel_path) DO UPDATE SET sha256=excluded.sha256,"
            " mtime=excluded.mtime, collection=excluded.collection,"
            " chunk_count=excluded.chunk_count, ingested_at=excluded.ingested_at",
            (note.rel_path, note.sha256, note.mtime, collection, chunk_count,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def remove(self, rel_path: str) -> None:
        self._conn.execute("DELETE FROM file_map WHERE rel_path=?", (rel_path,))
        self._conn.commit()

    def get(self, rel_path: str) -> dict | None:
        row = self._conn.execute(
            "SELECT rel_path, sha256, mtime, collection, chunk_count, ingested_at"
            " FROM file_map WHERE rel_path=?", (rel_path,)).fetchone()
        if row is None:
            return None
        return {"rel_path": row[0], "sha256": row[1], "mtime": row[2],
                "collection": row[3], "chunk_count": row[4], "ingested_at": row[5]}

    def clear(self) -> None:
        self._conn.execute("DELETE FROM file_map")
        self._conn.commit()
