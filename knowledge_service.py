"""
AKO_Hub 知识库 API 服务 - 基于 bge-m3 三向量混合检索
支持: 防幻觉检索 / Inbox 文档入库 / DeepSeek 信息补全
"""
import os
import json
import uuid
import datetime
from typing import List, Optional

# [DEPRECATED_GUI] from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import chromadb
from config_loader import get_config
from hybrid_retrieval import HybridRetriever, build_hybrid_metadata

# ==================== Gbrain 发酵系统集成 ====================
from gbrain_ferment import FermentEngine, create_engine
from gbrain_models import ConceptStore
from gbrain_nightly import NightlyAgent

# [DEPRECATED_GUI] app = FastAPI()

# ==================== 加载配置 ====================
config = get_config()

DB_PATH = config.db_path
COLLECTION_NAME = config.collection_name
EMBEDDING_MODEL = config.embedding_model

# 读取扩展配置（统一通过 config_loader）
CONFIDENCE_THRESHOLD = config.confidence_threshold
SIMILARITY_THRESHOLD = config.similarity_threshold

LLM_API_BASE = config.llm_api_base
LLM_API_KEY = config.llm_api_key
LLM_MODEL = config.llm_model

INBOX_FOLDER = config.inbox_folder

# ==================== Hub 双写配置 ====================
_hub_client: Optional[chromadb.PersistentClient] = None
_hub_collection = None
_hub_collection_name: str = ""
_hub_enabled: bool = False

