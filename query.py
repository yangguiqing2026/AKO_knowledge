"""
AKO_Hub 知识库查询工具 - 使用 bge-m3 三向量混合检索
支持置信度阈值判断，信息不足时明确告知"不知道"
"""
import chromadb
import re
import sys
import os
import json
from config_loader import get_config
from hybrid_retrieval import HybridRetriever

# ==================== 加载配置 ====================
config = get_config()

DB_PATH = config.db_path
COLLECTION_NAME = config.collection_name
EMBEDDING_MODEL = config.embedding_model
CHROMA_MODE = config.chroma_mode
CHROMA_HOST = config.chroma_server_host
CHROMA_PORT = config.chroma_server_port

CONFIDENCE_THRESHOLD = config.confidence_threshold
SIMILARITY_THRESHOLD = config.similarity_threshold

# 根据配置选择连接方式
if CHROMA_MODE == 'remote':
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    print(f"   远程模式: 连接 {CHROMA_HOST}:{CHROMA_PORT}")
else:
    client = chromadb.PersistentClient(path=DB_PATH)
    print(f"   本地模式: {DB_PATH}")

col = client.get_collection(COLLECTION_NAME)

# 检查集合配置
try:
    collection_info = col.count()
    print(f"   集合 '{COLLECTION_NAME}' 包含 {collection_info} 条记录")
except Exception as e:
    print(f"   无法访问集合: {e}")
    sys.exit(1)

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


def ask(q: str, n: int = 50):
    """查询知识库 - 使用三向量混合检索，带置信度阈值防幻觉"""
    # 使用混合检索器 (dense + sparse + colbert 融合)
    result = retriever.search(q, top_k=min(n, 30))

    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    scores = result.get("scores", [[]])[0]

    if not docs:
        print("\n[不知道] 知识库中未找到相关信息。")
        return None

    # 取最相关结果
    doc = docs[0]
    meta = metas[0] or {}
    dist = distances[0]
    score = scores[0] if scores else 0.0

    # 余弦距离范围是 [0, 2], 转换为相似度 [0, 1]
    similarity = 1 - (dist / 2)

    # ===== 防幻觉：置信度阈值判断 =====
    if score < CONFIDENCE_THRESHOLD or similarity < SIMILARITY_THRESHOLD:
        print(f"\n[不知道] 知识库中没有与您的问题足够相关的信息。")
        print(f"  (最高融合分: {score:.4f} < 阈值 {CONFIDENCE_THRESHOLD}, "
              f"相似度: {similarity:.3f} < 阈值 {SIMILARITY_THRESHOLD})")
        return None

    # 提取元数据
    source = meta.get('source', '未知')

    print(f"\n来源: {source}")
    print(f"相关度: {similarity:.3f} | 融合分: {score:.4f}")
    print("-" * 60)

    # 智能提取关键内容
    # 从查询中提取关键词(中文+英文)
    chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,}', q)
    english_words = re.findall(r'[a-zA-Z]+', q)
    keywords_in_query = chinese_words + [w.lower() for w in english_words]

    # 查找第一个包含关键词的位置
    doc_lower = doc.lower()
    match_pos = -1

    for kw in keywords_in_query:
        pos = doc_lower.find(kw)
        if pos != -1:
            if match_pos == -1 or pos < match_pos:
                match_pos = pos

    # 如果找到匹配, 提取匹配位置前后各150字符
    if match_pos != -1:
        start = max(0, match_pos - 100)
        end = min(len(doc), match_pos + 200)
        preview = doc[start:end].replace('\n', ' ').strip()
        preview = re.sub(r'\s+', ' ', preview)
    else:
        preview = doc[:200].replace('\n', ' ')

    print(preview)
    print("-" * 60)

    # 显示前3条简要信息
    if len(docs) > 1:
        print(f"\n其他相关结果 (共 {len(docs)} 条):")
        for i in range(1, min(4, len(docs))):
            src = (metas[i] or {}).get('source', '未知')
            sim = 1 - (distances[i] / 2)
            preview_text = (docs[i][:80]).replace('\n', ' ')
            print(f"  [{i+1}] {src[:30]} | 相关度: {sim:.3f} | {preview_text}...")


if __name__ == "__main__":
    # 显示当前配置
    print(f"{config.get_profile_info()}")

    # 依赖检查(静默)
    if not check_dependencies():
        sys.exit(1)

    # 支持命令行参数或交互式模式
    if len(sys.argv) > 1:
        # 命令行模式: python query.py "你的问题"
        query_text = " ".join(sys.argv[1:])
        ask(query_text)
    else:
        # 交互式模式
        print("\n进入交互查询模式 (输入 'quit' 或 'exit' 退出)\n")
        while True:
            try:
                user_input = input("请输入问题: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("再见!")
                    break
                ask(user_input)
            except KeyboardInterrupt:
                print("\n\n再见!")
                break
            except Exception as e:
                print(f"[错误] {e}\n")