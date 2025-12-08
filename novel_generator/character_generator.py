# -*- coding: utf-8 -*-
"""
角色生成相关功能 - 用于章节草稿生成前的角色信息准备
"""
import os
import re
import traceback
import threading
from utils import read_file, save_string_to_txt, clear_file_content
from novel_generator.common import invoke_stream_with_cleaning, format_character_info
from novel_generator.json_utils import load_store
from prompt_definitions import create_character_prompt

def generate_characters_for_draft(chapter_info, filepath, llm_adapter, log_func=None, check_interrupted=None):
    """
    为章节草稿生成角色信息的流程函数
    
    参数:
        chapter_info: 章节信息字典，包含章节标题、编号等信息
        filepath: 文件保存路径
        llm_adapter: LLM适配器
        log_func: 日志记录函数
    
    返回:
        str: 生成的角色信息字符串，用于chapter_draft_prompt的setting_characters变量
    """
    def _log(message):
        if log_func:
            log_func(message)
        else:
            print(message)

    try:
        # 获取章节信息
        novel_number = chapter_info.get('novel_number', 1)
        chapter_title = chapter_info.get('chapter_title', f"第{novel_number}章")
        genre = chapter_info.get('genre', "")
        volume_count = chapter_info.get('volume_count', 3)
        num_chapters = chapter_info.get('num_chapters', 30)
        volume_number = chapter_info.get('volume_number', 1)
        word_number = chapter_info.get('word_number', 3000)
        topic = chapter_info.get('topic', "")
        user_guidance = chapter_info.get('user_guidance', "")
        global_summary = chapter_info.get('global_summary', "")
        plot_points = chapter_info.get('plot_points', "")
        volume_outline = chapter_info.get('volume_outline', "")
        
        # 读取角色数据库,只提取角色索引表部分
        character_db_file = os.path.join(filepath, "角色数据库.txt")
        Character_Database = ""
        if os.path.exists(character_db_file):
            with open(character_db_file, "r", encoding="utf-8") as f:
                content = f.read()
                # 使用正则表达式提取整个“角色索引表”部分
                # 这个模式会从“## 角色索引表”开始，一直匹配到下一个“## ”标题之前或文件末尾
                pattern = r"(## 角色索引表（唯一标识区）[\s\S]*?)(?=\n## |\Z)"
                match = re.search(pattern, content)
                if match:
                    Character_Database = match.group(1).strip()
                    _log("成功提取角色索引表内容")
                else:
                    _log("未找到角色索引表内容")
        
        # 1. 先清空待用角色.txt的内容
        待用角色_file = os.path.join(filepath, "待用角色.txt")
        clear_file_content(待用角色_file)
        
        # 读取剧情要点文件
        plot_points = ""
        plot_points_file = os.path.join(filepath, "剧情要点.txt")
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
                    
                    # 尝试匹配剧情要点
                    for pattern in title_patterns:
                        match = re.search(pattern, content)
                        if match and match.group(1).strip():
                            plot_points = match.group(1).strip()
                            _log(f"成功提取第{previous_chapter}章的剧情要点")
                            break
                    
                    if not plot_points:
                        _log(f"未找到第{previous_chapter}章的剧情要点")
        
        # 使用提取的剧情要点更新chapter_info
        chapter_info['plot_points'] = plot_points

        # 从传入的 chapter_info 字典中直接获取章节目录内容
        chapter_blueprint_content = chapter_info.get('current_chapter_blueprint', "")
        if not chapter_blueprint_content:
            _log("未能从 chapter_info 中获取 current_chapter_blueprint。")

        # 2. 使用LLM按照create_character_prompt提示词内容，从角色数据库中提取角色ID和新角色信息
        character_prompt = create_character_prompt.format(
            genre=genre,
            volume_count=volume_count,
            num_chapters=num_chapters,
            volume_number=volume_number,
            novel_number=novel_number,
            chapter_title=chapter_title,
            word_number=word_number,
            chapter_blueprint_content=chapter_blueprint_content,
            topic=topic,
            user_guidance=user_guidance,
            global_summary=global_summary,
            plot_points=plot_points,
            volume_outline=volume_outline,
            Character_Database=Character_Database
        )
        
        _log("正在调用LLM生成角色信息...")
        character_result = ""
        # 使用流式调用以支持中断
        for chunk in invoke_stream_with_cleaning(llm_adapter, character_prompt, log_func=log_func, check_interrupted=check_interrupted):
            character_result += chunk

        # 检查是否在流式调用期间被中断
        if check_interrupted and check_interrupted():
            _log("角色信息生成被用户中断。")
            return "" # 返回空字符串以中止后续流程

        if not character_result:
            _log("生成角色信息失败")
            return ""
        
        # 3. 提取到角色ID暂时保存到待用角色.txt文件
        save_string_to_txt(character_result, 待用角色_file)
        
        # 4. 从角色结果中提取角色ID列表
        character_ids = []
        for line in character_result.split('\n'):
            # 匹配ID格式（如ID0001）
            id_match = re.search(r'(ID\d+)', line)
            if id_match:
                character_ids.append(id_match.group(1))
        
        # 5. 使用提取到的角色ID检索角色信息，兼容新旧两种格式
        if novel_number > 1:
            _log(f"当前生成第{novel_number}章，需要从JSON文件和TXT数据库中检索角色信息")
            
            retrieved_characters = []
            processed_ids = set()

            # 首先，从新的JSON数据源检索
            try:
                character_store = load_store(filepath, "character_state_collection")
                if character_store:
                    for char_id in character_ids:
                        if char_id in character_store:
                            char_data = character_store[char_id]
                            if isinstance(char_data, dict):
                                formatted_info = format_character_info(char_data)
                                if formatted_info:
                                    retrieved_characters.append(formatted_info)
                                    processed_ids.add(char_id)
                                    _log(f"从JSON源检索并格式化了角色 {char_id}")
            except Exception as e:
                _log(f"从JSON源检索角色时出错: {e}")

            # 接着，从旧的TXT数据源检索尚未处理的角色
            try:
                db_file = os.path.join(filepath, "角色数据库.txt")
                if os.path.exists(db_file):
                    content = read_file(db_file)
                    character_entries = re.split(r'\n(?=ID\d{4}：)', content)
                    
                    # 创建一个字典以便快速查找
                    entry_map = {}
                    for entry in character_entries:
                        id_match = re.match(r'(ID\d{4})', entry)
                        if id_match:
                            entry_map[id_match.group(1)] = entry.strip()

                    for char_id in character_ids:
                        if char_id not in processed_ids and char_id in entry_map:
                            retrieved_characters.append(entry_map[char_id])
                            processed_ids.add(char_id)
                            _log(f"从TXT源检索了角色 {char_id}")
            except Exception as e:
                _log(f"从TXT源检索角色时出错: {e}")

            # 将所有检索到的信息附加到文件中
            if retrieved_characters:
                llm_generated_content = read_file(待用角色_file)
                # 使用分隔符以提高可读性
                final_content = llm_generated_content + "\n\n---\n\n" + "\n\n---\n\n".join(retrieved_characters)
                save_string_to_txt(final_content, 待用角色_file)
        else:
            _log("当前生成第1章，跳过从数据源检索角色信息")
        
        # 6. 读取完整的待用角色.txt文件内容
        final_character_info = read_file(待用角色_file)
        
        return final_character_info
    
    except Exception as e:
        _log(f"生成角色信息时出错: {e}")
        _log(traceback.format_exc())
        # Re-raise the exception to allow the polling mechanism to catch it
        raise

