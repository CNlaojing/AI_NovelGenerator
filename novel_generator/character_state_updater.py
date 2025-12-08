# novel_generator/character_state_updater.py
# -*- coding: utf-8 -*-
"""
角色状态更新相关功能
"""
import os
import traceback
import re
from utils import read_file, save_string_to_txt
from novel_generator.common import invoke_with_cleaning
from prompt_definitions import Character_name_prompt, update_character_state_prompt

def extract_character_index_table(file_path: str) -> str:
    """
    从 角色数据库.txt 文件中精确提取 ## 角色索引表（唯一标识区） 部分，
    并只返回 ID编号, 正式名称, 其他称谓集合 这三列的内容。
    """
    try:
        content = read_file(file_path)
        if not content:
            return ""
        
        lines = content.splitlines()
        table_start_index = -1
        in_table = False
        extracted_lines = []

        for line in lines:
            stripped_line = line.strip()
            if stripped_line == "## 角色索引表（唯一标识区）":
                in_table = True
                continue # 开始寻找表格内容，跳过标题行

            if in_table:
                # 忽略表头和分隔线
                if stripped_line.startswith('| ID编号') or stripped_line.startswith('|--'):
                    continue
                
                if stripped_line.startswith('|') and stripped_line.endswith('|'):
                    columns = [col.strip() for col in stripped_line.split('|')]
                    # columns[0] is empty because of the leading '|'
                    if len(columns) > 4: # ID, Name, Aliases, ...
                        char_id = columns[1]
                        char_name = columns[2]
                        char_aliases = columns[3]
                        extracted_lines.append(f"| {char_id} | {char_name} | {char_aliases} |")
        
        if extracted_lines:
            # 构建一个简化的表头
            header = "| ID编号 | 正式名称 | 其他称谓集合 |\n|---|---|---|"
            return header + "\n" + "\n".join(extracted_lines)
        else:
            return "角色索引表未找到或内容为空。"
            
    except Exception:
        return "读取或解析角色数据库时出错。"

def update_character_db_txt(db_txt_path: str, character_store: dict, log_func=print):
    """
    [重构 V4] 使用从 .md 文件加载的 character_store (字典) 来生成结构化的 角色数据库.txt (Markdown格式)。
    此版本使用更精确的数据提取逻辑。
    """
    try:
        log_func(f"  -> 开始根据角色状态生成新的 角色数据库.txt...")

        # --- 数据处理 ---
        characters_for_table = []
        factions = {}
        weight_tiers = {
            "主角级（96-100）": 0, "核心配角（81-95）": 0, "关键角色（61-80）": 0,
            "次要配角（41-60）": 0, "单元角色（21-40）": 0, "背景角色（1-20）": 0,
        }

        def _get_weight_tier_name(weight):
            if 96 <= weight <= 100: return "主角级（96-100）"
            if 81 <= weight <= 95: return "核心配角（81-95）"
            if 61 <= weight <= 80: return "关键角色（61-80）"
            if 41 <= weight <= 60: return "次要配角（41-60）"
            if 21 <= weight <= 40: return "单元角色（21-40）"
            if 1 <= weight <= 20: return "背景角色（1-20）"
            return None

        for char_id, char_data in character_store.items():
            char_name = char_data.get("正式名称", char_id)
            
            # -- 提取数据 (根据用户最新规则) --
            base_info = char_data.get("基础信息", {})
            weight_str = base_info.get("角色权重", "0")
            weight_match = re.search(r'(\d+)', weight_str)
            weight = int(weight_match.group(1)) if weight_match else 0
            
            faction = char_data.get("势力特征", {}).get("势力归属", "无")
            status = char_data.get("生命状态", {}).get("身体状态", "未知")
            aliases = base_info.get("其他称谓", "无")
            location = char_data.get("位置详情", "未知")
            last_chapter = base_info.get("最后出场章节", "未记录")
            
            last_chapter_num = 0
            match = re.search(r'\d+', last_chapter)
            if match:
                last_chapter_num = int(match.group(0))

            # -- 填充表格数据 --
            characters_for_table.append({
                "id": char_id, "name": char_name, "aliases": aliases,
                "faction": faction, "status": status, "location": location, "weight": weight,
                "last_chapter": last_chapter, "last_chapter_num": last_chapter_num
            })

            # -- 统计信息 --
            tier_name = _get_weight_tier_name(weight)
            if tier_name: weight_tiers[tier_name] += 1
            
            if faction != "无" and faction:
                if faction not in factions: factions[faction] = []
                factions[faction].append(f"{char_id}-{char_name}")

        # --- 构建Markdown文本 ---
        md_content = ["# 角色数据库", ""]
        
        md_content.append("## 分类统计")
        md_content.append("### 权重分布")
        for tier, count in weight_tiers.items(): md_content.append(f"{tier}：{count}")
        md_content.append("")

        md_content.append("### 角色信息")
        total_chars = len(characters_for_table)
        core_chars = weight_tiers["主角级（96-100）"] + weight_tiers["核心配角（81-95）"]
        current_chap = 0
        if characters_for_table:
            current_chap = max(char.get("last_chapter_num", 0) for char in characters_for_table)
        
        active_chars_count = sum(1 for char in characters_for_table if char.get("last_chapter_num", 0) >= current_chap - 20)

        md_content.append(f"角色总数：{total_chars}")
        md_content.append(f"核心角色（权重≥81）：{core_chars}")
        md_content.append(f"活跃角色（最近20章出场）：{active_chars_count}")
        md_content.append("")

        md_content.append("### 势力分类")
        md_content.append("| 势力名称 | 成员列表 |")
        md_content.append("|----------|----------|")
        if factions:
            for faction_name, members in sorted(factions.items()):
                md_content.append(f"| {faction_name} | {'、'.join(members)} |")
        else:
            md_content.append("| (无) | (无) |")
        md_content.append("")

        md_content.append("## 角色索引表（唯一标识区）")
        md_content.append("")
        md_content.append("| ID编号 | 正式名称 | 其他称谓集合 | 势力归属 | 当前状态 | 最后出场章节 | 位置详情 | 权重等级 |")
        md_content.append("|--------|----------|----------|----------|----------|----------|----------|----------|")
        
        sorted_characters = sorted(characters_for_table, key=lambda x: x['weight'], reverse=True)
        
        for char in sorted_characters:
            last_chapter = char.get("last_chapter", "未记录")
            md_content.append(f"| {char['id']} | {char['name']} | {char['aliases']} | {char['faction']} | {char['status']} | {last_chapter} | {char['location']} | {char['weight']} |")
        
        final_md = "\n".join(md_content)
        save_string_to_txt(final_md, db_txt_path)
        log_func(f"✅ 角色数据库.txt 已成功生成并更新。")

    except Exception as e:
        log_func(f"❌ 生成 角色数据库.txt 时出错: {e}")
        log_func(traceback.format_exc())

