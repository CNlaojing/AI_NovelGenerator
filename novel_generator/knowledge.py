#novel_generator/knowledge.py
# -*- coding: utf-8 -*-
"""
知识文件导入至向量库（advanced_split_content、import_knowledge_file）
伏笔内容提取与向量化（process_and_vectorize_foreshadowing）
"""
import os
import logging
import re
import json
import traceback
import nltk
import warnings
from utils import read_file
from novel_generator.vectorstore_utils import load_vector_store, update_vector_store
from langchain.docstore.document import Document

# 禁用特定的Torch警告
warnings.filterwarnings('ignore', message='.*Torch was not compiled with flash attention.*')
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def advanced_split_content(content: str, similarity_threshold: float = 0.7, max_length: int = 500) -> list:
    """使用基本分段策略"""
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)
    sentences = nltk.sent_tokenize(content)
    if not sentences:
        return []

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

def import_knowledge_file(
    embedding_api_key: str,
    embedding_url: str,
    embedding_interface_format: str,
    embedding_model_name: str,
    file_path: str,
    filepath: str
):
    """
    导入知识文件到向量库
    
    Args:
        embedding_api_key: 嵌入API密钥
        embedding_url: 嵌入API基础URL
        embedding_interface_format: 嵌入接口格式
        embedding_model_name: 嵌入模型名称
        file_path: 要导入的知识文件路径
        filepath: 向量库保存路径（从UI界面的保存路径输入框获取）
    """
    # 确保filepath不为空
    if not filepath or not filepath.strip():
        logging.warning("向量库保存路径为空，将使用当前工作目录")
        filepath = os.path.join(os.getcwd())
    logging.info(f"开始导入知识库文件: {file_path}, 接口格式: {embedding_interface_format}, 模型: {embedding_model_name}")
    if not os.path.exists(file_path):
        logging.warning(f"知识库文件不存在: {file_path}")
        return
    content = read_file(file_path)
    if not content.strip():
        logging.warning("知识库文件内容为空。")
        return
    paragraphs = advanced_split_content(content)
    from embedding_adapters import create_embedding_adapter
    embedding_adapter = create_embedding_adapter(
        embedding_interface_format,
        embedding_api_key,
        embedding_url if embedding_url else "http://localhost:11434/api",
        embedding_model_name
    )
    # 检查向量库目录是否存在，如果不存在则创建
    vectorstore_dir = os.path.join(filepath, "vectorstore")
    if not os.path.exists(vectorstore_dir):
        logging.info(f"向量库目录不存在，创建目录: {vectorstore_dir}")
        os.makedirs(vectorstore_dir, exist_ok=True)
        
    store = load_vector_store(embedding_adapter, filepath)
    if not store:
        logging.info("Vector store does not exist or load failed. Updating vector store for knowledge import...")
        # Use update_vector_store which handles creation if it doesn't exist
        store = update_vector_store(embedding_adapter, filepath, "knowledge_collection", documents=[Document(page_content=p) for p in paragraphs])
        if store:
            logging.info("知识库文件已成功导入至向量库(新初始化)。")
        else:
            logging.warning("知识库导入失败，跳过。")

