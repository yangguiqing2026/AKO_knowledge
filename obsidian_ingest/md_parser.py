# -*- coding: utf-8 -*-
"""N1 MdParser: frontmatter / wikilink 解析 + 标题层级分块。

metadata 契约(字段名禁止更改, 下游检索要过滤):
  source, type="obsidian_note", top_folder, title, heading_path,
  tags(逗号拼接), links(逗号拼接), chunk_index, sha256, ingested_at
Chroma metadata 只接受标量, list 一律逗号拼接成 str。
"""
import re
from datetime import datetime, timezone

import yaml

from .models import ChunkRecord, NoteRecord

# --- frontmatter ---
_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)

# --- wikilink: [[target]] / [[target|alias]] / ![[embed]] ---
_WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")

# --- 标题 ---
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)

MIN_NOTE_LEN = 300  # 整篇不足此长度 -> 单块


def parse_note(note: NoteRecord, raw: str) -> tuple[dict, str, list[str]]:
    """解析 frontmatter 与 wikilink。

    Returns:
        (frontmatter_meta, body_text, links)
        - frontmatter_meta: dict(无 frontmatter 或解析失败时为 {})
        - body_text: 去掉 frontmatter、wikilink 已替换为显示文本的正文
        - links: [[内链]] 与 ![[嵌入]] 的目标列表(去重, 保序)
    """
    fm: dict = {}
    body = raw
    m = _FM_RE.match(raw)
    if m:
        try:
            data = yaml.safe_load(m.group(1))
            if isinstance(data, dict):
                fm = data
        except yaml.YAMLError:
            fm = {}
        body = raw[m.end():]

    links: list[str] = []

    def _sub(match: re.Match) -> str:
        bang, target, alias = match.group(1), match.group(2).strip(), match.group(3)
        if target not in links:
            links.append(target)
        if bang:  # ![[嵌入]] -> 从正文移除, 仅留痕于 links
            return ""
        return (alias or target).strip()

    body = _WIKILINK_RE.sub(_sub, body)
    return fm, body, links


def _extract_title(body: str, fallback: str) -> str:
    for m in _HEADING_RE.finditer(body):
        if len(m.group(1)) == 1:
            return m.group(2).strip()
    return fallback


def _split_sections(body: str) -> list[tuple[str, str]]:
    """按 H2/H3 切分; 返回 [(heading_path, section_text), ...]。

    heading_path 形如 "章/节"; 前言(首个 H2/H3 之前)记 "(前言)"。
    H1 仅参与 heading_path 的顶层, 不触发切分。
    """
    sections: list[tuple[str, str]] = []
    h1 = h2 = ""
    cur_path = "(前言)"
    cur_lines: list[str] = []

    def flush():
        text = "\n".join(cur_lines).strip()
        if text:
            sections.append((cur_path, text))

    for line in body.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            if level == 1:
                h1, h2 = title, ""
            elif level in (2, 3):
                flush()
                cur_lines = []
                if level == 2:
                    h2 = title
                else:
                    pass  # H3 沿用所属 H2
                cur_path = "/".join(x for x in (h1, h2) if x) or "(未命名)"
                cur_lines.append(line)
                continue
        cur_lines.append(line)
    flush()
    return sections


def _window(text: str, size: int, overlap: int) -> list[str]:
    """字符滑窗; size/overlap 来自 config, 禁止硬编码调用值。"""
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    out = []
    for start in range(0, len(text), step):
        piece = text[start:start + size].strip()
        if piece:
            out.append(piece)
        if start + size >= len(text):
            break
    return out


def chunk_note(note: NoteRecord, body: str, fm: dict, links: list[str],
               chunk_size: int, overlap: int) -> list[ChunkRecord]:
    """把一篇笔记切成 ChunkRecord 列表。

    规则: 按 H2/H3 分节 -> 节内按 chunk_size/overlap 滑窗;
          整篇不足 MIN_NOTE_LEN 字时整篇作单块。
    """
    title = _extract_title(body, fallback=note.abs_path.stem)
    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,，]", tags) if t.strip()]
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    body_clean = body.strip()
    if not body_clean:
        return []
    if len(body_clean) < MIN_NOTE_LEN:
        pieces = [("(整篇)", body_clean)]
    else:
        pieces = []
        for path, sec in _split_sections(body_clean):
            for w in _window(sec, chunk_size, overlap):
                pieces.append((path, w))

    chunks: list[ChunkRecord] = []
    for i, (path, text) in enumerate(pieces, start=1):
        meta = {
            "source": note.rel_path,
            "type": "obsidian_note",
            "top_folder": note.top_folder,
            "title": title,
            "heading_path": path,
            "tags": ",".join(str(t) for t in tags),
            "links": ",".join(links),
            "chunk_index": i,
            "sha256": note.sha256,
            "ingested_at": ingested_at,
        }
        chunks.append(ChunkRecord(
            chunk_id=f"{note.rel_path}#{i:03d}",
            rel_path=note.rel_path,
            seq=i,
            text=text,
            metadata=meta,
        ))
    return chunks
