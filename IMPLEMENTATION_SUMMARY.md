# 智能配置系统 - 完成总结

## ✅ 已完成的工作

### 1. 核心文件创建

| 文件 | 说明 | 状态 |
|------|------|------|
| `config.json` | 主配置文件 | ✅ 已创建 |
| `config.example.json` | 配置示例文件 | ✅ 已创建 |
| `config_loader.py` | 配置加载模块 | ✅ 已创建 |
| `switch_config.py` | 配置切换工具 | ✅ 已创建 |
| `CONFIG_README.md` | 使用说明文档 | ✅ 已创建 |
| `.gitignore` | Git忽略配置 | ✅ 已创建 |

### 2. 脚本适配

| 脚本 | 修改内容 | 状态 |
|------|---------|------|
| `ingest_pdf.py` | 使用配置系统,支持动态配置 | ✅ 已完成 |
| `query.py` | 使用配置系统,支持动态配置 | ✅ 已完成 |
| `knowledge_service.py` | 使用配置系统,支持动态配置 | ✅ 已完成 |

## 🎯 主要改进

### 之前的问题
- ❌ 需要手动注释/取消注释代码
- ❌ 容易忘记切换导致错误
- ❌ 三个脚本配置不一致
- ❌ 硬编码路径难以维护

### 现在的优势
- ✅ 只需修改配置文件或运行切换命令
- ✅ 自动同步所有脚本配置
- ✅ 支持环境变量临时覆盖
- ✅ 集中管理,易于扩展
- ✅ 防止配置错误

## 📖 使用方法

### 方法1: 使用切换工具(最简单)

```bash
# 查看当前配置
python switch_config.py

# 切换到电脑A
python switch_config.py computer_a

# 切换到电脑B
python switch_config.py computer_b
```

### 方法2: 编辑配置文件

编辑 `config.json`,修改:
```json
{
  "active_profile": "computer_a"  // 改为 computer_b
}
```

### 方法3: 环境变量(临时)

```powershell
# PowerShell
$env:AKO_PROFILE="computer_b"
python ingest_pdf.py
```

## 🔧 配置结构

```json
{
  "active_profile": "computer_a",    // 当前激活的配置
  "profiles": {                       // 各电脑的配置
    "computer_a": {
      "name": "电脑 A",
      "db_path": ".",                  // "." 表示根目录
      "pdf_folder": "D:\\AG_docs\\pdfs",
      "collection_name": "ako_photos"
    },
    "computer_b": { ... }
  },
  "common_settings": {                // 通用设置
    "chunk_size": 768,
    "overlap": 256,
    "batch_size": 16,
    "embedding_model": "nomic-embed-text",
    "ocr_languages": "chi_sim+eng"
  }
}
```

## 💡 最佳实践

1. **百度云盘同步时**
   - 确保两台电脑使用相同的 `collection_name`
   - 数据库文件在根目录,会自动同步
   - 同步完成后再运行查询

2. **数据库位置**
   - 数据库文件 (chroma.sqlite3) 直接放在项目根目录
   - 与脚本同级,便于同步
   - 不再使用子文件夹

2. **添加新电脑**
   - 在 `profiles` 中添加新配置项
   - 修改 `active_profile` 或使用切换工具

3. **版本控制**
   - `config.json` 已加入 `.gitignore`
   - 提交时使用 `config.example.json` 作为模板

4. **测试配置**
   ```bash
   python config_loader.py  # 测试配置加载
   python switch_config.py  # 查看当前配置
   ```

## 📊 测试结果

✅ 配置加载测试通过
✅ 配置切换测试通过
✅ 所有脚本适配完成
✅ 配置一致性验证通过

## 🚀 下一步

现在你可以:
1. 运行 `python ingest_pdf.py` 入库PDF
2. 运行 `python query.py` 查询知识
3. 运行 `python -m uvicorn knowledge_service:app --reload` 启动API服务

所有脚本会自动使用统一的配置!
