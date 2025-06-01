#novel_generator/vectorstore_utils.py
# -*- coding: utf-8 -*-
"""
向量库相关操作（初始化、更新、检索、清空、文本切分等）
"""
import os
import logging
import traceback
import nltk
import numpy as np
import re
import ssl
import requests
import warnings
from langchain_chroma import Chroma
from typing import List, Optional, Dict, Any

# 禁用特定的Torch警告
warnings.filterwarnings('ignore', message='.*Torch was not compiled with flash attention.*')
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # 禁用tokenizer并行警告

from chromadb.config import Settings
from langchain.docstore.document import Document
from sklearn.metrics.pairwise import cosine_similarity
from .common import call_with_retry

def get_vectorstore_dir(filepath: str, collection_name: str = None) -> str:
    """获取 vectorstore 路径
    
    Args:
        filepath: 基础文件路径
        collection_name: 集合名称，如果提供，将创建对应名称的子文件夹
        
    Returns:
        向量库路径
    """
    base_dir = os.path.join(filepath, "vectorstore")
    if collection_name:
        # 创建以collection_name命名的子文件夹
        return os.path.join(base_dir, collection_name)
    return base_dir

def clear_vector_store(filepath: str, collection_name: str = None) -> bool:
    """清空向量库
    
    Args:
        filepath: 向量库保存路径
        collection_name: 集合名称，如果提供，则只清空指定集合的向量库；如果为None，则清空所有向量库
    
    Returns:
        是否成功清空
    """
    import shutil
    store_dir = get_vectorstore_dir(filepath, collection_name)
    if not os.path.exists(store_dir):
        logging.info(f"No vector store found to clear for collection '{collection_name if collection_name else 'all'}'.")
        return False
    try:
        shutil.rmtree(store_dir)
        logging.info(f"Vector store directory '{store_dir}' removed for collection '{collection_name if collection_name else 'all'}'.")
        return True
    except Exception as e:
        logging.error(f"无法删除向量库文件夹，请关闭程序后手动删除 {store_dir}。\n {str(e)}")
        traceback.print_exc()
        return False

def init_vector_store(embedding_adapter, texts: List[str], filepath: str, collection_name: str, metadatas: Optional[List[dict]] = None, ids: Optional[List[str]] = None):
    """初始化向量存储"""
    try:
        import chromadb
        store_dir = get_vectorstore_dir(filepath, collection_name)
        os.makedirs(store_dir, exist_ok=True)
        logging.info(f"正在初始化向量库，保存位置: {store_dir}")

        # 创建 EmbeddingFunction 包装类
        class EmbeddingFunctionWrapper:
            def __init__(self, embedding_adapter):
                self.embedding_adapter = embedding_adapter

            def __call__(self, input: List[str]) -> List[List[float]]:
                return self.embedding_adapter.embed_documents(input)

        # 使用最简单的客户端构造方式
        logging.info("创建 ChromaDB 客户端...")
        chroma_client = chromadb.PersistentClient(
            path=store_dir
        )

        # 处理集合的创建或重置
        try:
            # 尝试获取集合，如果存在则删除以进行重置
            chroma_client.get_collection(name=collection_name) # 检查是否存在
            logging.info(f"找到现有集合: {collection_name}，将重置该集合。")
            chroma_client.delete_collection(name=collection_name) # 如果存在则删除
        except (chromadb.errors.NotFoundError, chromadb.errors.InvalidCollectionException) as e:
            # 如果集合不存在 (NotFoundError 或 InvalidCollectionException 表明不存在)
            if "does not exist" in str(e).lower():
                logging.info(f"未找到现有集合 '{collection_name}'，将创建新集合。详细信息: {e}")
            else:
                # 对于其他类型的 NotFoundError 或 InvalidCollectionException，记录并返回 None
                logging.error(f"检查或删除集合 '{collection_name}' 时发生非预期的 '不存在' 类型错误: {e}")
                traceback.print_exc()
                return None 
        except Exception as e:
            # 捕获在 get_collection 或 delete_collection 期间发生的任何其他意外错误
            logging.error(f"获取或删除现有集合 '{collection_name}' 时发生未知错误: {e}")
            traceback.print_exc()
            return None # 初始化失败

        # 创建新的集合
        # 无论之前是否存在并已删除，还是之前就不存在，都尝试创建
        collection = chroma_client.create_collection(
            name=collection_name,
            embedding_function=EmbeddingFunctionWrapper(embedding_adapter)
        )

        # 添加文档
        if texts:
            # 准备数据
            doc_ids = ids if ids else [f"doc_{i}" for i in range(len(texts))]
            doc_metadatas = metadatas if metadatas else [{"source": "initial"} for _ in texts]
            
            # 分批添加文档，每批100个
            batch_size = 100
            for i in range(0, len(texts), batch_size):
                end_idx = min(i + batch_size, len(texts))
                collection.add(
                    documents=texts[i:end_idx],
                    metadatas=doc_metadatas[i:end_idx],
                    ids=doc_ids[i:end_idx]
                )
                logging.info(f"已添加 {end_idx} 个文档到向量库")

        logging.info(f"向量库 {collection_name} 初始化成功")
        return collection

    except Exception as e:
        logging.error(f"初始化向量库时出错: {str(e)}")
        traceback.print_exc()
        return None

