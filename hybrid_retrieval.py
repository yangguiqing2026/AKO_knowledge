"""
AKO_Hub 混合检索引擎 - 基于 bge-m3 三向量 (Dense + Sparse + ColBERT) 融合检索

最大化 bge-m3 检索精度的核心组件：
- Dense:   bge-m3 原生 1024-dim 密集向量 (语义理解)
- Sparse:  bge-m3 原生 sparse lexicon (关键词精确匹配)
- ColBERT: bge-m3 原生 multi-vector token embeddings (细粒度 token 级交互)
- 融合:    分数校准后加权求和 + MMR 多样性去重
"""
import json
import math
import re
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from FlagEmbedding import BGEM3FlagModel  # type: ignore
except Exception:  # pragma: no cover
    BGEM3FlagModel = None

try:
    import ollama
except Exception:  # pragma: no cover
    ollama = None


def normalize_text(text: str) -> str:
    """规范化文本 (去多余空白)"""
    return re.sub(r"\s+", " ", text or "").strip()


def tokenize(text: str) -> List[str]:
    """中英文分词 (简化, 用于客户端备用)"""
    text = normalize_text(text)
    if not text:
        return []
    tokens = re.findall(r"[\u4e00-\u9fa5]+|[A-Za-z0-9._-]+", text)
    return [token.lower() for token in tokens if len(token) > 1]


def compute_query_complexity(query: str) -> Dict[str, float]:
    """分析查询复杂度, 用于自适应权重调参"""
    text = normalize_text(query)
    if not text:
        return {"entropy": 0.0, "specificity": 0.0, "length_factor": 0.0}

    tokens = tokenize(text)
    token_count = len(tokens)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))

    # 1. 词汇多样性 (熵近似)
    if token_count > 1:
        freq = Counter(t.lower() for t in tokens)
        total = token_count
        entropy = -sum((c / total) * math.log(c / total + 1e-9) for c in freq.values())
        entropy = min(1.0, entropy / math.log(max(2, token_count)))
    else:
        entropy = 0.0

    # 2. 专有名词密度 (大写字母/数字/特殊符号)
    specific_chars = len(re.findall(r"[A-Z0-9._\-#()《》]", text))
    specificity = min(1.0, specific_chars / max(1, len(text)) * 5)

    # 3. 长度因子 (短查询→偏sparse, 长查询→偏dense)
    length_factor = min(1.0, token_count / 12.0)

    return {
        "entropy": round(entropy, 4),
        "specificity": round(specificity, 4),
        "length_factor": round(length_factor, 4),
    }