def parse_character_state_md(md_content: str) -> dict:
    """
    [重构 V4] 解析 角色状态.md 的内容为一个字典。
    此版本使用独立的正则表达式直接从文本块中提取每个字段，以确保稳健性。
    """
    store = {}
    if not md_content:
        return store
        
    character_blocks = re.split(r'\n(?=ID\d+[\s：:])', md_content)
    
    for block in character_blocks:
        block = block.strip()
        if not block: continue

        # 1. ID 和 正式名称
        header_match = re.search(r'^(ID\d+)[\s：:]*(.*)', block)
        if not header_match: continue
        char_id = header_match.group(1).strip()
        char_name = header_match.group(2).strip() or char_id

        char_data = {"正式名称": char_name}

        # 2. 其他称谓集合
        aliases_match = re.search(r'-\s*其他称谓：(.*)', block)
        char_data["其他称谓集合"] = aliases_match.group(1).strip() if aliases_match else "无"

        # 3. 权重等级
        weight_match = re.search(r'-\s*角色权重：\s*(\d+)', block)
        char_data["权重等级"] = int(weight_match.group(1)) if weight_match else 0

        # 4. 势力归属
        faction_match = re.search(r'  所属势力：(.*)', block)
        char_data["势力归属"] = faction_match.group(1).strip() if faction_match else "无"

        # 5. 当前状态
        status_match = re.search(r'-\s*身体状态：(.*)', block)
        char_data["当前状态"] = status_match.group(1).strip() if status_match else "未知"

        # 6. 最后出场章节
        last_chapter_match = re.search(r'-\s*最后出场章节：(.*)', block)
        if last_chapter_match:
            char_data.setdefault("基础信息", {})["最后出场章节"] = last_chapter_match.group(1).strip()

        # 7. 位置详情 (找到最新章节)
        location_lines = re.findall(r'位置轨迹：\n((?:- .+\n?)*)', block, re.MULTILINE)
        if location_lines:
            all_tracks = []
            for line in location_lines[0].strip().split('\n'):
                line = line.lstrip('- ').strip()
                match = re.search(r'所在章节：第(\d+)章', line)
                if match:
                    all_tracks.append((line, int(match.group(1))))
            
            if all_tracks:
                latest_track = max(all_tracks, key=lambda x: x[1])
                char_data["位置详情"] = latest_track[0]
            else:
                # 如果有位置轨迹但没有章节信息，取第一条
                first_line = location_lines[0].strip().split('\n')[0].lstrip('- ').strip()
                char_data["位置详情"] = first_line
        else:
            char_data["位置详情"] = "未知"
            
        store[char_id] = char_data
            
    return store

