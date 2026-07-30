# 入库脚本版本演进

## 📊 版本对比

### v1: ingest_pdf.py (基础版)
**功能:**
- ✅ PDF 文字提取
- ✅ PDF 图片 OCR
- ❌ Word/PPT/图片支持

**特点:**
- 单一格式
- 基础功能完整

---

### v2: ingest_all.py (多格式版)
**新增功能:**
- ✅ Word (.docx) 支持
- ✅ PPT (.pptx) 支持
- ✅ 自动去重
- ✅ 批量嵌入优化
- ✅ 进度显示 [当前/总数]
- ✅ 请求延迟保护
- ✅ 统一时间戳
- ✅ 错误分类统计

**支持格式:**
- PDF, Word, PPT

---

### v3: ingest_all_v2.py (完整版) ⭐推荐
**新增功能:**
- ✅ **图片 OCR 支持** (PNG/JPG/BMP/TIFF/GIF/WEBP)
- ✅ 智能分块(图片短文本不分块)
- ✅ 更灵活的依赖检查

**支持格式:**
- PDF, Word, PPT, **图片** ✨

**图片处理特性:**
```python
# 支持的图片格式
IMG_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', 
            '.tiff', '.tif', '.gif', '.webp')

# 智能分块: 图片OCR结果通常较短,整段入库
if ext in IMG_EXTS and len(full_text) < CHUNK_SIZE:
    chunks = [full_text]  # 不分块
else:
    chunks = chunk_text(full_text)  # 正常分块
```

---

## 🎯 推荐使用场景

| 场景 | 推荐脚本 | 原因 |
|------|---------|------|
| 仅PDF文档 | `ingest_pdf.py` | 轻量简洁 |
| PDF + Word + PPT | `ingest_all.py` | 多格式支持 |
| **全格式(含图片)** | **`ingest_all_v2.py`** | **功能最全** ⭐ |

---

## 📁 文件夹结构

```
D:\AG_docs\
├── pdfs\      # PDF 文件 (*.pdf)
├── word\      # Word 文档 (*.docx)
├── ppt\       # PPT 演示文稿 (*.pptx)
└── images\    # 图片文件 (*.png, *.jpg, etc.)  ← v3新增
```

---

## 🔧 配置说明

### config.json
```json
{
  "profiles": {
    "computer_a": {
      "pdf_folder": "D:\\AG_docs\\pdfs",
      "word_folder": "D:\\AG_docs\\word",
      "ppt_folder": "D:\\AG_docs\\ppt",
      "img_folder": "D:\\AG_docs\\images"  // v3新增
    }
  }
}
```

---

## 💡 图片OCR使用示例

### 1. 准备图片
将需要OCR的图片放入 `images/` 文件夹:
```
D:\AG_docs\images\
├── 截图1.png
├── 图表.jpg
├── 流程图.bmp
└── ...
```

### 2. 运行入库
```bash
python ingest_all_v2.py
```

### 3. 输出示例
```
📂 图片: 5 个文件

[1/10] 处理: 截图1.png ...
  提取 1 段，开始入库...
  已入库 1/1
[完成] 截图1.png → 1 段

[2/10] 处理: 图表.jpg ...
  提取 1 段，开始入库...
  已入库 1/1
[完成] 图表.jpg → 1 段
```

### 4. 查询测试
```bash
python query.py "图表中的数据"
```

---

## ⚠️ 注意事项

### 图片OCR
1. **识别精度**: 取决于图片质量和Tesseract训练数据
2. **语言支持**: 默认中英文混合 (`chi_sim+eng`)
3. **文件大小**: 建议单张图片 < 10MB
4. **处理时间**: 每张图片约1-5秒(取决于复杂度)

### 性能优化
1. **批量处理**: 建议每批50-100个文件
2. **内存占用**: 大量高清图片时注意内存
3. **请求延迟**: 已内置保护,无需调整

---

## 🚀 迁移指南

### 从 v2 升级到 v3

1. **更新配置**
   ```bash
   # 已在 config.json 中添加 img_folder
   ```

2. **创建图片文件夹**
   ```bash
   mkdir D:\AG_docs\images
   ```

3. **使用新脚本**
   ```bash
   # 之前
   python ingest_all.py
   
   # 现在
   python ingest_all_v2.py
   ```

4. **无需重新入库**
   - 已有数据不受影响
   - 新图片会自动入库

---

## 📈 功能演进总结

| 功能 | v1 | v2 | v3 |
|------|----|----|----|
| PDF | ✅ | ✅ | ✅ |
| Word | ❌ | ✅ | ✅ |
| PPT | ❌ | ✅ | ✅ |
| 图片OCR | ❌ | ❌ | ✅ |
| 自动去重 | ❌ | ✅ | ✅ |
| 进度显示 | ❌ | ✅ | ✅ |
| 请求保护 | ❌ | ✅ | ✅ |
| 错误分类 | ❌ | ✅ | ✅ |
| 智能分块 | ❌ | ❌ | ✅ |

---

## 🎉 最终推荐

**使用 `ingest_all_v2.py`**,它集成了所有优化:
- ✅ 支持4种格式(PDF/Word/PPT/图片)
- ✅ 所有性能优化
- ✅ 完善的错误处理
- ✅ 清晰的进度提示

一步到位,无需切换脚本!
