# scripts/view_vectorstore.py
# -*- coding: utf-8 -*-
import os
import sys
import logging
import traceback

# Add the project root to the sys.path to allow importing project modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from novel_generator.vectorstore_utils import load_vector_store, get_vectorstore_dir
from embedding_adapters import create_embedding_adapter
from config_manager import load_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def view_vectorstore_content(filepath: str, collection_name: str, embedding_config: dict):
    """
    加载指定的向量库并打印其内容。
    """
    logger.info(f"尝试加载向量库: {collection_name} from {filepath}")
    
    try:
        # 创建嵌入适配器
        embedding_adapter = create_embedding_adapter(
            interface_format=last_embedding_format, # Use the format string directly
            api_key=embedding_config.get("api_key"),
            base_url=embedding_config.get("base_url"),
            model_name=embedding_config.get("model_name")
        )
        
        if embedding_adapter is None:
            logger.error("无法创建嵌入适配器，请检查配置。")
            return
            
        # 加载向量库
        vectorstore = load_vector_store(
            embedding_adapter=embedding_adapter,
            filepath=filepath,
            collection_name=collection_name
        )
        
        if vectorstore is None:
            logger.warning(f"未找到或无法加载向量库: {collection_name} at {get_vectorstore_dir(filepath, collection_name)}")
            return
            
        logger.info(f"成功加载向量库: {collection_name}")
        
        # 获取向量库中的文档数量
        try:
            count = vectorstore.count()
            logger.info(f"向量库 '{collection_name}' 包含 {count} 个文档。")
        except Exception as e:
            logger.warning(f"无法获取向量库 '{collection_name}' 的文档数量: {str(e)}")
            logger.debug(traceback.format_exc())

        # 获取并打印所有文档
        # Note: Chroma's get() method can retrieve all documents if no ids or where filters are provided.
        # This might consume significant memory for large vector stores.
        try:
            # Fetch all documents. Limit=None means no limit.
            # You might want to add a limit for very large collections.
            results = vectorstore.get(include=['metadatas', 'documents'])
            
            if not results or not results.get('documents'):
                logger.info("向量库中没有找到文档。")
                return
                
            logger.info(f"找到 {len(results['documents'])} 个文档：")
            for i, doc in enumerate(results['documents']):
                metadata = results['metadatas'][i]
                doc_id = results['ids'][i]
                logger.info(f"\n--- Document {i+1} (ID: {doc_id}) ---")
                logger.info(f"Metadata: {metadata}")
                logger.info(f"Content:\n{doc}")
                logger.info("---")
                
        except Exception as e:
            logger.error(f"获取向量库内容时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            
    except Exception as e:
        logger.error(f"加载或处理向量库时发生未知错误: {str(e)}")
        logger.debug(traceback.format_exc())

if __name__ == "__main__":
    # Load configuration
    config_file = "config.json"
    loaded_config = load_config(config_file)
    
    if not loaded_config:
        logger.error(f"无法加载配置文件: {config_file}")
        sys.exit(1)
        
    # Get filepath from config (assuming it's saved in 'other_params')
    filepath = loaded_config.get("other_params", {}).get("filepath")
    if not filepath:
        logger.error("配置文件中未找到 'filepath' 参数，请先在UI中设置保存路径并保存配置。")
        sys.exit(1)
        
    # Get embedding config from config
    last_embedding_format = loaded_config.get("last_embedding_interface_format", "OpenAI")
    embedding_configs = loaded_config.get("embedding_configs", {})
    embedding_config = embedding_configs.get(last_embedding_format)
    
    if not embedding_config:
         logger.error(f"配置文件中未找到嵌入模型 '{last_embedding_format}' 的配置信息。")
         sys.exit(1)

    # Define the collection name
    collection_name = "foreshadowing_collection"
    
    # Run the function to view the vector store content
    view_vectorstore_content(filepath, collection_name, embedding_config)