def generate_characters_for_draft_async(chapter_info, filepath, llm_adapter, callback, log_func=None):
    """
    Asynchronously generates character information for a chapter draft.
    The result is passed to the callback function.
    """
    def task():
        """The actual work to be done in a separate thread."""
        try:
            # Call the original synchronous function, passing the log_func
            result = generate_characters_for_draft(
                chapter_info, filepath, llm_adapter, log_func=log_func
            )
            # Pass the result to the callback function
            if callback:
                callback(result)
        except Exception as e:
            if log_func:
                log_func(f"Error in character generation thread: {e}")
                log_func(traceback.format_exc())
            else:
                print(f"Error in character generation thread: {e}")
                print(traceback.format_exc())
            # Pass an error message to the callback
            if callback:
                callback(f"(准备角色信息时出错: {str(e)})")

    # Create and start the thread
    thread = threading.Thread(target=task, daemon=True)
    thread.start()

def update_character_in_file(file_path, char_id, char_info, log_func=None):
    """
    更新待用角色.txt文件中特定角色ID的信息
    
    参数:
        file_path: 待用角色.txt文件路径
        char_id: 角色ID
        char_info: 角色信息
    """
    try:
        # 读取当前文件内容
        current_content = read_file(file_path)
        
        # 查找角色ID在文件中的位置
        id_pattern = re.compile(rf"{char_id}\s*[：:](.*?)(?=ID\d+|$)", re.DOTALL)
        match = id_pattern.search(current_content)
        
        if match:
            # 如果找到了角色ID，替换对应的内容
            start, end = match.span()
            new_content = current_content[:start] + char_info + current_content[end:]
            save_string_to_txt(new_content, file_path)
        else:
            # 如果没有找到角色ID，将角色信息添加到文件末尾
            save_string_to_txt(current_content + "\n\n" + char_info, file_path)
    
    except Exception as e:
        if log_func:
            log_func(f"更新角色信息时出错: {e}")
            log_func(traceback.format_exc())
        else:
            print(f"更新角色信息时出错: {e}")
            print(traceback.format_exc())
