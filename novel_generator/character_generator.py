# -*- coding: utf-8 -*-
"""
角色生成相关功能 - 用于章节草稿生成前的角色信息准备
"""
import os
import logging
import re
import traceback
from utils import read_file, save_string_to_txt, clear_file_content
from novel_generator.common import invoke_with_cleaning
from novel_generator.vectorstore_utils import load_vector_store
from prompt_definitions import create_character_prompt

def generate_characters_for_draft(chapter_info, filepath, llm_adapter, embedding_adapter):
    """
    为章节草稿生成角色信息的流程函数
    
    参数:
        chapter_info: 章节信息字典，包含章节标题、编号等信息
        filepath: 文件保存路径
        llm_adapter: LLM适配器
        embedding_adapter: 嵌入适配器
    
    返回:
        str: 生成的角色信息字符串，用于chapter_draft_prompt的setting_characters变量
    """
    try:
        # 获取章节信息
        novel_number = chapter_info.get('novel_number', 1)
        chapter_title = chapter_info.get('chapter_title', f"第{novel_number}章")
        chapter_role = chapter_info.get('chapter_role', "")
        chapter_purpose = chapter_info.get('chapter_purpose', "")
        suspense_type = chapter_info.get('suspense_type', "")
        emotion_evolution = chapter_info.get('emotion_evolution', "")
        foreshadowing = chapter_info.get('foreshadowing', "")
        plot_twist_level = chapter_info.get('plot_twist_level', "")
        chapter_summary = chapter_info.get('chapter_summary', "")
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
        
        # 读取角色数据库
        character_db_file = os.path.join(filepath, "角色数据库.txt")
        Character_Database = ""
        if os.path.exists(character_db_file):
            Character_Database = read_file(character_db_file)
        
        # 1. 先清空待用角色.txt的内容
        待用角色_file = os.path.join(filepath, "待用角色.txt")
        clear_file_content(待用角色_file)
        
        # 2. 使用LLM按照create_character_prompt提示词内容，从角色数据库中提取角色ID和新角色信息
        character_prompt = create_character_prompt.format(
            genre=genre,
            volume_count=volume_count,
            num_chapters=num_chapters,
            volume_number=volume_number,
            novel_number=novel_number,
            chapter_title=chapter_title,
            word_number=word_number,
            chapter_role=chapter_role,
            chapter_purpose=chapter_purpose,
            suspense_type=suspense_type,
            emotion_evolution=emotion_evolution,
            foreshadowing=foreshadowing,
            plot_twist_level=plot_twist_level,
            chapter_summary=chapter_summary,
            topic=topic,
            user_guidance=user_guidance,
            global_summary=global_summary,
            plot_points=plot_points,
            volume_outline=volume_outline,
            Character_Database=Character_Database
        )
        
        character_result = invoke_with_cleaning(llm_adapter, character_prompt)
        
        if not character_result:
            logging.error("生成角色信息失败")
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
        
        # 5. 使用提取到的角色ID检索角色信息
        # 根据用户要求，区分第1章和后续章节的处理逻辑
        if novel_number > 1:  # 如果是生成第2章及以后的章节
            logging.info(f"当前生成第{novel_number}章，需要检索向量库内的角色信息")
            if embedding_adapter:
                vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
                if vectorstore:
                    for char_id in character_ids:
                        try:
                            # 使用角色ID作为查询条件，使用$and操作符组合多个条件
                            retrieved_docs = vectorstore.get(
                                where={"$and": [{"id": char_id}, {"type": "character_state"}]}, 
                                include=["metadatas", "documents"]
                            )
                            
                            if retrieved_docs and retrieved_docs.get('ids'):
                                # 找到最新的角色状态
                                latest_chapter = -1
                                latest_doc = ""
                                
                                for i, doc_id in enumerate(retrieved_docs['ids']):
                                    metadata = retrieved_docs['metadatas'][i]
                                    doc_chapter = metadata.get('chapter', -1)
                                    
                                    if doc_chapter > latest_chapter:
                                        latest_chapter = doc_chapter
                                        latest_doc = retrieved_docs['documents'][i]
                                
                                if latest_doc:
                                    # 将检索到的角色信息添加到待用角色.txt文件中对应角色ID的位置
                                    update_character_in_file(待用角色_file, char_id, latest_doc)
                                    logging.info(f"从向量库中检索到角色ID {char_id} 的状态")
                        except Exception as e:
                            logging.warning(f"检索角色ID {char_id} 的状态时出错: {e}")
                            logging.warning(traceback.format_exc())
        else:  # 如果是生成第1章
            logging.info("当前生成第1章，跳过检索向量库内的角色信息")
        
        # 6. 读取完整的待用角色.txt文件内容
        final_character_info = read_file(待用角色_file)
        
        return final_character_info
    
    except Exception as e:
        logging.error(f"生成角色信息时出错: {e}")
        logging.error(traceback.format_exc())
        return ""

def update_character_in_file(file_path, char_id, char_info):
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
        id_pattern = re.compile(f"{char_id}\s*[：:](.*?)(?=ID\d+|$)", re.DOTALL)
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
        logging.error(f"更新角色信息时出错: {e}")
        logging.error(traceback.format_exc())