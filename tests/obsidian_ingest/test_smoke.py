# -*- coding: utf-8 -*-
"""obsidian_ingest 冒烟测试: 扫描排除 / 解析分块 / 台账对账 / 路由 / 端到端入库。

端到端用例依赖本机 Ollama bge-m3; 不可达时自动 skip。
运行(在 D:\\AKO_knowledge 下): ./.venv/Scripts/python.exe -m pytest tests/obsidian_ingest/test_smoke.py -v
"""
import sys
from pathlib import Path

import pytest

KB_ROOT = Path(__file__).resolve().parents[2]
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))

from obsidian_ingest.manifest import Manifest
from obsidian_ingest.md_parser import chunk_note, parse_note
from obsidian_ingest.vault_reader import read_note_text, scan_vault
from obsidian_ingest.vault_router import load_router, route_collection, route_file

FIXTURE = Path(__file__).parent / "fixture_vault"
CHUNK_SIZE, OVERLAP = 450, 100  # 与 config.json common_settings 对齐


# ---------- N0 扫描与排除 ----------

def test_scan_vault_exclusions():
    notes = scan_vault(FIXTURE)
    rels = sorted(n.rel_path for n in notes)
    assert rels == ["Inbox/临时记录.md", "无标题笔记.md", "规范/消防要点.md"]
    assert not any("_system" in r or ".obsidian" in r for r in rels)
    by_name = {n.rel_path: n for n in notes}
    assert by_name["无标题笔记.md"].top_folder == "(root)"
    assert by_name["Inbox/临时记录.md"].top_folder == "Inbox"
    assert all(len(n.sha256) == 64 for n in notes)


# ---------- N1 解析与分块 ----------

def test_parse_frontmatter_and_wikilinks():
    notes = {n.rel_path: n for n in scan_vault(FIXTURE)}
    note = notes["规范/消防要点.md"]
    fm, body, links = parse_note(note, read_note_text(note.abs_path))
    assert fm.get("aliases") == ["消防要点汇编"]
    assert "---" not in body and "tags:" not in body  # frontmatter 不进正文
    assert "陶粒墙板技术方案" in links
    assert "GB50016 建筑设计防火规范" in links
    assert "[[ ]]" not in body and "[[" not in body    # wikilink 已替换为显示文本
    assert "防火规范" in body                          # 别名替换生效


def test_chunk_single_block_for_short_note():
    notes = {n.rel_path: n for n in scan_vault(FIXTURE)}
    note = notes["无标题笔记.md"]
    fm, body, links = parse_note(note, read_note_text(note.abs_path))
    chunks = chunk_note(note, body, fm, links, CHUNK_SIZE, OVERLAP)
    assert len(chunks) == 1                            # 不足 300 字整篇单块
    assert chunks[0].chunk_id == "无标题笔记.md#001"
    assert chunks[0].metadata["type"] == "obsidian_note"
    assert chunks[0].metadata["source"] == "无标题笔记.md"


def test_chunk_window_and_metadata():
    notes = {n.rel_path: n for n in scan_vault(FIXTURE)}
    note = notes["规范/消防要点.md"]
    fm, body, links = parse_note(note, read_note_text(note.abs_path))
    chunks = chunk_note(note, body, fm, links, CHUNK_SIZE, OVERLAP)
    assert len(chunks) >= 2                            # 长文产生多块
    assert all(len(c.text) <= CHUNK_SIZE for c in chunks)
    assert [c.chunk_id for c in chunks] == [f"规范/消防要点.md#{i:03d}" for i in range(1, len(chunks) + 1)]
    assert chunks[0].metadata["title"] == "陶粒墙板消防设计要点"
    assert "消防" in chunks[0].metadata["tags"]
    assert all(isinstance(c.metadata["links"], str) for c in chunks)  # Chroma 标量限制


# ---------- N2 路由 ----------

def test_router_default():
    router = load_router(KB_ROOT / "obsidian_ingest" / "vault_router.yaml")
    assert route_collection("(root)", router) == "ako_taoli_general_arch"
    assert route_collection("未知目录", router) == "ako_taoli_general_arch"


def test_router_file_rules():
    """文件级规则: ALC 标准应路由到规范专库并使用 1200/200 粗分块。"""
    router = load_router(KB_ROOT / "obsidian_ingest" / "vault_router.yaml")
    alc = "AKO_knowledge_base/ALC板材安装构法标准·同解说（2013年版）.md"
    col, cs, ov = route_file(alc, "AKO_knowledge_base", router)
    assert (col, cs, ov) == ("ako_taoli_codes_arch", 1200, 200)
    # 普通文件不受文件级规则影响
    col2, cs2, ov2 = route_file("Inbox/临时记录.md", "Inbox", router)
    assert (col2, cs2, ov2) == ("ako_taoli_general_arch", None, None)


# ---------- 台账对账 ----------

def test_manifest_diff_lifecycle(tmp_path):
    mf = Manifest(tmp_path / "manifest.db")
    notes = scan_vault(FIXTURE)
    new, changed, unchanged, deleted = mf.diff(notes)
    assert len(new) == 3 and not changed and not unchanged and not deleted

    for n in notes:
        mf.upsert(n, "ako_taoli_general_arch", 2)
    new, changed, unchanged, deleted = mf.diff(notes)
    assert not new and not changed and len(unchanged) == 3 and not deleted

    # 模拟变更: 篡改 sha256
    fake = notes[0].model_copy(update={"sha256": "0" * 64})
    new, changed, unchanged, deleted = mf.diff([fake] + notes[1:])
    assert [n.rel_path for n in changed] == [notes[0].rel_path]

    # 模拟删除: 只传两篇
    new, changed, unchanged, deleted = mf.diff(notes[1:])
    assert deleted == [notes[0].rel_path]
    mf.remove(notes[0].rel_path)
    assert mf.get(notes[0].rel_path) is None
    mf.close()


# ---------- 端到端(真实 Ollama + 临时 Chroma) ----------

def test_e2e_ingest_and_query(tmp_path):
    requests = pytest.importorskip("requests")
    try:
        requests.get("http://localhost:11434/api/tags", timeout=3)
    except Exception:
        pytest.skip("Ollama 不可达, 跳过端到端用例")

    import chromadb
    from obsidian_ingest.embedder import BgeM3Embedder, write_chunks

    notes = scan_vault(FIXTURE)
    embedder = BgeM3Embedder(batch=4)
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    col_name = "test_obsidian_ingest"

    total = 0
    for note in notes:
        fm, body, links = parse_note(note, read_note_text(note.abs_path))
        chunks = chunk_note(note, body, fm, links, CHUNK_SIZE, OVERLAP)
        vecs = embedder.embed([c.text for c in chunks])
        assert all(len(v) == 1024 for v in vecs)
        write_chunks(client, col_name, chunks, vecs)
        total += len(chunks)

    col = client.get_collection(col_name)
    assert col.count() == total

    qvec = embedder.embed(["陶粒墙板 耐火极限"])[0]
    res = col.query(query_embeddings=[qvec], n_results=2)
    hit_sources = [m["source"] for m in res["metadatas"][0]]
    assert "规范/消防要点.md" in hit_sources           # 语义检索命中正确文件
    client.delete_collection(col_name)                 # 现场清理
