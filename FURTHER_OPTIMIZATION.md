# ingest_all_v2.py 进一步优化建议

## ✅ 当前状态评估

代码质量: ⭐⭐⭐⭐ (4/5)
- 功能完整
- 结构清晰
- 错误处理完善
- 性能优化到位

## 🔧 可优化的点

### 1. 避免重复计算扩展名

**当前问题:**
```python
# extract_file 中
ext = os.path.splitext(source_name)[1].lower()

# ingest_file 中又调用一次
ext = os.path.splitext(source_name)[1].lower()
```

**优化方案:**
```python
def get_file_info(file_path: str):
    """一次性获取文件信息"""
    ext = os.path.splitext(file_path)[1].lower()
    file_type = ext.replace('.', '') if ext.startswith('.') else 'unknown'
    return ext, file_type

# 使用
ext, file_type = get_file_info(source_name)
```

**收益:** 
- 减少重复计算
- 代码更清晰

---

### 2. 使用字典映射替代if-elif链

**当前代码:**
```python
def extract_file(file_path: str, source_name: str) -> str:
    ext = os.path.splitext(source_name)[1].lower()
    if ext == '.pdf':
        return extract_pdf(file_path)
    elif ext == '.docx':
        return extract_docx(file_path)
    elif ext == '.pptx':
        return extract_pptx(file_path)
    elif ext in IMG_EXTS:
        return ocr_image_file(file_path)
    else:
        print(f"  [跳过] 不支持的格式: {ext}")
        return ""
```

**优化方案:**
```python
# 在模块级别定义提取器映射
EXTRACTORS = {
    '.pdf': extract_pdf,
    '.docx': extract_docx,
    '.pptx': extract_pptx,
}

def extract_file(file_path: str, source_name: str) -> str:
    ext = os.path.splitext(source_name)[1].lower()
    
    # 检查是否是图片
    if ext in IMG_EXTS:
        return ocr_image_file(file_path)
    
    # 查找对应的提取器
    extractor = EXTRACTORS.get(ext)
    if extractor:
        return extractor(file_path)
    else:
        print(f"  [跳过] 不支持的格式: {ext}")
        return ""
```

**收益:**
- 更易扩展(添加新格式只需修改字典)
- 代码更简洁
- 符合开闭原则

---

### 3. 添加OCR结果缓存

**场景:** 同一张图片可能被多次处理

**优化方案:**
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def ocr_image_file_cached(img_path: str, mtime: float) -> str:
    """带缓存的图片OCR"""
    try:
        with open(img_path, 'rb') as f:
            return ocr_image(f.read())
    except Exception as e:
        return f"[OCR失败: {e}]"

def ocr_image_file(img_path: str) -> str:
    """读取图片文件OCR(带缓存)"""
    # 使用文件修改时间作为缓存键的一部分
    mtime = os.path.getmtime(img_path)
    return ocr_image_file_cached(img_path, mtime)
```

**收益:**
- 避免重复OCR
- 提升处理速度
- 注意: 缓存会占用内存

---

### 4. 添加文件大小检查

**当前问题:** 超大文件可能导致内存溢出

**优化方案:**
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

def check_file_size(file_path: str, max_size: int = MAX_FILE_SIZE) -> bool:
    """检查文件大小"""
    size = os.path.getsize(file_path)
    if size > max_size:
        print(f"  [跳过] 文件过大: {size / 1024 / 1024:.1f}MB > {max_size / 1024 / 1024:.0f}MB")
        return False
    return True

def ingest_file(file_path: str, source_name: str, timestamp: str):
    print(f"处理: {source_name} ...")
    
    # 检查文件大小
    if not check_file_size(file_path):
        return 0
    
    # ... 后续处理
```

**收益:**
- 防止内存溢出
- 提前发现问题
- 用户友好提示

---

### 5. 使用logging替代print

**当前问题:** 所有输出都用print,无法控制详细程度

**优化方案:**
```python
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 使用
logger.info("开始处理文件")
logger.warning("文件夹不存在")
logger.error("处理失败")
logger.debug("详细信息")  # 只在DEBUG模式显示
```

**收益:**
- 可控制输出级别
- 支持日志文件
- 更专业的日志格式
- 便于问题排查

---

### 6. 添加重试机制

**场景:** 网络波动导致Ollama请求失败

**优化方案:**
```python
def embed_with_retry(text: str, max_retries: int = 3) -> list:
    """带重试的嵌入生成"""
    for attempt in range(max_retries):
        try:
            r = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text[:1500])
            return r["embedding"]
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                logger.warning(f"嵌入失败, {wait_time}秒后重试 ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                logger.error(f"嵌入失败,已达最大重试次数: {e}")
                return None
```

**收益:**
- 提高成功率
- 应对临时故障
- 指数退避避免雪崩

---

### 7. 添加进度条库(tqdm)

**当前:** 手动显示 `[1/10]`

**优化方案:**
```python
from tqdm import tqdm

# 使用
for idx, (fp, fn) in enumerate(tqdm(all_files, desc="处理文件"), 1):
    # 自动显示进度条
    n = ingest_file(fp, fn, timestamp)
```

**输出效果:**
```
处理文件:  80%|████████ | 8/10 [00:45<00:12, 0.17it/s]
```

**收益:**
- 更美观的进度显示
- 预估剩余时间
- 处理速度统计

---

### 8. 配置文件化阈值参数

**当前:** 硬编码在代码中
```python
if not full_text or len(full_text) < 50:  # 50硬编码
if (idx + 1) % 5 == 0:  # 5硬编码
    time.sleep(0.1)  # 0.1硬编码
```

**优化方案:**
在 `config.json` 中添加:
```json
{
  "common_settings": {
    "min_text_length": 50,
    "embed_batch_delay_count": 5,
    "embed_batch_delay_time": 0.1,
    "max_file_size_mb": 50
  }
}
```

**收益:**
- 无需修改代码即可调整参数
- 不同环境不同配置
- 更易维护

---

## 📊 优化优先级

| 优化项 | 优先级 | 难度 | 收益 |
|--------|--------|------|------|
| 字典映射替代if-elif | ⭐⭐⭐⭐⭐ | 低 | 高 |
| 文件大小检查 | ⭐⭐⭐⭐⭐ | 低 | 高 |
| 重试机制 | ⭐⭐⭐⭐ | 中 | 高 |
| 避免重复计算 | ⭐⭐⭐ | 低 | 中 |
| 使用logging | ⭐⭐⭐ | 中 | 中 |
| OCR缓存 | ⭐⭐ | 中 | 低 |
| tqdm进度条 | ⭐⭐ | 低 | 低 |
| 配置化阈值 | ⭐ | 低 | 低 |

---

## 🎯 推荐实施顺序

### 第一阶段(立即实施)
1. ✅ 字典映射替代if-elif
2. ✅ 文件大小检查
3. ✅ 避免重复计算

### 第二阶段(短期优化)
4. 重试机制
5. 使用logging

### 第三阶段(长期优化)
6. OCR缓存
7. tqdm进度条
8. 配置化阈值

---

## 💡 总结

**当前代码已经很好了!** 

以上优化都是锦上添花,不是必须的。建议:
- 如果追求极致性能和可维护性 → 实施第一阶段
- 如果生产环境使用 → 实施第一+第二阶段
- 如果只是个人使用 → 当前版本已足够

代码的核心价值在于:
- ✅ 功能完整(PDF/Word/PPT/图片)
- ✅ 配置灵活(多电脑支持)
- ✅ 容错性好(完善的错误处理)
- ✅ 性能合理(批量嵌入+延迟保护)

继续保持!👍
