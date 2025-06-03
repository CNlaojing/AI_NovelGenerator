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
    更新角色状态的六步流程函数
    
    参数:
        chapter_text: 章节文本
        chapter_title: 章节标题
        chap_num: 章节编号
        filepath: 文件保存路径
        llm_adapter: LLM适配器
        embedding_adapter: 嵌入适配器
    
    返回:
        dict: 包含状态和结果的字典
    """
    # 导入章节目录解析函数
    from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
    try:
        character_state_file = os.path.join(filepath, "角色状态.txt")
        result = {"status": "error", "message": "", "character_state": ""}
        
        # 1. 使用LLM检索当前生成的章节草稿，检索出文件内的所有角色名
        character_names_prompt = Character_name_prompt.format(novel_number=chap_num, chapter_title=chapter_title, chapter_text=chapter_text)
        character_names_result = invoke_with_cleaning(llm_adapter, character_names_prompt)
        
        # 2. 直接使用程序根据角色名，检索"角色数据库.txt"文件
        all_character_file = os.path.join(filepath, "角色数据库.txt")
        character_db_content = ""
        
        # 检查角色数据库.txt是否存在，如果不存在或为空则创建基本结构
        if os.path.exists(all_character_file):
            character_db_content = read_file(all_character_file)
        
        # 如果文件不存在或为空，创建基本结构
        if not character_db_content or character_db_content.strip() == "":
            character_db_content = """# 角色数据库
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


