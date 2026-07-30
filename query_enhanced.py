"""
增强版查询工具 - 基于 bge-m3 三向量混合检索
"""
import chromadb
import re
import os
import sys
from config_loader import get_config
from hybrid_retrieval import HybridRetriever

# ==================== 加载配置 ====================
config = get_config()

DB_PATH = config.db_path
COLLECTION_NAME = config.collection_name
EMBEDDING_MODEL = config.embedding_model
# =================================================

client = chromadb.PersistentClient(path=DB_PATH)
col = client.get_collection(COLLECTION_NAME)

# 初始化混合检索器
retriever = HybridRetriever(
    collection=col,
    embedding_model=EMBEDDING_MODEL,
)


def check_dependencies():
    """检查依赖是否就绪"""
    errors = []

    try:
        import ollama
        ollama.list()
    except Exception as e:
        errors.append(f"Ollama 服务未运行: {e}")

    if errors:
        print("   依赖检查失败:")
        for err in errors:
            print(f"     - {err}")
        return False

    print("   依赖检查通过")
    return True


def ask(q: str, n: int = 10):
    """查询知识库 - 使用三向量混合检索"""
    result = retriever.search(q, top_k=n)

    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    scores = result.get("scores", [[]])[0]

    if not docs:
        print("\n未找到相关内容")
        return

    # 显示前5个结果
    display_count = min(5, len(docs))

    print(f"\n问题: {q}")
    print("=" * 60)

    for i in range(display_count):
        doc = docs[i]
        meta = metas[i] or {}
        dist = distances[i]
        score = scores[i] if scores else 0.0

        # 余弦距离范围是 [0, 2], 转换为相似度 [0, 1]
        similarity = 1 - (dist / 2)

        # 提取元数据
        source = meta.get('source', '未知')
        chunk_index = meta.get('chunk_index', 'N/A')
        timestamp = meta.get('timestamp', 'N/A')

        print(f"\n[{i+1}] 来源: {source}")
        print(f"     相关度: {similarity:.3f} | 融合分: {score:.4f} | 片段索引: {chunk_index}")
        print(f"     时间戳: {timestamp}")
        print("-" * 60)

        # 显示文档内容(最多500字符)
        content = doc[:500] if len(doc) > 500 else doc
        print(content)
        if len(doc) > 500:
            print("... (内容已截断)")
        print("-" * 60)


def main():
    print("=" * 60)
    print("PDF 知识库查询工具 (bge-m3 三向量混合检索)")
    print("=" * 60)

    print(f"\n{config.get_profile_info()}")
    print("=" * 60)

    if not check_dependencies():
        print("\n请先解决上述依赖问题")
        return

    # 检查集合
    try:
        count = col.count()
        print(f"   集合 '{COLLECTION_NAME}' 包含 {count} 条记录\n")
    except Exception as e:
        print(f"   无法访问集合: {e}")
        return

    # 获取查询参数
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        ask(question)
    else:
        print("进入交互模式 (输入 'quit' 退出)\n")
        while True:
            try:
                q = input("请输入问题: ").strip()
                if q.lower() in ['quit', 'exit', '退出']:
                    break
                if q:
                    ask(q)
                    print()
            except (EOFError, KeyboardInterrupt):
                break


if __name__ == "__main__":
    main()