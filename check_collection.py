"""
检查 ChromaDB 集合配置和距离度量
"""
import chromadb
from config_loader import get_config

config = get_config()

print("=" * 60)
print("ChromaDB 集合诊断工具")
print("=" * 60)

print(f"\n数据库路径: {config.db_path}")
print(f"集合名称: {config.collection_name}")

client = chromadb.PersistentClient(path=config.db_path)

try:
    col = client.get_collection(config.collection_name)
    print(f"\n✅ 集合 '{config.collection_name}' 存在")
    
    # 获取集合记录数
    count = col.count()
    print(f"   记录数: {count}")
    
    # 尝试获取集合元数据(包含距离度量信息)
    try:
        # ChromaDB 不直接暴露 distance 配置,但可以通过查询推断
        if count > 0:
            sample = col.peek(limit=1)
            print(f"\n📊 样本数据:")
            print(f"   ID: {sample['ids'][0]}")
            print(f"   文档长度: {len(sample['documents'][0])} 字符")
            print(f"   元数据: {sample['metadatas'][0]}")
            
            # 测试查询,查看距离范围
            # 注意: 这里不使用 query_texts,而是直接获取已有记录来避免维度问题
            sample_data = col.get(ids=[sample['ids'][0]], include=['embeddings'])
            if sample_data and 'embeddings' in sample_data and len(sample_data['embeddings']) > 0:
                embedding_dim = len(sample_data['embeddings'][0])
                print(f"\n🔍 向量维度分析:")
                print(f"   嵌入维度: {embedding_dim}")
                
                # 根据维度判断模型
                if embedding_dim == 768:
                    print(f"   ✅ 使用 nomic-embed-text (768维)")
                elif embedding_dim == 384:
                    print(f"   ⚠️  使用 all-MiniLM-L6-v2 (384维)")
                else:
                    print(f"   ❓ 未知模型 ({embedding_dim}维)")
            
            # 通过 peek 获取多条记录来分析距离
            test_peek = col.peek(limit=5)
            if test_peek and len(test_peek['ids']) > 1:
                # 随机选一个向量作为查询向量
                query_embedding = test_peek['embeddings'][0] if 'embeddings' in test_peek else None
                
                if query_embedding:
                    test_query = col.query(
                        query_embeddings=[query_embedding],
                        n_results=min(count, 5)
                    )
                    
                    if test_query['distances'] and len(test_query['distances']) > 0:
                        distances = test_query['distances'][0]
                        print(f"\n🔍 距离度量分析:")
                        print(f"   最小距离: {min(distances):.3f}")
                        print(f"   最大距离: {max(distances):.3f}")
                        print(f"   平均距离: {sum(distances)/len(distances):.3f}")
                        
                        # 判断距离类型
                        max_dist = max(distances)
                        if max_dist <= 2.0:
                            print(f"   ✅ 使用余弦相似度(cosine) - 距离范围 [0, 2]")
                            distance_type = "cosine"
                        elif max_dist <= 10.0:
                            print(f"   ⚠️  可能使用内积(ip) - 距离范围不定")
                            distance_type = "ip"
                        else:
                            print(f"   ❌ 使用欧氏距离(l2) - 距离范围 [0, ∞)")
                            distance_type = "l2"
                        
                        print(f"\n💡 建议:")
                        if distance_type == "cosine":
                            print(f"   相关度计算公式: score = 1 - (distance / 2)")
                        elif distance_type == "l2":
                            print(f"   相关度计算公式: score = 1 / (1 + distance)")
                            print(f"   或者重新创建集合并指定 cosine 度量")
                        else:
                            print(f"   需要根据实际距离范围调整公式")
    except Exception as e:
        print(f"\n⚠️  无法获取详细信息: {e}")
        
except Exception as e:
    print(f"\n❌ 集合 '{config.collection_name}' 不存在或无法访问")
    print(f"   错误: {e}")
    print(f"\n💡 建议: 先运行入库脚本创建集合")

print("\n" + "=" * 60)