def update_character_states(chapter_text, chapter_title, chap_num, filepath, llm_adapter, chapter_blueprint_content="", log_func=None, genre="", volume_count=0, num_chapters=0, volume_number=1, **kwargs):
    """
    使用基于Markdown的工作流更新角色状态，并同步回 .txt 数据库。
    """
    def _log(message, level="info"):
        if log_func:
            log_func(message)
        else:
            print(message)

    try:
        result = {"status": "error", "message": "", "character_state": ""}
        
        character_state_md_path = os.path.join(filepath, "定稿内容", "角色状态.md")
        character_db_txt_path = os.path.join(filepath, "角色数据库.txt")

        _log("步骤1: 识别本章出场角色...")
        # 修改：只提取角色索引表部分
        character_db_content = extract_character_index_table(character_db_txt_path) or "角色数据库为空或索引表未找到。"
        character_names_prompt = Character_name_prompt.format(
            novel_number=chap_num,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            Character_Database=character_db_content
        )
        character_id_result = invoke_with_cleaning(llm_adapter, character_names_prompt, log_func=log_func)
        
        if not character_id_result or character_id_result.strip() == "(空)":
            _log("    ℹ️ 本章未涉及角色状态变化，跳过更新。")
            result["status"] = "success"
            result["message"] = "LLM未能识别出任何角色，或识别结果为空。"
            result["character_state"] = ""
            return result
        _log(f"  -> LLM识别出的本章角色:\n---\n{character_id_result}\n---")

        _log("步骤2: 准备旧角色状态的Markdown数据...")
        old_state_md = read_file(character_state_md_path) or "角色状态文件为空，请根据本章内容创建。"
        _log(f"  -> 已加载旧的Markdown状态。")

        _log("步骤3: 调用LLM生成新的Markdown格式角色状态...")
        char_update_prompt = update_character_state_prompt.format(
            genre=genre,
            volume_count=volume_count,
            num_chapters=num_chapters,
            volume_number=volume_number,
            novel_number=chap_num,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            old_state=old_state_md,
            Character_Database=character_id_result
        )
        new_state_md_str = invoke_with_cleaning(llm_adapter, char_update_prompt, log_func=log_func)
        
        if not new_state_md_str or new_state_md_str.strip() == "(空)" or "{}" in new_state_md_str:
            _log("    ℹ️ LLM返回的角色状态为空或无变化，跳过更新。")
            result["status"] = "success"
            result["message"] = "LLM返回的角色状态为空或无变化。"
            result["character_state"] = ""
            return result

        _log("步骤4: 合并并保存新的Markdown状态...")
        from novel_generator.json_utils import _markdown_to_json, load_store, save_store
        
        # 解析LLM返回的新状态
        new_states_dict = _markdown_to_json(new_state_md_str, "character_state_collection")
        if not new_states_dict:
            _log("    ℹ️ LLM返回的角色状态无法解析，跳过更新。")
            result["status"] = "success"
            result["message"] = "LLM返回的角色状态无法解析。"
            return result

        # 加载现有的所有角色状态
        existing_states_dict = load_store(filepath, "character_state_collection")
        
        # 合并新旧状态
        existing_states_dict.update(new_states_dict)
        
        # 使用 save_store 保存，它会自动处理排序和写入
        if save_store(filepath, "character_state_collection", existing_states_dict):
            _log(f"✅ 角色状态Markdown文件 '{os.path.basename(character_state_md_path)}' 合并更新成功。")
        else:
            raise Exception("保存合并后的角色状态失败。")

        _log("步骤5: 同步更新 角色数据库.txt...")
        try:
            character_store = parse_character_state_md(new_state_md_str)
            if character_store:
                update_character_db_txt(character_db_txt_path, character_store, _log)
            else:
                _log("  -> ⚠️ 解析生成的Markdown内容为空，跳过同步。")
        except Exception as sync_e:
            _log(f"  -> ❌ 在同步到 角色数据库.txt 时发生错误: {sync_e}")

        result["status"] = "success"
        result["character_state"] = new_state_md_str
        return result

    except Exception as e:
        _log(f"更新角色状态时出现未处理的异常: {str(e)}", level="error")
        _log(traceback.format_exc(), level="error")
        raise