def split_by_length(text: str, max_length: int = 500):
    """按照 max_length 切分文本"""
    segments = []
    start_idx = 0
    while (start_idx < len(text)):
        end_idx = min(start_idx + max_length, len(text))
        segment = text[start_idx:end_idx]
        segments.append(segment.strip())
        start_idx = end_idx
    return segments

def split_text_for_vectorstore(chapter_text: str, max_length: int = 500, similarity_threshold: float = 0.7):
    """
    对新的章节文本进行分段后,再用于存入向量库。
    使用 embedding 进行文本相似度计算。
    """
    if not chapter_text.strip():
        return []
    
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)
    sentences = nltk.sent_tokenize(chapter_text)
    if not sentences:
        return []
    
    # 直接按长度分段,不做相似度合并
    final_segments = []
    current_segment = []
    current_length = 0
    
    for sentence in sentences:
        sentence_length = len(sentence)
        if current_length + sentence_length > max_length:
            if current_segment:
                final_segments.append(" ".join(current_segment))
            current_segment = [sentence]
            current_length = sentence_length
        else:
            current_segment.append(sentence)
            current_length += sentence_length
    
    if current_segment:
        final_segments.append(" ".join(current_segment))
    
    return final_segments

def load_vector_store(embedding_adapter, filepath: str, collection_name: str):
    """加载向量库"""
    try:
        import chromadb
        store_dir = get_vectorstore_dir(filepath, collection_name)
        if not os.path.exists(store_dir):
            logging.info(f"向量库目录不存在: {store_dir}")
            return None

        # 创建包装类
        class EmbeddingFunctionWrapper:
            def __init__(self, embedding_adapter):
                self.embedding_adapter = embedding_adapter

            def __call__(self, input: List[str]) -> List[List[float]]:
                return self.embedding_adapter.embed_documents(input)

        # 使用最简单的客户端构造方式
        logging.info(f"正在加载向量库: {store_dir}")
        chroma_client = chromadb.PersistentClient(
            path=store_dir
        )

        # 尝试获取集合
        try:
            collection = chroma_client.get_collection(
                name=collection_name,
                embedding_function=EmbeddingFunctionWrapper(embedding_adapter)
            )
            logging.info(f"成功加载向量库集合: {collection_name}")
            return collection
        except ValueError as e:
            logging.info(f"集合 {collection_name} 不存在: {str(e)}")
            return None

    except Exception as e:
        logging.error(f"加载向量库失败: {str(e)}")
        traceback.print_exc()
        return None

