"""
为数据库中缺失 sparse_lexicon / colbert_tokens 的文档补全三向量元数据
使用 hybrid_retrieval.py 中的 build_hybrid_metadata() 生成
"""
import chromadb
import time
from config_loader import get_config

config = get_config()
client = chromadb.PersistentClient(path=config.db_path)
col = client.get_or_create_collection(config.collection_name)

print(f"连接数据库: {config.collection_name}")

# 获取全部数据
data = col.get(include=['metadatas', 'documents'])
documents = data.get('documents', [])
metadatas = data.get('metadatas', [])
ids = data.get('ids', [])

total = len(ids)
print(f"文档总数: {total}")

# 找出需要补全的文档
need_update = []
for i, (doc_id, doc, meta) in enumerate(zip(ids, documents, metadatas)):
    meta = meta or {}
    has_sparse = 'sparse_lexicon' in meta
    has_colbert = 'colbert_tokens' in meta
    if not has_sparse or not has_colbert:
        need_update.append((i, doc_id, doc, meta))

print(f"需要补全三向量: {len(need_update)} / {total}")

if not need_update:
    print("所有文档已包含三向量数据，无需补全。")
    exit(0)

# 导入 build_hybrid_metadata
from hybrid_retrieval import build_hybrid_metadata

batch_size = 50
updated = 0
errors = 0

print(f"\n开始补全，共 {len(need_update)} 条，每批 {batch_size} 条...")
print("=" * 60)

for start in range(0, len(need_update), batch_size):
    batch = need_update[start:start + batch_size]
    
    for i, doc_id, doc, meta in batch:
        try:
            # 生成三向量元数据
            hybrid_meta = build_hybrid_metadata(doc)
            # 合并到现有 metadata
            meta = dict(meta)  # 复制一份
            meta['sparse_lexicon'] = hybrid_meta['sparse_lexicon']
            meta['colbert_tokens'] = hybrid_meta['colbert_tokens']
            
            # 更新到数据库
            col.update(
                ids=[doc_id],
                metadatas=[meta],
            )
            updated += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [错误] {doc_id}: {e}")
    
    progress = min(100, int((start + batch_size) / len(need_update) * 100))
    print(f"  进度: {start + len(batch)}/{len(need_update)} ({progress}%) - 成功:{updated}, 错误:{errors}")
    time.sleep(0.05)

print("=" * 60)
print(f"补全完成!")
print(f"  成功: {updated}")
print(f"  失败: {errors}")

# 验证结果
print("\n验证...")
data2 = col.get(include=['metadatas'])
metas2 = data2.get('metadatas', [])
has_both = 0
for meta in metas2:
    if meta and 'sparse_lexicon' in meta and 'colbert_tokens' in meta:
        has_both += 1
print(f"  包含完整三向量元数据: {has_both} / {len(metas2)}")