def process_and_vectorize_foreshadowing(chapter_text, chapter_info, filepath, embedding_adapter=None, llm_adapter=None):
    """
    从章节文本中提取伏笔内容，并进行向量化存储
    
    Args:
        chapter_text: 章节正文
        chapter_info: 章节信息，包含伏笔条目等
        filepath: 向量库保存路径
        embedding_adapter: 嵌入适配器，从调用方传入
        llm_adapter: LLM适配器，从调用方传入
    
    Returns:
        提取和向量化的结果
    """
    try:
        # 获取章节编号和标题
        chapter_number = chapter_info.get('novel_number', '0')
        chapter_title = chapter_info.get('chapter_title', '')
        logging.info(f"开始处理第{chapter_number}章《{chapter_title}》的伏笔内容")
        
        # 提取伏笔条目
        foreshadowing_items = chapter_info.get("foreshadowing", "")
        if not foreshadowing_items.strip():
            logging.info(f"第{chapter_number}章没有伏笔条目，跳过处理")
            return {"status": "no_foreshadowing"}
        
        # 解析伏笔编号
        foreshadowing_ids = []
        for line in foreshadowing_items.split('\n'):
            # 使用正则表达式提取伏笔编号 (如MF001, SF001, YF001等)
            ids = re.findall(r'([A-Z]F\d{3})', line)
            foreshadowing_ids.extend(ids)
        
        if not foreshadowing_ids:
            logging.info(f"第{chapter_number}章未找到有效的伏笔编号，跳过处理")
            return {"status": "no_valid_ids"}
        
        logging.info(f"提取到的伏笔编号: {', '.join(foreshadowing_ids)}")
        
        # 从向量库中检索伏笔内容
        # 使用传入的 embedding_adapter 参数加载向量库
        
        # 加载伏笔向量库（使用专门的collection_name）
        from novel_generator.vectorstore_utils import load_vector_store
        vector_store = load_vector_store(embedding_adapter, filepath, collection_name="foreshadowing_collection")
        if not vector_store:
            logging.info("伏笔向量库不存在或加载失败，将创建新的伏笔向量库")
            # 这里不直接返回，因为后续会创建新的向量库
        
        # 1. 获取伏笔历史内容
        from prompt_definitions import foreshadowing_history_processing_prompt
        
        # 使用传入的 LLM 适配器
        if not llm_adapter:
            logging.warning("LLM适配器未传入，无法处理伏笔内容")
            return {"status": "llm_adapter_not_provided"}
        
        # 从向量库中检索原始伏笔历史内容
        raw_foreshadowing_history = {}
        for fb_id in foreshadowing_ids:
            try:
                # 使用伏笔ID作为过滤条件检索
                results = vector_store.get(where={"id": fb_id}, include=["metadatas", "documents"])
                if results and results.get('ids'):
                    for i, doc_id in enumerate(results['ids']):
                        metadata = results['metadatas'][i]
                        content = results['documents'][i]
                        raw_foreshadowing_history[fb_id] = content
            except Exception as e:
                logging.warning(f"检索伏笔 {fb_id} 历史内容时出错: {str(e)}")
        
        # 构建伏笔ID列表字符串
        foreshadowing_ids_str = "\n".join([f"- {fb_id}" for fb_id in foreshadowing_ids])
        
        # 构建伏笔历史内容提示词
        history_prompt = foreshadowing_history_processing_prompt.format(
            novel_number=chapter_number,
            chapter_title=chapter_title,
            foreshadowing_ids=foreshadowing_ids_str,
            chapter_text=chapter_text
        )
        
        # 调用LLM处理伏笔历史内容
        from novel_generator.common import invoke_llm
        try:
            # 将原始伏笔历史内容转换为文本格式
            raw_history_text = ""
            for fb_id, content in raw_foreshadowing_history.items():
                raw_history_text += f"{fb_id}\n历史内容：{content}\n\n"
            
            # 将原始伏笔历史内容添加到提示词中
            history_prompt_with_data = history_prompt + "\n\n已检索到的伏笔历史内容：\n" + raw_history_text
            
            # 调用LLM处理
            history_result = invoke_llm(llm_adapter, history_prompt_with_data)
            
            # 解析LLM返回的普通文本结果
            foreshadowing_history = {}
            # 使用正则表达式解析文本格式
            pattern = r'(\w+\d+):\n历史内容：([^\n]+(?:\n(?!\w+\d+:)[^\n]+)*)'
            matches = re.findall(pattern, history_result)
            for fb_id, content in matches:
                foreshadowing_history[fb_id] = content.strip()
            logging.info(f"成功处理伏笔历史内容: {len(foreshadowing_history)}个伏笔")
        except Exception as e:
            logging.warning(f"处理伏笔历史内容失败: {str(e)}，使用原始检索结果")
            # 失败时使用原始检索结果
            foreshadowing_history = raw_foreshadowing_history
        
        # 2. 获取当前章节伏笔内容
        from prompt_definitions import foreshadowing_content_processing_prompt
        
        # 构建伏笔ID列表字符串
        foreshadowing_ids_str = "\n".join([f"- {fb_id}" for fb_id in foreshadowing_ids])
        
        # 构建当前章节伏笔内容提示词
        content_prompt = foreshadowing_content_processing_prompt.format(
            novel_number=chapter_number,
            chapter_title=chapter_title,
            foreshadowing_ids=foreshadowing_ids_str,
            chapter_text=chapter_text
        )
        
        # 调用LLM提取当前章节伏笔内容
        from novel_generator.common import invoke_llm
        try:
            content_result = invoke_llm(llm_adapter, content_prompt)
            # 解析LLM返回的普通文本结果
            current_foreshadowing_content = {}
            # 使用正则表达式解析文本格式
            pattern = r'(\w+\d+):\n本章内容：([^\n]+(?:\n(?!\w+\d+:)[^\n]+)*)'  # 匹配伏笔ID和内容
            matches = re.findall(pattern, content_result)
            for fb_id, content in matches:
                current_foreshadowing_content[fb_id] = content.strip()
            logging.info(f"成功提取当前章节伏笔内容: {len(current_foreshadowing_content)}个伏笔")
        except Exception as e:
            logging.warning(f"提取当前章节伏笔内容失败: {str(e)}，使用备用方案")
            # 备用方案：手动构建当前伏笔内容
            current_foreshadowing_content = {}
            for fb_id in foreshadowing_ids:
                # 从章节信息中提取该伏笔的状态和标题
                fb_state = "未知"
                fb_title = ""
                fb_due_chapter = ""
                for line in foreshadowing_items.split('\n'):
                    if fb_id in line:
                        # 尝试提取状态 (埋设/触发/强化/回收/悬置)
                        states = re.findall(r'-(埋设|触发|强化|回收|悬置)-', line)
                        if states:
                            fb_state = states[0]
                        
                        # 尝试提取标题
                        title_match = re.search(fr'{fb_id}\([^)]+\)-([^-]+)-', line)
                        if title_match:
                            fb_title = title_match.group(1)
                        
                        # 尝试提取回收章节设定
                        due_match = re.search(r'（第(\d+)章前必须回收）', line)
                        if due_match:
                            fb_due_chapter = f"第{due_match.group(1)}章"
                
                # 构建当前伏笔内容
                content = f"伏笔ID: {fb_id}, 状态: {fb_state}, 标题: {fb_title}, 章节: 第{chapter_number}章"
                current_foreshadowing_content[fb_id] = content
        
        # 3. 整合伏笔内容
        from prompt_definitions import foreshadowing_processing_prompt
        
        # 将伏笔历史内容转换为文本格式
        foreshadowing_history_text = ""
        for fb_id, content in foreshadowing_history.items():
            foreshadowing_history_text += f"{fb_id}\n历史内容：{content}\n\n"
        
        # 将当前章节伏笔内容转换为文本格式
        current_foreshadowing_content_text = ""
        for fb_id, content in current_foreshadowing_content.items():
            current_foreshadowing_content_text += f"{fb_id}\n本章内容：{content}\n\n"
        
        # 构建整合提示词
        foreshadowing_prompt = foreshadowing_processing_prompt.format(
            novel_number=chapter_number,
            chapter_title=chapter_title,
            foreshadowing_history=foreshadowing_history_text,
            current_foreshadowing_content=current_foreshadowing_content_text
        )
        
        # 调用LLM整合内容
        from novel_generator.common import invoke_llm
        integrated_content = invoke_llm(llm_adapter, foreshadowing_prompt)
        
        # 解析整合后的内容
        try:
            foreshadowing_data = {}
            # 使用正则表达式解析文本格式，只提取伏笔ID和内容
            pattern = r'(\w+\d+):\n内容：([^\n]+(?:\n(?!\w+\d+:)[^\n]+)*)'
            matches = re.findall(pattern, integrated_content)
            
            for fb_id, content in matches:
                # 简化伏笔数据结构，只保留ID、内容和伏笔最后章节
                foreshadowing_data[fb_id] = {
                    "content": content.strip(),
                    "metadata": {
                        "id": fb_id,
                        "伏笔最后章节": f"第{chapter_number}章"
                    }
                }
            logging.info(f"成功整合伏笔内容: {len(foreshadowing_data)}个伏笔")
        except Exception as e:
            logging.warning(f"解析整合后的伏笔内容失败: {str(e)}")
            # 使用备用方案构建伏笔数据
            foreshadowing_data = {}
            for fb_id in foreshadowing_ids:
                # 简化伏笔数据结构，只保留ID、内容和伏笔最后章节
                content = f"伏笔ID: {fb_id}, 章节: 第{chapter_number}章"
                foreshadowing_data[fb_id] = {
                    "content": content,
                    "metadata": {
                        "id": fb_id,
                        "伏笔最后章节": f"第{chapter_number}章"
                    }
                }
        
        # 修改向量库存储逻辑
        vector_store = load_vector_store(embedding_adapter, filepath, collection_name="foreshadowing_collection")
        if vector_store:
            logging.info("成功加载伏笔向量库，准备更新伏笔内容")
            for fb_id, fb_data in foreshadowing_data.items():
                try:
                    # 使用已整合的伏笔数据
                    content = fb_data["content"]
                    metadata = fb_data["metadata"]

                    # 存储到向量库
                    vector_store.add(
                        documents=[content],
                        metadatas=[metadata],
                        ids=[f"{fb_id}_{chapter_info['novel_number']}"]
                    )
                    logging.info(f"成功向量化伏笔 {fb_id}")

                except Exception as e:
                    logging.error(f"向量化伏笔 {fb_id} 时出错: {str(e)}")
                    continue

        # 在获取foreshadowing_data后，确保向量库已初始化
        if not vector_store and embedding_adapter:
            logging.info("伏笔向量库不存在，创建新的向量库...")
            # 确保向量库目录存在
            vectorstore_dir = os.path.join(filepath, "vectorstore", "foreshadowing_collection")
            os.makedirs(vectorstore_dir, exist_ok=True)
            
            # 创建一个初始文档列表
            documents = []
            metadatas = []
            ids = []
            
            # 将伏笔数据添加到文档列表
            for fb_id, fb_info in foreshadowing_data.items():
                documents.append(fb_info["content"])
                metadatas.append(fb_info["metadata"])
                ids.append(f"{fb_id}_{chapter_info['novel_number']}")
            
            # 初始化新的向量库
            from novel_generator.vectorstore_utils import init_vector_store
            vector_store = init_vector_store(
                embedding_adapter=embedding_adapter,
                texts=documents,
                filepath=filepath,
                collection_name="foreshadowing_collection",
                metadatas=metadatas,
                ids=ids
            )
            if vector_store:
                logging.info("成功创建新的伏笔向量库")
            else:
                logging.error("创建伏笔向量库失败")
                return {"status": "error", "message": "创建伏笔向量库失败"}
        elif vector_store:
            logging.info("伏笔向量库已存在，更新内容...")
            # 更新现有向量库
            for fb_id, fb_info in foreshadowing_data.items():
                try:
                    # 先删除该伏笔的旧数据
                    vector_store.delete(where={"id": fb_id})
                    # 添加新数据
                    vector_store.add(
                        documents=[fb_info["content"]],
                        metadatas=[fb_info["metadata"]],
                        ids=[f"{fb_id}_{chapter_info['novel_number']}"]
                    )
                    logging.info(f"成功更新伏笔 {fb_id} 的向量库数据")
                except Exception as e:
                    logging.error(f"更新伏笔 {fb_id} 的向量库数据时出错: {str(e)}")

        return {
            "status": "success",
            "foreshadowing_data": foreshadowing_data
        }
    
    except Exception as e:
        logging.error(f"处理伏笔内容时发生错误: {str(e)}")
        logging.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

