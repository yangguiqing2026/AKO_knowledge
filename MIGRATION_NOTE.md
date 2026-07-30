# 数据库迁移说明

## 📍 数据库位置变更

### 之前 (错误配置)
- 数据库在子文件夹: `ako_knowledge_db/chroma.sqlite3`
- 导致查询时找不到数据

### 现在 (正确配置)
- 数据库在根目录: `chroma.sqlite3`
- 与脚本同级,便于百度云盘同步

## 🔄 自动迁移

已执行的操作:
```bash
# 将数据库从子文件夹复制到根目录
Copy-Item -Path ".\ako_knowledge_db\chroma.sqlite3" -Destination ".\chroma.sqlite3"
```

## ✅ 验证结果

- ✅ 数据库路径: `D:\AKO_knowledge`
- ✅ 集合名称: `ako_photos`
- ✅ 配置文件已更新为 `"db_path": "."`
- ✅ active_profile 已设置为 `computer_a`

## 📝 配置说明

### config.json 关键配置
```json
{
  "active_profile": "computer_a",  // 当前电脑
  "profiles": {
    "computer_a": {
      "db_path": ".",                // "." 表示根目录
      ...
    }
  }
}
```

### config_loader.py 处理逻辑
```python
if db_path == '.' or db_path == '':
    # '.' 或空字符串表示脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = base_dir
```

## ⚠️ 注意事项

1. **首次使用**: 运行 `python ingest_pdf.py` 入库 PDF 数据
2. **百度云盘同步**: 确保两台电脑都使用相同的配置
3. **旧数据**: 如果之前在子文件夹有数据,已自动复制到根目录
4. **清理**: 确认根目录数据库正常后,可删除 `ako_knowledge_db/` 文件夹

## 🔍 检查命令

```bash
# 查看当前配置
python switch_config.py

# 测试数据库连接
python -c "import chromadb; from config_loader import get_config; c = get_config(); client = chromadb.PersistentClient(path=c.db_path); print('Collections:', [col.name for col in client.list_collections()])"
```