"""
            save_string_to_txt(character_db_content, all_character_file)
            logging.info("已创建角色数据库.txt基本结构")
        
        # 解析角色名结果，提取角色名列表
        character_names = []
        # 尝试解析JSON格式的角色名列表
        try:
            character_names = json.loads(character_names_result)
        except:
            # 如果不是JSON格式，尝试直接按行分割
            character_names = [name.strip() for name in character_names_result.split('\n') if name.strip()]
            # 如果还是没有提取到，尝试使用正则表达式提取
            if not character_names:
                character_names = re.findall(r'[\[\(]?([^\[\]\(\)]+)[\]\)]?', character_names_result)
                character_names = [name.strip() for name in character_names if name.strip()]
        
        logging.info(f"处理后的角色名列表: {character_names}")
        
        # 查找角色编号和正式名称
        character_ids = {}
        max_id = 0
        
        # 从角色数据库中提取现有角色ID
        # 匹配角色索引表中的行
        id_pattern = re.compile(r'\| (ID\d+) \| ([^|]+) \|', re.MULTILINE)
        for match in id_pattern.finditer(character_db_content):
            char_id = match.group(1)
            char_name = match.group(2).strip()
            character_ids[char_name] = char_id
            # 提取ID数字部分
            id_num = int(char_id[2:])
            max_id = max(max_id, id_num)
        
        # 为新角色分配ID
        for char_name in character_names:
            if char_name not in character_ids:
                max_id += 1
                character_ids[char_name] = f"ID{max_id:04d}"
                
                # 不在这里添加到角色数据库.txt，而是在后面的表格更新逻辑中统一处理
                logging.info(f"为新角色 {char_name} 分配ID: {character_ids[char_name]}")
        
        logging.info(f"角色ID映射: {character_ids}")
        
        # 3. 根据检索出的角色编号，从角色状态向量库中检索出角色的完整角色状态
        old_states = {}
        vectorstore = None
        
        # 检查角色状态向量库是否存在
        if embedding_adapter:
            # 从character_state_collection加载向量库
            vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
            
            # 如果向量库不存在，尝试初始化一个空的向量库
            if not vectorstore and embedding_adapter:
                logging.info("角色状态向量库不存在，尝试初始化新的向量库...")
                try:
                    # 初始化一个空的向量库，后续会添加内容
                    vectorstore = init_vector_store(embedding_adapter, ["初始化角色状态向量库"], filepath, "character_state_collection", 
                                                  metadatas=[{"id": "init", "name": "init", "chapter": 0, "type": "init"}], 
                                                  ids=["init_0"])
                    if vectorstore:
                        # 删除初始化用的文档
                        vectorstore.delete(where={"type": "init"})
                        logging.info("成功初始化角色状态向量库 character_state_collection")
                    else:
                        logging.warning("初始化角色状态向量库 character_state_collection 失败")
                except Exception as e:
                    logging.warning(f"初始化角色状态向量库时出错: {e}")
            
            if vectorstore:
                for char_name, char_id in character_ids.items():
                    try:
                        # 只使用角色ID作为查询条件，不再使用type字段
                        # ChromaDB要求where参数只有一个操作符
                        retrieved_docs = vectorstore.get(where={"character_id": char_id}, include=["metadatas", "documents"]) # MODIFIED
                        
                        # 如果通过character_id没有找到，则尝试使用character_name查询
                        if not retrieved_docs or not retrieved_docs.get('ids'):
                            retrieved_docs = vectorstore.get(where={"character_name": char_name}, include=["metadatas", "documents"]) # MODIFIED
                        
                        if retrieved_docs and retrieved_docs.get('ids'):
                            # 找到最新的角色状态
                            latest_chapter = -1
                            latest_doc = ""
                            
                            for i, doc_id in enumerate(retrieved_docs['ids']):
                                metadata = retrieved_docs['metadatas'][i]
                                # 确认这是角色状态类型的文档
                                if metadata.get('type') == "character_state":
                                    doc_chapter = metadata.get('chapter', -1)
                                    
                                    if doc_chapter > latest_chapter:
                                        latest_chapter = doc_chapter
                                        latest_doc = retrieved_docs['documents'][i]
                            
                            if latest_doc:
                                old_states[char_name] = latest_doc
                                logging.info(f"从向量库中检索到角色 {char_name} 的状态")
                    except Exception as e:
                        logging.warning(f"检索角色 {char_name} 的状态时出错: {e}")
                        logging.warning(traceback.format_exc())
        
        # 清空角色状态.txt文件，并将检索出来的角色状态写入该文件
        # 将检索到的角色状态组合成字符串
        old_state = "\n\n".join(old_states.values()) if old_states else "无"
        
        # 将角色状态写入角色状态.txt文件
        try:
            with open(character_state_file, 'w', encoding='utf-8') as f:
                f.write(old_state)
            logging.info(f"已将检索到的角色状态写入文件: {character_state_file}")
        except Exception as e:
            logging.error(f"写入角色状态文件时出错: {e}")
            logging.error(traceback.format_exc())
            
        # 如果向量库不存在，则创建一个新的角色状态向量库
        if not vectorstore and embedding_adapter:
            logging.info("创建新的角色状态向量库: character_state_collection")
            vectorstore = init_vector_store(embedding_adapter, ["初始化角色状态向量库"], filepath, "character_state_collection")
            if vectorstore:
                # 删除初始化用的文档
                try:
                    vectorstore.delete(where={"document": "初始化角色状态向量库"})
                except:
                    pass
                logging.info("成功创建角色状态向量库 character_state_collection")

        
        # 4. 使用LLM根据update_character_state_prompt的提示词，按照格式输出角色的新状态
        # 从章节目录.txt中获取章节信息
        directory_file = os.path.join(filepath, "章节目录.txt")
        chapter_info = {}
        
        if os.path.exists(directory_file):
            directory_content = read_file(directory_file)
            if directory_content:
                # 使用章节目录解析函数获取章节信息
                # 使用传入的章节编号chap_num，而不是硬编码的值
                chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
        
        # 设置变量，优先使用从章节目录中解析出的信息
        # 尝试从小说设定文件中获取genre信息
        novel_setting_file = os.path.join(filepath, "小说设定.txt")
        genre = ""
        if os.path.exists(novel_setting_file):
            novel_setting = read_file(novel_setting_file)
            genre_match = re.search(r"类型：([^\n]+)", novel_setting)
            if genre_match:
                genre = genre_match.group(1).strip()
        
        # 尝试从章节目录中获取总章节数
        directory_file = os.path.join(filepath, "章节目录.txt")
        volume_count = 1
        num_chapters = 1
        if os.path.exists(directory_file):
            directory_content = read_file(directory_file)
            if directory_content:
                # 计算章节总数
                chapter_pattern = re.compile(r'第\s*(\d+)\s*章')
                chapters = chapter_pattern.findall(directory_content)
                if chapters:
                    chapters = [int(c) for c in chapters]
                    num_chapters = max(chapters)
                
                # 尝试获取卷数
                volume_pattern = re.compile(r'第[一二三四五六七八九十]卷|第\s*(\d+)\s*卷')
                volumes = volume_pattern.findall(directory_content)
                if volumes:
                    volume_count = len(volumes) if isinstance(volumes[0], str) and not volumes[0].isdigit() else max([int(v) for v in volumes if v and v.isdigit()])
                    volume_count = max(1, volume_count)
        # 根据章节编号确定当前卷号
        if num_chapters > 0 and volume_count > 0:
            chapters_per_volume = num_chapters // volume_count
            if chapters_per_volume > 0:
                volume_number = (chap_num - 1) // chapters_per_volume + 1
            else:
                volume_number = 1
        else:
            volume_number = 1
            
        novel_number = chap_num  # 使用已有的章节编号参数
        # chapter_title 已经作为参数传入
        # 计算章节字数
        word_number = len(chapter_text) if chapter_text else 0
        chapter_role = chapter_info.get('chapter_role', '')
        chapter_purpose = chapter_info.get('chapter_purpose', '')
        suspense_type = chapter_info.get('suspense_type', '')
        emotion_evolution = chapter_info.get('emotion_evolution', '')
        foreshadowing = chapter_info.get('foreshadowing', '')
        plot_twist_level = chapter_info.get('plot_twist_level', '')
        chapter_summary = chapter_info.get('chapter_summary', '')
        
        # 构建角色数据库字符串，包含角色名和对应的ID
        Character_Database = "\n".join([f"{char_id}: {char_name}" for char_name, char_id in character_ids.items()])
        
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
            Character_Database=Character_Database
        )
        new_character_state = invoke_with_cleaning(llm_adapter, char_update_prompt)
        
        if not new_character_state:
            result["message"] = "生成角色状态失败"
            return result
            
        save_string_to_txt(new_character_state, character_state_file)
        
        # 5. 按照分析出的角色编号，删除角色状态向量库内的对应内容，并重新向量化新的角色状态
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

        
        # 6. 按照新的角色状态，更新角色数据库.txt
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
                faction_match = re.search(r'所属组织/势力：([^\n]+)', block)
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
                
                # 提取角色权重
                weight_match = re.search(r'角色权重：(\d+)', block)
                if weight_match:
                    weight = weight_match.group(1).strip()
                
                # 提取最后出场位置（从位置轨迹中提取最后一个位置条目的场景名称）
                location_section = re.search(r'位置轨迹：\s*\n([\s\S]*?)(?:\n\n|\n\[|$)', block)
                if location_section:
                    location_text = location_section.group(1).strip()
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
        if not os.path.exists(all_character_file) or not read_file(all_character_file).strip():
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
            save_string_to_txt(basic_structure, all_character_file)
            logging.info("已创建角色数据库.txt基本结构")
        
        # 更新角色数据库.txt文件中的表格
        if os.path.exists(all_character_file) and updated_chars:
            character_db_content = read_file(all_character_file)
            
            # 定义新的表头和分隔符
            new_table_header = "| ID编号 | 正式名称 | 其他称谓集合 | 势力归属 | 当前状态 | 最后出场章 | 最后出场位置 | 权重等级 |"
            new_table_separator = "|--------|----------|----------|----------|----------|------------|----------|----------|"
            
            # 定义旧的表头和分隔符，用于查找和替换
            old_table_header_pattern = r"\| ID编号 \| 正式名称 \| 其他称谓集合 \| 势力归属 \| 当前状态 \| 最后出场章 \| 权重等级 \|"
            old_table_separator_pattern = r"\|--------\|----------\|----------\|----------\|----------\|------------\|----------\|"
            
            # 替换旧的表头和分隔符（如果存在）
            character_db_content = re.sub(old_table_header_pattern, "", character_db_content)
            character_db_content = re.sub(old_table_separator_pattern, "", character_db_content)
            
            # 查找表格位置 (使用新的表头)
            table_header = new_table_header
            table_separator = new_table_separator
            
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
                new_stats_text = f"""## 分类统计\n### 权重分布\n主角级（96-100）：{weight_counts['96-100']}\n关键角色（81-95）：{weight_counts['81-95']}\n核心配角（61-80）：{weight_counts['61-80']}\n次要配角（41-60）：{weight_counts['41-60']}\n单元角色（21-40）：{weight_counts['21-40']}\n背景角色（1-20）：{weight_counts['1-20']}\n### 角色信息\n角色总数：{total_chars}\n核心角色（权重≥81）：{core_chars}\n活跃角色（最近X章出场）：0 # TODO: Implement active character tracking\n势力分类：无 # TODO: Implement faction tracking\n\n## 角色索引表（唯一标识区）"""
                
                # 更新分类统计部分
                stats_pattern = re.compile(r'## 分类统计.*?## 角色索引表（唯一标识区）', re.DOTALL)
                character_db_content = stats_pattern.sub(new_stats_text, character_db_content)
                
                save_string_to_txt(character_db_content, all_character_file)
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
                faction_match = re.search(r'所属组织/势力：([^\n]+)', block)
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
                
                # 提取角色权重
                weight_match = re.search(r'角色权重：(\d+)', block)
                if weight_match:
                    weight = weight_match.group(1).strip()
                
                # 提取最后出场位置（从位置轨迹中提取最后一个位置条目的场景名称）
                location_section = re.search(r'位置轨迹：\s*\n([\s\S]*?)(?:\n\n|\n\[|$)', block)
                if location_section:
                    location_text = location_section.group(1).strip()
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
        if not os.path.exists(all_character_file) or not read_file(all_character_file).strip():
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
            save_string_to_txt(basic_structure, all_character_file)
            logging.info("已创建角色数据库.txt基本结构")
        
        # 更新角色数据库.txt文件中的表格
        if os.path.exists(all_character_file) and updated_chars:
            character_db_content = read_file(all_character_file)
            
            # 定义新的表头和分隔符
            new_table_header = "| ID编号 | 正式名称 | 其他称谓集合 | 势力归属 | 当前状态 | 最后出场章 | 最后出场位置 | 权重等级 |"
            new_table_separator = "|--------|----------|----------|----------|----------|------------|----------|----------|"
            
            # 定义旧的表头和分隔符，用于查找和替换
            old_table_header_pattern = r"\| ID编号 \| 正式名称 \| 其他称谓集合 \| 势力归属 \| 当前状态 \| 最后出场章 \| 权重等级 \|"
            old_table_separator_pattern = r"\|--------\|----------\|----------\|----------\|----------\|------------\|----------\|"
            
            # 替换旧的表头和分隔符（如果存在）
            character_db_content = re.sub(old_table_header_pattern, "", character_db_content)
            character_db_content = re.sub(old_table_separator_pattern, "", character_db_content)
            
            # 查找表格位置 (使用新的表头)
            table_header = new_table_header
            table_separator = new_table_separator
            
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
                for i in range(2, len(table_lines)):
                    line = table_lines[i].strip()
                    if not line or line.startswith('##'):
                        continue
                    
                    # 提取ID
                    id_match = re.match(r'\|\s*(ID\d+)\s*\|', line)
                    if id_match:
                        char_id = id_match.group(1)
                        existing_ids.add(char_id)
                        
                        # 如果这个角色在更新列表中，则更新行
                        if char_id in updated_chars:
                            char_info = updated_chars[char_id]
                            new_line = f"| {char_id} | {char_info['name']} | {char_info['other_names']} | {char_info['faction']} | {char_info['status']} | {char_info['last_chapter']} | {char_info['weight']} |"
                            new_table.append(new_line)
                        else:
                            # 保留原行
                            new_table.append(line)
                
                # 添加新角色
                for char_id, char_info in updated_chars.items():
                    if char_id not in existing_ids:
                        new_line = f"| {char_id} | {char_info['name']} | {char_info['other_names']} | {char_info['faction']} | {char_info['status']} | {char_info['last_chapter']} | {char_info['weight']} |"
                        new_table.append(new_line)
                
                # 添加在角色状态中没有但在character_ids中有的角色（新分配ID的角色）
                for char_name, char_id in character_ids.items():
                    if char_id not in existing_ids and char_id not in updated_chars:
                        # 为新角色创建一个基本行
                        new_line = f"| {char_id} | {char_name} | | 无归属 | 活跃 | 第{chap_num}章 | 未知 | 50 |"
                        new_table.append(new_line)
                        logging.info(f"添加新角色到表格: {char_name} ({char_id})")
                
                # 替换表格
                new_table_content = '\n'.join(new_table)
                
                # 删除表格上方可能存在的ID列表（之前的添加方式）
                index_section = "## 角色索引表（唯一标识区）"
                index_section_start = character_db_content.find(index_section) + len(index_section)
                table_start_clean = character_db_content.find(table_header)
                
                if index_section_start < table_start_clean:
                    # 删除索引区和表格之间的ID列表
                    pre_table_content = character_db_content[index_section_start:table_start_clean].strip()
                    # 只保留不包含ID的行
                    clean_pre_table_lines = [line for line in pre_table_content.split('\n') if not re.match(r'ID\d+：', line.strip())]
                    clean_pre_table_content = '\n'.join(clean_pre_table_lines)
                    if clean_pre_table_content:
                        clean_pre_table_content = '\n' + clean_pre_table_content + '\n'
                    else:
                        clean_pre_table_content = '\n\n'
                    
                    # 重建内容
                    character_db_content = character_db_content[:index_section_start] + clean_pre_table_content + new_table_content + character_db_content[table_end:]
                else:
                    # 直接替换表格
                    character_db_content = character_db_content[:table_start] + new_table_content + character_db_content[table_end:]
            
            # 更新分类统计
            stats_section = "## 分类统计"
            if stats_section in character_db_content:
                # 计算角色总数
                total_chars = len(updated_chars)
                
                # 计算各权重等级的角色数量
                weight_counts = {
                    "主角级": 0,  # 96-100
                    "关键角色": 0,  # 81-95
                    "核心配角": 0,  # 61-80
                    "次要配角": 0,  # 41-60
                    "单元角色": 0,  # 21-40
                    "背景角色": 0   # 1-20
                }
                
                # 计算核心角色数量（权重≥81）
                core_chars = 0
                
                # 收集势力信息
                factions = {}
                
                for char_id, char_info in updated_chars.items():
                    try:
                        weight = int(char_info['weight'])
                        
                        # 更新权重分布
                        if weight >= 96:
                            weight_counts["主角级"] += 1
                        elif weight >= 81:
                            weight_counts["关键角色"] += 1
                            core_chars += 1
                        elif weight >= 61:
                            weight_counts["核心配角"] += 1
                        elif weight >= 41:
                            weight_counts["次要配角"] += 1
                        elif weight >= 21:
                            weight_counts["单元角色"] += 1
                        else:
                            weight_counts["背景角色"] += 1
                        
                        # 更新势力信息
                        faction = char_info['faction']
                        if faction != "无归属" and faction.strip():
                            if faction in factions:
                                factions[faction] += 1
                            else:
                                factions[faction] = 1
                    except ValueError:
                        logging.warning(f"角色 {char_id} 的权重值 '{char_info['weight']}' 无法转换为整数")
                
                # 更新权重分布
                for weight_level, count in weight_counts.items():
                    pattern = f"{weight_level}.*?：\d+"
                    replacement = f"{weight_level}：{count}"
                    if re.search(pattern, character_db_content, re.DOTALL):
                        character_db_content = re.sub(pattern, replacement, character_db_content)
                
                # 更新角色总数
                stats_pattern = r'角色总数：\d+'
                if re.search(stats_pattern, character_db_content):
                    character_db_content = re.sub(stats_pattern, f"角色总数：{total_chars}", character_db_content)
                else:
                    # 如果没有角色总数行，则添加一行
                    stats_section_start = character_db_content.find(stats_section) + len(stats_section)
                    character_db_content = character_db_content[:stats_section_start] + f"\n角色总数：{total_chars}" + character_db_content[stats_section_start:]
                
                # 更新核心角色数量
                core_chars_pattern = r'核心角色（权重≥81）：\d+'
                if re.search(core_chars_pattern, character_db_content):
                    character_db_content = re.sub(core_chars_pattern, f"核心角色（权重≥81）：{core_chars}", character_db_content)
                
                # 更新活跃角色数量（最近本章出场）
                active_chars_pattern = r'活跃角色（最近\d+章出场）：\d+'
                active_chars_replacement = f"活跃角色（最近{chap_num}章出场）：{total_chars}"
                if re.search(active_chars_pattern, character_db_content):
                    character_db_content = re.sub(active_chars_pattern, active_chars_replacement, character_db_content)
                
                # 更新势力分类
                faction_str = "势力分类："
                if factions:
                    faction_str += ", ".join([f"{faction}({count})" for faction, count in factions.items()])
                else:
                    faction_str += "无"
                
                faction_pattern = r'势力分类：.*'
                if re.search(faction_pattern, character_db_content):
                    character_db_content = re.sub(faction_pattern, faction_str, character_db_content)

            
            # 保存更新后的角色数据库文件
            save_string_to_txt(character_db_content, all_character_file)
            logging.info("角色数据库.txt文件已更新")
        
        # 向量化角色状态
        try:
            # 加载向量库
            vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
            
            # 解析角色状态，提取每个角色的信息
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
                            # 先尝试使用character_id删除
                            vectorstore.delete(where={"character_id": char_id, "type": "character_state"})
                            # 再尝试使用character_name删除，确保清理干净
                            vectorstore.delete(where={"character_name": char_name, "type": "character_state"})
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
                    vectorstore = init_vector_store(embedding_adapter, char_texts, filepath, "character_state_collection", 
                                                   metadatas=char_metadatas, ids=char_ids)
                    if vectorstore:
                        logging.info("成功初始化角色状态向量库 character_state_collection")
                    else:
                        logging.warning("初始化角色状态向量库 character_state_collection 失败")
            except Exception as e:
                logging.warning(f"向量化角色状态时出错: {e}")
                logging.warning(traceback.format_exc())
        except Exception as e:
            logging.error(f"向量化角色状态时出现异常: {str(e)}")
            logging.error(traceback.format_exc())
               
        result["status"] = "success"
        result["character_state"] = new_character_state
        return result
        
    except Exception as e:
        logging.error(f"更新角色状态时出现异常: {str(e)}")
        logging.error(traceback.format_exc())
        return {"status": "error", "message": str(e), "character_state": ""}