def extract_foreshadow_info(directory_content: str, fb_id: str) -> dict:
    """
    从章节目录文本中提取指定伏笔ID的详细信息
    
    Args:
        directory_content: 章节目录文本内容
        fb_id: 伏笔ID (如 MF001, SF001 等)
    
    Returns:
        包含伏笔信息的字典，包括类型、标题、状态和回收限制等
    """
    try:
        # 查找包含该伏笔ID的行
        pattern = rf'{fb_id}\(([^)]+)\)-([^-]+)-([^-]+)-([^(（]+)(?:（([^)）]+)）)?'
        match = re.search(pattern, directory_content)
        if match:
            return {
                'type': match.group(1).strip(),  # 伏笔类型
                'title': match.group(2).strip(),  # 伏笔标题
                'status': match.group(3).strip(), # 伏笔状态
                'content': match.group(4).strip(), # 伏笔内容
                'due_chapter': re.search(r'第(\d+)章', match.group(5)).group(1) if match.group(5) and re.search(r'第(\d+)章', match.group(5)) else "未知"
            }
        return None
    except Exception as e:
        logging.error(f"提取伏笔信息时出错: {str(e)}")
        return None

def get_foreshadowing_type(fb_id):
    """
    根据伏笔ID获取伏笔类型
    
    Args:
        fb_id: 伏笔ID (如MF001, SF001, YF001等)
    
    Returns:
        伏笔类型描述
    """
    prefix = fb_id[:2] if len(fb_id) >= 2 else ""
    type_map = {
        "MF": "主线伏笔",
        "SF": "支线伏笔",
        "YF": "一般伏笔",
        "AF": "暗线伏笔",
        "CF": "人物伏笔"
    }
    return type_map.get(prefix, "未知类型")

