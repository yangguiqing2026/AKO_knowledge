"""
配置验证脚本 - 检查所有配置是否正确
"""
import os
import sys
from config_loader import get_config


def validate_config():
    """验证配置是否正确"""
    print("=" * 60)
    print("配置验证工具")
    print("=" * 60)
    
    errors = []
    warnings = []
    
    try:
        config = get_config()
        
        # 1. 检查当前配置
        print("\n✅ 配置加载成功")
        print(config.get_profile_info())
        
        # 2. 检查数据库路径
        db_path = config.db_path
        print(f"\n📁 数据库路径: {db_path}")
        
        if not os.path.exists(db_path):
            errors.append(f"数据库目录不存在: {db_path}")
        else:
            print(f"✅ 数据库目录存在")
            
            # 检查数据库文件
            db_file = os.path.join(db_path, "chroma.sqlite3")
            if os.path.exists(db_file):
                print(f"✅ 数据库文件存在 ({os.path.getsize(db_file) / 1024:.1f} KB)")
                
                # 检查集合
                try:
                    import chromadb
                    client = chromadb.PersistentClient(path=db_path)
                    collections = [col.name for col in client.list_collections()]
                    print(f"✅ 集合列表: {collections}")
                    
                    if 'ako_photos' in collections:
                        col = client.get_collection('ako_photos')
                        count = col.count()
                        print(f"✅ ako_photos 集合文档数: {count}")
                        
                        if count == 0:
                            warnings.append("数据库为空,需要运行 ingest_pdf.py 入库数据")
                    else:
                        warnings.append("未找到 ako_photos 集合")
                        
                except Exception as e:
                    errors.append(f"数据库访问错误: {e}")
            else:
                warnings.append("数据库文件不存在,首次运行 ingest_pdf.py 会自动创建")
        
        # 3. 检查 PDF 文件夹
        pdf_folder = config.pdf_folder
        print(f"\n📂 PDF 文件夹: {pdf_folder}")
        
        if not os.path.exists(pdf_folder):
            warnings.append(f"PDF 文件夹不存在: {pdf_folder}")
        else:
            pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]
            print(f"✅ PDF 文件数量: {len(pdf_files)}")
            
            if len(pdf_files) == 0:
                warnings.append("PDF 文件夹中没有 PDF 文件")
        
        # 4. 检查配置文件位置
        print(f"\n⚙️  配置文件:")
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        if os.path.exists(config_file):
            print(f"✅ config.json 存在")
        else:
            errors.append("config.json 不存在")
        
        # 5. 显示结果
        print("\n" + "=" * 60)
        print("验证结果")
        print("=" * 60)
        
        if errors:
            print(f"\n❌ 发现 {len(errors)} 个错误:")
            for err in errors:
                print(f"  - {err}")
        
        if warnings:
            print(f"\n⚠️  发现 {len(warnings)} 个警告:")
            for warn in warnings:
                print(f"  - {warn}")
        
        if not errors and not warnings:
            print("\n✅ 所有检查通过!")
        
        print("\n" + "=" * 60)
        
        return len(errors) == 0
        
    except Exception as e:
        print(f"\n❌ 配置验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = validate_config()
    sys.exit(0 if success else 1)
