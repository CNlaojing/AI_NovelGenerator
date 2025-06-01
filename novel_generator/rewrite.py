# novel_generator/rewrite.py
# -*- coding: utf-8 -*-
"""
伏笔内容处理模块，用于章节草稿生成前的准备工作
"""
import os
import re
import logging
from typing import Dict, List, Tuple

from llm_adapters import create_llm_adapter
from utils import read_file
from prompt_definitions import chapter_rewrite_prompt # 移除 foreshadowing_extraction_prompt
from novel_generator.common import invoke_with_cleaning
from novel_generator.vectorstore_utils import get_relevant_context_from_vector_store


def extract_chapter_foreshadowing(blueprint_text: str, chapter_number: int) -> str:
    """
    从章节目录中提取指定章节的伏笔条目内容，优化提取逻辑
    """
    try:
        chapter_pattern = f"第{chapter_number}章.*?(?=第{chapter_number+1}章|$)"
        chapter_match = re.search(chapter_pattern, blueprint_text, re.DOTALL)
        if not chapter_match:
            logging.warning(f"无法在章节目录中找到第{chapter_number}章")
            return "无"
            
        chapter_content = chapter_match.group(0)
        foreshadow_lines = []
        in_foreshadow = False
        
        for line in chapter_content.splitlines():
            line = line.strip()
            if '├─伏笔条目：' in line:
                in_foreshadow = True
                continue
            
            if in_foreshadow:
                if line.startswith('├─') or line.startswith('└─'):
                    if '伏笔' not in line:
                        break
                elif line.startswith('│'):
                    line = line.lstrip('│├└─ ')
                    if line and ('-' in line):
                        foreshadow_lines.append(line)

        return '\n'.join(foreshadow_lines) if foreshadow_lines else "无"
            
    except Exception as e:
        logging.error(f"提取章节伏笔信息时出错: {str(e)}")
        return "无"


def parse_foreshadowing(foreshadowing: str) -> List[Dict]:
    """
    解析伏笔条目内容，提取伏笔ID、类型、标题和状态
    """
    foreshadows = []
    
    for line in foreshadowing.split('\n'):
        if '-' in line:
            # 匹配伏笔ID和类型
            id_type_match = re.search(r'([A-Z]F\d{3})\(([^)]+)\)', line)
            if not id_type_match:
                continue
                
            fid = id_type_match.group(1)
            f_type = id_type_match.group(2)
            
            # 分割伏笔内容
            parts = line.split('-')
            if len(parts) < 3:
                continue
                
            title = parts[1].strip()
            status = parts[2].strip()
            
            foreshadows.append({
                'id': fid,
                'type': f_type,
                'title': title,
                'status': status
            })
    
    return foreshadows


def get_foreshadowing_history(filepath: str, foreshadowing: str) -> List[Dict]:
    """
    获取伏笔历史状态记录
    """
    try:
        foreshadow_dict = {}
        state_file = os.path.join(filepath, "伏笔状态.txt")
        if not os.path.exists(state_file):
            logging.warning("伏笔状态文件不存在")
            return []
            
        state_content = read_file(state_file)
        current_fid = None
        
        # 先解析当前章节的伏笔
        for line in foreshadowing.split('\n'):
            if '-' in line:
                fid_match = re.search(r'([A-Z]F\d{3})', line)
                if fid_match:
                    fid = fid_match.group(1)
                    parts = line.split('-')
                    if len(parts) >= 3:
                        title = parts[1].strip()
                        logging.info(f"解析到伏笔[{fid}]: {title}")
                        foreshadow_dict[fid] = {
                            'title': title,
                            'history': []
                        }
        
        # 从状态文件中找出历史记录
        for line in state_content.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('〇'):
                fid_match = re.search(r'〇([A-Z]F\d{3})', line)
                if fid_match:
                    current_fid = fid_match.group(1)
                    if current_fid in foreshadow_dict:
                        deadline_match = re.search(r'（第(\d+)章前必须回收）', line)
                        if deadline_match:
                            foreshadow_dict[current_fid]['deadline'] = int(deadline_match.group(1))
            elif line.startswith('-') and current_fid in foreshadow_dict:
                state_match = re.match(r'- (.*?)：第(\d+)章', line)
                if state_match:
                    foreshadow_dict[current_fid]['history'].append({
                        'status': state_match.group(1),
                        'chapter': int(state_match.group(2))
                    })
                    
        return foreshadow_dict
        
    except Exception as e:
        logging.error(f"获取伏笔历史状态时出错: {str(e)}")
        return {}


