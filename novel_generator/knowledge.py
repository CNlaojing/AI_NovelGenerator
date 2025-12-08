#novel_generator/knowledge.py
# -*- coding: utf-8 -*-
"""
知识文件导入至向量库（advanced_split_content、import_knowledge_file）
伏笔内容提取与向量化（process_and_vectorize_foreshadowing）
"""
import os
import re
import json
import traceback
import nltk
import warnings
from utils import read_file
from novel_generator.json_utils import load_store, save_store, save_json_store
from langchain.docstore.document import Document

# 禁用特定的Torch警告
warnings.filterwarnings('ignore', message='.*Torch was not compiled with flash attention.*')
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def process_and_store_foreshadowing(chapter_text, chapter_info, filepath, llm_adapter=None, log_func=None):
    """
    从章节文本中提取伏笔内容，并存储到JSON文件
    
    Args:
        chapter_text: 章节正文
        chapter_info: 章节信息，包含伏笔条目等
        filepath: JSON文件保存路径
        llm_adapter: LLM适配器，从调用方传入
        log_func: 日志记录函数
    
    Returns:
        提取和存储的结果
    """
    # 日志辅助函数
    def _log(message, level="info"): # level is kept for compatibility but not used
        if log_func:
            log_func(message)
        else:
            # Fallback to standard print if no log_func is provided
            print(message)
            
    try:
        # 获取章节编号和标题
        chapter_number = chapter_info.get('novel_number', '0')
        chapter_title = chapter_info.get('chapter_title', '')
        _log(f"开始处理第{chapter_number}章《{chapter_title}》的伏笔内容")
        
        # 提取伏笔条目
        foreshadowing_items = chapter_info.get("foreshadowing", "")
        if not foreshadowing_items.strip():
            _log(f"第{chapter_number}章没有伏笔条目，跳过处理")
            return {"status": "no_foreshadowing"}
        
        # 解析伏笔编号
        foreshadowing_ids = []
        if chapter_info and 'foreshadowing' in chapter_info and chapter_info['foreshadowing']:
            # 简化正则表达式，专注于提取伏笔ID
            entries_pattern = r'([A-Z]F\d{3})\('  # 改为只匹配伏笔ID格式
            foreshadowing_str = chapter_info['foreshadowing']
            # 确保输入是字符串
            if isinstance(foreshadowing_str, (list, tuple)):
                foreshadowing_str = '\n'.join(map(str, foreshadowing_str))
                
            entries_matches = re.finditer(entries_pattern, foreshadowing_str)
            
            # 记录找到的所有伏笔ID
            found_ids = set()
            for match in entries_matches:
                fb_id = match.group(1)
                if fb_id not in found_ids:
                    found_ids.add(fb_id)
                    foreshadowing_ids.append(fb_id)
                    _log(f"提取到伏笔编号: {fb_id}")
            
            if not foreshadowing_ids:
                _log(f"第{chapter_info.get('novel_number', '未知')}章未找到有效的伏笔编号，跳过处理")
                return {"status": "no_valid_foreshadowing"}
            
            _log(f"本章涉及伏笔编号列表：{', '.join(foreshadowing_ids)}")

        # 加载伏笔JSON存储
        foreshadowing_store = load_store(filepath, "foreshadowing_collection")
        
        # 1. 获取伏笔历史内容
        _log("  步骤1: 获取伏笔历史内容...")
        from prompt_definitions import foreshadowing_history_processing_prompt
        
        # 使用传入的 LLM 适配器
        if not llm_adapter:
            _log("LLM适配器未传入，无法处理伏笔内容", level="warning")
            return {"status": "llm_adapter_not_provided"}
        
        # 从JSON存储中检索原始伏笔历史内容
        raw_foreshadowing_history = {}
        if foreshadowing_store:
            _log("    正在从JSON文件检索伏笔历史内容...")
            for fb_id in foreshadowing_ids:
                fb_data = foreshadowing_store.get(fb_id)
                if fb_data and '内容' in fb_data:
                    content = fb_data['内容']
                    raw_foreshadowing_history[fb_id] = content
                    summary = content.split('\n')[0]
                    _log(f"      ✅ 成功检索到伏笔 {fb_id} 的历史: \"{summary}...\"")
                else:
                    _log(f"      ℹ️ 未找到伏笔 {fb_id} 的历史，可能是一个新伏笔。")
        else:
            _log("    伏笔JSON文件不存在，跳过历史内容检索。")
        
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
            if raw_foreshadowing_history:
                for fb_id, content in raw_foreshadowing_history.items():
                    raw_history_text += f"{fb_id}\n历史内容：{content}\n\n"
            else:
                raw_history_text = "无\n"
            
            # 将原始伏笔历史内容添加到提示词中
            history_prompt_with_data = history_prompt + "\n\n已检索到的伏笔历史内容：\n" + raw_history_text
            
            # 调用LLM处理
            _log("    -> 正在调用LLM总结伏笔历史...")
            history_result = invoke_llm(llm_adapter, history_prompt_with_data, log_func=log_func)
            
            # 解析LLM返回的普通文本结果
            foreshadowing_history = {}
            summary_log = []
            pattern = r'(\w+\d+):\n历史内容：([^\n]+)'
            matches = re.findall(pattern, history_result)
            for fb_id, content in matches:
                foreshadowing_history[fb_id] = content.strip()
                summary_log.append(f"{fb_id}: {content.strip().split('。')[0]}...")
            
            if summary_log:
                _log(f"    -> LLM返回的伏笔历史总结:\n---\n" + "\n".join(summary_log) + "\n---")
            else:
                _log(f"    -> LLM返回的伏笔历史总结:\n---\n{history_result}\n---")

            # 使用正则表达式解析文本格式
            pattern = r'(\w+\d+):\n历史内容：([^\n]+(?:\n(?!\w+\d+:)[^\n]+)*)'
            matches = re.findall(pattern, history_result)
            for fb_id, content in matches:
                foreshadowing_history[fb_id] = content.strip()
            _log(f"    成功处理伏笔历史内容: {len(foreshadowing_history)}个伏笔")
        except Exception as e:
            _log(f"    处理伏笔历史内容失败: {str(e)}，使用原始检索结果", level="warning")
            # 失败时使用原始检索结果
            foreshadowing_history = raw_foreshadowing_history
        
        # 2. 获取当前章节伏笔内容
        _log("  步骤2: 获取当前章节伏笔内容...")
        from prompt_definitions import foreshadowing_content_processing_prompt
        
        # 构建伏笔条目字符串，使用完整的伏笔条目信息
        foreshadowing_entries = []
        if chapter_info and 'foreshadowing' in chapter_info and chapter_info['foreshadowing']:
            # 将伏笔条目按行分割
            entries = chapter_info['foreshadowing'].split('\n')
            for entry in entries:
                # 只保留包含伏笔编号和明确是本章需要处理的伏笔条目
                if any(fb_id in entry for fb_id in foreshadowing_ids):
                    foreshadowing_entries.append(entry.strip())
        
        # 合并所有伏笔条目
        foreshadowing_entries_str = "\n".join(foreshadowing_entries)
        
        # 将伏笔历史内容转换为文本格式，以便传递给提示
        foreshadowing_history_text_for_content = ""
        if foreshadowing_history:
            for fb_id, content in foreshadowing_history.items():
                foreshadowing_history_text_for_content += f"{fb_id}:\n历史内容：{content}\n\n"
        else:
            foreshadowing_history_text_for_content = "无历史内容。\n"

        # 构建当前章节伏笔内容提示词
        content_prompt = foreshadowing_content_processing_prompt.format(
            novel_number=chapter_number,
            chapter_title=chapter_title,
            foreshadowing_entries=foreshadowing_entries_str,
            foreshadowing_history=foreshadowing_history_text_for_content,
            chapter_text=chapter_text
        )
        
        # 调用LLM提取当前章节伏笔内容
        from novel_generator.common import invoke_llm
        try:
            _log("    -> 正在调用LLM提取本章伏笔内容...")
            content_result = invoke_llm(llm_adapter, content_prompt, log_func=log_func)
            
            # 解析LLM返回的普通文本结果
            current_foreshadowing_content = {}
            summary_log = []
            pattern = r'(\w+\d+):\n本章内容：([^\n]+)'
            matches = re.findall(pattern, content_result)
            for fb_id, content in matches:
                current_foreshadowing_content[fb_id] = content.strip()
                summary_log.append(f"{fb_id}: {content.strip().split('。')[0]}...")

            if summary_log:
                _log(f"    -> LLM返回的本章伏笔内容:\n---\n" + "\n".join(summary_log) + "\n---")
            else:
                _log(f"    -> LLM返回的本章伏笔内容:\n---\n{content_result}\n---")

            # 使用正则表达式解析文本格式
            pattern = r'(\w+\d+):\n本章内容：([^\n]+(?:\n(?!\w+\d+:)[^\n]+)*)'  # 匹配伏笔ID和内容
            matches = re.findall(pattern, content_result)
            for fb_id, content in matches:
                current_foreshadowing_content[fb_id] = content.strip()
            _log(f"    成功提取当前章节伏笔内容: {len(current_foreshadowing_content)}个伏笔")
        except Exception as e:
            _log(f"    提取当前章节伏笔内容失败: {str(e)}，使用备用方案", level="warning")
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
        _log("  步骤3: 整合伏笔内容...")
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
        _log("    -> 正在调用LLM整合伏笔历史与本章内容...")
        integrated_content = invoke_llm(llm_adapter, foreshadowing_prompt, log_func=log_func)
        
        # 解析整合后的内容
        summary_log = []
        try:
            foreshadowing_data = {}
            # 使用正则表达式解析文本格式，只提取伏笔ID和内容
            pattern = r'(\w+\d+):\n内容：([^\n]+)'
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
                summary_log.append(f"{fb_id}: {content.strip().split('。')[0]}...")

            if summary_log:
                _log(f"    -> LLM返回的最终整合伏笔内容:\n---\n" + "\n".join(summary_log) + "\n---")
            else:
                _log(f"    -> LLM返回的最终整合伏笔内容:\n---\n{integrated_content}\n---")
            _log(f"    成功整合伏笔内容: {len(foreshadowing_data)}个伏笔")
        except Exception as e:
            _log(f"    -> LLM返回的最终整合伏笔内容:\n---\n{integrated_content}\n---")
            _log(f"    解析整合后的伏笔内容失败: {str(e)}", level="warning")
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
        
        # 步骤4: 更新JSON文件
        _log("  步骤4: 更新伏笔状态MD文件...")
        
        # 加载现有的伏笔数据
        foreshadowing_store = load_store(filepath, "foreshadowing_collection")

        # 准备要更新的数据
        for fb_id, fb_info in foreshadowing_data.items():
            foreshadowing_store[fb_id] = {
                "ID": fb_id,
                "内容": fb_info.get("content", ""),
                "伏笔最后章节": fb_info.get("metadata", {}).get("伏笔最后章节", f"第{chapter_number}章")
            }
            _log(f"      -> 准备更新伏笔 {fb_id}...")

        # 保存回JSON文件
        if save_json_store(filepath, "foreshadowing_collection", foreshadowing_store):
            _log("    ✅ 伏笔状态JSON文件更新完毕。")
        else:
            _log("    ❌ 更新伏笔状态JSON文件失败。", level="error")

        return {
            "status": "success",
            "foreshadowing_data": foreshadowing_data
        }
    
    except Exception as e:
        _log(f"处理伏笔内容时发生错误: {str(e)}", level="error")
        _log(traceback.format_exc(), level="error")
        # Re-raise the exception to allow the polling mechanism to catch it
        raise

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
        # No log_func available here, so we print
        print(f"提取伏笔信息时出错: {str(e)}")
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
