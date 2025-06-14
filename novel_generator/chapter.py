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
from .common import invoke_with_cleaning
from prompt_definitions import create_character_prompt  # 添加这行导入
from utils import read_file, save_string_to_txt, clear_file_content
from embedding_adapters import create_embedding_adapter  # 添加这一行导入语句
from .vectorstore_utils import load_vector_store, get_vectorstore_dir  # 添加向量库工具函数导入
from .character_generator import generate_characters_for_draft  # 添加角色生成函数导入

def generate_chapter_draft(
    interface_format: str,
    api_key: str,
    base_url: str,
    llm_model: str,
    filepath: str,
    novel_number: int,
    chapter_title: str = "",
    chapter_role: str = "常规章节",
    chapter_purpose: str = "推进主线",
    suspense_type: str = "信息差型",
    emotion_evolution: str = "焦虑-震惊-坚定",
    foreshadowing: str = "",
    plot_twist_level: str = "Lv.2",
    chapter_summary: str = "",
    characters_involved: str = "",
    key_items: str = "",
    scene_location: str = "",
    time_constraint: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 600,
    embedding_interface_format: str = "OpenAI",
    embedding_api_key: str = "",
    embedding_base_url: str = "https://api.openai.com/v1",
    embedding_model_name: str = "text-embedding-ada-002",
    embedding_retrieval_k: int = 4
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
        llm_adapter = create_llm_adapter(
            interface_format=interface_format,
            base_url=base_url,
            model_name=llm_model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        # 创建嵌入适配器
        embedding_adapter = None
        try:
            if embedding_api_key:  # 只有在提供了API密钥时才创建嵌入适配器
                embedding_adapter = create_embedding_adapter(
                    interface_format=embedding_interface_format,
                    base_url=embedding_base_url,
                    model_name=embedding_model_name,
                    api_key=embedding_api_key
                )
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
        
        # 如果从章节目录中提取失败，则使用传入的foreshadowing参数
        if not chapter_foreshadowing and foreshadowing:
            chapter_foreshadowing = foreshadowing
            logging.info(f"8.1.1 使用传入的伏笔条目: {chapter_foreshadowing}")
        
        logging.info(f"8.1.1 当前章节的伏笔条目原始文本: {chapter_foreshadowing}")
        
        # 8.1.2 提取完整的伏笔条目
        foreshadowing_entries = []
        if chapter_foreshadowing:
            # 修改正则表达式，严格匹配行首的伏笔条目格式
            entries_pattern = r'^\s*[│├└]*\s*([A-Z]F\d{3})\(([^)]+)\)-([^-]+)-([^-]+)-([^（]+)（([^）]+)）'
            entries_matches = re.findall(entries_pattern, chapter_foreshadowing, re.M)
            
            for match in entries_matches:
                if len(match) >= 6:
                    entry = {
                        "id": match[0],
                        "type": match[1],
                        "operation": match[3],  # 记录伏笔操作(埋设/回收/强化)
                        "title": match[2],
                        "content": match[4],
                        "note": match[5]
                    }
                    foreshadowing_entries.append(entry)
                    logging.info(f"8.1.2 提取到伏笔条目: ID={entry['id']}, 操作={entry['operation']}, 标题={entry['title']}")

        # 8.1.3 从伏笔条目中提取需要检索历史的伏笔ID
        foreshadowing_ids = []
        if foreshadowing_entries:
            # 只收集需要回收、强化、触发、悬置的伏笔ID
            needed_operations = ["回收", "强化", "触发", "悬置"]
            foreshadowing_ids = [
                entry["id"] 
                for entry in foreshadowing_entries 
                if entry["operation"] in needed_operations
            ]
            logging.info(f"8.1.3 本章需要检索历史的伏笔ID: {foreshadowing_ids}")
        else:
            logging.warning("8.1.3 未找到需要检索历史的伏笔ID")

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
            'chapter_role': chapter_role,
            'chapter_purpose': chapter_purpose,
            'suspense_type': suspense_type,
            'emotion_evolution': emotion_evolution,
            'foreshadowing': foreshadowing,
            'plot_twist_level': plot_twist_level,
            'chapter_summary': chapter_summary,
            'genre': genre,
            'volume_count': (novel_number - 1) // 160 + 1,  # 估算卷数
            'num_chapters': 30,  # 默认章节数
            'volume_number': (novel_number - 1) // 160 + 1,  # 估算当前卷号
            'word_number': max_tokens,
            'topic': topic,
            'user_guidance': user_guidance,
            'global_summary': global_summary,
            'plot_points': prev_chapter_content,  # 使用前一章内容作为剧情要点
            'volume_outline': volume_outline,
            'knowledge_context': "无相关伏笔历史记录"  # 默认值，后续会更新
        }
        
        # 从向量库中检索伏笔历史和角色历史状态
        logging.info("8.1.4 准备使用伏笔编号作为元数据，搜索最新一条嵌入向量库的伏笔内容")
        knowledge_context = "无相关伏笔历史记录" # 默认值
        vectorstore = None
        logging.info("8.1.4.1 准备从向量库检索伏笔历史记录...")

        if embedding_adapter:  # 只有在成功创建嵌入适配器时才尝试加载向量库
            logging.info("8.1.5 开始使用已创建的嵌入适配器加载向量库...")
            logging.info(f"8.1.5.1 向量库路径: {filepath}")
            # 检查向量库目录是否存在，不存在则直接返回None而不创建
            store_dir = get_vectorstore_dir(filepath)
            if not os.path.exists(store_dir):
                logging.warning(f"8.1.5.2 向量库目录不存在: {store_dir}，跳过向量库加载")
                logging.info("8.1.5.3 生成草稿阶段不创建向量库，直接使用默认知识上下文")
            else:
                # 使用专门的伏笔向量库（foreshadowing_collection）
                try:
                    vectorstore = load_vector_store(embedding_adapter, filepath, collection_name="foreshadowing_collection")
                    if (vectorstore):
                        logging.info("8.1.5.4 成功加载伏笔向量库，准备检索伏笔历史记录")
                    else:
                        logging.warning("8.1.5.5 加载伏笔向量库失败，无法检索伏笔历史记录")
                        logging.info("8.1.5.6 请确保已经完成定稿，向量化伏笔内容到伏笔向量库")
                except Exception as e:
                    logging.error(f"8.1.5.7 加载伏笔向量库时出错: {str(e)}")
                    logging.info("8.1.5.8 将使用默认知识上下文继续生成章节")

        # 修改伏笔检索逻辑
        if vectorstore and foreshadowing_ids:
            try:
                logging.info(f"开始从向量库检索伏笔历史记录，伏笔编号: {foreshadowing_ids}")
                knowledge_context = ""
                
                for fb_id in foreshadowing_ids:
                    # 使用精确的元数据查询
                    results = vectorstore.get(
                        where={"id": fb_id},
                        include=["metadatas", "documents"]
                    )
                    
                    if results and results.get('ids'):
                        # 按章节号排序，获取最新的记录
                        entries = list(zip(results['ids'], results['metadatas'], results['documents']))
                        entries.sort(key=lambda x: x[1].get('chapter', 0), reverse=True)
                        latest_entry = entries[0]
                        
                        metadata = latest_entry[1]
                        content = latest_entry[2]
                        
                        # 格式化伏笔记录
                        entry = f"{metadata.get('id', '未知')}:\n"
                        entry += f"内容：{content}\n"
                        entry += f"伏笔最后章节：{metadata.get('chapter', 0)}\n\n"
                        
                        knowledge_context += entry
                        logging.info(f"成功检索伏笔 {fb_id} 的历史记录")
                
                if not knowledge_context:
                    knowledge_context = "(未找到相关伏笔历史记录)\n"
                    
            except Exception as e:
                logging.error(f"检索伏笔历史记录时出错: {str(e)}")
                knowledge_context = f"(检索伏笔历史记录时出错: {str(e)})\n"
    
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
            chapter_role=chapter_role,
            chapter_purpose=chapter_purpose,
            suspense_type=suspense_type,
            emotion_evolution=emotion_evolution,
            foreshadowing=foreshadowing,
            plot_twist_level=plot_twist_level,
            chapter_summary=chapter_summary,
            characters_involved=characters_involved, # 保持原有角色名称列表传递，用于其他逻辑
            characters_involved_detail=setting_characters, # 将生成的角色详细信息传递给新的参数
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            knowledge_context=knowledge_context,  # 使用从向量库检索到的伏笔历史记录
            word_number=max_tokens,
            volume_outline=volume_outline,
            user_guidance=user_guidance,
            genre=genre,
            topic=topic,
            setting_characters=setting_characters  # 添加生成的角色信息 (这里可能需要调整，暂时保留，因为prompt本身也用到了setting_characters)
        )
        
        # 记录最终使用的提示词到日志
        logging.info("\n==================================================\n发送到 LLM 的提示词:\n--------------------------------------------------\n\n" + prompt + "\n--------------------------------------------------")
        
        # 创建异步结果变量和事件
        result_data = {"content": None, "error": None}
        completion_event = threading.Event()

        def async_llm_call(prompt, callback):
            def llm_thread():
                try:
                    # 创建LLM适配器
                    llm_adapter = create_llm_adapter(
                        interface_format=interface_format,
                        base_url=base_url,
                        model_name=llm_model,
                        api_key=api_key,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=timeout
                    )
                    
                    result = invoke_with_cleaning(llm_adapter, prompt)
                    if not result or not result.strip():
                        raise ValueError("LLM返回内容为空")
                    
                    # 保存章节草稿
                    os.makedirs(os.path.join(filepath, "chapters"), exist_ok=True)
                    chapter_file = os.path.join(filepath, "chapters", f"chapter_{novel_number}.txt")
                    clear_file_content(chapter_file)
                    save_string_to_txt(result, chapter_file)
                    
                    callback(result)
                except Exception as e:
                    callback(None, str(e))

            # 创建新线程运行LLM调用
            thread = threading.Thread(target=llm_thread)
            thread.daemon = True
            thread.start()

        def on_llm_complete(result, error=None):
            if error:
                result_data["error"] = error
            else:
                result_data["content"] = result
            completion_event.set()

        # 异步调用LLM
        async_llm_call(prompt, on_llm_complete)

        # 等待完成
        completion_event.wait()

        if result_data["error"]:
            raise ValueError(result_data["error"])

        return result_data["content"]
        
    except Exception as e:
        error_msg = f"生成章节草稿时出错: {str(e)}\n{traceback.format_exc()}"
        logging.error(error_msg)
        return f"生成章节草稿失败: {str(e)}"