def process_and_vectorize_characters(chapter_text, chapter_info, filepath):
    """
    从章节文本中提取角色信息，并进行向量化存储
    
    Args:
        chapter_text: 章节正文
        chapter_info: 章节信息
        filepath: 向量库保存路径
    
    Returns:
        提取和向量化的结果
    """
    try:
        # 获取章节编号和标题
        chapter_number = chapter_info.get('novel_number', '0')
        chapter_title = chapter_info.get('chapter_title', '')
        logging.info(f"开始处理第{chapter_number}章《{chapter_title}》的角色信息")
        
        # 从向量库中检索角色信息
        from embedding_adapters import get_embedding_adapter
        embedding_adapter = get_embedding_adapter()
        
        # 加载向量库
        vector_store = load_vector_store(embedding_adapter, filepath)
        if not vector_store:
            logging.warning("向量库加载失败，无法处理角色信息")
            return {"status": "vector_store_load_failed"}
        
        # 提取角色信息 (简化版，实际应使用LLM提取)
        # 这里仅作为示例，实际实现可能需要更复杂的逻辑
        character_data = {}
        
        # 更新向量库
        documents = []
        for char_id, char_info in character_data.items():
            doc = Document(
                page_content=char_info["content"],
                metadata=char_info["metadata"]
            )
            documents.append(doc)
        
        if documents:
            update_vector_store(vector_store, documents)
            logging.info(f"成功更新向量库，添加了{len(documents)}个角色文档")
        
        return {
            "status": "success",
            "character_data": character_data
        }
    
    except Exception as e:
        logging.error(f"处理角色信息时发生错误: {str(e)}")
        logging.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}
    else:
        try:
            docs = [Document(page_content=str(p)) for p in paragraphs]
            store.add_documents(docs)
            logging.info("知识库文件已成功导入至向量库(追加模式)。")
        except Exception as e:
            logging.warning(f"知识库导入失败: {e}")
            traceback.print_exc()

def clean_json_response(response_str: str) -> str:
    """
    清理LLM返回的JSON字符串，移除可能存在的Markdown代码块标记
    
    Args:
        response_str: LLM返回的原始字符串
        
    Returns:
        清理后的JSON字符串
    """
    # 移除开头的```json或```标记
    response_str = re.sub(r'^\s*```(?:json)?\s*', '', response_str)
    # 移除结尾的```标记
    response_str = re.sub(r'\s*```\s*$', '', response_str)
    return response_str.strip()

