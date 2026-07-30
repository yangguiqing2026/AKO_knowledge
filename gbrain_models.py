# -*- coding: utf-8 -*-
"""
Gbrain 数据模型 — ConceptPage / CompiledTruth / EvidenceTimeline

核心概念:
  - 每个概念 (Concept) 有一页 ConceptPage
  - 页面顶部是 CompiledTruth (当前最佳理解)
  - 下方是 append-only 的 EvidenceTimeline (证据时间线)
  - 引用计数驱动分层富化: 1次→stub, 3次→补充, 8次→完整处理
"""
import datetime
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Evidence:
    """单条证据 — 从知识库检索到的原始片段"""
    source: str           # 来源文件/笔记
    chunk_id: str         # ChromaDB 块 ID
    text: str             # 片段原文
    context_before: str = ""   # 上下文前文
    context_after: str = ""    # 上下文后文
    timestamp: str = ""   # 入库时间


@dataclass
class TimelineEntry:
    """时间线条目 — append-only"""
    seq: int                    # 序号
    timestamp: str              # 记录时间
    event: str                  # 事件描述 (新发现 / 修正 / 确认)
    evidence: List[Evidence] = field(default_factory=list)
    source_hash: str = ""       # 证据来源的内容哈希，用于去重


@dataclass
class CompiledTruth:
    """当前最佳理解 — 页面顶部摘要"""
    summary: str                # 一句话总结
    confidence: float           # 置信度 [0, 1]
    key_facts: List[str] = field(default_factory=list)  # 关键事实列表
    contradictions: List[str] = field(default_factory=list)  # 矛盾点
    open_questions: List[str] = field(default_factory=list)  # 未解问题
    last_updated: str = ""


@dataclass
class ConceptPage:
    """概念页面 — Gbrain 核心数据结构"""
    concept_id: str             # 概念唯一标识 (来自 wikilink 规范化)
    concept_name: str           # 显示名
    mention_count: int = 0      # 被引用次数
    enrichment_level: int = 0   # 富化等级: 0=stub, 1=basic, 2=full
    compiled_truth: Optional[CompiledTruth] = None
    timeline: List[TimelineEntry] = field(default_factory=list)
    related_concepts: List[str] = field(default_factory=list)  # 关联概念
    backlinks: List[str] = field(default_factory=list)         # 反向链接
    tags: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    needs_review: bool = False  # 是否需要夜间审查

    # Enrichment thresholds
    STUB_THRESHOLD = 1    # 提到1次 → stub
    BASIC_THRESHOLD = 3   # 提到3次 → 自动搜索补充
    FULL_THRESHOLD = 8    # 提到8次 → 完整处理

    @property
    def is_stub(self) -> bool:
        return self.enrichment_level == 0

    @property
    def is_full(self) -> bool:
        return self.enrichment_level >= 2

    def determine_level(self) -> int:
        """根据引用次数确定富化等级"""
        if self.mention_count >= self.FULL_THRESHOLD:
            return 2
        elif self.mention_count >= self.BASIC_THRESHOLD:
            return 1
        else:
            return 0

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "mention_count": self.mention_count,
            "enrichment_level": self.enrichment_level,
            "compiled_truth": {
                "summary": self.compiled_truth.summary,
                "confidence": self.compiled_truth.confidence,
                "key_facts": self.compiled_truth.key_facts,
                "contradictions": self.compiled_truth.contradictions,
                "open_questions": self.compiled_truth.open_questions,
                "last_updated": self.compiled_truth.last_updated,
            } if self.compiled_truth else None,
            "timeline": [
                {
                    "seq": t.seq,
                    "timestamp": t.timestamp,
                    "event": t.event,
                    "source_hash": t.source_hash,
                }
                for t in self.timeline
            ],
            "related_concepts": self.related_concepts,
            "backlinks": self.backlinks,
            "tags": self.tags,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "needs_review": self.needs_review,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptPage":
        cp = cls(
            concept_id=d["concept_id"],
            concept_name=d["concept_name"],
            mention_count=d.get("mention_count", 0),
            enrichment_level=d.get("enrichment_level", 0),
            related_concepts=d.get("related_concepts", []),
            backlinks=d.get("backlinks", []),
            tags=d.get("tags", []),
            first_seen=d.get("first_seen", ""),
            last_seen=d.get("last_seen", ""),
            needs_review=d.get("needs_review", False),
        )
        if d.get("compiled_truth"):
            ct = d["compiled_truth"]
            cp.compiled_truth = CompiledTruth(
                summary=ct.get("summary", ""),
                confidence=ct.get("confidence", 0.0),
                key_facts=ct.get("key_facts", []),
                contradictions=ct.get("contradictions", []),
                open_questions=ct.get("open_questions", []),
                last_updated=ct.get("last_updated", ""),
            )
        if d.get("timeline"):
            cp.timeline = [
                TimelineEntry(
                    seq=t.get("seq", 0),
                    timestamp=t.get("timestamp", ""),
                    event=t.get("event", ""),
                    source_hash=t.get("source_hash", ""),
                )
                for t in d["timeline"]
            ]
        return cp


# ============================================================
# 概念存储: JSON 文件持久化 (位于 data/gbrain_graph.json)
# ============================================================
import os
import threading


class ConceptStore:
    """概念图存储 — 线程安全 JSON 持久化"""

    def __init__(self, db_path: str = ""):
        from pathlib import Path
        base = db_path or str(Path(__file__).resolve().parent)
        os.makedirs(os.path.join(base, "data"), exist_ok=True)
        self._file = os.path.join(base, "data", "gbrain_graph.json")
        self._lock = threading.Lock()
        self._concepts: Dict[str, ConceptPage] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._file):
                with open(self._file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._concepts = {
                    k: ConceptPage.from_dict(v) for k, v in raw.items()
                }
        except Exception:
            self._concepts = {}

    def _save(self):
        with self._lock:
            data = {k: v.to_dict() for k, v in self._concepts.items()}
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def get(self, concept_id: str) -> Optional[ConceptPage]:
        return self._concepts.get(concept_id)

    def get_all(self) -> Dict[str, ConceptPage]:
        return dict(self._concepts)

    def upsert(self, page: ConceptPage) -> None:
        self._concepts[page.concept_id] = page
        self._save()

    def delete(self, concept_id: str) -> bool:
        if concept_id in self._concepts:
            del self._concepts[concept_id]
            self._save()
            return True
        return False

    def count(self) -> int:
        return len(self._concepts)

    def get_by_level(self, level: int) -> List[ConceptPage]:
        return [p for p in self._concepts.values() if p.enrichment_level == level]

    def get_needs_review(self) -> List[ConceptPage]:
        return [p for p in self._concepts.values() if p.needs_review]

    def get_stubs(self) -> List[ConceptPage]:
        return self.get_by_level(0)

    def get_full(self) -> List[ConceptPage]:
        return self.get_by_level(2)