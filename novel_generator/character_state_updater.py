# novel_generator/character_state_updater.py
# -*- coding: utf-8 -*-
"""
角色状态更新相关功能
"""
import os
import logging
import traceback
import re
import json
from utils import read_file, save_string_to_txt, clear_file_content
from novel_generator.common import invoke_with_cleaning
from novel_generator.vectorstore_utils import load_vector_store, init_vector_store
from prompt_definitions import Character_name_prompt, update_character_state_prompt

def update_character_states(chapter_text, chapter_title, chap_num, filepath, llm_adapter, embedding_adapter):
    """
    更新角色状态的三步流程函数
    """
    try:
        result = {"status": "error", "message": "", "character_state": ""}
        character_state_file = os.path.join(filepath, "角色状态.txt")

        # 从角色数据库中读取现有角色信息
        character_db_file = os.path.join(filepath, "角色数据库.txt")
        character_db_content = ""
        if os.path.exists(character_db_file):
            db_content = read_file(character_db_file)
            table_start = db_content.find("## 角色索引表")
            if table_start != -1:
                table_content = db_content[table_start:]
                # 使用正则表达式匹配表格行，提取三个关键属性
                table_rows = re.findall(r'\|\s*(ID\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|', table_content)
                if table_rows:
                    character_db_content = "角色数据库：\n"
                    for row in table_rows:
                        char_id = row[0].strip()
                        char_name = row[1].strip()
                        char_alt_names = row[2].strip()
                        if "ID" in char_id:  # 确保是有效的角色ID
                            character_db_content += f"ID编号: {char_id}\n"
                            character_db_content += f"正式名称: {char_name}\n"
                            character_db_content += f"其他称谓: {char_alt_names}\n\n"

        # 调用Character_name_prompt提取角色
        character_names_prompt = Character_name_prompt.format(
            novel_number=chap_num,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            Character_Database=character_db_content
        )
        character_id_result = invoke_with_cleaning(llm_adapter, character_names_prompt)
        if not character_id_result:
            result["message"] = "角色名和ID提取失败"
            return result

        # 步骤2: 从向量库检索角色状态
        logging.info("步骤2: 检索角色状态...")
        old_state = "无"  # 默认值
        vectorstore = None

        if embedding_adapter:
            vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
            
            if not vectorstore:
                # 初始化向量库
                try:
                    vectorstore = init_vector_store(
                        embedding_adapter=embedding_adapter,
                        texts=["初始化角色状态向量库"],
                        filepath=filepath,
                        collection_name="character_state_collection",
                        metadatas=[{"type": "init"}],
                        ids=["init_0"]
                    )
                    if vectorstore:
                        vectorstore.delete(where={"type": "init"})
                        logging.info("成功初始化角色状态向量库")
                except Exception as e:
                    logging.warning(f"初始化角色状态向量库时出错: {e}")

            # 解析角色ID并检索状态
            character_states = []
            for line in character_id_result.split('\n'):
                if ':' in line or '：' in line:
                    parts = line.replace('：', ':').split(':')
                    if len(parts) == 2:
                        char_id = parts[0].strip()
                        char_name = parts[1].strip()
                        try:
                            # 检索角色状态
                            if vectorstore:
                                docs = vectorstore.get(
                                    where={"character_id": char_id},
                                    include=["documents"]
                                )
                                if docs and docs.get('documents'):
                                    character_states.extend(docs['documents'])
                        except Exception as e:
                            logging.warning(f"检索角色 {char_id} 状态时出错: {e}")

            # 组合所有角色状态
            old_state = "\n\n".join(character_states) if character_states else "无"

        # 步骤3: 使用update_character_state_prompt更新角色状态
        logging.info("步骤3: 更新角色状态...")
        # ... (获取章节相关信息的代码保持不变)
        
        # 导入章节目录解析函数
        from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
        try:
            # 1. 先获取所有需要的变量值
            # 从章节目录.txt中获取章节信息
            directory_file = os.path.join(filepath, "章节目录.txt")  # 修复这里
            chapter_info = {}
            if os.path.exists(directory_file):  # 现在正确地检查文件是否存在
                directory_content = read_file(directory_file)
                if directory_content:
                    chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)

            # 获取基本信息变量
            novel_setting_file = os.path.join(filepath, "小说设定.txt")
            genre = ""
            volume_count = 1
            num_chapters = 1
            volume_number = 1
            novel_number = chap_num
            word_number = len(chapter_text) if chapter_text else 0

            # 从小说设定中获取genre
            if os.path.exists(novel_setting_file):
                novel_setting = read_file(novel_setting_file)
                genre_match = re.search(r"类型：([^\n]+)", novel_setting)
                if genre_match:
                    genre = genre_match.group(1).strip()

            # 从章节目录获取章节数和卷数
            if os.path.exists(directory_file):
                directory_content = read_file(directory_file)
                if directory_content:
                    # 计算章节总数
                    chapter_pattern = re.compile(r'第\s*(\d+)\s*章')
                    chapters = chapter_pattern.findall(directory_content)
                    if chapters:
                        chapters = [int(c) for c in chapters]
                        num_chapters = max(chapters)
                    
                    # 获取卷数
                    volume_pattern = re.compile(r'第[一二三四五六七八九十]卷|第\s*(\d+)\s*卷')
                    volumes = volume_pattern.findall(directory_content)
                    if volumes:
                        volume_count = len(volumes) if isinstance(volumes[0], str) and not volumes[0].isdigit() else max([int(v) for v in volumes if v and v.isdigit()])
                        volume_count = max(1, volume_count)

            # 计算当前卷号
            if num_chapters > 0 and volume_count > 0:
                chapters_per_volume = num_chapters // volume_count
                if chapters_per_volume > 0:
                    volume_number = (chap_num - 1) // chapters_per_volume + 1
                else:
                    volume_number = 1

            # 获取章节相关信息
            chapter_role = chapter_info.get('chapter_role', '')
            chapter_purpose = chapter_info.get('chapter_purpose', '')
            suspense_type = chapter_info.get('suspense_type', '')
            emotion_evolution = chapter_info.get('emotion_evolution', '')
            foreshadowing = chapter_info.get('foreshadowing', '')
            plot_twist_level = chapter_info.get('plot_twist_level', '')
            chapter_summary = chapter_info.get('chapter_summary', '')
        except Exception as e:
            logging.error(f"获取章节相关信息时出错: {e}")
            logging.error(traceback.format_exc())
            result["message"] = f"获取章节相关信息时出错: {e}"
            return result

        # 构建更新提示词
        char_update_prompt = update_character_state_prompt.format(
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
            chapter_text=chapter_text,
            old_state=old_state,
            Character_Database=character_id_result  # 使用步骤1的结果
        )

        # 生成新的角色状态
        new_character_state = invoke_with_cleaning(llm_adapter, char_update_prompt)
        if not new_character_state:
            result["message"] = "生成新角色状态失败"
            return result

        # 保存新的角色状态
        save_string_to_txt(new_character_state, character_state_file)

        # 更新向量库和角色数据库
        if vectorstore:
            # 解析新的角色状态，提取每个角色的状态
            char_blocks = re.split(r'\n\s*\n', new_character_state)
            char_texts = []
            char_metadatas = []
            char_ids = []
            
            for block in char_blocks:
                # 尝试提取角色ID和名称
                id_match = re.match(r'(ID\d+)\s*[：:]\s*([^\n]+)', block)
                if id_match:
                    char_id = id_match.group(1)
                    char_name = id_match.group(2).strip()
                    
                    # 提取权重数值
                    weight = "50"  # 默认权重
                    weight_match = re.search(r'角色权重：(\d+)', block)
                    if weight_match:
                        weight = weight_match.group(1).strip()
                    
                    # 提取未回收伏笔编号
                    foreshadowing_ids = []
                    foreshadowing_match = re.search(r'未回收：([^\n]+)', block)
                    if foreshadowing_match:
                        foreshadowing_str = foreshadowing_match.group(1).strip()
                        foreshadowing_ids = [f_id.strip() for f_id in foreshadowing_str.split(',') if f_id.strip()]
                    
                    # 如果未找到标准格式，尝试其他可能的格式
                    if not foreshadowing_ids:
                        alt_match = re.search(r'未回收伏笔编号：([^\n]+)', block)
                        if alt_match:
                            foreshadowing_str = alt_match.group(1).strip()
                            foreshadowing_ids = [f_id.strip() for f_id in foreshadowing_str.split(',') if f_id.strip()]
                    
                    # 准备向量化数据
                    char_texts.append(block)
                    char_metadatas.append({
                        "id": char_id,
                        "name": char_name,
                        "chapter": chap_num,
                        "weight": int(weight),
                        "foreshadowing_ids": ",".join(foreshadowing_ids),
                        "type": "character_state",
                        "character_id": char_id,
                        "character_name": char_name,
                        "unretrieved_foreshadowing_ids": ",".join(foreshadowing_ids),
                        "base_weight": int(weight)
                    })
                    char_ids.append(f"{char_id}_{chap_num}")
                    
                    # 如果向量库存在，先删除现有的角色状态
                    if vectorstore:
                        try:
                            # 使用正确的where条件格式
                            vectorstore.delete(
                                where={"$and": [
                                    {"character_id": {"$eq": char_id}},
                                    {"type": {"$eq": "character_state"}}
                                ]}
                            )
                            # 再尝试使用character_name删除，确保清理干净
                            vectorstore.delete(
                                where={"$and": [
                                    {"character_name": {"$eq": char_name}},
                                    {"type": {"$eq": "character_state"}}
                                ]}
                            )
                            logging.info(f"已删除角色 {char_name} ({char_id}) 的现有状态")
                        except Exception as e:
                            logging.warning(f"删除角色 {char_name} 的状态时出错: {e}")
                            logging.warning(traceback.format_exc())
            
            # 向量化所有角色状态
            try:
                if vectorstore and char_texts:
                    # 使用正确的add()方法添加文本
                    vectorstore.add(
                        documents=char_texts,
                        metadatas=char_metadatas,
                        ids=char_ids
                    )
                    logging.info(f"已向量化 {len(char_texts)} 个角色的新状态")
                elif embedding_adapter and char_texts:
                    # 如果向量库不存在，则初始化向量库
                    vectorstore = init_vector_store(
                        embedding_adapter=embedding_adapter,
                        texts=char_texts,
                        filepath=filepath,
                        collection_name="character_state_collection",
                        metadatas=char_metadatas,
                        ids=char_ids
                    )
                    if vectorstore:
                        logging.info("成功初始化角色状态向量库")
                    else:
                        logging.warning("初始化角色状态向量库失败")
            except Exception as e:
                logging.warning(f"向量化角色状态时出错: {e}")
                logging.warning(traceback.format_exc())

            # 更新角色数据库.txt
            # 解析新的角色状态，提取每个角色的信息
            char_blocks = re.split(r'\n\s*\n', new_character_state)
            updated_chars = {}
            
            for block in char_blocks:
                # 尝试提取角色ID和名称
                id_match = re.match(r'(ID\d+)\s*[：:]\s*([^\n]+)', block)
                if id_match:
                    char_id = id_match.group(1)
                    char_name = id_match.group(2).strip()
                    
                    # 提取其他信息
                    other_names = ""
                    faction = "无归属"
                    status = "活跃"
                    last_chapter = f"第{chap_num}章"
                    weight = "50"
                    last_location = "未知"
                    
                    # 提取称谓
                    other_names_match = re.search(r'称谓：([^\n]+)', block)
                    if other_names_match:
                        other_names = other_names_match.group(1).strip()
                    
                    # 提取势力归属
                    faction_match = re.search(r'势力归属：\s*\n\s*籍贯/家乡：[^\n]*\s*\n\s*所属势力：([^\n]+)', block)
                    if faction_match:
                        faction = faction_match.group(1).strip()
                    
                    # 提取身体状态
                    status_match = re.search(r'身体状态：([^\n]+)', block)
                    if status_match:
                        status = status_match.group(1).strip()
                    elif re.search(r'当前状态', block):
                        status_match = re.search(r'当前状态\s*\n([^\n]+)', block)
                        if status_match:
                            status = status_match.group(1).strip()
                    
                    # 提取最后出场章节
                    chapter_match = re.search(r'最后出场章节：([^\n]+)', block)
                    if chapter_match:
                        last_chapter = chapter_match.group(1).strip()
                    
                    # 提取角色权重
                    weight_match = re.search(r'角色权重：(\d+)', block)
                    if weight_match:
                        weight = weight_match.group(1).strip()
                    
                    # 提取最后出场位置（从位置轨迹中提取最后一个位置条目的场景名称）
                    location_section = re.search(r'位置轨迹：\s*\n([\s\S]*?)(?=\n\n|\n[^-\s]|$)', block)
                    if location_section:
                        location_text = location_section.group(1).strip()
                        # 提取位置轨迹中的每一行，格式为：- 场景名称（时间线：第X章）（事件：摘要）（同行人物）（目的）
                        location_entries = re.findall(r'- ([^（\(]+)(?:\(|（)', location_text)
                        if location_entries:
                            # 获取最后一个位置条目的场景名称
                            last_location = location_entries[-1].strip()
                    
                    updated_chars[char_id] = {
                        "name": char_name,
                        "block": block,
                        "other_names": other_names,
                        "faction": faction,
                        "status": status,
                        "last_chapter": last_chapter,
                        "weight": weight,
                        "last_location": last_location
                    }
            
            # 确保角色数据库.txt文件存在并有基本结构
            if not os.path.exists(character_db_file) or not read_file(character_db_file).strip():
                # 创建基本结构
                basic_structure = """# 角色数据库
## 分类统计
### 权重分布
主角级（96-100）：0
关键角色（81-95）：0
核心配角（61-80）：0
次要配角（41-60）：0
单元角色（21-40）：0
背景角色（1-20）：0
### 角色信息
角色总数：0
核心角色（权重≥81）：0
活跃角色（最近X章出场）：0
势力分类：无

## 角色索引表（唯一标识区）

| ID编号 | 正式名称 | 其他称谓集合 | 势力归属 | 当前状态 | 最后出场章 | 最后出场位置 | 权重等级 |
|--------|----------|----------|----------|----------|------------|----------|----------|
"""
                save_string_to_txt(basic_structure, character_db_file)
                logging.info("已创建角色数据库.txt基本结构")
            
            # 更新角色数据库.txt文件中的表格
            if os.path.exists(character_db_file) and updated_chars:
                character_db_content = read_file(character_db_file)
                
                # 定义表头和分隔符
                table_header = "| ID编号 | 正式名称 | 其他称谓集合 | 势力归属 | 当前状态 | 最后出场章 | 最后出场位置 | 权重等级 |"
                table_separator = "|--------|----------|----------|----------|----------|------------|----------|----------|"
                
                # 如果表格不存在，则在角色索引表后创建表格
                if table_header not in character_db_content:
                    index_section = "## 角色索引表（唯一标识区）"
                    if index_section in character_db_content:
                        # 找到下一个章节的位置
                        index_section_start = character_db_content.find(index_section)
                        next_section_start = character_db_content.find("##", index_section_start + len(index_section))
                        
                        if next_section_start == -1:
                            next_section_start = len(character_db_content)
                        
                        # 在角色索引表和下一个章节之间插入表格
                        table_content = f"\n\n{table_header}\n{table_separator}"
                        character_db_content = character_db_content[:next_section_start] + table_content + character_db_content[next_section_start:]
                
                # 现在更新表格内容
                table_start = character_db_content.find(table_header)
                if table_start != -1:
                    table_end = character_db_content.find("##", table_start)
                    if table_end == -1:
                        table_end = len(character_db_content)
                    
                    # 提取现有表格行
                    table_section = character_db_content[table_start:table_end]
                    table_lines = table_section.split('\n')
                    
                    # 创建新表格内容
                    new_table = [table_lines[0], table_lines[1]]  # 保留表头和分隔行
                    
                    # 添加或更新角色行
                    existing_ids = set()
                    for line in table_lines[2:]:
                        if line.strip() and line.startswith('| ID'):
                            parts = [part.strip() for part in line.split('|')]
                            if len(parts) > 1:
                                char_id = parts[1]
                                if char_id in updated_chars:
                                    # 更新现有角色行
                                    char_info = updated_chars[char_id]
                                    new_table.append(f"| {char_id} | {char_info['name']} | {char_info['other_names']} | {char_info['faction']} | {char_info['status']} | {char_info['last_chapter']} | {char_info['last_location']} | {char_info['weight']} |")
                                    existing_ids.add(char_id)
                                else:
                                    # 保留未更新的角色行
                                    new_table.append(line)
                    
                    # 添加新角色行
                    for char_id, char_info in updated_chars.items():
                        if char_id not in existing_ids:
                            new_table.append(f"| {char_id} | {char_info['name']} | {char_info['other_names']} | {char_info['faction']} | {char_info['status']} | {char_info['last_chapter']} | {char_info['last_location']} | {char_info['weight']} |")
                    
                    new_table_text = "\n".join(new_table)
                    
                    # 替换旧的表格部分
                    character_db_content = character_db_content[:table_start] + new_table_text + character_db_content[table_end:]
                    
                    # 更新分类统计
                    total_chars = len(updated_chars)
                    weight_counts = {"96-100": 0, "81-95": 0, "61-80": 0, "41-60": 0, "21-40": 0, "1-20": 0}
                    core_chars = 0
                    
                    for char_info in updated_chars.values():
                        try:
                            weight = int(char_info.get("weight", 0))
                            if 96 <= weight <= 100: weight_counts["96-100"] += 1
                            elif 81 <= weight <= 95: weight_counts["81-95"] += 1; core_chars += 1
                            elif 61 <= weight <= 80: weight_counts["61-80"] += 1
                            elif 41 <= weight <= 60: weight_counts["41-60"] += 1
                            elif 21 <= weight <= 40: weight_counts["21-40"] += 1
                            elif 1 <= weight <= 20: weight_counts["1-20"] += 1
                        except ValueError:
                            logging.warning(f"Invalid weight value for character {char_info['name']}: {char_info.get('weight')}")
                    
                    # 构建新的分类统计文本
                    new_stats_text = f"""## 分类统计\n### 权重分布\n主角级（96-100）：{weight_counts['96-100']}\n关键角色（81-95）：{weight_counts['81-95']}\n核心配角（61-80）：{weight_counts['61-80']}\n次要配角（41-60）：{weight_counts['41-60']}\n单元角色（21-40）：{weight_counts['21-40']}\n背景角色（1-20）：{weight_counts['1-20']}\n### 角色信息\n角色总数：{total_chars}\n核心角色（权重≥81）：{core_chars}\n活跃角色（最近X章出场）：0 # 待办：实现活跃角色追踪\n势力分类：无 # 待办：实现势力追踪\n\n## 角色索引表（唯一标识区）"""
                    
                    # 更新分类统计部分
                    stats_pattern = re.compile(r'## 分类统计.*?## 角色索引表（唯一标识区）', re.DOTALL)
                    character_db_content = stats_pattern.sub(new_stats_text, character_db_content)
                    
                    save_string_to_txt(character_db_content, character_db_file)
                    logging.info("成功更新角色数据库.txt")
                    
                else:
                    logging.warning("未找到角色数据库.txt中的表格，跳过表格更新")
                
            elif not updated_chars:
                logging.warning("没有需要更新的角色信息，跳过角色数据库.txt更新")

        result["status"] = "success"
        result["character_state"] = new_character_state
        return result

    except Exception as e:
        logging.error(f"更新角色状态时出现异常: {str(e)}")
        logging.error(traceback.format_exc())
        result["message"] = f"更新角色状态时出现异常: {str(e)}"
        return result