# 从 config_loader 读取 hub_integration 配置
if config.hub_enabled:
    _hub_chroma_root = config.hub_chroma_root
    _hub_collection_name = config.hub_collection
    try:
        _hub_client = chromadb.PersistentClient(path=_hub_chroma_root)
        _hub_collection = _hub_client.get_or_create_collection(
            _hub_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        _hub_enabled = True
        print(f"[Hub 双写]   已启用 => {_hub_chroma_root}/{_hub_collection_name}")
    except Exception as _e:
        print(f"[Hub 双写]   初始化失败 (本地模式正常运行): {_e}")

# =================================================

client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_or_create_collection(COLLECTION_NAME)

# 初始化混合检索器
retriever = HybridRetriever(
    collection=collection,
    embedding_model=EMBEDDING_MODEL,
)


# 请求模型定义
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    use_threshold: bool = True  # 是否启用置信度阈值


class AddRequest(BaseModel):
    doc_id: str
    text: str


class IngestRequest(BaseModel):
    file_path: Optional[str] = None  # 指定文件路径，为空则处理整个 Inbox


class EnrichRequest(BaseModel):
    doc_id: str
    instruction: str = "请根据已有内容补充相关背景信息和细节"


# 响应模型定义
class SearchResponse(BaseModel):
    results: List[str]
    distances: List[float]
    ids: List[str]
    scores: Optional[List[float]] = None
    confidence_ok: bool = True  # 是否通过置信度检查
    message: str = ""


class AddResponse(BaseModel):
    status: str
    message: str = ""


class IngestResponse(BaseModel):
    status: str
    files_processed: int = 0
    chunks_added: int = 0
    message: str = ""


class EnrichResponse(BaseModel):
    status: str
    original_text: str = ""
    enriched_text: str = ""
    message: str = ""


# [DEPRECATED_GUI] @app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    """搜索相似文档 - 使用 bge-m3 三向量混合检索，支持防幻觉阈值"""
    try:
        result = retriever.search(request.query, top_k=request.top_k)

        if not result["documents"][0]:
            return SearchResponse(
                results=[], distances=[], ids=[], scores=[],
                confidence_ok=False, message="知识库中未找到相关信息",
            )

        docs = result["documents"][0]
        scores_list = result.get("scores", [[]])[0]
        distances_list = result["distances"][0]

        # 防幻觉检查
        confidence_ok = True
        message = ""
        if request.use_threshold and scores_list:
            top_score = scores_list[0]
            top_dist = distances_list[0] if distances_list else 1.0
            top_sim = 1 - (top_dist / 2)
            if top_score < CONFIDENCE_THRESHOLD or top_sim < SIMILARITY_THRESHOLD:
                confidence_ok = False
                message = (
                    f"知识库中没有足够相关的信息 "
                    f"(融合分={top_score:.4f}<{CONFIDENCE_THRESHOLD}, "
                    f"相似度={top_sim:.3f}<{SIMILARITY_THRESHOLD})"
                )

        return SearchResponse(
            results=docs,
            distances=distances_list,
            ids=result["ids"][0],
            scores=scores_list,
            confidence_ok=confidence_ok,
            message=message,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


# [DEPRECATED_GUI] @app.post("/add", response_model=AddResponse)
def add(request: AddRequest):
    """添加新文档 (同时双写到 Hub 统一库)"""
    try:
        # 检查文档ID是否已存在
        existing = collection.get(ids=[request.doc_id])
        if existing["ids"]:
            raise HTTPException(status_code=409, detail=f"文档ID '{request.doc_id}' 已存在")

        # 生成嵌入
        import ollama
        embed = ollama.embeddings(model=EMBEDDING_MODEL, prompt=request.text)["embedding"]

        # 构建含 sparse lexicon 的 metadata
        from hybrid_retrieval import build_hybrid_metadata
        meta = build_hybrid_metadata(request.text)
        meta["source"] = "api"
        meta["timestamp"] = ""

        collection.add(
            ids=[request.doc_id],
            embeddings=[embed],
            documents=[request.text],
            metadatas=[meta],
        )

        # 双写到 Hub
        hub_msg = ""
        if _hub_enabled and _hub_collection is not None:
            try:
                _hub_collection.add(
                    ids=[request.doc_id],
                    embeddings=[embed],
                    documents=[request.text],
                    metadatas=[{
                        "source": "ako_knowledge",
                        "local_collection": COLLECTION_NAME,
                        **meta,
                    }],
                )
                hub_msg = f" (已同步到 Hub: {_hub_collection_name})"
            except Exception as hub_e:
                hub_msg = f" (Hub 同步失败: {hub_e})"

        return AddResponse(status="ok", message=f"文档添加成功{hub_msg}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加失败: {str(e)}")


# [DEPRECATED_GUI] @app.get("/")
def root():
    """根路径 — 返回服务基本信息"""
    return {
        "status": "running",
        "engine": "bge-m3 hybrid (dense + sparse + colbert)",
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "similarity_threshold": SIMILARITY_THRESHOLD,
    }


# [DEPRECATED_GUI] @app.get("/health")
async def health():
    """Health check endpoint — returns component + status + checks"""
    checks = {}

    # Local ChromaDB
    try:
        count = collection.count()
        checks["chromadb"] = f"connected ({count} docs)"
    except Exception as e:
        checks["chromadb"] = f"error: {e}"

    # Hub ChromaDB (if enabled)
    if _hub_enabled and _hub_collection is not None:
        try:
            hub_count = _hub_collection.count()
            checks["hub_chromadb"] = f"connected ({hub_count} docs)"
        except Exception as e:
            checks["hub_chromadb"] = f"error: {e}"
    else:
        checks["hub_chromadb"] = "disabled"

    # LLM API (DeepSeek)
    if LLM_API_KEY:
        try:
            import httpx
            with httpx.Client(timeout=5) as client:
                resp = client.get(
                    f"{LLM_API_BASE.rstrip('/')}/v1/models",
                    headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                )
                checks["llm"] = f"reachable ({resp.status_code})"
        except Exception as e:
            checks["llm"] = f"unreachable: {e}"
    else:
        checks["llm"] = "skipped (no API key)"

    return {
        "status": "ok",
        "component": "knowledge",
        "checks": checks,
    }


# [DEPRECATED_GUI] @app.get("/hub_status")
def hub_status():
    """Hub 双写状态"""
    if not _hub_enabled:
        return {"hub_enabled": False, "message": "Hub 双写未启用"}
    try:
        count = _hub_collection.count() if _hub_collection else 0
        return {
            "hub_enabled": True,
            "hub_collection": _hub_collection_name,
            "hub_record_count": count,
            "local_collection": COLLECTION_NAME,
            "local_count": collection.count(),
        }
    except Exception as e:
        return {"hub_enabled": True, "error": str(e)}


# ==================== /ingest - Inbox 文档入库 ====================

def _parse_inbox_markdown(file_path: str) -> dict:
    """
    解析 Inbox 格式的 Markdown 文件
    提取 frontmatter (YAML) + 正文内容
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    frontmatter = {}
    body = content

    # 解析 YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            # 简单解析 key: value
            for line in fm_text.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key == "tags":
                        # tags 可能是列表
                        continue
                    frontmatter[key] = val

    return {
        "frontmatter": frontmatter,
        "body": body,
        "filename": os.path.basename(file_path),
    }


def _chunk_text_simple(text: str, chunk_size: int = 450, overlap: int = 100) -> list:
    """简单文本分块 (用于 ingest)"""
    if not text or len(text) < 50:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        if end == len(text):
            break
        start = end - overlap
    return chunks


# [DEPRECATED_GUI] @app.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest):
    """
    Inbox 文档入库 - 支持 Markdown 文件解析 + 自动分块 + 嵌入入库
    指定 file_path 处理单个文件，不指定则处理整个 Inbox 文件夹
    """
    import ollama

    files_to_process = []

    if request.file_path:
        if not os.path.exists(request.file_path):
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")
        files_to_process.append(request.file_path)
    else:
        if not os.path.exists(INBOX_FOLDER):
            raise HTTPException(status_code=404, detail=f"Inbox 文件夹不存在: {INBOX_FOLDER}")
        for f in os.listdir(INBOX_FOLDER):
            if f.endswith((".md", ".txt")):
                files_to_process.append(os.path.join(INBOX_FOLDER, f))

    if not files_to_process:
        return IngestResponse(status="ok", message="没有可处理的文件")

    total_chunks = 0
    files_processed = 0
    timestamp = datetime.datetime.now().isoformat()

    for fp in files_to_process:
        try:
            parsed = _parse_inbox_markdown(fp)
            body = parsed["body"]
            if not body or len(body) < 20:
                continue

            source_name = parsed["frontmatter"].get("title", parsed["filename"])
            chunks = _chunk_text_simple(body)
            if not chunks:
                continue

            # 检查是否已入库
            existing = collection.get(where={"source": source_name})
            if existing["ids"]:
                continue

            for idx, chunk in enumerate(chunks):
                doc_id = str(uuid.uuid4())
                embed = ollama.embeddings(model=EMBEDDING_MODEL, prompt=chunk)["embedding"]
                meta = build_hybrid_metadata(chunk)
                meta.update({
                    "source": source_name,
                    "type": "markdown",
                    "chunk_index": idx,
                    "timestamp": timestamp,
                    "original_file": parsed["filename"],
                })
                # 添加 frontmatter 中的标签
                if "tags" in parsed["frontmatter"]:
                    meta["tags"] = parsed["frontmatter"]["tags"]

                collection.add(
                    ids=[doc_id],
                    embeddings=[embed],
                    documents=[chunk],
                    metadatas=[meta],
                )

                # Hub 双写
                if _hub_enabled and _hub_collection is not None:
                    try:
                        _hub_collection.add(
                            ids=[doc_id],
                            embeddings=[embed],
                            documents=[chunk],
                            metadatas=[{"source": "ako_knowledge", **meta}],
                        )
                    except Exception:
                        pass

            total_chunks += len(chunks)
            files_processed += 1

        except Exception as e:
            print(f"[ingest] 处理 {fp} 失败: {e}")
            continue

    return IngestResponse(
        status="ok",
        files_processed=files_processed,
        chunks_added=total_chunks,
        message=f"入库完成: {files_processed} 个文件, {total_chunks} 个片段",
    )


# ==================== /enrich - DeepSeek 信息补全 ====================

def _call_deepseek(prompt: str, context: str = "") -> str:
    """调用 DeepSeek API 进行信息补全"""
    if not LLM_API_KEY:
        raise HTTPException(status_code=400, detail="DeepSeek API Key 未配置，请设置环境变量 AKO_KNOWLEDGE_DEEPSEEK_API_KEY 或在 config.json llm_settings.api_key 中配置")

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="需要安装 httpx: pip install httpx")

    messages = []
    if context:
        messages.append({"role": "system", "content": f"以下是知识库中的相关内容:\n{context}\n\n请基于以上内容进行补充。"})
    messages.append({"role": "user", "content": prompt})

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{LLM_API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"DeepSeek API 调用失败: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DeepSeek 调用失败: {str(e)}")


# [DEPRECATED_GUI] @app.post("/enrich", response_model=EnrichResponse)
def enrich(request: EnrichRequest):
    """
    信息补全 - 从知识库检索相关内容，调用 DeepSeek 生成补充信息
    """
    # 先检索知识库中的相关内容
    search_result = retriever.search(request.instruction, top_k=3)
    context_docs = search_result.get("documents", [[]])[0]
    context = "\n\n".join(context_docs[:3]) if context_docs else ""

    # 获取原文档内容
    try:
        existing = collection.get(ids=[request.doc_id])
        if not existing["ids"]:
            raise HTTPException(status_code=404, detail=f"文档 {request.doc_id} 不存在")
        original_text = existing["documents"][0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档失败: {e}")

    # 调用 DeepSeek 补全
    prompt = f"以下是知识库中的一段内容:\n\n{original_text}\n\n请根据以下指令进行补充:\n{request.instruction}"
    if context:
        prompt += f"\n\n相关知识库内容供参考:\n{context}"

    enriched = _call_deepseek(prompt, context)

    return EnrichResponse(
        status="ok",
        original_text=original_text,
        enriched_text=enriched,
        message="信息补全完成",
    )


# ==================== /maintain - 知识库健康检查 ====================

# [DEPRECATED_GUI] @app.get("/maintain")
def maintain():
    """
    知识库健康检查 - 检测过期内容、死链接、孤儿页，返回健康评分
    """
    try:
        from maintain import run_full_check
        report = run_full_check()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")


# ==================== /migrate - Obsidian/Markdown 迁移 ====================

class MigrateRequest(BaseModel):
    source_type: str  # "obsidian" 或 "folder"
    path: str  # vault 或文件夹路径
    skip_existing: bool = True


class MigrateResponse(BaseModel):
    status: str
    files_processed: int = 0
    chunks_added: int = 0
    skipped: int = 0
    errors: int = 0
    message: str = ""


# [DEPRECATED_GUI] @app.post("/migrate", response_model=MigrateResponse)
def migrate(request: MigrateRequest):
    """
    从 Obsidian Vault 或 Markdown 文件夹迁移入库
    """
    try:
        if request.source_type == "obsidian":
            from migrate import migrate_from_obsidian
            report = migrate_from_obsidian(request.path, request.skip_existing)
        elif request.source_type == "folder":
            from migrate import migrate_from_folder
            report = migrate_from_folder(request.path, request.skip_existing)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的源类型: {request.source_type}")

        return MigrateResponse(
            status="ok",
            files_processed=report.get("files_processed", 0),
            chunks_added=report.get("chunks_added", 0),
            skipped=report.get("skipped", 0),
            errors=report.get("errors", 0),
            message=report.get("message", "迁移完成"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"迁移失败: {str(e)}")


# ==================== /briefing - 每日简报 ====================

class BriefingRequest(BaseModel):
    use_llm: bool = True
    days: int = 7


class BriefingResponse(BaseModel):
    date: str
    stats: dict
    recent: list
    expiring: list
    briefing_text: str


# [DEPRECATED_GUI] @app.post("/briefing", response_model=BriefingResponse)
def briefing(request: BriefingRequest):
    """
    生成每日简报 - 汇总知识库动态、新增内容、过期风险
    """
    try:
        from briefing import generate_briefing
        report = generate_briefing(use_llm=request.use_llm, days=request.days)
        return BriefingResponse(**report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"简报生成失败: {str(e)}")


# ======================================================================
# Gbrain 发酵系统 API
# ======================================================================

# 全局 Gbrain 引擎实例 (懒加载)
_gbrain_engine: Optional[FermentEngine] = None
_gbrain_nightly: Optional[NightlyAgent] = None


def _get_gbrain_engine() -> FermentEngine:
    """获取或创建 Gbrain 发酵引擎单例"""
    global _gbrain_engine
    if _gbrain_engine is None:
        _gbrain_engine = create_engine(
            db_path=DB_PATH,
            collection_name=COLLECTION_NAME,
            vault_root=r"D:\AKOBUILD",
        )
    return _gbrain_engine


def _get_nightly_agent() -> NightlyAgent:
    """获取夜间 Agent"""
    global _gbrain_nightly
    if _gbrain_nightly is None:
        _gbrain_nightly = NightlyAgent(
            db_path=DB_PATH,
            vault_root=r"D:\AKOBUILD",
            collection_name=COLLECTION_NAME,
            git_auto_commit=True,
        )
    return _gbrain_nightly


# ── 请求/响应模型 ──

class FermentRequest(BaseModel):
    full_graph: bool = True  # 是否扫描 vault (耗时较长)


class FermentResponse(BaseModel):
    status: str
    timestamp: str = ""
    graph_stats: dict = {}
    stubs_created: int = 0
    upgrades_basic: int = 0
    upgrades_full: int = 0
    enriched_basic: int = 0
    enriched_full: int = 0
    total_pages: int = 0
    message: str = ""


class ConceptQueryRequest(BaseModel):
    concept_name: str


class ConceptPageResponse(BaseModel):
    concept_id: str = ""
    concept_name: str = ""
    mention_count: int = 0
    enrichment_level: int = 0
    is_stub: bool = False
    is_full: bool = False
    compiled_truth: Optional[dict] = None
    timeline: list = []
    related_concepts: list = []
    backlinks: list = []
    tags: list = []
    first_seen: str = ""
    last_seen: str = ""


class ConceptSearchRequest(BaseModel):
    query: str
    top_k: int = 10


class GraphStatsResponse(BaseModel):
    total_concepts: int = 0
    total_edges: int = 0
    max_mentions: int = 0
    avg_mentions: float = 0.0
    distribution: dict = {}
    zero_cost: bool = True


# ── /ferment — 执行发酵 ──

# [DEPRECATED_GUI] @app.post("/ferment", response_model=FermentResponse)
def ferment(request: FermentRequest):
    """
    Gbrain 发酵 — 执行完整发酵周期

    流程:
      1. 零成本正则扫描 [[wikilink]] 构建概念图谱
      2. 对账 update mention_count
      3. 分层富化: 1次→stub, 3次→基础富化, 8次→完整处理
      4. 追加时间线
    """
    try:
        engine = _get_gbrain_engine()
        report = engine.ferment(full_graph=request.full_graph)
        graph = report.get("graph_stats", {})

        return FermentResponse(
            status="ok",
            timestamp=report["timestamp"],
            graph_stats=graph,
            stubs_created=report["stubs_created"],
            upgrades_basic=report["upgrades_basic"],
            upgrades_full=report["upgrades_full"],
            enriched_basic=report["enriched_basic"],
            enriched_full=report["enriched_full"],
            total_pages=report["total_pages"],
            message=(
                f"发酵完成: +{report['stubs_created']} stubs, "
                f"↑{report['upgrades_basic']} basic, "
                f"↑{report['upgrades_full']} full, "
                f"总计 {report['total_pages']} 概念页"
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发酵失败: {str(e)}")


# ── /concept/{name} — 查询概念页 ──

# [DEPRECATED_GUI] @app.get("/concept/{concept_name}")
def get_concept(concept_name: str):
    """
    查询单个概念的完整页面 — CompiledTruth + 时间线 + 关联概念
    """
    try:
        engine = _get_gbrain_engine()
        page = engine.get_concept_page(concept_name)
        if page is None:
            # 尝试模糊搜索
            results = engine.search_concepts(concept_name, top_k=1)
            if results:
                page = results[0]
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"概念 '{concept_name}' 未找到",
                )
        return {
            "status": "ok",
            "page": page,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


# ── /concept/{name}/timeline — 概念时间线 ──

# [DEPRECATED_GUI] @app.get("/concept/{concept_name}/timeline")
def get_concept_timeline(concept_name: str):
    """
    获取概念的证据时间线 (只追加，不修改)
    """
    try:
        engine = _get_gbrain_engine()
        timeline = engine.get_timeline(concept_name)
        if timeline is None:
            raise HTTPException(
                status_code=404,
                detail=f"概念 '{concept_name}' 未找到",
            )
        return {
            "status": "ok",
            "concept_name": concept_name,
            "timeline": timeline,
            "total_events": len(timeline),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


# ── /concepts/search — 搜索概念 ──

# [DEPRECATED_GUI] @app.post("/concepts/search")
def search_concepts(request: ConceptSearchRequest):
    """
    模糊搜索概念 (匹配 concept_id 或 concept_name)
    """
    try:
        engine = _get_gbrain_engine()
        results = engine.search_concepts(request.query, top_k=request.top_k)
        return {
            "status": "ok",
            "query": request.query,
            "results": results,
            "total": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


# ── /gbrain/queue — 待富化队列 ──

# [DEPRECATED_GUI] @app.get("/gbrain/queue")
def get_enrichment_queue():
    """
    获取待富化概念队列 (needs_review=True)
    """
    try:
        engine = _get_gbrain_engine()
        queue = engine.get_enrichment_queue()
        return {
            "status": "ok",
            "queue": queue,
            "total": len(queue),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


# ── /gbrain/stats — 图谱统计 ──

# [DEPRECATED_GUI] @app.get("/gbrain/stats")
def get_gbrain_stats():
    """
    获取 Gbrain 概念图谱统计
    """
    try:
        engine = _get_gbrain_engine()
        all_pages = engine.store.get_all()
        
        stubs = len([p for p in all_pages.values() if p.is_stub])
        basics = len([p for p in all_pages.values() if p.enrichment_level == 1])
        fulls = len([p for p in all_pages.values() if p.is_full])
        
        mention_counts = [p.mention_count for p in all_pages.values()]
        
        return {
            "status": "ok",
            "total_concepts": len(all_pages),
            "distribution": {
                "stubs": stubs,
                "basic": basics,
                "full": fulls,
            },
            "total_mentions": sum(mention_counts),
            "max_mentions": max(mention_counts) if mention_counts else 0,
            "avg_mentions": round(sum(mention_counts) / max(1, len(mention_counts)), 1),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计失败: {str(e)}")


# ── /gbrain/daily — 发酵日报 ──

# [DEPRECATED_GUI] @app.post("/gbrain/daily")
def generate_daily_report():
    """
    生成发酵日报 - 汇总概念图谱状态 + TOP 概念 + 学习轨迹
    """
    try:
        agent = _get_nightly_agent()
        report = agent.generate_daily_report()
        return {
            "status": "ok",
            "report": report,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"日报生成失败: {str(e)}")


# ── /gbrain/nightly — 触发夜间维护 ──

# [DEPRECATED_GUI] @app.post("/gbrain/nightly")
def trigger_nightly():
    """
    手动触发夜间维护任务 (发酵 + 清理 + git commit)
    """
    try:
        agent = _get_nightly_agent()
        # [DEPRECATED_GUI] result = agent.run(full_graph=True, quiet=True)
        return {
            "status": "ok",
            "result": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"夜间维护失败: {str(e)}")
