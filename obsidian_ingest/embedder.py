# -*- coding: utf-8 -*-
"""N3 kb_embedder: bge-m3 向量化(Ollama) + ChromaDB 写入 + Hub 双写。

- bge-m3: POST http://localhost:11434/api/embed, batch=4(5500U 安全内存), 失败重试 2 次
- 本地为主, Hub 为副本: 双写失败只记 errors, 不影响本地写入结果
- 更新文件: 先按旧 chunk_count 推导旧 ids 删除, 再写新块
"""
import sys
import time
from pathlib import Path

import requests

# 引导: 使 config_loader 可从知识库根目录导入(与 cwd 无关)
_KB_ROOT = Path(__file__).resolve().parent.parent
if str(_KB_ROOT) not in sys.path:
    sys.path.insert(0, str(_KB_ROOT))

from .models import ChunkRecord  # noqa: E402


class OllamaUnavailable(RuntimeError):
    """Ollama 服务不可达(CLI 退出码 2)。"""


class BgeM3Embedder:
    """bge-m3 三向量之 Dense 向量(1024 维), 走 Ollama /api/embed。"""

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "bge-m3", batch: int = 4, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch = batch
        self.retries = retries

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/api/embed"
        payload = {"model": self.model, "input": texts}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = requests.post(url, json=payload, timeout=120)
                r.raise_for_status()
                data = r.json()
                embs = data.get("embeddings")
                if not embs or len(embs) != len(texts):
                    raise RuntimeError(f"embed 返回数量异常: 期望 {len(texts)} 实得 {len(embs or [])}")
                return embs
            except requests.ConnectionError as ex:
                raise OllamaUnavailable(
                    f"Ollama 不可达({self.base_url}), 请先启动 Ollama 服务") from ex
            except Exception as ex:  # noqa: BLE001
                last = ex
                if attempt < self.retries:
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"bge-m3 向量化失败: {last}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """分批向量化; 返回与输入等长的 1024 维向量列表。"""
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            out.extend(self._embed_batch(texts[i:i + self.batch]))
        return out


def _get_or_create(client, name: str):
    return client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"})


def write_chunks(client, collection_name: str, chunks: list[ChunkRecord],
                 vectors: list[list[float]]) -> None:
    """把一批块写入指定 collection(幂等: 先按 ids 删除再写入)。"""
    if not chunks:
        return
    col = _get_or_create(client, collection_name)
    ids = [c.chunk_id for c in chunks]
    try:
        col.delete(ids=ids)
    except Exception:  # noqa: BLE001 - id 不存在时忽略
        pass
    col.add(
        ids=ids,
        embeddings=vectors,
        documents=[c.text for c in chunks],
        metadatas=[c.metadata for c in chunks],
    )


def delete_file_chunks(client, collection_name: str, rel_path: str,
                       old_chunk_count: int) -> None:
    """按 rel_path + 旧块数推导 ids 删除(更新/墓碑共用)。"""
    if old_chunk_count <= 0:
        return
    try:
        col = client.get_collection(collection_name)
    except Exception:  # noqa: BLE001 - collection 不存在则无事可做
        return
    ids = [f"{rel_path}#{i:03d}" for i in range(1, old_chunk_count + 1)]
    try:
        col.delete(ids=ids)
    except Exception:  # noqa: BLE001
        pass


def purge_obsidian_chunks(client, collection_name: str) -> int:
    """--full 用: 清空 collection 中 type=obsidian_note 的全部块, 返回删除数。"""
    try:
        col = client.get_collection(collection_name)
    except Exception:  # noqa: BLE001
        return 0
    res = col.get(where={"type": "obsidian_note"}, include=[])
    ids = res.get("ids") or []
    if ids:
        col.delete(ids=ids)
    return len(ids)