def sparse_scan_recall(
    collection: Any,
    query_tokens: List[str],
    top_k: int = 20,
    exclude_ids: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    独立 sparse 召回：全库扫描 sparse_lexicon metadata，补充 dense 遗漏的文档。

    Args:
        collection: ChromaDB collection 对象
        query_tokens: tokenize() 输出的查询 token 列表
        top_k: 返回的 sparse 候选数量
        exclude_ids: 已召回的 doc id 集合，用于去重

    Returns:
        List of {"id", "document", "metadata", "sparse_score"}
    """
    exclude_ids = exclude_ids or set()
    if not query_tokens or collection is None:
        return []

    try:
        # 只取 ids 先 (轻量)，再分批取 metadata
        all_ids_data = collection.get(include=[])
    except Exception:
        return []

    ids = all_ids_data.get("ids", [])
    if not ids:
        return []

    query_token_set = set(query_tokens)
    scored: List[Dict[str, Any]] = []

    # 分批加载 metadata + documents，避免 colbert_tokens JSON 爆内存
    _BATCH = 200
    for start in range(0, len(ids), _BATCH):
        batch_ids = ids[start:start + _BATCH]
        try:
            batch_data = collection.get(
                ids=batch_ids,
                include=["documents", "metadatas"],
            )
        except Exception:
            continue

        b_ids = batch_data.get("ids", [])
        b_docs = batch_data.get("documents", [])
        b_metas = batch_data.get("metadatas", [])

        for doc_id, doc, meta in zip(b_ids, b_docs, b_metas):
            if doc_id in exclude_ids:
                continue
            meta = meta or {}
            sparse_raw = meta.get("sparse_lexicon")
            if not sparse_raw:
                continue

            # 解析 sparse_lexicon (JSON 格式的 token→weight 映射)
            try:
                if isinstance(sparse_raw, str):
                    lexicon = json.loads(sparse_raw)
                else:
                    lexicon = sparse_raw
            except Exception:
                continue

            if not isinstance(lexicon, dict):
                continue

            # 计算 sparse 交集分数：query tokens 与 doc lexicon 的加权交集
            score = 0.0
            for tok in query_token_set:
                if tok in lexicon:
                    score += float(lexicon[tok])
            # 归一化：除以 query token 数量
            if query_token_set:
                score /= len(query_token_set)

            if score > 0:
                scored.append({
                    "id": doc_id,
                    "document": doc or "",
                    "metadata": meta,
                    "sparse_score": score,
                })

    # 按 sparse_score 降序，取 top_k
    scored.sort(key=lambda x: x["sparse_score"], reverse=True)
    return scored[:top_k]


class HybridRetriever:
    """
    bge-m3 三向量混合检索器

    核心流程:
    1. FlagEmbedding 编码 → dense_vec, sparse_lexicon, colbert_vecs
    2. Dense 检索  → ChromaDB ANN (cosine)
    3. Sparse 检索 → BM25 词袋匹配 (sparse lexicon 交并比)
    4. ColBERT 评分→ MaxSim 跨 token embedding 交互
    5. 分数校准   → 各分支 min-max 归一化 + 自适应加权融合
    6. 多样性后处理→ MMR 去重
    """

    def __init__(
        self,
        collection: Any,
        embedding_model: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        flag_model: Any = None,
    ):
        self.collection = collection
        self.embedding_model = embedding_model or "bge-m3"
        self.config = config or {}
        self.flag_model = flag_model

        # 自动加载 FlagEmbedding (如果未传入且本地有模型)
        if self.flag_model is None:
            _local_paths = [
                "C:/Users/Yangyuehao/.cache/modelscope/BAAI/bge-m3",
                "BAAI/bge-m3",
            ]
            for _p in _local_paths:
                try:
                    from FlagEmbedding import BGEM3FlagModel
                    self.flag_model = BGEM3FlagModel(_p, use_fp16=False, device="cpu")
                    break
                except Exception:
                    continue

        # ------------------------------------------------------------------
        # 可调参数 (均可在 config 中覆盖)
        # ------------------------------------------------------------------
        self.rrf_k = int(self.config.get("rrf_k", 60))
        self.base_dense_weight = float(self.config.get("dense_weight", 0.45))
        self.base_sparse_weight = float(self.config.get("sparse_weight", 0.35))
        self.base_colbert_weight = float(self.config.get("colbert_weight", 0.20))
        self.candidate_multiplier = int(self.config.get("candidate_multiplier", 6))
        self.min_candidates = int(self.config.get("min_candidates", 30))
        self.mmr_lambda = float(self.config.get("mmr_lambda", 0.7))

        # bge-m3 编码调用次数计数器 (用于自适应节流)
        self._encode_count = 0

    # ======================================================================
    # 向量编码
    # ======================================================================

    def encode_query(self, query: str) -> Dict[str, Any]:
        """
        调用 bge-m3 编码查询, 返回三向量

        Returns:
            {
                "dense_vec": Optional[List[float]],
                "sparse_lexicon": Optional[Dict[str, float]],
                "colbert_vecs": Optional[List[List[float]]],
            }
        """
        result: Dict[str, Any] = {
            "dense_vec": None,
            "sparse_lexicon": None,
            "colbert_vecs": None,
        }

        # ------ 方法 1: FlagEmbedding (完整三向量) ------
        if self.flag_model is not None:
            try:
                output = self.flag_model.encode(
                    [query],
                    return_dense=True,
                    return_sparse=True,
                    return_colbert_vecs=True,
                )
                self._encode_count += 1

                dense_vecs = output.get("dense_vecs")
                if dense_vecs is not None:
                    vec = dense_vecs[0]
                    result["dense_vec"] = vec.tolist() if hasattr(vec, "tolist") else list(vec)

                sparse_lex = output.get("lexical_weights")
                if sparse_lex is not None and len(sparse_lex) > 0:
                    # FlagEmbedding returns List[Dict[str, float]]
                    lex = sparse_lex[0]
                    if isinstance(lex, dict):
                        result["sparse_lexicon"] = dict(lex)

                colbert = output.get("colbert_vecs")
                if colbert is not None:
                    vec = colbert[0]
                    if hasattr(vec, "tolist"):
                        result["colbert_vecs"] = vec.tolist()
                    elif isinstance(vec, list):
                        result["colbert_vecs"] = vec

                return result
            except Exception:
                pass

        # ------ 方法 2: Ollama fallback (仅密集向量) ------
        if ollama is not None:
            try:
                resp = ollama.embeddings(model=self.embedding_model, prompt=query)
                emb = resp.get("embedding")
                if emb:
                    result["dense_vec"] = emb
                    return result
            except Exception:
                pass

        return result

    # ======================================================================
    # 稀疏向量 (sparse lexicon) 评分
    # ======================================================================

    def _sparse_lexicon_score(
        self,
        query_lexicon: Dict[str, float],
        doc_sparse_raw: Optional[str] = None,
        doc_text: Optional[str] = None,
    ) -> float:
        """
        使用 bge-m3 sparse lexicon 计算查询-文档匹配分

        策略:
        1. 优先使用入库时存储的 doc sparse lexicon (精确)
        2. 降级到 tokenize(doc_text) 构建词袋 (近似)
        3. 计算方式: sum_{term}(min(q_w, d_w)) → 不惩罚文档长度

        Returns:
            [0, 1] 归一化分数
        """
        if not query_lexicon:
            return 0.0

        # 解析文档端稀疏词表
        doc_lexicon: Dict[str, float] = {}
        if doc_sparse_raw:
            try:
                doc_lexicon = json.loads(doc_sparse_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        # 降级: 从文本构建词袋
        if not doc_lexicon and doc_text:
            tokens = tokenize(doc_text)
            if tokens:
                freq = Counter(tokens)
                total = sum(freq.values())
                doc_lexicon = {t: w / total for t, w in freq.items()}

        if not doc_lexicon:
            return 0.0

        # 计算重叠分
        score = 0.0
        q_total = sum(abs(w) for w in query_lexicon.values()) or 1.0
        for term, q_weight in query_lexicon.items():
            d_weight = doc_lexicon.get(term, 0.0)
            if d_weight > 0:
                score += min(q_weight, d_weight)

        # 归一化: 用查询词表权重和进行归一化
        normalized = score / q_total
        return round(min(1.0, normalized), 6)

    # ======================================================================
    # ColBERT 评分 (MaxSim)
    # ======================================================================

    def _colbert_maxsim_score(
        self,
        query_colbert: List[List[float]],
        doc_colbert_raw: Optional[str] = None,
        doc_text: Optional[str] = None,
    ) -> float:
        """
        ColBERT MaxSim: 对每个查询 token embedding, 找文档中最相似的 token embedding

        Args:
            query_colbert: bge-m3 编码的 query multi-vector
            doc_colbert_raw: 入库时存储的 doc colbert token embeddings (JSON)
            doc_text: 文档原文 (用于降级)

        Returns:
            [0, 1] MaxSim 分数
        """
        if not query_colbert:
            return 0.0

        # 解析文档端 ColBERT 向量
        doc_vectors: List[List[float]] = []
        if doc_colbert_raw:
            try:
                doc_vectors = json.loads(doc_colbert_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        # 降级: 无文档向量时返回 0
        if not doc_vectors:
            return 0.0

        # 计算 MaxSim
        total_max_sim = 0.0
        for q_vec in query_colbert:
            q_norm = math.sqrt(sum(v * v for v in q_vec)) or 1.0
            best = 0.0
            for d_vec in doc_vectors:
                d_norm = math.sqrt(sum(v * v for v in d_vec)) or 1.0
                dot = sum(a * b for a, b in zip(q_vec, d_vec))
                sim = dot / (q_norm * d_norm)
                if sim > best:
                    best = sim
            total_max_sim += best

        return round(total_max_sim / len(query_colbert), 6)

    # ======================================================================
    # 分数校准 (跨分支归一化)
    # ======================================================================

    def _calibrate_scores(self, scores: List[float]) -> List[float]:
        """
        Min-Max 归一化到 [0, 1]

        避免原始分数尺度不一致导致融合偏差
        """
        if not scores:
            return scores
        min_s = min(scores)
        max_s = max(scores)
        if max_s == min_s:
            return [1.0 if s > 0 else 0.0 for s in scores]
        return [(s - min_s) / (max_s - min_s) for s in scores]

    # ======================================================================
    # RRF (Reciprocal Rank Fusion) - 保留用于 dense 候选排序
    # ======================================================================

    def compute_rrf_scores(
        self,
        doc_ids: Sequence[str],
        k: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        将排名列表转为 RRF 分数

        RRF(d) = sum_{r in rankings} 1 / (k + rank(d))
        """
        k = k or self.rrf_k
        scores: Dict[str, float] = {}
        for rank, doc_id in enumerate(doc_ids, start=1):
            scores[doc_id] = 1.0 / (k + rank)
        return scores

    # ======================================================================
    # 自适应权重
    # ======================================================================

    def get_query_adaptive_weights(self, query: str) -> Dict[str, float]:
        """
        根据查询特征动态调整三向量融合权重

        启发式规则:
        - 短代码/专有名词密集 → sparse ↑, colbert ↑, dense ↓
        - 长自然语言/低特异性 → dense ↑, sparse ↓
        - 中等长度 → 均衡
        """
        text = normalize_text(query)
        if not text:
            return {
                "dense_weight": self.base_dense_weight,
                "sparse_weight": self.base_sparse_weight,
                "colbert_weight": self.base_colbert_weight,
            }

        complexity = compute_query_complexity(text)
        specificity = complexity["specificity"]
        length_factor = complexity["length_factor"]

        # 判断查询类型
        is_short_code = bool(re.fullmatch(r"[A-Za-z0-9._\-+#]+", text))
        token_count = len(tokenize(text))

        if is_short_code or token_count <= 2:
            # 短代码/精确匹配: 大幅提升 sparse
            dw = 0.20
            sw = 0.55
            cw = 0.25
        elif specificity > 0.4 and length_factor < 0.4:
            # 含较多专有名词的短查询
            dw = 0.30
            sw = 0.45
            cw = 0.25
        elif length_factor > 0.6:
            # 长自然语言: 偏 dense
            dw = 0.55
            sw = 0.20
            cw = 0.25
        else:
            # 中等: 均衡
            dw = 0.40
            sw = 0.35
            cw = 0.25

        # 确保权重和为 1.0
        total = dw + sw + cw
        return {
            "dense_weight": round(dw / total, 4),
            "sparse_weight": round(sw / total, 4),
            "colbert_weight": round(cw / total, 4),
        }

    # ======================================================================
    # MMR 多样性后处理
    # ======================================================================

    def _mmr_rerank(
        self,
        candidates: List[Dict[str, Any]],
        top_k: int,
        lambda_param: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Maximum Marginal Relevance (MMR) 去重重排序

        MMR(d) = lambda * rel(d) - (1-lambda) * max_s sim(d, s)

        目的: 避免返回多个高度相似的文档片段
        """
        if lambda_param is None:
            lambda_param = self.mmr_lambda
        if len(candidates) <= top_k:
            return candidates

        # MMR = argmax_{d in C\\S} [lambda * relevance(d) - (1-lambda) * max_{s in S} sim(d, s)]
        selected: List[Dict[str, Any]] = []
        remaining = list(candidates)

        while len(selected) < top_k and remaining:
            if not selected:
                # 第一轮: 直接选最高分
                best_idx = 0
                selected.append(remaining.pop(best_idx))
            else:
                mmr_scores = []
                for i, cand in enumerate(remaining):
                    relevance = cand.get("score", 0.0)
                    # 计算与已选文档的最大相似度
                    max_sim = 0.0
                    for sel in selected:
                        # 近似: 使用 cosine distance 转 similarity
                        d1 = cand.get("distance", 1.0)
                        d2 = sel.get("distance", 1.0)
                        # 简化: distance 越接近越相似
                        sim = 1.0 - abs(d1 - d2) / 2.0
                        max_sim = max(max_sim, sim)
                    mmr = lambda_param * relevance - (1.0 - lambda_param) * max_sim
                    mmr_scores.append((i, mmr))

                if not mmr_scores:
                    break
                best_idx = max(mmr_scores, key=lambda x: x[1])[0]
                selected.append(remaining.pop(best_idx))

        return selected

    # ======================================================================
    # 核心检索
    # ======================================================================

    def search(self, query: str, top_k: int = 5) -> Dict[str, List[Any]]:
        """
        三向量混合检索主入口

        Args:
            query: 用户查询字符串
            top_k: 返回结果数量

        Returns:
            {
                "documents": [[str]],
                "metadatas": [[dict]],
                "distances": [[float]],
                "ids": [[str]],
                "scores": [[float]],
            }
        """
        if self.collection is None:
            return {
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
                "scores": [[]],
            }

        # ---------- Step 1: 编码查询 ----------
        encoded = self.encode_query(query)
        dense_vec = encoded.get("dense_vec")
        sparse_lex = encoded.get("sparse_lexicon")
        colbert_vecs = encoded.get("colbert_vecs")

        if dense_vec is None:
            return {
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
                "scores": [[]],
            }

        # ---------- Step 2: 自适应权重 ----------
        weights = self.get_query_adaptive_weights(query)

        # ---------- Step 3: Dense 候选召回 ----------
        candidate_count = max(top_k * self.candidate_multiplier, self.min_candidates)
        results = self.collection.query(
            query_embeddings=[dense_vec],
            n_results=candidate_count,
            include=["documents", "metadatas", "distances"],
        )

        ids = list(results.get("ids", [[]])[0])
        docs = list(results.get("documents", [[]])[0])
        metas = list(results.get("metadatas", [[]])[0])
        distances = list(results.get("distances", [[]])[0])

        if not ids:
            return {
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
                "scores": [[]],
            }

        # ---------- Step 3b: 独立 Sparse 召回 (补充 dense 遗漏) ----------
        # sparse_lex: dict{token:weight} (FlagEmbedding) 或 None (Ollama fallback)
        if isinstance(sparse_lex, dict):
            _q_tokens = [t.lower() for t in sparse_lex.keys()]
        else:
            _q_tokens = tokenize(query)
        sparse_extra = sparse_scan_recall(
            self.collection,
            query_tokens=_q_tokens,
            top_k=top_k * 2,
            exclude_ids=set(ids),
        )
        # 合并 sparse-only 召回的文档进候选池
        for item in sparse_extra:
            ids.append(item["id"])
            docs.append(item["document"])
            metas.append(item["metadata"])
            distances.append(-1.0)  # sparse 没有 cosine distance，填占位符

        if not ids:
            return {
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
                "scores": [[]],
            }

        # ---------- Step 4: Sparse + ColBERT 评分 ----------

        sparse_scores: List[float] = []
        colbert_scores: List[float] = []

        for doc, meta in zip(docs, metas):
            meta = meta or {}
            doc_sparse_raw = meta.get("sparse_lexicon")
            doc_colbert_raw = meta.get("colbert_tokens")

            # Sparse 评分
            if sparse_lex:
                ss = self._sparse_lexicon_score(
                    sparse_lex,
                    doc_sparse_raw=doc_sparse_raw,
                    doc_text=doc,
                )
            else:
                ss = 0.0
            sparse_scores.append(ss)

            # ColBERT 评分
            if colbert_vecs:
                cs = self._colbert_maxsim_score(
                    colbert_vecs,
                    doc_colbert_raw=doc_colbert_raw,
                    doc_text=doc,
                )
            else:
                cs = 0.0
            colbert_scores.append(cs)

        # ---------- Step 5: Sparse 排名 RRF + dense 保底 ----------
        # 按 sparse 分数排序, 用于 RRF 贡献
        sparse_ranked_ids = [
            id_ for id_, _ in sorted(
                zip(ids, sparse_scores), key=lambda x: x[1], reverse=True
            )
        ]
        # 两路 RRF: dense(ANN rank) + sparse(lexicon rank)
        dense_candidate_count = candidate_count  # Step 3 dense 召回数量
        combined_rrf: Dict[str, float] = {}
        for rank, doc_id in enumerate(ids[:dense_candidate_count], start=1):
            combined_rrf[doc_id] = combined_rrf.get(doc_id, 0.0) + 1.0 / (self.rrf_k + rank)
        # sparse-only 文档的 dense RRF 保底 = dense 最低分的 50%
        if dense_candidate_count > 0:
            min_dense_rrf = 1.0 / (self.rrf_k + dense_candidate_count)
            sparse_floor = min_dense_rrf * 0.5
        else:
            sparse_floor = 0.0
        for doc_id in ids[dense_candidate_count:]:
            combined_rrf[doc_id] = combined_rrf.get(doc_id, 0.0) + sparse_floor
        for rank, doc_id in enumerate(sparse_ranked_ids, start=1):
            combined_rrf[doc_id] = combined_rrf.get(doc_id, 0.0) + 1.0 / (self.rrf_k + rank)

        # ---------- Step 6: 分支分数校准 ----------
        rrf_values = [combined_rrf.get(did, 0.0) for did in ids]
        calibrated_rrf = self._calibrate_scores(rrf_values)
        calibrated_sparse = self._calibrate_scores(sparse_scores)
        calibrated_colbert = self._calibrate_scores(colbert_scores)

        # ---------- Step 7: 融合 ----------
        candidates: List[Dict[str, Any]] = []
        for i, (doc_id, doc, meta, dist) in enumerate(zip(ids, docs, metas, distances)):
            final_score = (
                weights["dense_weight"] * calibrated_rrf[i]
                + weights["sparse_weight"] * calibrated_sparse[i]
                + weights["colbert_weight"] * calibrated_colbert[i]
            )
            candidates.append(
                {
                    "id": doc_id,
                    "document": doc,
                    "metadata": meta or {},
                    "distance": dist,
                    "score": round(final_score, 6),
                    "dense_score": round(calibrated_rrf[i], 6),
                    "sparse_score": round(calibrated_sparse[i], 6),
                    "colbert_score": round(calibrated_colbert[i], 6),
                }
            )

        # ---------- Step 8: 排序 & MMR 去重 ----------
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        diverse = self._mmr_rerank(ranked, top_k)

        return {
            "documents": [[item["document"] for item in diverse]],
            "metadatas": [[item["metadata"] for item in diverse]],
            "distances": [[item["distance"] for item in diverse]],
            "ids": [[item["id"] for item in diverse]],
            "scores": [[item["score"] for item in diverse]],
        }


# ======================================================================
# 兼容性别名 (向后兼容旧 API)
# ======================================================================

def build_sparse_features(text: str) -> Dict[str, float]:
    """构建稀疏词袋特征 (为入库时存储 sparse_lexicon 使用)"""
    tokens = tokenize(text)
    if not tokens:
        return {}
    counter = Counter(tokens)
    total = sum(counter.values())
    return {token: round(weight / total, 6) for token, weight in counter.items()}


def build_colbert_features(text: str) -> List[Dict[str, Any]]:
    """构建 ColBERT token 列表 (为入库时存储 colbert_tokens 使用)"""
    tokens = tokenize(text)
    return [{"token": token} for token in tokens if token]


def build_hybrid_metadata(text: str) -> Dict[str, str]:
    """入库辅助: 构建 metadata 中的 sparse_lexicon 和 colbert_tokens 字段"""
    sparse = build_sparse_features(text)
    colbert = build_colbert_features(text)
    return {
        "sparse_lexicon": json.dumps(sparse, ensure_ascii=False),
        "colbert_tokens": json.dumps(colbert, ensure_ascii=False),
    }