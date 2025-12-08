# -*- coding: utf-8 -*-
"""
章节生成模块 - 负责生成章节草稿、处理章节内容、提取伏笔和元数据
"""
import os
import re
import json
import logging
import traceback
import time
import asyncio
import threading
from typing import Dict, List, Tuple, Any, Optional
from .common import invoke_stream_with_cleaning
from prompt_definitions import create_character_prompt  # 添加这行导入
from utils import read_file, save_string_to_txt, clear_file_content
from embedding_adapters import create_embedding_adapter  # 添加这一行导入语句
# from .vectorstore_utils import load_vector_store, get_vectorstore_dir  # [DEPRECATED]
from .character_generator import generate_characters_for_draft  # 添加角色生成函数导入
from .json_utils import load_store # 新增导入

def generate_chapter_draft(
    llm_config: dict,
    embedding_config: dict,
    filepath: str,
    novel_number: int,
    chapter_title: str = "",
    characters_involved: str = "",
    key_items: str = "",
    scene_location: str = "",
    time_constraint: str = "",
    embedding_retrieval_k: int = 4,
    log_func=None
) -> str:
    # 获取当前卷号
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    if not os.path.exists(volume_file):
        raise FileNotFoundError("请先生成分卷大纲(分卷大纲.txt)")
    
    # 读取分卷大纲内容
    volume_content = read_file(volume_file)
    
    # 确定当前章节所属的卷
    volume_number = 1
    for i in range(1, 100):
        pattern = rf"#=== 第{i}卷.*?第(\d+)章 至 第(\d+)章"
        # 使用导入的re模块
        match = re.search(pattern, volume_content)
        if match:
            start_chap = int(match.group(1))
            end_chap = int(match.group(2))
            if start_chap <= novel_number <= end_chap:
                volume_number = i
                break
    
    # 提取当前卷大纲
    from .volume import extract_volume_outline
    volume_outline = extract_volume_outline(volume_content, volume_number)
    """
    生成章节草稿
    
    Args:
        interface_format: LLM接口格式
        api_key: API密钥
        base_url: API基础URL
        llm_model: 语言模型名称
        filepath: 文件保存路径
        novel_number: 章节编号
        chapter_title: 章节标题
        chapter_role: 章节定位
        chapter_purpose: 核心作用
        suspense_type: 悬念类型
        emotion_evolution: 情绪演变
        foreshadowing: 伏笔条目
        plot_twist_level: 颠覆指数
        chapter_summary: 章节简述
        characters_involved: 涉及角色
        key_items: 关键物品
        scene_location: 场景位置
        time_constraint: 时间约束
        temperature: 温度参数
        max_tokens: 最大令牌数
        timeout: 超时时间
        embedding_interface_format: 嵌入接口格式
        embedding_api_key: 嵌入API密钥
        embedding_base_url: 嵌入API基础URL
        embedding_model_name: 嵌入模型名称
        embedding_retrieval_k: 检索K值
        
    Returns:
        生成的章节草稿文本
    """
    from prompt_definitions import chapter_draft_prompt
    from llm_adapters import create_llm_adapter
    
    try:
        # 创建LLM适配器
        llm_adapter = create_llm_adapter(llm_config)
        
        # 创建嵌入适配器
        embedding_adapter = None
        try:
            if embedding_config.get("api_key"):  # 只有在提供了API密钥时才创建嵌入适配器
                embedding_adapter = create_embedding_adapter(embedding_config)
            else:
                logging.warning("未提供嵌入API密钥，将跳过知识检索功能")
        except Exception as e:
            logging.warning(f"创建嵌入适配器失败: {str(e)}，将跳过知识检索功能")
        
        # 获取小说设定
        novel_setting_file = os.path.join(filepath, "小说设定.txt")
        novel_setting = read_file(novel_setting_file)
        
        # 获取角色状态
        character_state_file = os.path.join(filepath, "角色状态.txt")
        character_state = read_file(character_state_file)
        
        # 获取前情摘要
        global_summary_file = os.path.join(filepath, "前情摘要.txt")
        global_summary = read_file(global_summary_file)
        
        # 获取前一章内容（如果存在）
        prev_chapter_content = ""
        if novel_number > 1:
            prev_chapter_file = os.path.join(filepath, "chapters", f"chapter_{novel_number-1}.txt")
            if (os.path.exists(prev_chapter_file)):
                prev_chapter_content = read_file(prev_chapter_file)
        
        # 获取章节目录
        directory_file = os.path.join(filepath, "章节目录.txt")
        directory_content = read_file(directory_file)
        
        # 获取分卷大纲
        volume_file = os.path.join(filepath, "分卷大纲.txt")
        volume_content = read_file(volume_file)
        volume_outline = ""
        if volume_content:
            from .volume import extract_volume_outline
            volume_outline = extract_volume_outline(volume_content, (novel_number - 1) // 160 + 1)
        
        # 解析伏笔 ID 和角色名
        logging.info("8.1 伏笔历史记录提取预处理 - 开始")
        logging.info(f"当前章节编号: {novel_number}, 标题: {chapter_title}")
        
        # 8.1.1 从章节目录中提取当前章节的伏笔条目
        chapter_foreshadowing = ""
        if directory_content:
            # 查找当前章节在章节目录中的伏笔条目
            chapter_pattern = rf"第{novel_number}章\s+{re.escape(chapter_title)}[\s\S]*?伏笔条目：[\s\S]*?(?=颠覆指数：|$)"
            chapter_match = re.search(chapter_pattern, directory_content)
            if (chapter_match):
                chapter_section = chapter_match.group(0)
                # 提取伏笔条目部分
                foreshadowing_section_pattern = r"伏笔条目：[\s\S]*?(?=颠覆指数：|$)"
                foreshadowing_section_match = re.search(foreshadowing_section_pattern, chapter_section)
                if (foreshadowing_section_match):
                    chapter_foreshadowing = foreshadowing_section_match.group(0).replace("伏笔条目：", "").strip()
                    logging.info(f"8.1.1 从章节目录中提取到的伏笔条目: {chapter_foreshadowing}")
                else:
                    logging.warning("8.1.1 未在章节目录中找到伏笔条目部分")
            else:
                logging.warning(f"8.1.1 未在章节目录中找到第{novel_number}章 {chapter_title}")
        else:
            logging.warning("8.1.1 章节目录内容为空")
        
        foreshadowing = "" # Add this line to define the variable
        # 如果从章节目录中提取失败，则使用传入的foreshadowing参数
        if not chapter_foreshadowing and foreshadowing:
            chapter_foreshadowing = foreshadowing
            logging.info(f"8.1.1 使用传入的伏笔条目: {chapter_foreshadowing}")
        
        logging.info(f"8.1.1 当前章节的伏笔条目原始文本: {chapter_foreshadowing}")
        
        # 8.1.2 使用更稳健的方式提取需要检索历史的伏笔ID
        foreshadowing_ids = []
        if chapter_foreshadowing:
            # --- 关键修复：使用 findall 和 set 去重 ---
            # 1. 使用更通用的正则表达式一次性找到所有可能的ID
            raw_ids = re.findall(r'([A-Z]{1,2}F\d+)', chapter_foreshadowing)
            
            # 2. 对提取到的ID列表进行去重，并保持首次出现的顺序
            if raw_ids:
                foreshadowing_ids = sorted(list(set(raw_ids)), key=raw_ids.index)
                logging.info(f"8.1.2 从伏笔条目中提取并去重后的ID: {foreshadowing_ids}")
        
        if foreshadowing_ids:
            logging.info(f"8.1.3 本章需要检索历史的伏笔ID列表: {foreshadowing_ids}")
        else:
            logging.warning("8.1.3 未在本章找到需要检索历史的伏笔ID")

        character_names = [name.strip() for name in characters_involved.split('、') if name.strip()] # 假设以中文顿号分隔
        logging.info(f"分析出当前章节的角色: {character_names}")

        # 准备章节信息字典 - 提前定义，避免后续引用错误
        import json
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
        user_guidance = ""
        genre = ""
        topic = ""
        logging.info("准备获取其他必要参数...")
        
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                    other_params = config_data.get("other_params", {})
                    user_guidance = other_params.get("user_guidance", "")
                    genre = other_params.get("genre", "")
                    topic = other_params.get("topic", "")
            except Exception as e:
                logging.warning(f"读取配置文件失败: {str(e)}，将使用默认值")
                logging.info("由于配置文件读取失败，user_guidance、genre和topic将使用默认空值")           
        
        # 提前定义章节信息字典
        chapter_info = {
            'novel_number': novel_number,
            'chapter_title': chapter_title,
            'genre': genre,
            'volume_count': (novel_number - 1) // 160 + 1,  # 估算卷数
            'num_chapters': 30,  # 默认章节数
            'volume_number': (novel_number - 1) // 160 + 1,  # 估算当前卷号
            'word_number': llm_config.get('max_tokens', 2048),
            'topic': topic,
            'user_guidance': user_guidance,
            'global_summary': global_summary,
            'plot_points': prev_chapter_content,  # 使用前一章内容作为剧情要点
            'volume_outline': volume_outline,
            'knowledge_context': "无相关伏笔历史记录"  # 默认值，后续会更新
        }
        
        # 从JSON文件中检索伏笔历史
        logging.info("8.1.4 准备从JSON文件检索伏笔历史记录...")
        knowledge_context = ""
        
        if foreshadowing_ids:
            try:
                foreshadowing_store = load_store(filepath, "foreshadowing_collection")
                if foreshadowing_store:
                    logging.info(f"开始从JSON文件检索伏笔历史记录，伏笔编号: {foreshadowing_ids}")
                    for fb_id in foreshadowing_ids:
                        fb_data = foreshadowing_store.get(fb_id)
                        if fb_data:
                            entry = f"{fb_data.get('ID', '未知ID')}:\n"
                            entry += f"内容：{fb_data.get('内容', '')}\n"
                            entry += f"伏笔最后章节：{fb_data.get('伏笔最后章节', '未知')}\n\n"
                            knowledge_context += entry
                            logging.info(f"成功检索伏笔 {fb_id} 的历史记录")
                        else:
                            logging.warning(f"在JSON文件中未找到伏笔 {fb_id} 的记录")
                else:
                    logging.warning("伏笔状态JSON文件不存在或为空，无法检索历史记录")
            except Exception as e:
                logging.error(f"从JSON文件检索伏笔历史记录时出错: {str(e)}")
                knowledge_context = f"(从JSON文件检索伏笔历史记录时出错: {str(e)})\n"

        if not knowledge_context:
            knowledge_context = "(未找到相关伏笔历史记录)\n"
    
        # 确保knowledge_context被正确传递
        # 从chapter_info字典中获取knowledge_context，确保伏笔历史记录被正确传递
        knowledge_context = chapter_info.get('knowledge_context', '无相关伏笔历史记录')
        logging.info(f"从chapter_info中获取knowledge_context，长度: {len(knowledge_context)}字节")
        
        # 使用之前创建的嵌入适配器，不需要重复创建
            
        # 生成角色信息
        setting_characters = generate_characters_for_draft(chapter_info, filepath, llm_adapter, embedding_adapter)
        logging.info(f"生成的角色信息长度: {len(setting_characters)}字节")
        
        prompt = build_chapter_prompt(
            novel_setting=novel_setting,
            character_state=character_state,
            global_summary=global_summary,
            prev_chapter_content=prev_chapter_content,
            novel_number=novel_number,
            chapter_title=chapter_title,
            characters_involved=characters_involved, # 保持原有角色名称列表传递，用于其他逻辑
            characters_involved_detail=setting_characters, # 将生成的角色详细信息传递给新的参数
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            knowledge_context=knowledge_context,  # 使用从向量库检索到的伏笔历史记录
            word_number=llm_config.get('max_tokens', 2048),
            volume_outline=volume_outline,
            user_guidance=user_guidance,
            genre=genre,
            topic=topic,
            setting_characters=setting_characters  # 添加生成的角色信息 (这里可能需要调整，暂时保留，因为prompt本身也用到了setting_characters)
        )
        
        # 记录并流式输出提示词
        if log_func:
            log_func("发送到 LLM 的提示词:\n" + prompt)
            log_func("\nLLM 返回内容:")
        else:
            logging.info("\n==================================================\n发送到 LLM 的提示词:\n--------------------------------------------------\n\n" + prompt + "\n--------------------------------------------------")

        # 流式调用LLM
        result = ""
        for chunk in invoke_stream_with_cleaning(llm_adapter, prompt):
            if chunk:
                result += chunk
                if log_func:
                    log_func(chunk, stream=True)
        
        if log_func:
            log_func("\n")

        if not result or not result.strip():
            raise ValueError("LLM返回内容为空")

        # 保存章节草稿
        os.makedirs(os.path.join(filepath, "chapters"), exist_ok=True)
        chapter_file = os.path.join(filepath, "chapters", f"chapter_{novel_number}.txt")
        clear_file_content(chapter_file)
        save_string_to_txt(result, chapter_file)

        return result
        
    except Exception as e:
        error_msg = f"生成章节草稿时出错: {str(e)}\n{traceback.format_exc()}"
        logging.error(error_msg)
        return f"生成章节草稿失败: {str(e)}"

def finalize_chapter(
    llm_config: dict,
    embedding_config: dict,
    filepath: str,
    novel_number: int,
    chapter_draft: str,
    chapter_title: str = "",
    chapter_role: str = "常规章节",
    chapter_purpose: str = "推进主线",
    suspense_type: str = "信息差型",
    emotion_evolution: str = "焦虑-震惊-坚定",
    foreshadowing: str = "",
    plot_twist_level: str = "Lv.2",
    chapter_summary: str = "",
    log_func=None
) -> str:
    """
    完善章节内容
    
    Args:
        interface_format: LLM接口格式
        api_key: API密钥
        base_url: API基础URL
        llm_model: 语言模型名称
        filepath: 文件保存路径
        novel_number: 章节编号
        chapter_draft: 章节草稿
        chapter_title: 章节标题
        chapter_role: 章节定位
        chapter_purpose: 核心作用
        suspense_type: 悬念类型
        emotion_evolution: 情绪演变
        foreshadowing: 伏笔条目
        plot_twist_level: 颠覆指数
        chapter_summary: 章节简述
        temperature: 温度参数
        max_tokens: 最大令牌数
        timeout: 超时时间
        embedding_interface_format: 嵌入接口格式
        embedding_api_key: 嵌入API密钥
        embedding_base_url: 嵌入API基础URL
        embedding_model_name: 嵌入模型名称
        
    Returns:
        完善后的章节内容
    """
    from prompt_definitions import chapter_finalization_prompt
    from llm_adapters import create_llm_adapter
    from embedding_adapters import create_embedding_adapter
    
    try:
        # 创建LLM适配器
        llm_adapter = create_llm_adapter(llm_config)
        
        # 创建嵌入适配器
        embedding_adapter = None
        try:
            if embedding_config.get("api_key"):  # 只有在提供了API密钥时才创建嵌入适配器
                embedding_adapter = create_embedding_adapter(embedding_config)
            else:
                logging.warning("未提供嵌入API密钥，将跳过知识检索功能")
        except Exception as e:
            logging.warning(f"创建嵌入适配器失败: {str(e)}，将跳过知识检索功能")
        
        # 获取角色状态
        character_state_file = os.path.join(filepath, "角色状态.txt")
        character_state = read_file(character_state_file)
        
        # 检查是否存在用户编辑过的定稿提示词文件
        prompt_file = os.path.join(filepath, "定稿的提示词.txt")
        if os.path.exists(prompt_file):
            # 如果存在用户编辑过的提示词文件，直接使用该文件内容作为提示词
            logging.info("使用用户编辑过的定稿提示词文件")
            prompt = read_file(prompt_file)
        else:
            # 如果不存在，则构建默认提示词
            logging.info("构建默认定稿提示词")
            prompt = chapter_finalization_prompt.format(
                chapter_draft=chapter_draft,
                character_state=character_state,
                novel_number=novel_number,
                chapter_title=chapter_title,
                chapter_role=chapter_role,
                chapter_purpose=chapter_purpose,
                suspense_type=suspense_type,
                emotion_evolution=emotion_evolution,
                foreshadowing=foreshadowing,
                plot_twist_level=plot_twist_level,
                chapter_summary=chapter_summary
            )
        
        # 记录并流式输出提示词
        if log_func:
            log_func("发送到 LLM 的定稿提示词:\n" + prompt)
            log_func("\nLLM 返回内容:")
        else:
            logging.info("\n==================================================\n发送到 LLM 的定稿提示词:\n--------------------------------------------------\n\n" + prompt + "\n--------------------------------------------------")
        
        # 流式调用LLM
        finalized_chapter = ""
        for chunk in invoke_stream_with_cleaning(llm_adapter, prompt):
            if chunk:
                finalized_chapter += chunk
                if log_func:
                    log_func(chunk, stream=True)
        
        if log_func:
            log_func("\n")

        # 保存完善后的章节内容
        os.makedirs(os.path.join(filepath, "chapters"), exist_ok=True)
        chapter_file = os.path.join(filepath, "chapters", f"chapter_{novel_number}.txt")
        clear_file_content(chapter_file)
        save_string_to_txt(finalized_chapter, chapter_file)
        
        # [DEPRECATED] 向量库更新和内容处理功能已停用
        # if embedding_adapter:
        #     update_vector_store(embedding_adapter, finalized_chapter, filepath)
        
        # if embedding_adapter:
        #     process_chapter_content(
        #         embedding_adapter=embedding_adapter,
        #         llm_adapter=llm_adapter,
        #         filepath=filepath,
        #         novel_number=novel_number,
        #         chapter_title=chapter_title,
        #         chapter_content=finalized_chapter,
        #         chapter_summary=chapter_summary,
        #         foreshadowing=foreshadowing
        #     )
        
        logging.info(f"成功完善第{novel_number}章《{chapter_title}》内容")
        return finalized_chapter
        
    except Exception as e:
        error_msg = f"完善章节内容时出错: {str(e)}\n{traceback.format_exc()}"
        logging.error(error_msg)
        return f"完善章节内容失败: {str(e)}"

# def update_vector_store(embedding_adapter, chapter_content: str, filepath: str) -> None:
#     """
#     [DEPRECATED] 更新向量库，将章节内容添加到向量库中
#     """
#     logging.warning("`update_vector_store` function is deprecated and no longer used.")
#     return

# def process_chapter_content(
#     embedding_adapter,
#     llm_adapter,
#     filepath: str,
#     novel_number: int,
#     chapter_title: str,
#     chapter_content: str,
#     chapter_summary: str,
#     foreshadowing: str
# ) -> None:
#     """
#     [DEPRECATED] 处理章节内容，提取伏笔和元数据
#     """
#     logging.warning("`process_chapter_content` function is deprecated and no longer used.")
#     return

def extract_chapter_info(directory_content: str, chap_num: int) -> dict:
    """
    从章节目录内容中提取指定章节的信息
    
    Args:
        directory_content: 章节目录文本内容
        chap_num: 章节编号
        
    Returns:
        包含章节信息的字典，包括标题、角色、伏笔等
    """
    try:
        # 匹配章节模式
        pattern = f"第{chap_num}章.*?(?=第{chap_num+1}章|$)"
        chapter_match = re.search(pattern, directory_content, re.DOTALL)
        if not chapter_match:
            return {}
            
        chapter_content = chapter_match.group(0)
        info = {
            "title": "",
            "characters": [],
            "foreshadowing": [],
            "summary": ""
        }
        
        # 提取章节标题
        title_match = re.search(r"第\d+章\s*[:：]\s*(.*?)\n", chapter_content)
        if title_match:
            info["title"] = title_match.group(1).strip()
            
        # 提取章节简述
        summary_match = re.search(r"本章简述[:：]\s*(.*?)\n", chapter_content)
        if summary_match:
            info["summary"] = summary_match.group(1).strip()
            
        # 提取涉及角色
        characters_match = re.search(r"涉及角色[:：]\s*(.*?)\n", chapter_content)
        if characters_match:
            info["characters"] = [c.strip() for c in characters_match.group(1).split(",") if c.strip()]
            
        # 提取伏笔条目
        foreshadowing_match = re.search(r"伏笔条目[:：]\s*(.*?)\n", chapter_content)
        if foreshadowing_match:
            info["foreshadowing"] = [f.strip() for f in foreshadowing_match.group(1).split(";") if f.strip()]
            
        return info
        
    except Exception as e:
        logging.error(f"提取章节信息时出错: {str(e)}")
        return {}

def build_chapter_prompt(chapter_info: dict) -> str:
    """
    使用预先构建的字典格式化章节草稿生成提示词。
    这个函数现在非常简单，因为大部分逻辑已经移到上游处理。
    """
    try:
        from prompt_definitions import chapter_draft_prompt
        # 直接使用传入的字典进行格式化
        return chapter_draft_prompt.format(**chapter_info)
    except KeyError as e:
        logging.error(f"构建章节提示词时缺少必要的键: {e}")
        raise
    except Exception as e:
        logging.error(f"构建章节提示词时发生未知错误: {str(e)}")
        raise