def get_foreshadowing_deadline(fid: str, state_content: str) -> int:
    """
    从伏笔状态文件中获取指定伏笔ID的回收期限
    """
    for line in state_content.split('\n'):
        if fid in line and '（第' in line and '章前必须回收）' in line:
            deadline_match = re.search(r'（第(\d+)章前必须回收）', line)
            if deadline_match:
                return int(deadline_match.group(1))
    return 0


def get_foreshadowing_title(fid: str, state_content: str) -> str:
    """
    从伏笔状态文件中获取指定伏笔ID的标题
    """
    for line in state_content.split('\n'):
        if fid in line and '：' in line and '（第' in line:
            title_match = re.search(r'：(.+?)（', line)
            if title_match:
                return title_match.group(1).strip()
    return ""


def process_foreshadowing_context(
    api_key: str,
    base_url: str,
    model_name: str,
    interface_format: str,
    embedding_adapter,
    filepath: str,
    chapter_number: int,
    chapter_title: str,
    foreshadowing: str,
    max_tokens: int = 2048,
    timeout: int = 600
) -> str:
    """处理伏笔内容，生成用于章节草稿的伏笔上下文"""
    try:
        if not foreshadowing or foreshadowing == "无":
            logging.info("未找到当前章节伏笔内容")
            return "（无相关伏笔记录）"

        # 1. 解析当前章节的伏笔信息
        logging.info(f"解析当前章节伏笔信息：\n{foreshadowing}")
        foreshadows = parse_foreshadowing(foreshadowing)
        if not foreshadows:
            logging.warning("未找到有效伏笔条目")
            return "（未找到有效伏笔条目）"

        # 2. 读取伏笔状态文件获取预设状态
        state_file = os.path.join(filepath, "伏笔状态.txt")
        state_content = read_file(state_file)
        if not state_content:
            logging.warning("伏笔状态文件为空")
            return "（伏笔状态文件为空）"

        # 3. 解析伏笔状态
        historical_results = []
        for foreshadow in foreshadows:
            fid = foreshadow['id']
            status = foreshadow['status']
            
            if status != '埋设':  # 跳过新埋设的伏笔
                # 从伏笔状态文件中查找对应伏笔
                title = get_foreshadowing_title(fid, state_content)
                deadline = get_foreshadowing_deadline(fid, state_content)
                
                if not title:
                    logging.warning(f"未找到伏笔[{fid}]的历史状态")
                    continue
                    
                logging.info(f"已找到伏笔[{fid}]的历史状态：标题[{title}], 期限[第{deadline}章]")
                
                # 4. 根据伏笔标题检索向量库
                logging.info(f"开始检索伏笔[{fid}]的历史内容...")
                retrieved_texts = get_relevant_context_from_vector_store(
                    embedding_adapter=embedding_adapter,
                    query=title,  # 使用伏笔标题作为检索关键词
                    filepath=filepath,
                    k=1
                )
                
                if retrieved_texts:
                    content = retrieved_texts[0][:400]
                    logging.info(f"检索到伏笔[{fid}]的历史内容: {content[:100]}...")
                    historical_results.append({
                        'id': fid,
                        'type': foreshadow['type'],
                        'title': title,
                        'deadline': deadline,
                        'status': status,
                        'history': content
                    })
                else:
                    logging.info(f"未检索到伏笔[{fid}]的历史内容")
            else:
                logging.info(f"跳过新埋设的伏笔[{fid}]")

        # 5. 格式化历史伏笔内容
        if not historical_results:
            logging.info("没有找到任何有效的历史伏笔记录")
            return "（无相关历史伏笔记录）"
            
        # 按照知识库格式要求格式化内容
        state_lines = []
        for result in historical_results:
            # 格式：编号(类型)-标题-（第X章前必须回收）
            state_lines.append(f"{result['id']}({result['type']})-{result['title']}-（第{result['deadline']}章前必须回收）")
            # 格式：-状态（章节）：历史内容
            state_lines.append(f"-{result['status']}（第{chapter_number-1}章）：{result['history']}")
            
        foreshadowing_state_knowledge = "\n".join(state_lines)
        logging.info("完成伏笔历史内容格式化")

        # 6. 使用LLM精简内容
        logging.info("开始使用LLM精简伏笔内容...")
        llm_adapter = create_llm_adapter(
            interface_format=interface_format,
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            temperature=0.3,
            max_tokens=max_tokens,
            timeout=timeout
        )

    except Exception as e:
        logging.error(f"处理伏笔内容时出错: {str(e)}")
        return f"（处理伏笔内容出错: {str(e)}）"


