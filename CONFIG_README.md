# 智能配置系统使用说明

## 📋 概述

本系统使用配置文件管理多电脑环境,无需手动注释/取消注释代码。

## 🚀 快速开始

### 1. 配置文件说明

- `config.json` - 主配置文件(已创建)
- `config.example.json` - 配置示例文件
- `config_loader.py` - 配置加载模块

### 2. 切换电脑配置

**方法一:修改配置文件**(推荐)

编辑 `config.json`,修改 `active_profile` 字段:

```json
{
  "active_profile": "computer_a"  // 改为 "computer_b" 切换到电脑B
}
```

**方法二:使用环境变量**(临时切换)

Windows PowerShell:
```powershell
$env:AKO_PROFILE="computer_b"
python ingest_pdf.py
```

Windows CMD:
```cmd
set AKO_PROFILE=computer_b
python ingest_pdf.py
```

Linux/Mac:
```bash
export AKO_PROFILE=computer_b
python ingest_pdf.py
```

### 3. 添加新电脑配置

在 `config.json` 的 `profiles` 中添加新配置项:

```json
"profiles": {
  "computer_a": { ... },
  "computer_b": { ... },
  "computer_c": {  // 新增电脑C
    "name": "电脑 C",
    "db_path": "ako_knowledge_db",
    "pdf_folder": "F:\\AG_docs\\pdfs",
    "collection_name": "ako_photos"
  }
}
```

然后设置 `"active_profile": "computer_c"` 即可。

## ⚙️ 配置项说明

### profiles (电脑配置)

| 字段 | 说明 | 示例 |
|------|------|------|
| name | 电脑名称(显示用) | "电脑 A" |
| db_path | 数据库路径("."表示根目录) | "." |
| pdf_folder | PDF文件夹路径 | "D:\\AG_docs\\pdfs" |
| collection_name | 集合名称 | "ako_photos" |

### common_settings (通用设置)

| 字段 | 说明 | 默认值 |
|------|------|--------|
| chunk_size | 文本分块大小 | 768 |
| overlap | 分块重叠大小 | 256 |
| batch_size | 批量处理大小 | 16 |
| embedding_model | 嵌入模型名称 | "nomic-embed-text" |
| ocr_languages | OCR识别语言 | "chi_sim+eng" |

## 📁 项目结构

```
AKO_knowledge/
├── config.json              # 主配置文件
├── config.example.json      # 配置示例
├── config_loader.py         # 配置加载模块
├── ingest_pdf.py            # PDF入库工具(已适配)
├── query.py                 # 查询工具(已适配)
├── knowledge_service.py     # API服务(已适配)
└── chroma.sqlite3           # 数据库文件(根目录)
```

## ✅ 优势

1. **无需修改代码** - 只需修改配置文件
2. **集中管理** - 所有配置在一个文件中
3. **灵活切换** - 支持配置文件和环境变量两种方式
4. **易于扩展** - 可添加任意多台电脑配置
5. **统一配置** - 三个脚本自动同步配置

## 🔧 测试配置

运行以下命令测试配置是否正确:

```bash
python config_loader.py
```

会显示当前配置信息和可用配置项列表。

## ⚠️ 注意事项

1. 首次使用前,确保 `config.json` 存在
2. 修改配置后,重新运行脚本即可生效
3. 数据库路径建议使用相对路径,便于同步
4. 百度云盘同步时,确保两台电脑都使用相同的 `collection_name`
