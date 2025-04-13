# consistency_checker.py
# -*- coding: utf-8 -*-
import os
import logging
import re
import datetime  # 添加 datetime 导入
from llm_adapters import create_llm_adapter
from novel_generator.common import invoke_with_cleaning
from prompt_definitions import Chapter_Review_prompt
from chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.volume import extract_volume_outline

def extract_recent_plot_arcs(filepath: str, max_chars: int = 2000) -> str:
    """提取最近的剧情要点"""
    try:
        plot_arcs_file = os.path.join(filepath, "plot_arcs.txt")
        if not os.path.exists(plot_arcs_file):
            return ""
            
        with open(plot_arcs_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        if not content:
            return ""
            
        # 分割内容为条目
        entries = content.split("\n=== ")
        valid_entries = []
        
        # 从后向前处理条目
        current_length = 0
        for entry in reversed(entries):
            if not entry.strip():
                continue
                
            # 只保留包含关键信息的条目
            if any(key in entry for key in ["章审校", "核心功能", "伏笔设计", "颠覆指数", "[关键问题]"]):
                entry_text = f"=== {entry}" if not entry.startswith("===") else entry
                entry_length = len(entry_text)
                
                if current_length + entry_length <= max_chars:
                    valid_entries.insert(0, entry_text)
                    current_length += entry_length
                else:
                    break
                    
        return "\n".join(valid_entries)
    except Exception as e:
        logging.error(f"提取剧情要点时出错: {str(e)}")
        return ""

def check_consistency(
    character_state: str,
    global_summary: str, 
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    interface_format: str,
    max_tokens: int,
    timeout: int,
    filepath: str = "",
    novel_number: int = 1,
    Review_text: str = ""  # 添加新参数，直接接收主界面编辑框内容
) -> str:
    """检查章节内容与已有设定的一致性"""
    
    logging.info("=== 开始一致性审校 ===")
    logging.info(f"开始校验第{novel_number}章内容...")

    try:
        # 检查传入的文本内容
        if not Review_text or not Review_text.strip():
            msg = "错误：当前编辑框内容为空，无法进行一致性审校"
            logging.warning(msg)
            return msg

        # 获取章节信息
        directory_file = os.path.join(filepath, "Novel_directory.txt")
        chapter_title = f"第{novel_number}章"
        chapter_info = {
            'chapter_role': '常规章节',
            'chapter_purpose': '推进主线',
            'suspense_type': '信息差型',
            'emotion_evolution': '焦虑→震惊→坚定',
            'foreshadowing': '1.新埋设.无',
            'plot_twist_level': 'Lv.1',
            'chapter_summary': ''
        }
        
        if os.path.exists(directory_file):
            with open(directory_file, 'r', encoding='utf-8') as f:
                chapter_info = get_chapter_info_from_blueprint(f.read(), novel_number) or chapter_info
                if 'chapter_title' in chapter_info:
                    chapter_title = chapter_info['chapter_title']

        # 获取分卷大纲
        volume_outline = ""
        if os.path.exists(os.path.join(filepath, "Novel_Volume.txt")):
            with open(os.path.join(filepath, "Novel_Volume.txt"), 'r', encoding='utf-8') as f:
                volume_content = f.read()
                for match in re.finditer(r'第(\d+)卷.*?第(\d+)章.*?第(\d+)章', volume_content):
                    if int(match.group(2)) <= novel_number <= int(match.group(3)):
                        volume_outline = extract_volume_outline(volume_content, int(match.group(1)))
                        break

        # 提取最近的剧情要点
        plot_arcs = extract_recent_plot_arcs(filepath, 2000)

        # 调用 LLM 进行审校
        llm_adapter = create_llm_adapter(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            temperature=temperature,
            interface_format=interface_format,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        prompt = Chapter_Review_prompt.format(
            novel_number=novel_number,
            chapter_title=chapter_title,
            chapter_role=chapter_info['chapter_role'],
            chapter_purpose=chapter_info['chapter_purpose'],
            suspense_type=chapter_info['suspense_type'],
            emotion_evolution=chapter_info['emotion_evolution'],
            foreshadowing=chapter_info['foreshadowing'],
            plot_twist_level=chapter_info['plot_twist_level'],
            chapter_summary=chapter_info['chapter_summary'][:75],
            global_summary=global_summary,
            character_state=character_state,
            volume_outline=volume_outline,
            Review_text=Review_text,  # 使用传入的编辑框内容
            plot_arcs=plot_arcs  # 添加处理后的剧情要点
        )

        logging.info("发送审校请求到LLM...")
        result = invoke_with_cleaning(llm_adapter, prompt)
        
        if result and result.strip():
            logging.info("=== 完成一致性审校 ===")
            
            # 保存审校结果
            try:
                plot_arcs_file = os.path.join(filepath, "plot_arcs.txt")
                with open(plot_arcs_file, 'a', encoding='utf-8') as f:
                    if "无明显冲突" not in result:  # 只有存在冲突时才记录
                        f.write(f"\n=== 第{novel_number}章审校记录 ===\n")
                        f.write(f"审校时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write("发现的问题：\n")
                        
                        # 处理每个冲突条目
                        conflict_lines = []
                        for line in result.split('\n'):
                            if any(key in line for key in ["[冲突", "[伏笔", "[角色", "[大纲"]):
                                # 确保每个条目都有适当的缩进和格式
                                formatted_line = line.strip()
                                if not formatted_line.startswith('-'):
                                    formatted_line = f"- {formatted_line}"
                                conflict_lines.append(formatted_line)
                        
                        if conflict_lines:  # 只有实际有冲突内容时才写入
                            f.write('\n'.join(conflict_lines))
                            f.write("\n\n")  # 添加额外空行作为分隔
            except Exception as e:
                logging.error(f"写入剧情要点文件时出错: {str(e)}")  # 修复括号
            
            return result
            
        return "审校未返回有效结果"
            
    except Exception as e:
        error_msg = f"审校过程出错: {str(e)}"
        logging.error(error_msg)
        return error_msg
