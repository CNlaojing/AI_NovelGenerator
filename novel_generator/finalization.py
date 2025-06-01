#novel_generator/finalization.py
# -*- coding: utf-8 -*-
"""
章节定稿相关功能
"""
import os
import logging
import traceback
from typing import Dict, List, Any, Optional
import json

from utils import read_file, save_string_to_txt as save
import re
import datetime
from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.common import invoke_with_cleaning
from novel_generator.vectorstore_utils import update_vector_store
from utils import read_file, clear_file_content, save_string_to_txt
from llm_adapters import create_llm_adapter
from embedding_adapters import create_embedding_adapter
from prompt_definitions import summary_prompt, update_character_state_prompt

def finalize_chapter(
    novel_number: int,
    word_number: int,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    filepath: str,
    embedding_api_key: str,
    embedding_url: str,
    embedding_interface_format: str,
    embedding_model_name: str,
    interface_format: str,
    max_tokens: int,
    timeout: int = 600
):
    """
    对指定章节做最终处理：更新前情摘要、更新角色状态、插入向量库等。
    默认无需再做扩写操作，若有需要可在外部调用 enrich_chapter_text 处理后再定稿。
    """
    chapters_dir = os.path.join(filepath, "chapters")
    chapter_file = os.path.join(chapters_dir, f"chapter_{novel_number}.txt")
    chapter_text = read_file(chapter_file).strip()
    if not chapter_text:
        logging.warning(f"Chapter {novel_number} is empty, cannot finalize.")
        return

    # 获取章节信息
    directory_file = os.path.join(filepath, "章节目录.txt")
    chapter_info = None
    if os.path.exists(directory_file):
        blueprint_text = read_file(directory_file)
        chapter_info = get_chapter_info_from_blueprint(blueprint_text, novel_number)

    global_summary_file = os.path.join(filepath, "前情摘要.txt")
    old_global_summary = read_file(global_summary_file)
    character_state_file = os.path.join(filepath, "角色状态.txt")
    old_character_state = read_file(character_state_file)

    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

    # 先更新前情摘要
    prompt_summary = summary_prompt.format(
        chapter_text=chapter_text,
        global_summary=old_global_summary
    )
    new_global_summary = invoke_with_cleaning(llm_adapter, prompt_summary)
    if not new_global_summary.strip():
        new_global_summary = old_global_summary

    # 创建嵌入适配器（提前创建，以便角色状态更新使用）
    embedding_adapter = create_embedding_adapter(
        embedding_interface_format,
        embedding_api_key,
        embedding_url,
        embedding_model_name
    )
    
    # 更新角色状态 - 调用character_state_updater.py中的六步流程
    try:
        # 导入角色状态更新函数
        from novel_generator.character_state_updater import update_character_states
        
        # 获取正确的章节标题
        chapter_title = f"第{novel_number}章"
        if chapter_info and chapter_info.get("chapter_title"):
            chapter_title = chapter_info.get("chapter_title")
        
        # 调用角色状态更新函数
        update_result = update_character_states(
            chapter_text=chapter_text,
            chapter_title=chapter_title,  # 使用从章节目录中获取的正确章节标题
            chap_num=novel_number,
            filepath=filepath,
            llm_adapter=llm_adapter,
            embedding_adapter=embedding_adapter
        )
        
        # 读取最新的角色状态文件内容，因为update_character_states函数会直接更新文件
        new_char_state = read_file(character_state_file)
        
        if not new_char_state or not new_char_state.strip():
            # 如果文件为空，则保持原有内容不变
            new_char_state = old_character_state
            error_msg = update_result.get('message', '未知错误') if update_result else '未知错误'
            logging.warning(f"更新第{novel_number}章角色状态失败: {error_msg}")
        else:
            logging.info(f"成功更新第{novel_number}章的角色状态")
    except Exception as e:
        # 如果出现异常，记录错误并保持原有内容不变
        new_char_state = old_character_state
        logging.error(f"更新第{novel_number}章角色状态时出现异常: {str(e)}")
        logging.error(traceback.format_exc())

    # 更新文件
    clear_file_content(global_summary_file)
    save_string_to_txt(new_global_summary, global_summary_file)

    # 更新剧情要点
    plot_arcs_file = os.path.join(filepath, "剧情要点.txt")
    if not os.path.exists(plot_arcs_file):
        with open(plot_arcs_file, 'w', encoding='utf-8') as f:
            f.write("=== 剧情要点与未解决冲突记录 ===\n")
    
    try:
        # 检查是否已存在当前章节的记录，以避免重复
        existing_content = read_file(plot_arcs_file)
        chapter_marker = f"=== 第{novel_number}章定稿记录 ==="
        if chapter_marker in existing_content:
            logging.warning(f"第{novel_number}章已有定稿记录，跳过剧情要点更新")
            return

        with open(plot_arcs_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{chapter_marker}\n")
            f.write(f"定稿时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            if chapter_info:
                # 添加核心功能和颠覆指数
                f.write(f"核心功能：{chapter_info.get('chapter_purpose', '')}\n")
                f.write(f"颠覆指数：{chapter_info.get('plot_twist_level', '')}\n")
                
                # 获取当前章节在目录中的完整文本
                chapter_pattern = f"第{novel_number}章.*?(?=第{novel_number+1}章|$)"
                chapter_match = re.search(chapter_pattern, blueprint_text, re.DOTALL)
                
                if chapter_match:
                    chapter_text = chapter_match.group(0)
                    # 提取伏笔部分
                    foreshadow_pattern = r"├─伏笔条目：\n((?:│[└├]─.*\n?)*)"
                    foreshadow_match = re.search(foreshadow_pattern, chapter_text, re.DOTALL)
                    
                    f.write("伏笔设计：\n")
                    if foreshadow_match:
                        foreshadow_lines = foreshadow_match.group(1).strip().split('\n')
                        for line in foreshadow_lines:
                            line = line.strip()
                            if line and not line.startswith("伏笔条目"):
                                clean_line = line.replace("│├─", "").replace("│└─", "").strip()
                                # 只保留伏笔相关内容，过滤掉其他格式的行
                                if clean_line and not any(x in clean_line for x in ["颠覆指数", "本章简述"]):
                                    f.write(f"- {clean_line}\n")
                    else:
                        f.write("- 本章无伏笔\n")
                else:
                    f.write("- 本章无伏笔\n")

                # 添加本章简述到剧情要点根级别
                chapter_summary = chapter_info.get('chapter_summary', '')
                if chapter_summary:
                    f.write(f"本章简述：{chapter_summary[:75]}\n")

            else:
                f.write("（未找到章节信息）\n")

            # 更新日志信息
            logging.debug(f"Raw foreshadow content: {chapter_info.get('foreshadow', 'None')}")

    except Exception as e:
        logging.error(f"Error updating plot arcs for Chapter {novel_number}: {str(e)}")

    # 更新向量库
    # 嵌入适配器已在前面创建
    
    # 2. 提取伏笔内容并处理
    if chapter_info and 'foreshadowing' in chapter_info and chapter_info['foreshadowing'].strip():
        # 导入伏笔处理函数
        from novel_generator.knowledge import process_and_vectorize_foreshadowing
        
        # 调用伏笔处理函数，提取伏笔内容并向量化
        process_result = process_and_vectorize_foreshadowing(
            chapter_text=chapter_text,
            chapter_info=chapter_info,
            filepath=filepath,
            embedding_adapter=embedding_adapter,
            llm_adapter=llm_adapter
        )
        
        if process_result.get('status') == 'success':
            logging.info(f"成功处理并向量化第{novel_number}章的伏笔内容")
        else:
            logging.warning(f"处理第{novel_number}章伏笔内容时出现问题: {process_result.get('message', '未知错误')}")
    else:
        # 如果没有伏笔内容，直接更新章节文本到向量库
        logging.info(f"第{novel_number}章没有伏笔内容")
        # 已删除将正文向量添加到向量库的代码

    logging.info(f"Chapter {novel_number} has been finalized.")

def enrich_chapter_text(
    chapter_text: str,
    word_number: int,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    interface_format: str,
    max_tokens: int,
    timeout: int=600
) -> str:
    """
    对章节文本进行扩写，使其更接近 word_number 字数，保持剧情连贯。
    """
    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )
    prompt = f"""以下章节文本较短，请在保持剧情连贯的前提下进行扩写，使其更充实，接近 {word_number} 字左右：
原内容：
{chapter_text}
"""
    enriched_text = invoke_with_cleaning(llm_adapter, prompt)
    return enriched_text if enriched_text else chapter_text

