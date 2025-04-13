# -*- coding: utf-8 -*-
import os
import logging
from novel_generator.common import invoke_with_cleaning
from llm_adapters import create_llm_adapter
from prompt_definitions import (
    volume_outline_prompt,
    subsequent_volume_prompt,
    final_volume_prompt
)
from utils import read_file, save_string_to_txt, clear_file_content
import re

def Novel_volume_generate(
    interface_format: str,
    api_key: str,
    base_url: str,
    llm_model: str,
    topic: str,
    filepath: str,
    number_of_chapters: int,
    word_number: int,
    volume_count: int,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: int = 600,
    user_guidance: str = "",
    characters_involved: str = "",
    start_from_volume: int = None,  # 新增：指定从哪一卷开始生成
    generate_single: bool = False    # 新增：是否仅生成单卷
) -> str:
    """根据小说架构和指定的分卷数生成分卷大纲"""
    logging.info(f"开始生成小说分卷，计划分为{volume_count}卷...")
    
    # 加载必要文件和初始化配置
    novel_setting_file = os.path.join(filepath, "Novel_architecture.txt")
    if not os.path.exists(novel_setting_file):
        raise FileNotFoundError("请先生成小说架构(Novel_architecture.txt)")
    
    novel_setting = read_file(novel_setting_file)
    character_state = ""
    character_state_file = os.path.join(filepath, "character_state.txt")
    if os.path.exists(character_state_file):
        character_state = read_file(character_state_file)

    # 检查现有分卷内容
    volume_file = os.path.join(filepath, "Novel_Volume.txt")
    existing_volume_outlines = []
    current_volume = 0
    
    if os.path.exists(volume_file):
        content = read_file(volume_file)
        if content.strip():
            volumes = content.split("\n\n")
            for vol in volumes:
                if vol.strip().startswith("#=== 第") and "卷" in vol:
                    existing_volume_outlines.append(vol)
                    try:
                        vol_num = int(vol.split("第")[1].split("卷")[0])
                        current_volume = max(current_volume, vol_num)
                    except:
                        pass

    # 设置起始卷数
    if start_from_volume is not None:
        current_volume = start_from_volume - 1
    elif current_volume >= volume_count:
        logging.info("所有分卷已生成完成")
        return read_file(volume_file)

    # 计算章节分布
    chapters_per_volume = number_of_chapters // volume_count
    remaining_chapters = number_of_chapters % volume_count
    volume_chapters = []
    start_chapter = 1
    for i in range(volume_count):
        extra_chapter = 1 if i < remaining_chapters else 0
        end_chapter = start_chapter + chapters_per_volume + extra_chapter - 1
        volume_chapters.append((start_chapter, end_chapter))
        start_chapter = end_chapter + 1

    # 创建 LLM 适配器
    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=llm_model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

    # 生成分卷大纲
    volume_outlines = existing_volume_outlines.copy()
    previous_outline = existing_volume_outlines[-1] if existing_volume_outlines else ""

    # 确定生成范围
    end_volume = current_volume + 1 if generate_single else volume_count

    # 生成指定范围的分卷
    for i in range(current_volume, end_volume):
        try:
            logging.info(f"生成第{i+1}卷大纲...")
            start_chap, end_chap = volume_chapters[i]

            # 构造提示词根据卷号
            if i == 0:
                prompt = volume_outline_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    novel_setting=novel_setting,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    x=start_chap,
                    y=end_chap
                )
            elif i == volume_count - 1:
                prompt = final_volume_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    novel_setting=novel_setting,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    previous_volume_outline=previous_outline,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    x=start_chap
                )
            else:
                prompt = subsequent_volume_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    novel_setting=novel_setting,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    previous_volume_outline=previous_outline,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    volume_number=i+1,
                    x=start_chap,
                    y=end_chap
                )

            outline = invoke_with_cleaning(llm_adapter, prompt)
            if not outline.strip():
                raise Exception(f"第{i+1}卷大纲生成失败")

            volume_title = "终章" if i == volume_count - 1 else ""
            new_volume = f"#=== 第{i+1}卷{volume_title}  第{start_chap}章 至 第{end_chap}章 ===\n{outline}"
            volume_outlines.append(new_volume)
            previous_outline = outline

            # 每生成一卷就保存一次
            current_content = "\n\n".join(volume_outlines) + "\n"
            clear_file_content(volume_file)
            save_string_to_txt(current_content, volume_file)
            logging.info(f"第{i+1}卷大纲已生成并保存")

        except Exception as e:
            logging.error(f"生成第{i+1}卷大纲时出错: {str(e)}")
            # 保存已生成的内容
            if volume_outlines:
                current_content = "\n\n".join(volume_outlines) + "\n"
                clear_file_content(volume_file)
                save_string_to_txt(current_content, volume_file)
            raise
    
    return "\n\n".join(volume_outlines) + "\n"

def get_current_volume_info(filepath: str, volume_count: int) -> tuple:
    """获取当前分卷信息
    返回: (当前卷数, 总卷数, 剩余待生成卷数)
    """
    current_volume = 0
    volume_file = os.path.join(filepath, "Novel_Volume.txt")
    
    if os.path.exists(volume_file):
        content = read_file(volume_file)
        if content.strip():
            volumes = content.split("\n\n")
            for vol in volumes:
                if vol.strip().startswith("#=== 第") and "卷" in vol:
                    try:
                        vol_num = int(vol.split("第")[1].split("卷")[0])
                        current_volume = max(current_volume, vol_num)
                    except:
                        pass
    
    remaining_volumes = volume_count - current_volume
    return current_volume, volume_count, remaining_volumes

def extract_volume_outline(content: str, volume_number: int) -> str:
    """从完整的分卷大纲中提取指定卷的内容"""
    try:
        # 匹配以 #=== 第N卷 开始，到下一个 #=== 第N卷 或文件结尾的内容
        pattern = rf"#=== 第{volume_number}卷.*?(?=#=== 第\d+卷|$)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(0).strip()
        return ""
    except Exception as e:
        logging.error(f"提取分卷大纲时出错: {str(e)}")
        return ""
