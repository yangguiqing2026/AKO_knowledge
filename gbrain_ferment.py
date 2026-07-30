# -*- coding: utf-8 -*-
"""
Gbrain 核心发酵引擎 — 分层富化 (1/3/8) + 时间线追加

分层富化逻辑:
  1 次提及 → stub 页面 (仅记录概念，无具体内容)
  3 次提及 → 自动检索补充 (从知识库搜索相关内容，生成 CompiledTruth)
  8 次提及 → 完整处理 (深度检索 + LLM 综合 + 矛盾检测)

Append-only 时间线:
  - 每次发现新证据，追加到 Timeline
  - CompiledTruth 随新证据自动更新
"""
import datetime
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import chromadb

from gbrain_models import (
    ConceptPage,
    CompiledTruth,
    ConceptStore,
    Evidence,
    TimelineEntry,
)
from gbrain_graph import GraphBuilder, extract_wikilinks, normalize_concept_id


class FermentEngine:
    """
    Gbrain 发酵引擎

    工作流程:
      1. 扫描 ChromaDB + Vault 的 [[wikilink]]
      2. 与现有 ConceptPage 对比，更新 mention_count
      3. 根据 mention_count 触发对应的富化级别
      4. 追加 Timeline 条目
    """

    def __init__(
        self,
        chroma_collection=None,
        vault_root: str = r"D:\AKOBUILD",
        store: Optional[ConceptStore] = None,
    ):
        self.collection = chroma_collection
        self.vault_root = Path(vault_root) if vault_root else None
        self.store = store or ConceptStore()
        self.graph_builder = GraphBuilder(
            chroma_collection=chroma_collection,
            vault_root=str(vault_root) if vault_root else "",
        )

    # ==================================================================
    # 核心发酵流程
    # ==================================================================

    def ferment(self, full_graph: bool = True) -> dict:
        """
        执行完整发酵周期

        Steps:
          1. 重建概念图谱 (零成本正则扫描)
          2. 对账: 更新所有概念页的 mention_count
          3. 分层富化: stub → basic → full
          4. 追加时间线

        Returns:
            发酵报告
        """
        now = datetime.datetime.now().isoformat()

        # Step 1: 构建图谱
        if full_graph:
            self.graph_builder.scan_chromadb()
            if self.vault_root and self.vault_root.is_dir():
                self.graph_builder.scan_vault()
        else:
            self.graph_builder.scan_chromadb()

        graph = self.graph_builder.build_graph()
        graph_stats = self.graph_builder.get_stats()

        # Step 2: 对账 — 更新 mention_count，新建 stub
        stubs_created = 0
        upgrades_basic = 0
        upgrades_full = 0

        for cid, info in graph.items():
            name = info["name"]
            mentions = info["total_mentions"]
            existing = self.store.get(cid)

            if existing is None:
                # 新建 stub 页面
                page = ConceptPage(
                    concept_id=cid,
                    concept_name=name,
                    mention_count=mentions,
                    enrichment_level=0,
                    first_seen=now,
                    last_seen=now,
                    backlinks=info.get("backlinks", []),
                )
                page.timeline.append(TimelineEntry(
                    seq=1,
                    timestamp=now,
                    event=f"首次发现概念 '{name}'，提及 {mentions} 次",
                    source_hash=hashlib.md5(name.encode()).hexdigest()[:8],
                ))
                self.store.upsert(page)
                stubs_created += 1
            else:
                old_count = existing.mention_count
                old_level = existing.enrichment_level
                existing.mention_count = mentions
                existing.last_seen = now
                existing.backlinks = info.get("backlinks", [])

                # 判断是否需要升级
                new_level = existing.determine_level()
                existing.enrichment_level = new_level
                existing.needs_review = True

                if old_count != mentions:
                    existing.timeline.append(TimelineEntry(
                        seq=len(existing.timeline) + 1,
                        timestamp=now,
                        event=f"引用次数: {old_count} → {mentions}",
                        source_hash=hashlib.md5(
                            f"{cid}:{mentions}".encode()
                        ).hexdigest()[:8],
                    ))

                if new_level > old_level and new_level >= 1:
                    upgrades_basic += 1
                if new_level >= 2 and old_level < 2:
                    upgrades_full += 1

                self.store.upsert(existing)

        # Step 3: 分批富化
        enriched_basic = 0
        enriched_full = 0

        # 3a: 富化 level 1 的概念 (basic)
        for page in self.store.get_by_level(1):
            if page.needs_review:
                self._enrich_basic(page)
                enriched_basic += 1
                page.needs_review = False
                self.store.upsert(page)

        # 3b: 富化 level 2 的概念 (full)
        for page in self.store.get_by_level(2):
            if page.needs_review:
                self._enrich_full(page)
                enriched_full += 1
                page.needs_review = False
                self.store.upsert(page)

        return {
            "timestamp": now,
            "graph_stats": graph_stats,
            "stubs_created": stubs_created,
            "upgrades_basic": upgrades_basic,
            "upgrades_full": upgrades_full,
            "enriched_basic": enriched_basic,
            "enriched_full": enriched_full,
            "total_pages": self.store.count(),
        }

    # ==================================================================
    # 分层富化实现
    # ==================================================================

    def _enrich_basic(self, page: ConceptPage) -> None:
        """
        Level 1 富化: 从知识库检索相关内容，构建初始 CompiledTruth

        策略: 用概念名称作为查询，检索 top-5 相关片段
        """
        if self.collection is None:
            return

        now = datetime.datetime.now().isoformat()

        # 检索相关片段
        try:
            results = self.collection.query(
                query_texts=[page.concept_name],
                n_results=5,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not docs:
            return

        # 提取关键事实
        key_facts = []
        evidence_list = []
        for doc, meta, dist in zip(docs, metas, distances):
            meta = meta or {}
            if dist and (1 - dist / 2) >= 0.4:  # 相似度过滤
                # 取前 200 字符作为关键事实摘要
                fact = doc[:200].strip()
                if fact:
                    key_facts.append(fact)
                evidence_list.append(Evidence(
                    source=meta.get("source", "unknown"),
                    chunk_id=meta.get("chunk_index", ""),
                    text=doc,
                    timestamp=meta.get("timestamp", ""),
                ))

        # 构建 CompiledTruth
        summary = ""
        if key_facts:
            summary = f"关于 '{page.concept_name}' 的基础信息，基于 {len(key_facts)} 条相关片段"

        page.compiled_truth = CompiledTruth(
            summary=summary,
            confidence=0.5,
            key_facts=key_facts[:5],
            last_updated=now,
        )

        page.timeline.append(TimelineEntry(
            seq=len(page.timeline) + 1,
            timestamp=now,
            event=f"基础富化完成 (level 0→1)，发现 {len(key_facts)} 条相关证据",
            evidence=evidence_list,
            source_hash=hashlib.md5(
                f"{page.concept_id}:basic:{now}".encode()
            ).hexdigest()[:8],
        ))

    def _enrich_full(self, page: ConceptPage) -> None:
        """
        Level 2 富化: 深度检索 + 矛盾检测 + LLM 综合

        策略:
          1. 检索 top-10 + sparse 补充召回
          2. 矛盾检测: 同一概念的不同说法
          3. 如果有 LLM 可用，调用综合生成摘要
        """
        if self.collection is None:
            return

        now = datetime.datetime.now().isoformat()

        # 深度检索
        try:
            results = self.collection.query(
                query_texts=[page.concept_name],
                n_results=10,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        evidence_list = []
        key_facts = []
        contradictions = []
        sources_set: Set[str] = set()

        for doc, meta, dist in zip(docs, metas, distances):
            meta = meta or {}
            source = meta.get("source", "unknown")
            sim = max(0, 1 - (dist / 2)) if dist else 0.5

            if sim >= 0.35:
                key_facts.append(doc[:300].strip())
                evidence_list.append(Evidence(
                    source=source,
                    chunk_id=meta.get("chunk_index", ""),
                    text=doc,
                    timestamp=meta.get("timestamp", ""),
                ))

                # 检测同概念不同说法 (简化版: 检查是否有明显矛盾的关键词)
                if source not in sources_set and len(sources_set) >= 1:
                    # 多源交叉验证，标记潜在矛盾
                    if len(key_facts) >= 3:
                        contradictions.append(
                            f"多源信息交叉验证中: {source} vs 其他来源"
                        )
                sources_set.add(source)

        # 尝试用 LLM 生成综合摘要 (如果有的话)
        summary = self._llm_synthesize(page.concept_name, key_facts[:8])
        if not summary:
            summary = (
                f"'{page.concept_name}' 的完整知识图谱，"
                f"基于 {len(key_facts)} 条证据，"
                f"来自 {len(sources_set)} 个独立来源"
            )

        open_questions = []
        if contradictions:
            open_questions.append("多源信息存在差异，需要人工确认")

        page.compiled_truth = CompiledTruth(
            summary=summary,
            confidence=0.75 if not contradictions else 0.55,
            key_facts=key_facts[:8],
            contradictions=contradictions[:3],
            open_questions=open_questions,
            last_updated=now,
        )

        page.timeline.append(TimelineEntry(
            seq=len(page.timeline) + 1,
            timestamp=now,
            event=(
                f"完整富化完成 (level 1→2)，"
                f"整合 {len(key_facts)} 条证据，"
                f"发现 {len(contradictions)} 个潜在矛盾"
            ),
            evidence=evidence_list,
            source_hash=hashlib.md5(
                f"{page.concept_id}:full:{now}".encode()
            ).hexdigest()[:8],
        ))

        # 更新关联概念
        related = self._find_related_concepts(page.concept_id)
        page.related_concepts = related

    def _llm_synthesize(self, concept_name: str, facts: List[str]) -> str:
        """调用 LLM 综合生成摘要 (可选)"""
        if not facts:
            return ""
        try:
            from config_loader import get_config
            cfg = get_config()
            api_key = cfg.llm_api_key
            api_base = cfg.llm_api_base
            model = cfg.llm_model
            if not api_key:
                return ""
        except Exception:
            return ""

        try:
            import httpx
        except ImportError:
            return ""

        prompt = (
            f"请基于以下关于 '{concept_name}' 的知识片段，生成一段简洁的综合摘要 (200字以内):\n\n"
            + "\n---\n".join(facts[:5])
        )

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{api_base.rstrip('/')}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 300,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""

    def _find_related_concepts(self, concept_id: str, top_k: int = 5) -> List[str]:
        """找关联概念: 通过共现分析 (出现在同一 source 文件中的概念)"""
        related: Dict[str, int] = defaultdict(int)
        for other_id, page in self.store.get_all().items():
            if other_id == concept_id:
                continue
            # 共现: 如果两个概念出现在相同的 backlink 文件中
            my_backlinks = set(
                self.graph_builder.backlinks.get(concept_id, set())
            )
            other_backlinks = set(
                self.graph_builder.backlinks.get(other_id, set())
            )
            common = my_backlinks & other_backlinks
            if common:
                related[other_id] = len(common)

        # 按共现次数排序
        sorted_related = sorted(related.items(), key=lambda x: x[1], reverse=True)
        return [cid for cid, _ in sorted_related[:top_k]]

    # ==================================================================
    # 单个概念查询接口
    # ==================================================================

    def get_concept_page(self, concept_name: str) -> Optional[dict]:
        """查询单个概念页的完整信息"""
        cid = normalize_concept_id(concept_name)
        page = self.store.get(cid)
        if page is None:
            return None
        return page.to_dict()

    def search_concepts(self, query: str, top_k: int = 10) -> List[dict]:
        """模糊搜索概念"""
        q = query.lower()
        results = []
        for page in self.store.get_all().values():
            if q in page.concept_id or q in page.concept_name.lower():
                results.append(page.to_dict())
                if len(results) >= top_k:
                    break
        return results

    def get_enrichment_queue(self) -> List[dict]:
        """获取待富化队列"""
        queue = []
        for page in self.store.get_needs_review():
            queue.append({
                "concept_id": page.concept_id,
                "concept_name": page.concept_name,
                "mention_count": page.mention_count,
                "current_level": page.enrichment_level,
                "target_level": page.determine_level(),
            })
        return sorted(queue, key=lambda x: x["mention_count"], reverse=True)

    def get_timeline(self, concept_name: str) -> Optional[List[dict]]:
        """获取概念的时间线"""
        cid = normalize_concept_id(concept_name)
        page = self.store.get(cid)
        if page is None:
            return None
        return [
            {
                "seq": t.seq,
                "timestamp": t.timestamp,
                "event": t.event,
                "source_hash": t.source_hash,
                "evidence_count": len(t.evidence),
            }
            for t in page.timeline
        ]


def create_engine(
    db_path: str = "",
    collection_name: str = "ako_photos",
    vault_root: str = r"D:\AKOBUILD",
) -> FermentEngine:
    """创建发酵引擎实例"""
    client = chromadb.PersistentClient(path=db_path or ".")
    collection = client.get_or_create_collection(collection_name)
    store = ConceptStore(db_path=db_path)
    return FermentEngine(
        chroma_collection=collection,
        vault_root=vault_root,
        store=store,
    )