"""
AKO_knowledge PDF 入库工具 (简化版)
仅处理 PDF 文件，从 config.json 读取 PDF 文件夹配置
"""
import chromadb
import ollama
import uuid
import os
import sys
import datetime
import time
import io
import fitz

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

from config_loader import get_config

# ==================== 加载配置 ====================
config = get_config()

DB_PATH = config.db_path
PDF_FOLDER = config.pdf_folder
COLLECTION_NAME = config.collection_name
CHUNK_SIZE = config.chunk_size
OVERLAP = config.overlap
BATCH_SIZE = config.batch_size
EMBEDDING_MODEL = config.embedding_model
OCR_LANGUAGES = config.ocr_languages
CHROMA_MODE = config.chroma_mode
CHROMA_HOST = config.chroma_server_host
CHROMA_PORT = config.chroma_server_port

# ==================== 初始化 ====================
if CHROMA_MODE == 'remote':
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    print(f"🔗 远程模式: 连接 {CHROMA_HOST}:{CHROMA_PORT}")
else:
    client = chromadb.PersistentClient(path=DB_PATH)
    print(f"💾 本地模式: {DB_PATH}")

col = client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"}
)


def check_dependencies():
    """检查依赖"""
    errors = []

    # 检查 Ollama 服务
    try:
        ollama.list()
    except Exception as e:
        errors.append(f"Ollama 服务未运行: {e}")

    # 检查 PDF 文件夹
    if not os.path.exists(PDF_FOLDER):
        errors.append(f"PDF 文件夹不存在: {PDF_FOLDER}")

    if errors:
        print("❌ 依赖检查失败:")
        for err in errors:
            print(f"  - {err}")
        return False

    print("✅ 依赖检查通过")
    return True


def embed_batch(texts: list) -> list:
    """批量生成嵌入向量"""
    embeddings = []
    for idx, text in enumerate(texts):
        try:
            safe_text = text[:450]
            if len(text) > 450:
                print(f"  [警告] 文本过长 ({len(text)} 字符),已截断至 450 字符")
            r = ollama.embeddings(model=EMBEDDING_MODEL, prompt=safe_text)
            embeddings.append(r["embedding"])
            if (idx + 1) % 5 == 0:
                time.sleep(0.1)
        except Exception as e:
            print(f"  [错误] 嵌入生成失败: {e}")
            embeddings.append(None)
    return embeddings


def chunk_text_recursive(text: str, chunk_size: int = None, chunk_overlap: int = None):
    """递归式文本分块"""
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = OVERLAP

    if not text or len(text) < 50:
        return []
    if len(text) <= chunk_size:
        return [text]

    separators = [
        '\n\n', '\n', '。', '！', '？', '. ', '! ', '? ',
        '；', '; ', '，', ', ',
    ]

    chunks = _recursive_split(text, chunk_size, chunk_overlap, separators, 0)
    chunks = _merge_small_chunks(chunks, chunk_size * 0.8)
    return chunks


def _recursive_split(text: str, chunk_size: int, chunk_overlap: int,
                     separators: list, level: int) -> list:
    if len(text) <= chunk_size:
        return [text]

    if level >= len(separators):
        return _hard_chunk(text, chunk_size, chunk_overlap)

    separator = separators[level]

    if separator in text:
        parts = text.split(separator)
        chunks = []
        current_chunk = ""

        for part in parts:
            part = part.strip()
            if not part:
                continue
            if current_chunk:
                test_chunk = current_chunk + separator + part
            else:
                test_chunk = part

            if len(test_chunk) > chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = part
            else:
                current_chunk = test_chunk

        if current_chunk:
            chunks.append(current_chunk)

        final_chunks = []
        for chunk in chunks:
            if len(chunk) > chunk_size:
                sub_chunks = _recursive_split(chunk, chunk_size, chunk_overlap,
                                             separators, level + 1)
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)
        return final_chunks
    else:
        return _recursive_split(text, chunk_size, chunk_overlap,
                               separators, level + 1)


def _hard_chunk(text: str, chunk_size: int, chunk_overlap: int) -> list:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - chunk_overlap
    return chunks


def _merge_small_chunks(chunks: list, min_size: float) -> list:
    if not chunks:
        return chunks
    merged = [chunks[0]]
    for i in range(1, len(chunks)):
        if len(merged[-1]) < min_size:
            merged[-1] = merged[-1] + "\n\n" + chunks[i]
        else:
            merged.append(chunks[i])
    return merged