def finalize_chapter(
    interface_format: str,
    api_key: str,
    base_url: str,
    llm_model: str,
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
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 600,
    embedding_interface_format: str = "OpenAI",
    embedding_api_key: str = "",
    embedding_base_url: str = "https://api.openai.com/v1",
    embedding_model_name: str = "text-embedding-ada-002"
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
        llm_adapter = create_llm_adapter(
            interface_format=interface_format,
            base_url=base_url,
            model_name=llm_model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        # 创建嵌入适配器
        embedding_adapter = None
        try:
            if embedding_api_key:  # 只有在提供了API密钥时才创建嵌入适配器
                embedding_adapter = create_embedding_adapter(
                    interface_format=embedding_interface_format,
                    base_url=embedding_base_url,
                    model_name=embedding_model_name,
                    api_key=embedding_api_key
                )
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
        
        # 记录最终使用的提示词到日志
        logging.info("\n==================================================\n发送到 LLM 的定稿提示词:\n--------------------------------------------------\n\n" + prompt + "\n--------------------------------------------------")
        
        # 生成完善后的章节内容
        finalized_chapter = invoke_with_cleaning(llm_adapter, prompt)
        
        # 保存完善后的章节内容
        os.makedirs(os.path.join(filepath, "chapters"), exist_ok=True)
        chapter_file = os.path.join(filepath, "chapters", f"chapter_{novel_number}.txt")
        clear_file_content(chapter_file)
        save_string_to_txt(finalized_chapter, chapter_file)
        
        # 更新向量库
        if embedding_adapter:  # 只有在嵌入适配器存在时才更新向量库
            update_vector_store(embedding_adapter, finalized_chapter, filepath)
        
        # 提取章节内容中的伏笔和元数据
        if embedding_adapter:  # 只有在嵌入适配器存在时才处理章节内容
            process_chapter_content(
                embedding_adapter=embedding_adapter,
                llm_adapter=llm_adapter,
                filepath=filepath,
                novel_number=novel_number,
                chapter_title=chapter_title,
                chapter_content=finalized_chapter,
                chapter_summary=chapter_summary,
                foreshadowing=foreshadowing
            )
        
        logging.info(f"成功完善第{novel_number}章《{chapter_title}》内容")
        return finalized_chapter
        
    except Exception as e:
        error_msg = f"完善章节内容时出错: {str(e)}\n{traceback.format_exc()}"
        logging.error(error_msg)
        return f"完善章节内容失败: {str(e)}"

def update_vector_store(embedding_adapter, chapter_content: str, filepath: str) -> None:
    """
    更新向量库，将章节内容添加到向量库中
    
    Args:
        embedding_adapter: 嵌入适配器
        chapter_content: 章节内容
        filepath: 文件保存路径
    """
    try:
        from .vectorstore_utils import load_vector_store, get_vectorstore_dir
        store_dir = get_vectorstore_dir(filepath)
        
        # 如果向量库目录不存在则创建
        if not os.path.exists(store_dir):
            os.makedirs(store_dir, exist_ok=True)
            
        # 加载或创建向量库
        vectorstore = load_vector_store(
            embedding_adapter,
            filepath,
            collection_name="chapter_collection"
        )
        
        if vectorstore:
            # 将章节内容添加到向量库
            vectorstore.add(
                documents=[chapter_content],
                metadatas=[{"source": "chapter_content"}],
                ids=[f"chapter_{int(time.time())}"]
            )
            logging.info("成功更新向量库")
        else:
            logging.warning("向量库加载失败，无法更新向量库")
            
    except Exception as e:
        logging.error(f"更新向量库时出错: {str(e)}")

def process_chapter_content(
    embedding_adapter,
    llm_adapter,
    filepath: str,
    novel_number: int,
    chapter_title: str,
    chapter_content: str,
    chapter_summary: str,
    foreshadowing: str
) -> None:
    """
    处理章节内容，提取伏笔和元数据
    
    Args:
        embedding_adapter: 嵌入适配器
        llm_adapter: LLM适配器
        filepath: 文件保存路径
        novel_number: 章节编号
        chapter_title: 章节标题
        chapter_content: 章节内容
        chapter_summary: 章节简述
        foreshadowing: 伏笔条目
    """
    try:
        from . import chapter_processor
        # 获取角色状态
        character_state_file = os.path.join(filepath, "角色状态.txt")
        character_state = read_file(character_state_file)
        
        # 解析伏笔条目
        foreshadowing_items = []
        if foreshadowing:
            foreshadowing_items = [item.strip() for item in foreshadowing.split(',')]
        
        # 创建章节处理器
        processor = chapter_processor.ChapterProcessor(
            embedding_adapter=embedding_adapter,
            llm_adapter=llm_adapter,
            db_path=os.path.join(filepath, "data", "vector_database.json")
        )
        
        # 处理章节内容
        processor.process_chapter(
            chapter_text=chapter_content,
            chapter_number=novel_number,
            chapter_title=chapter_title,
            chapter_summary=chapter_summary,
            foreshadowing_items=foreshadowing_items,
            character_state_doc=character_state
        )
        
        logging.info(f"成功处理第{novel_number}章《{chapter_title}》内容，提取伏笔和元数据")
        
    except Exception as e:
        error_msg = f"处理章节内容时出错: {str(e)}\n{traceback.format_exc()}"
        logging.error(error_msg)

def build_chapter_prompt(
    novel_setting: str,
    character_state: str,
    global_summary: str,
    prev_chapter_content: str,
    novel_number: int,
    chapter_title: str,
    chapter_role: str,
    chapter_purpose: str,
    suspense_type: str,
    emotion_evolution: str,
    foreshadowing: str,
    plot_twist_level: str,
    chapter_summary: str,
    characters_involved: str,
    key_items: str,
    scene_location: str,
    time_constraint: str,
    knowledge_context: str,
    word_number: int,
    volume_outline: str,
    user_guidance: str,  # 新增用户指导参数
    genre: str,  # 新增小说类型参数
    topic: str,  # 新增小说主题参数
    setting_characters: str = "",  # 新增角色设计参数，用于第1章特殊处理
    characters_involved_detail: str = "", # 新增核心角色详细信息参数
    plot_points: str = ""  # 新增剧情要点参数，用于提供上一章剧情要点
) -> str:
    """
    构建章节生成提示词
    
    Args:
        与generate_chapter_draft函数参数相同
        
    Returns:
        构建好的提示词字符串
    """
    from prompt_definitions import chapter_draft_prompt
    
    return chapter_draft_prompt.format(
        novel_setting=novel_setting,
        character_state=character_state,
        global_summary=global_summary,
        prev_chapter_content=prev_chapter_content,
        novel_number=novel_number,
        chapter_title=chapter_title,
        chapter_role=chapter_role,
        chapter_purpose=chapter_purpose,
        suspense_type=suspense_type,
        word_number=word_number,
        volume_outline=volume_outline,
        emotion_evolution=emotion_evolution,
        foreshadowing=foreshadowing,
        plot_twist_level=plot_twist_level,
        chapter_summary=chapter_summary,
        characters_involved=characters_involved_detail, # 使用详细角色信息替换
        key_items=key_items,
        scene_location=scene_location,
        time_constraint=time_constraint,
        knowledge_context=knowledge_context,
        user_guidance=user_guidance,  # 添加 user_guidance 到 format 调用
        genre=genre,  # 添加 genre 到 format 调用
        topic=topic,  # 添加 topic 到 format 调用
        setting_characters=setting_characters,  # 添加 setting_characters 到 format 调用
        plot_points=plot_points  # 添加 plot_points 到 format 调用
    )


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

def build_chapter_prompt(chapter_info: dict, filepath: str) -> str:
    """构建章节草稿生成提示词"""
    try:
        from prompt_definitions import chapter_draft_prompt

        # 读取剧情要点文件
        plot_points_file = os.path.join(filepath, "剧情要点.txt")
        plot_points = ""
        if os.path.exists(plot_points_file):
            current_chapter = chapter_info.get('novel_number', 1)
            if current_chapter > 1:
                previous_chapter = current_chapter - 1
                with open(plot_points_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                    # 使用多个模式匹配前一章的剧情要点
                    title_patterns = [
                        rf"(第{previous_chapter}章.*?剧情要点：[\s\S]*?)(?=第{current_chapter}章|$)",  
                        rf"(第{previous_chapter}章.*?剧情要点[：:][\s\S]*?)(?=第{current_chapter}章|$)",  
                        rf"(第{previous_chapter}章[\s\S]*?)(?=第{current_chapter}章|$)"  
                    ]
                    
                    # 先尝试包含标题的匹配
                    for pattern in title_patterns:
                        match = re.search(pattern, content)
                        if match and match.group(1).strip():
                            plot_points = match.group(1).strip()
                            logging.info(f"成功提取第{previous_chapter}章的剧情要点")
                            break
                    
                    # 如果上述模式都没匹配到，记录警告
                    if not plot_points:
                        logging.warning(f"未找到第{previous_chapter}章的剧情要点")
                
        # 从 chapter_info 中提取所需参数
        return chapter_draft_prompt.format(
            novel_setting=chapter_info.get('novel_setting', ''),
            character_state=chapter_info.get('character_state', ''),
            global_summary=chapter_info.get('global_summary', ''),
            prev_chapter_content=chapter_info.get('prev_chapter_content', ''),
            novel_number=chapter_info.get('novel_number', 1),
            chapter_title=chapter_info.get('chapter_title', ''),
            chapter_role=chapter_info.get('chapter_role', ''),
            chapter_purpose=chapter_info.get('chapter_purpose', ''),
            suspense_type=chapter_info.get('suspense_type', ''),
            word_number=chapter_info.get('word_number', 3000),
            volume_outline=chapter_info.get('volume_outline', ''),
            emotion_evolution=chapter_info.get('emotion_evolution', ''),
            foreshadowing=chapter_info.get('foreshadowing', ''),
            plot_twist_level=chapter_info.get('plot_twist_level', ''),
            chapter_summary=chapter_info.get('chapter_summary', ''),
            characters_involved=chapter_info.get('characters_involved_detail', ''),
            key_items=chapter_info.get('key_items', ''),
            scene_location=chapter_info.get('scene_location', ''),
            time_constraint=chapter_info.get('time_constraint', ''),
            knowledge_context=chapter_info.get('knowledge_context', ''),
            user_guidance=chapter_info.get('user_guidance', ''),
            genre=chapter_info.get('genre', ''),
            topic=chapter_info.get('topic', ''),
            setting_characters=chapter_info.get('setting_characters', ''),
            plot_points=plot_points # 添加剧情要点内容
        )
        
    except Exception as e:
        logging.error(f"构建章节提示词时出错: {str(e)}")
        raise