def get_foreshadow_type(fid: str) -> str:
    """根据伏笔ID获取类型名称"""
    type_map = {
        'MF': '主线伏笔',
        'SF': '支线伏笔',
        'AF': '暗线伏笔',
        'CF': '人物伏笔',
        'YF': '一般伏笔'
    }
    prefix = fid[:2]
    return type_map.get(prefix, '未知类型')


def rewrite_chapter(current_text: str, filepath: str, novel_number: int, **kwargs) -> str:
    """改写章节内容"""
    try:
        # 1. 获取伏笔信息
        # blueprint_text (章节目录) 是必需的，以便 extract_chapter_foreshadowing 工作
        blueprint_file_path = os.path.join(filepath, "章节目录.txt")
        blueprint_text = read_file(blueprint_file_path)
        if blueprint_text is None:
            logging.warning(f"未能读取章节目录文件: {blueprint_file_path}，伏笔信息将为空。")
            blueprint_text = "" # 提供默认值以避免后续错误
        
        # extract_chapter_foreshadowing 在当前文件中定义
        foreshadowing_details = extract_chapter_foreshadowing(blueprint_text, novel_number)
        
        # 2. 获取重写所需的知识库内容过滤 (相关背景资料)
        # process_knowledge_context 在当前文件中定义
        relevant_context = process_knowledge_context(
            filepath,
            current_text,
            embedding_interface_format=kwargs.get("embedding_interface_format", "OpenAI"),
            embedding_api_key=kwargs.get("embedding_api_key", ""),
            embedding_base_url=kwargs.get("embedding_base_url", "https://api.openai.com/v1"),
            embedding_model_name=kwargs.get("embedding_model_name", "text-embedding-ada-002")
        )
        
        # 3. 使用传入的提示词
        # current_text 是从UI编辑器传来的完整内容，它已经包含了完整的提示词
        # 不需要再次构建提示词，直接使用current_text作为提示词
        logging.info("使用UI传入的提示词进行改写，不再重复构建提示词")
        prompt_payload = current_text
        
        # 4. 调用LLM进行改写
        llm_adapter = create_llm_adapter(
            interface_format=kwargs.get("interface_format", "OpenAI"),
            base_url=kwargs.get("base_url", "https://api.openai.com/v1"),
            model_name=kwargs.get("model_name", "gpt-4o-mini"), # 注意这里参数名是 model_name
            api_key=kwargs.get("api_key", ""),
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            timeout=kwargs.get("timeout", 600)
        )

        rewritten_text = invoke_with_cleaning(llm_adapter, prompt_payload) # Use default max_retries

        if rewritten_text:
            logging.info(f"章节 {novel_number} 改写成功。")
            return rewritten_text
        else:
            logging.error(f"章节 {novel_number} 改写失败，LLM未返回有效内容。")
            return None
        
    except KeyError as ke:
        logging.error(f"改写章节 {novel_number} 时发生 KeyError: {str(ke)}. kwargs: {kwargs}")
        import traceback
        logging.error(traceback.format_exc())
        return None
    except Exception as e:
        logging.error(f"改写章节 {novel_number} 时发生严重错误: {type(e).__name__} - {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def process_knowledge_context(
    filepath: str,
    text: str,
    embedding_interface_format: str,
    embedding_api_key: str,
    embedding_base_url: str,
    embedding_model_name: str
) -> str:
    """处理知识库内容 - 改写章节时不需要检索向量库"""
    # 根据需求，改写章节时不需要检索向量库，直接返回空字符串
    logging.info("改写章节时不需要检索向量库，跳过知识库内容检索")
    return ""