def ocr_image(image_bytes: bytes) -> str:
    """OCR 识别图片文字"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        text = pytesseract.image_to_string(img, lang=OCR_LANGUAGES)
        return text.strip()
    except Exception as e:
        return f"[OCR失败: {e}]"


def extract_pdf(pdf_path: str) -> str:
    """提取 PDF 文字 + OCR 图片"""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  [错误] 无法打开 PDF: {e}")
        return ""

    all_blocks = []
    processed_xrefs = set()

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]

            # 文字提取
            try:
                text = page.get_text()
                if text.strip():
                    all_blocks.append(f"[第{page_num+1}页 文字]\n{text.strip()}")
            except Exception as e:
                print(f"  [警告] 第{page_num+1}页文字提取失败: {e}")

            # 图片 OCR
            try:
                images = page.get_images(full=True)
                for img_index, img in enumerate(images, start=1):
                    xref = img[0]
                    if xref in processed_xrefs:
                        continue
                    processed_xrefs.add(xref)

                    try:
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue
                        ocr_text = ocr_image(base_image["image"])
                        if ocr_text and len(ocr_text) > 10:
                            all_blocks.append(
                                f"[第{page_num+1}页 图{img_index} OCR]\n{ocr_text}"
                            )
                    except Exception as e:
                        print(f"  [警告] 第{page_num+1}页图{img_index} OCR 失败: {e}")
            except Exception as e:
                print(f"  [警告] 第{page_num+1}页图片处理失败: {e}")
    finally:
        doc.close()

    return "\n\n".join(all_blocks)


def iter_pdf_blocks(pdf_path: str):
    """逐页生成 PDF 文本块"""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  [错误] 无法打开 PDF: {e}")
        return

    processed_xrefs = set()
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            try:
                text = page.get_text()
                if text.strip():
                    yield f"[第{page_num+1}页 文字]\n{text.strip()}"
            except Exception as e:
                print(f"  [警告] 第{page_num+1}页文字提取失败: {e}")

            try:
                images = page.get_images(full=True)
                for img_index, img in enumerate(images, start=1):
                    xref = img[0]
                    if xref in processed_xrefs:
                        continue
                    processed_xrefs.add(xref)
                    try:
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue
                        ocr_text = ocr_image(base_image["image"])
                        if ocr_text and len(ocr_text) > 10:
                            yield f"[第{page_num+1}页 图{img_index} OCR]\n{ocr_text}"
                    except Exception as e:
                        print(f"  [警告] 第{page_num+1}页图{img_index} OCR 失败: {e}")
            except Exception as e:
                print(f"  [警告] 第{page_num+1}页图片处理失败: {e}")
    finally:
        doc.close()


def _add_chunks_to_collection(chunks: list, source_name: str, start_index: int,
                              file_type: str, timestamp: str):
    ids = [str(uuid.uuid4()) for _ in chunks]
    embs = embed_batch(chunks)
    valid_data = []
    for emb, doc_text, id_, chunk_index in zip(
        embs, chunks, ids,
        range(start_index, start_index + len(chunks))
    ):
        if emb is not None:
            valid_data.append((emb, doc_text, id_, chunk_index))
    if not valid_data:
        return 0
    valid_embs, valid_docs, valid_ids, valid_indexes = zip(*valid_data)
    meta_list = []
    for doc_text, idx in zip(valid_docs, valid_indexes):
        meta_list.append({
            "source": source_name,
            "type": file_type,
            "chunk_index": idx,
            "timestamp": timestamp,
        })
    col.add(
        embeddings=list(valid_embs),
        documents=list(valid_docs),
        ids=list(valid_ids),
        metadatas=meta_list,
    )
    return len(valid_docs)


def ingest_pdf_file(pdf_path: str, source_name: str, timestamp: str):
    """处理单个 PDF 并入库"""
    print(f"处理: {source_name} ...")

    existing = col.get(where={"source": source_name})
    if existing["ids"]:
        print(f"  [跳过] 已存在 {len(existing['ids'])} 条记录")
        return 0

    file_type = 'pdf'
    total = 0
    chunk_index = 0
    batch = []

    for block in iter_pdf_blocks(pdf_path):
        if not block or len(block.strip()) < 20:
            continue
        chunks = chunk_text_recursive(block)
        if not chunks:
            continue
        for chunk in chunks:
            batch.append(chunk)
            if len(batch) >= BATCH_SIZE:
                total += _add_chunks_to_collection(
                    batch, source_name, chunk_index, file_type, timestamp
                )
                chunk_index += len(batch)
                batch = []

    if batch:
        total += _add_chunks_to_collection(
            batch, source_name, chunk_index, file_type, timestamp
        )
        chunk_index += len(batch)

    if chunk_index == 0:
        print(f"  [跳过] 内容过少")
        return 0

    print(f"  已生成 {chunk_index} 段, 已入库 {total} 条记录")
    return total


def main():
    print("=" * 60)
    print("知识库 PDF 入库工具")
    print("=" * 60)
    print(f"\n{config.get_profile_info()}")
    print("=" * 60)

    if not check_dependencies():
        print("\n请先解决上述依赖问题")
        return

    # 收集 PDF 文件
    if not os.path.exists(PDF_FOLDER):
        print(f"❌ PDF 文件夹不存在: {PDF_FOLDER}")
        return

    pdf_files = [
        (os.path.join(PDF_FOLDER, f), f)
        for f in os.listdir(PDF_FOLDER)
        if f.lower().endswith('.pdf')
    ]

    if not pdf_files:
        print(f"❌ 在 {PDF_FOLDER} 中未发现 PDF 文件")
        return

    print(f"📂 PDF: {len(pdf_files)} 个文件")
    print(f"\n共发现 {len(pdf_files)} 个文件，开始处理...")
    print("=" * 60)

    timestamp = datetime.datetime.now().isoformat()
    total_chunks = 0
    success_count = 0
    skip_count = 0
    error_count = 0

    for idx, (fp, fn) in enumerate(pdf_files, 1):
        print(f"\n[{idx}/{len(pdf_files)}] ", end="")
        try:
            n = ingest_pdf_file(fp, fn, timestamp)
            total_chunks += n
            if n > 0:
                success_count += 1
                print(f"[完成] {fn} → {n} 段")
            else:
                skip_count += 1
                print(f"[跳过] {fn}")
        except Exception as e:
            error_count += 1
            print(f"[错误] {fn} 处理失败: {e}")

    print("\n" + "=" * 60)
    print("全部完成!")
    print(f"  成功: {success_count} 个文件")
    print(f"  跳过: {skip_count} 个文件")
    print(f"  错误: {error_count} 个文件")
    print(f"  共入库 {total_chunks} 段")
    print("=" * 60)


if __name__ == "__main__":
    main()