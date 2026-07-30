# Ako Knowledge

> Author: AKO_studio

---
ako_doc_id: AKO_README_KNW_001
ako_version: v0.1.0
ako_status: 草稿
ako_title: 知识库服务 (KNW)
ako_category: 服务
ako_author: 杨越浩
ako_created: 2026-07-14
ako_source: AKO_DOC_001 v1.0.0
ako_project_root: D:\AKO_knowledge
---

# 知识库服务（KNW）

## 1. 结论前置

AKO_knowledge（KNW）是 AKO 体系的底层知识库服务，基于 ChromaDB 构建，提供向量存储、混合检索（bge-m3 Dense + Sparse + ColBERT）、PDF 文档入库、FastAPI 查询接口和双机配置无缝切换能力。已从初期 nomic-embed-text 升级至 bge-m3 三向量方案，支持防幻觉检索和 DeepSeek 信息补全，是 AKO 全部 Agent 的共享知识底座。

## 2. 修订记录

| 版本 | 日期 | 修订人 | 修订内容 | 签发人 |
|------|------|--------|----------|--------|
| v0.1.0 | 2026-07-14 | 杨越浩 | 按 AKO_DOC_001 初始化 | （待签发） |

## 3. 项目概述

### 3.1 定位

AKO 体系共享知识底座，为所有 Agent 提供统一的向量存储、检索和知识查询服务。

### 3.2 核心能力

- **向量存储与检索**：基于 ChromaDB 持久化，支持 cosine 相似度检索
- **bge-m3 三向量混合检索**：Dense + Sparse + ColBERT 多路召回 + 加权融合，显著优于单向量方案
- **PDF 智能入库**：支持批量 PDF 解析、OCR 识别、文本分块、向量化入库
- **FastAPI 查询服务**：提供 RESTful API 供其他 Agent 远程查询
- **双机配置切换**：通过 `config.json` + 环境变量无缝切换电脑 A/B 的数据库路径和参数
- **防幻觉检索**：置信度阈值控制 + 相似度阈值过滤，避免低质量结果
- **Hub 双写**：可选将知识条目同步写入 AKO_Hub 的 ChromaDB，保持双库一致

### 3.3 技术栈

- Python 3.9+
- ChromaDB（向量数据库）
- bge-m3 / nomic-embed-text（嵌入模型）
- FastAPI + uvicorn（API 服务）
- Ollama（本地嵌入与 LLM 推理）
- FlagEmbedding（bge-m3 模型加载）
- PyPDF2 / pdfplumber / pytesseract（PDF 解析与 OCR）
- Pydantic（数据模型与配置校验）

## 4. 快速开始

### 4.1 环境要求

- Python 3.9+
- Ollama 运行中
- 已安装 bge-m3 嵌入模型：`ollama pull bge-m3`

### 4.2 安装

```bash
pip install -r requirements.txt
```

配置：

```bash
# 查看当前配置
python config_loader.py

# 切换到电脑 A
python switch_config.py computer_a

# 或直接编辑 config.json 修改 active_profile
```

### 4.3 运行

启动 API 服务：

```bash
python -m uvicorn knowledge_service:app --host 0.0.0.0 --port 8000 --reload
```

PDF 入库：

```bash
python ingest_all_v2.py
```

知识查询：

```bash
# 命令行查询
python query.py "陶粒墙板技术方案"

# 增强查询
python query_enhanced.py "装配式建筑"

# 混合检索对比
python compare_retrieval.py "钢结构设计"
```

## 5. 项目结构

```
AKO_knowledge/
├── knowledge_service.py        # FastAPI 知识库服务（含防幻觉检索、Hub 双写）
├── hybrid_retrieval.py         # bge-m3 三向量混合检索引擎
├── ingest_all_v2.py            # PDF 批量入库工具
│
├── query.py                    # 基础查询工具
├── query_enhanced.py           # 增强查询（含 LLM 信息补全）
├── compare_retrieval.py        # 检索方案对比评测
│
├── briefing.py                 # 知识简报生成
├── backfill_vectors.py         # 向量回填工具
├── migrate.py                  # 数据迁移/重索引工具
├── maintain.py                 # 知识库维护工具
│
├── check_collection.py         # Collection 状态检查
├── check_vector_status.py      # 向量状态检查
│
├── config.json                 # 主配置文件（多 Profile）
├── config.example.json         # 配置模板
├── config_loader.py            # 配置加载模块
├── switch_config.py            # 配置切换工具
├── validate_config.py          # 配置校验
│
├── chroma.sqlite3              # ChromaDB 持久化文件（根目录）
├── data/                       # 本地数据目录
├── Inbox/                      # 待入库文档暂存区
│
├── tests/
│   └── test_hybrid_retrieval.py  # 混合检索测试
│
├── 启动知识库.bat               # Windows 快速启动脚本
├── README.md                   # 本文档
│
└── docs/                       # 相关文档
    ├── CONFIG_README.md         # 配置系统说明
    ├── IMPLEMENTATION_SUMMARY.md  # 实现总结
    ├── FURTHER_OPTIMIZATION.md   # 进一步优化建议
    ├── RECURSIVE_CHUNKING.md     # 递归分块策略
    ├── NOMIC_EMBED_CONFIG.md     # nomic-embed-text 配置
    └── ...
```

## 6. 相关文档

| 文档 | 说明 |
|------|------|
| [CONFIG_README.md](CONFIG_README.md) | 双机配置切换系统使用说明 |
| [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) | 智能配置系统实现总结 |
| [FURTHER_OPTIMIZATION.md](FURTHER_OPTIMIZATION.md) | 检索质量优化建议 |
| [RECURSIVE_CHUNKING.md](RECURSIVE_CHUNKING.md) | 递归分块策略说明 |
| [NOMIC_EMBED_CONFIG.md](NOMIC_EMBED_CONFIG.md) | nomic-embed-text 嵌入配置 |
| [MIGRATION_NOTE.md](MIGRATION_NOTE.md) | 迁移注意事项 |
| [INGEST_ALL_README.md](INGEST_ALL_README.md) | 批量入库使用说明 |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | 常用命令速查 |

## 7. 术语

| 术语 | 定义 |
|------|------|
| KNW | Knowledge Service，知识库服务代号 |
| 三向量混合检索 | bge-m3 模型同时输出 Dense（稠密向量）、Sparse（词袋稀疏向量）、ColBERT（token 级多向量），三路召回后加权融合 |
| 防幻觉检索 | 通过 confidence_threshold 和 similarity_threshold 双阈值过滤，仅返回高置信度结果 |
| Hub 双写 | 入库时同步将向量写入 AKO_Hub 的 ChromaDB，保持两个知识库一致性 |
| Profile/Profile 切换 | 通过 config.json 中的 active_profile 字段在两台电脑的配置间切换，无需改代码 |
| Collection | ChromaDB 中的向量集合，类似关系数据库中的"表" |
