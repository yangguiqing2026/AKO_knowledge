"""
bge-m3 三向量混合检索单元测试
"""
from hybrid_retrieval import (
    HybridRetriever,
    normalize_text,
    tokenize,
    compute_query_complexity,
    build_sparse_features,
    build_hybrid_metadata,
)


# ======================================================================
# 文本处理
# ======================================================================

def test_normalize_text_removes_extra_whitespace():
    assert normalize_text("  hello   world  ") == "hello world"


def test_normalize_text_empty():
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


def test_tokenize_chinese():
    # 简化分词器: 连续中文字符作为一个token
    # 精确分词需要 jieba 等中文分词语料库, bge-m3 原生lexicon 提供
    tokens = tokenize("贵州省装配式建筑评价标准")
    assert len(tokens) >= 1
    assert len(tokens[0]) > 1


def test_tokenize_mixed():
    tokens = tokenize("HRB400 钢筋 标准")
    assert "hrb400" in tokens
    assert "钢筋" in tokens
    assert "标准" in tokens


def test_tokenize_removes_single_chars():
    tokens = tokenize("a b c")
    assert all(len(t) > 1 for t in tokens)


# ======================================================================
# 查询复杂度分析
# ======================================================================

def test_query_complexity_short_code():
    result = compute_query_complexity("HRB400")
    assert result["specificity"] > 0
    assert result["length_factor"] < 0.5


def test_query_complexity_long_natural():
    # 含英文+数字+空格分词的混合查询更适合 tokenizer
    result = compute_query_complexity("陶粒墙板 在城市更新 项目中的 节能指标 是多少 dB50")
    assert result["length_factor"] > 0.3
    assert result["specificity"] > 0


# ======================================================================
# 自适应权重
# ======================================================================

def test_short_query_prefers_sparse_weight():
    retriever = HybridRetriever(None)
    weights = retriever.get_query_adaptive_weights("HRB400")
    assert weights["sparse_weight"] > weights["dense_weight"]


def test_long_query_prefers_dense_weight():
    retriever = HybridRetriever(None)
    # 长自然语言查询(含空格分词) → dense 权重更高
    weights = retriever.get_query_adaptive_weights(
        "陶粒墙板 在城市更新 项目中的 节能指标 是多少 有什么意义"
    )
    assert weights["dense_weight"] > weights["sparse_weight"]


def test_weights_sum_to_one():
    retriever = HybridRetriever(None)
    for query in ["HRB400", "标准", "贵州省装配式建筑评价标准编号是什么"]:
        weights = retriever.get_query_adaptive_weights(query)
        total = weights["dense_weight"] + weights["sparse_weight"] + weights["colbert_weight"]
        assert abs(total - 1.0) < 0.001, f"Query '{query}' weights sum to {total}"


# ======================================================================
# RRF 分数
# ======================================================================

def test_rrf_score_is_monotonic_with_rank():
    retriever = HybridRetriever(None)
    scores = retriever.compute_rrf_scores(["a", "b", "c"], k=60)
    assert scores["a"] > scores["b"] > scores["c"]


def test_rrf_single_document():
    retriever = HybridRetriever(None)
    scores = retriever.compute_rrf_scores(["x"], k=60)
    assert "x" in scores
    assert scores["x"] > 0


# ======================================================================
# 分数校准
# ======================================================================

def test_calibrate_scores_normalizes_to_range():
    retriever = HybridRetriever(None)
    calibrated = retriever._calibrate_scores([0.1, 0.5, 0.9])
    assert min(calibrated) == 0.0
    assert max(calibrated) == 1.0


def test_calibrate_scores_all_equal():
    retriever = HybridRetriever(None)
    calibrated = retriever._calibrate_scores([0.5, 0.5, 0.5])
    assert calibrated == [1.0, 1.0, 1.0]


def test_calibrate_scores_empty():
    retriever = HybridRetriever(None)
    assert retriever._calibrate_scores([]) == []


# ======================================================================
# 稀疏特征
# ======================================================================

def test_build_sparse_features():
    features = build_sparse_features("HRB400 钢筋 标准 钢筋")
    assert "hrb400" in features
    assert "钢筋" in features
    assert features["钢筋"] > features["hrb400"]  # "钢筋"出现2次


def test_build_hybrid_metadata():
    meta = build_hybrid_metadata("测试文本 测试内容")
    assert "sparse_lexicon" in meta
    assert "colbert_tokens" in meta
    import json
    sparse = json.loads(meta["sparse_lexicon"])
    assert isinstance(sparse, dict)
    assert len(sparse) > 0


# ======================================================================
# 空集合保护
# ======================================================================

def test_search_without_collection():
    retriever = HybridRetriever(None)
    result = retriever.search("测试查询")
    assert result["documents"] == [[]]
    assert result["ids"] == [[]]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])