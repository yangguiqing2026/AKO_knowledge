# 快速参考卡

## 🔄 切换配置

```bash
# 查看当前配置
python switch_config.py

# 切换到电脑A
python switch_config.py computer_a

# 切换到电脑B  
python switch_config.py computer_b
```

## 📝 常用命令

```bash
# 测试配置
python config_loader.py

# 验证配置
python validate_config.py

# 入库PDF (仅PDF)
python ingest_pdf.py

# 入库多格式 (PDF + Word + PPT)
python ingest_all.py

# 入库全格式 (PDF + Word + PPT + 图片, 推荐⭐)
python ingest_all_v2.py

# 查询知识(交互模式)
python query.py

# 查询知识(命令行)
python query.py "你的问题"

# 启动API服务
python -m uvicorn knowledge_service:app --reload
```

## ⚡ 环境变量切换(临时)

```powershell
# PowerShell
$env:AKO_PROFILE="computer_b"; python ingest_pdf.py
```

## 📂 重要文件

- `config.json` - 主配置文件
- `config_loader.py` - 配置加载模块
- `switch_config.py` - 配置切换工具
- `CONFIG_README.md` - 详细使用说明

## ⚠️ 注意事项

1. **数据库位置**: 数据库文件 (chroma.sqlite3) 直接放在根目录,与脚本同级
2. 百度云盘同步时确保使用相同的 `collection_name`
3. 修改配置后重新运行脚本即可生效
4. `config.json` 包含个人路径,不要提交到Git
5. 首次使用前请运行 `python ingest_pdf.py` 入库 PDF 数据
