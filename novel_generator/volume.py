# -*- coding: utf-8 -*-
import os
import logging
from novel_generator.common import invoke_with_cleaning
from llm_adapters import create_llm_adapter
from prompt_definitions import (
    volume_outline_prompt,
    subsequent_volume_prompt,
    final_volume_prompt,
    volume_design_format
)
from utils import read_file, save_string_to_txt, clear_file_content
from novel_generator.vectorstore_utils import load_vector_store
import re

def get_high_weight_characters(filepath: str, llm_adapter, weight_threshold: int = 91) -> str:
    """
    从角色状态向量库中检索权重大于等于指定阈值的所有角色状态
    
    参数:
        filepath: 项目文件路径
        llm_adapter: LLM适配器（用于获取embedding_adapter）
        weight_threshold: 权重阈值，默认为91
    
    返回:
        str: 权重大于等于指定阈值的角色状态内容，如果没有则返回空字符串
    """
    try:
        # 获取embedding_adapter
        embedding_adapter = getattr(llm_adapter, 'embedding_adapter', None)
        if not embedding_adapter:
            logging.warning("无法获取embedding_adapter，返回空的角色状态")
            return ""
        
        # 加载角色状态向量库
        vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
        if not vectorstore:
            logging.warning("角色状态向量库不存在，返回空的角色状态")
            return ""
        
        # 获取所有角色状态文档
        try:
            all_docs = vectorstore.get(where={"type": "character_state"}, include=["metadatas", "documents"])
            if not all_docs or not all_docs.get('ids'):
                logging.info("向量库中没有找到角色状态文档")
                return ""
            
            high_weight_characters = []
            
            # 遍历所有文档，筛选权重大于等于指定阈值的角色
            for i, doc_id in enumerate(all_docs['ids']):
                metadata = all_docs['metadatas'][i]
                document = all_docs['documents'][i]
                
                # 检查权重
                weight = metadata.get('weight', 0)
                base_weight = metadata.get('base_weight', 0)
                
                # 使用weight或base_weight中的较大值
                actual_weight = max(int(weight) if isinstance(weight, (int, str)) and str(weight).isdigit() else 0,
                                  int(base_weight) if isinstance(base_weight, (int, str)) and str(base_weight).isdigit() else 0)
                
                if actual_weight >= weight_threshold:
                    character_name = metadata.get('character_name', metadata.get('name', '未知角色'))
                    logging.info(f"找到高权重角色: {character_name} (权重: {actual_weight})")
                    high_weight_characters.append(document)
            
            if high_weight_characters:
                result = "\n\n".join(high_weight_characters)
                logging.info(f"成功检索到 {len(high_weight_characters)} 个权重≥{weight_threshold}的角色状态")
                return result
            else:
                logging.info(f"没有找到权重大于等于{weight_threshold}的角色")
                return ""
                
        except Exception as e:
            logging.error(f"检索角色状态时出错: {e}")
            return ""
            
    except Exception as e:
        logging.error(f"获取高权重角色状态时出错: {e}")
        return ""

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
    start_from_volume: int = None,
    generate_single: bool = False,
    num_characters: int = 8,
    character_prompt: str = "",
    genre: str = ""  # 添加 genre 参数，默认值为空值
) -> str:
    """
    生成分卷大纲，兼容原版分卷文件名和内容格式
    """
    logging.info(f"开始生成小说分卷，计划分为{volume_count}卷...")
    # 分卷文件名与原版保持一致
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    novel_setting_file = os.path.join(filepath, "小说设定.txt")
    if not os.path.exists(novel_setting_file):
        raise FileNotFoundError("请先生成小说架构(小说设定.txt)")
    novel_setting = read_file(novel_setting_file)
    character_state = ""
    character_state_file = os.path.join(filepath, "角色状态.txt")
    if os.path.exists(character_state_file):
        character_state = read_file(character_state_file)
    # 检查现有分卷内容
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
    end_volume = current_volume + 1 if generate_single else volume_count
    for i in range(current_volume, end_volume):
        try:
            logging.info(f"生成第{i+1}卷大纲...")
            start_chap, end_chap = volume_chapters[i]
            # 构造提示词
            if i == 0:
                # 如果提供了角色提示词，则生成角色
                setting_characters = ""
                if character_prompt and num_characters > 0:
                    logging.info(f"生成{num_characters}个主要角色...")
                    # 尝试从novel_setting中提取genre信息
                    genre = "奇幻"  # 默认值
                    if "类型：" in novel_setting:
                        genre_match = re.search(r"类型：([^\n]+)", novel_setting)
                        if genre_match:
                            genre = genre_match.group(1).strip()
                    
                    # 创建角色生成提示词
                    char_prompt = character_prompt.format(
                        genre=genre,
                        volume_count=volume_count,
                        num_chapters=number_of_chapters,
                        word_number=word_number,
                        topic=topic,
                        user_guidance=user_guidance,
                        novel_setting=novel_setting,
                        num_characters=num_characters
                    )
                    # 生成角色
                    setting_characters = invoke_with_cleaning(llm_adapter, char_prompt)
                    logging.info("角色生成完成")
                
                prompt = volume_outline_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    novel_setting=novel_setting,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    setting_characters=setting_characters,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    volume_number=i+1,  # 添加 volume_number 参数
                    genre=genre,  # 添加 genre 参数
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
                    Total_volume_number=volume_count,
                    volume_number=i+1,
                    genre=genre,
                    volume_design_format=volume_design_format,
                    x=start_chap
                )
            else:
                # 从角色状态向量库中检索权重大于等于91的角色状态
                setting_characters = get_high_weight_characters(filepath, llm_adapter)
                
                prompt = subsequent_volume_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    novel_setting=novel_setting,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    previous_volume_outline=previous_outline,
                    setting_characters=setting_characters,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    volume_number=i+1,
                    genre=genre,
                    volume_design_format=volume_design_format,
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
            if volume_outlines:
                current_content = "\n\n".join(volume_outlines) + "\n"
                clear_file_content(volume_file)
                save_string_to_txt(current_content, volume_file)
            raise
    return "\n\n".join(volume_outlines) + "\n"

def get_current_volume_info(filepath: str, volume_count: int) -> tuple:
    """
    获取当前分卷信息，返回(当前卷数, 总卷数, 剩余待生成卷数)
    """
    current_volume = 0
    volume_file = os.path.join(filepath, "分卷大纲.txt")
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
    """
    从完整的分卷大纲中提取指定卷的内容
    """
    try:
        pattern = rf"#=== 第{volume_number}卷.*?(?=#=== 第\d+卷|$)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(0).strip()
        return ""
    except Exception as e:
        logging.error(f"提取分卷大纲时出错: {str(e)}")
        return ""