def update_vector_store(embedding_adapter, new_chapter, filepath: str, collection_name: str):
    """
    将最新章节文本或文档列表插入到向量库中。
    若库不存在则初始化；若初始化/更新失败，则跳过。
    若embedding_adapter为None，则直接返回。
    
    参数:
        embedding_adapter: 嵌入适配器
        new_chapter: 可以是字符串（章节文本）或文档列表
        filepath: 文件路径
        collection_name: 集合名称，必须指定以更新特定的向量库
    """
    if embedding_adapter is None:
        logging.warning("嵌入适配器为None，跳过向量库更新")
        return
    from utils import read_file, clear_file_content, save_string_to_txt
    
    # 检查 new_chapter 是否为列表（文档列表）
    if isinstance(new_chapter, list):
        # 如果是文档列表，直接使用
        docs = new_chapter
    else:
        # 如果是字符串，进行文本分割
        splitted_texts = split_text_for_vectorstore(new_chapter)
        if not splitted_texts:
            logging.warning("No valid text to insert into vector store. Skipping.")
            return
        docs = [Document(page_content=str(t)) for t in splitted_texts]

    store = load_vector_store(embedding_adapter, filepath, collection_name)
    if not store:
        logging.info(f"Vector store for collection '{collection_name}' does not exist or failed to load. Initializing a new one...")
        # 如果是文档列表，我们需要提取文本内容用于初始化
        if isinstance(new_chapter, list):
            texts = [doc.page_content for doc in docs]
            store = init_vector_store(embedding_adapter, texts, filepath, collection_name)
        else:
            # 如果是字符串，使用分割后的文本
            store = init_vector_store(embedding_adapter, splitted_texts, filepath, collection_name)
        
        if not store:
            logging.warning("Init vector store failed, skip embedding.")
        else:
            logging.info("New vector store created successfully.")
        return

    try:
        # 直接使用已准备好的文档列表
        store.add_documents(docs)
        logging.info("Vector store updated successfully.")
    except Exception as e:
        logging.warning(f"Failed to update vector store: {e}")
        traceback.print_exc()

def get_relevant_context_from_vector_store(embedding_adapter, query: str, filepath: str, collection_name: str, k: int = 2) -> str:
    """
    从向量库中检索与 query 最相关的 k 条文本，拼接后返回。
    如果向量库加载/检索失败，则返回空字符串。
    最终只返回最多2000字符的检索片段。
    
    Args:
        embedding_adapter: 嵌入适配器
        query: 查询文本
        filepath: 向量库保存路径
        k: 返回的最相关文本数量
        collection_name: 集合名称，必须指定以查询特定的向量库
    
    Returns:
        拼接后的相关文本
    """
    store = load_vector_store(embedding_adapter, filepath, collection_name)
    if not store:
        logging.info("No vector store found or load failed. Returning empty context.")
        return ""

    try:
        docs = store.similarity_search(query, k=k)
        if not docs:
            logging.info(f"No relevant documents found for query '{query}'. Returning empty context.")
            return ""
        combined = "\n".join([d.page_content for d in docs])
        if len(combined) > 2000:
            combined = combined[:2000]
        return combined
    except Exception as e:
        logging.warning(f"Similarity search failed: {e}")
        traceback.print_exc()
        return ""

def _get_sentence_transformer(model_name: str = 'paraphrase-MiniLM-L6-v2'):
    """获取sentence transformer模型，处理SSL问题"""
    try:
        # 设置torch环境变量
        os.environ["TORCH_ALLOW_TF32_CUBLAS_OVERRIDE"] = "0"
        os.environ["TORCH_CUDNN_V8_API_ENABLED"] = "0"
        
        # 禁用SSL验证
        ssl._create_default_https_context = ssl._create_unverified_context
        
        # ...existing code...
    except Exception as e:
        logging.error(f"Failed to load sentence transformer model: {e}")
        traceback.print_exc()
        return None
