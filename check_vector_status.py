"""检查数据库中三向量数据的完整性"""
import chromadb
from config_loader import get_config

config = get_config()
client = chromadb.PersistentClient(path=config.db_path)
col = client.get_or_create_collection(config.collection_name)

total = col.count()
print(f"文档总数: {total}")

# 检查有多少文档缺少 sparse_lexicon / colbert_tokens
data = col.get(include=['metadatas', 'documents'])
metas = data.get('metadatas', [])
ids = data.get('ids', [])

missing_sparse = 0
missing_colbert = 0
has_both = 0

for i, meta in enumerate(metas):
    if not meta:
        missing_sparse += 1
        missing_colbert += 1
        continue
    has_sparse = 'sparse_lexicon' in meta
    has_colbert = 'colbert_tokens' in meta
    if not has_sparse:
        missing_sparse += 1
    if not has_colbert:
        missing_colbert += 1
    if has_sparse and has_colbert:
        has_both += 1

print(f"\n三向量元数据统计:")
print(f"  有 sparse_lexicon 和 colbert_tokens: {has_both}")
print(f"  缺少 sparse_lexicon: {missing_sparse}")
print(f"  缺少 colbert_tokens: {missing_colbert}")

if missing_sparse > 0 or missing_colbert > 0:
    print(f"\n需要为 {total - has_both} 条记录生成三向量数据")

# 打印几条示例
print("\n--- 示例 metadata ---")
cnt = 0
for meta in metas[:3]:
    if meta:
        keys = list(meta.keys())
        print(f"  keys: {keys}")