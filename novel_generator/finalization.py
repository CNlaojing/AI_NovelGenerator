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
from novel_generator.common import invoke_with_cleaning, get_chapter_filepath
# from novel_generator.vectorstore_utils import update_vector_store # [DEPRECATED]
from utils import read_file, clear_file_content, save_string_to_txt
from llm_adapters import create_llm_adapter
from embedding_adapters import create_embedding_adapter
from prompt_definitions import summary_prompt, update_character_state_prompt

def finalize_chapter(
    novel_number: int,
    word_number: int,
    llm_config: dict,
    filepath: str,
    embedding_config: dict,
    log_func=None
):
    """
    对指定章节做最终处理：更新前情摘要、更新角色状态、插入向量库等。
    默认无需再做扩写操作，若有需要可在外部调用 enrich_chapter_text 处理后再定稿。
    """
    try:
        logging.info("========== 开始章节定稿流程 ==========")
        logging.info(f"正在处理第 {novel_number} 章")
        
        # 使用新的辅助函数获取章节文件路径
        chapter_file = get_chapter_filepath(filepath, novel_number)
        
        if not os.path.exists(chapter_file):
            logging.warning(f"章节文件 {chapter_file} 不存在，无法定稿")
            return
            
        chapter_text = read_file(chapter_file).strip()
        if not chapter_text:
            logging.warning(f"第 {novel_number} 章内容为空，无法定稿")
            return

        # 创建LLM和Embedding适配器
        logging.info("----- 创建 LLM 和 Embedding 适配器 -----")
        llm_adapter = create_llm_adapter(llm_config)
        embedding_adapter = create_embedding_adapter(embedding_config)

        # --- 添加嵌入模型使用日志 ---
        if embedding_adapter and log_func:
            log_func(f"  -> 正在使用嵌入模型: {embedding_config.get('interface_format')} / {embedding_config.get('model_name')}")

        # 1. 更新前情摘要
        logging.info("----- [1/4] 更新前情摘要 -----")
        global_summary_file = os.path.join(filepath, "前情摘要.txt")
        old_global_summary = read_file(global_summary_file)
        prompt_summary = summary_prompt.format(
            chapter_text=chapter_text,
            global_summary=old_global_summary
        )
        if log_func:
            log_func("发送到 LLM 的提示词 (更新前情摘要):\n" + prompt_summary)
        new_global_summary = ""
        from novel_generator.common import invoke_stream_with_cleaning
        for chunk in invoke_stream_with_cleaning(llm_adapter, prompt_summary, log_func=log_func):
            if chunk:
                new_global_summary += chunk
        if new_global_summary.strip():
            save_string_to_txt(new_global_summary, global_summary_file)
            logging.info("前情摘要更新成功")
        else:
            logging.warning("前情摘要生成失败，保持原有内容")

        # 2. 更新角色状态
        logging.info("----- [2/4] 更新角色状态 -----")
        # 获取章节信息
        directory_file = os.path.join(filepath, "章节目录.txt")
        chapter_info = None
        if os.path.exists(directory_file):
            blueprint_text = read_file(directory_file)
            chapter_info = get_chapter_info_from_blueprint(blueprint_text, novel_number)

        character_state_file = os.path.join(filepath, "角色状态.txt")
        try:
            from novel_generator.character_state_updater import update_character_states
            chapter_title = f"第{novel_number}章"
            if chapter_info and chapter_info.get("chapter_title"):
                chapter_title = chapter_info.get("chapter_title")
            
            update_result = update_character_states(
                chapter_text=chapter_text,
                chapter_title=chapter_title,
                chap_num=novel_number,
                filepath=filepath,
                llm_adapter=llm_adapter,
                embedding_adapter=embedding_adapter
            )
            
            if update_result["status"] == "success":
                logging.info("角色状态更新成功")
            else:
                logging.warning(f"角色状态更新失败: {update_result.get('message', '未知错误')}")
        except Exception as e:
            logging.error(f"更新角色状态时出错: {str(e)}")
            logging.error(traceback.format_exc())

        # 3. 处理伏笔内容
        logging.info("----- [3/4] 处理伏笔内容 -----")
        if chapter_info and 'foreshadowing' in chapter_info and chapter_info['foreshadowing'].strip():
            logging.debug(f"发现伏笔内容: {chapter_info['foreshadowing']}")
            from novel_generator.knowledge import process_and_vectorize_foreshadowing
            process_result = process_and_vectorize_foreshadowing(
                chapter_text=chapter_text,
                chapter_info=chapter_info,
                filepath=filepath,
                embedding_adapter=embedding_adapter,
                llm_adapter=llm_adapter,
                log_func=log_func  # 传递日志回调函数
            )
            if process_result.get('status') == 'success':
                logging.info(f"成功处理并向量化伏笔内容: {process_result.get('count', 0)}个伏笔")
            else:
                logging.warning(f"处理伏笔内容时出现问题: {process_result.get('message', '未知错误')}")
        else:
            logging.info("本章节无伏笔内容需要处理")

        # 4. 更新剧情要点
        logging.info("----- [4/4] 更新剧情要点 -----")
        plot_arcs_file = os.path.join(filepath, "剧情要点.txt")
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

            logging.info("剧情要点更新成功")
        except Exception as e:
            logging.error(f"更新剧情要点时出错: {str(e)}")
            logging.error(traceback.format_exc())

        logging.info("========== 章节定稿流程完成 ==========\n")
        
    except Exception as e:
        logging.error(f"章节定稿过程中出现异常: {str(e)}")
        logging.error(traceback.format_exc())

def enrich_chapter_text(
    chapter_text: str,
    word_number: int,
    llm_config: dict
) -> str:
    """
    对章节文本进行扩写，使其更接近 word_number 字数，保持剧情连贯。
    """
    llm_adapter = create_llm_adapter(llm_config)
    prompt = f"""以下章节文本较短，请在保持剧情连贯的前提下进行扩写，使其更充实，接近 {word_number} 字左右：
原内容：
{chapter_text}
"""
    enriched_text = invoke_with_cleaning(llm_adapter, prompt)
    return enriched_text if enriched_text else chapter_text
