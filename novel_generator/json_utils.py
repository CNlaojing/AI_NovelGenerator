# novel_generator/json_utils.py
# -*- coding: utf-8 -*-
"""
数据文件存储相关操作，使用Markdown格式。
"""
import os
import json
import logging
import traceback
import re
from typing import Dict, Any, List, Optional

# 定义集合名称到文件名的映射
COLLECTION_TO_FILENAME = {
    "character_state_collection": "角色状态.md",
    "foreshadowing_collection": "伏笔状态.md"
}

def get_store_path(filepath: str, collection_name: str) -> str:
    """获取Markdown存储文件的完整路径"""
    filename = COLLECTION_TO_FILENAME.get(collection_name)
    if not filename:
        raise ValueError(f"未知的集合名称: {collection_name}")
    return os.path.join(filepath, "定稿内容", filename)

def _json_to_markdown_character(char_data: Dict[str, Any]) -> str:
    """将单个角色JSON对象转换为Markdown字符串，严格遵循提示词格式。"""
    markdown_parts = []

    # 角色ID和名称
    char_id = char_data.get('ID', '')
    char_name = char_data.get('名称', '')
    markdown_parts.append(f"{char_id}：{char_name}")

    # 定义字段的顺序和缩进规则
    field_order = [
        ("基础信息", 0),
        ("最后出场章节", 0),
        ("位置轨迹", 0),
        ("势力特征", 0),
        ("关键事件记录", 0),
        ("生命状态", 0),
        ("持有物品", 0),
        ("技术能力", 0),
        ("关系网", 0),
        ("行为模式/决策偏好", 0),
        ("语言风格/对话关键词", 0),
        ("情感线状态", 0)
    ]

    for field_name, indent_level in field_order:
        if field_name not in char_data or not char_data[field_name]:
            continue

        content = char_data[field_name]
        markdown_parts.append(f"{field_name}：")

        if isinstance(content, dict):
            for key, value in content.items():
                if key == "势力归属" and isinstance(value, dict):
                    markdown_parts.append(f"- {key}：")
                    for sub_key, sub_value in value.items():
                        # 使用全角空格进行嵌套缩进
                        markdown_parts.append(f"  {sub_key}：{sub_value}")
                else:
                    markdown_parts.append(f"- {key}：{value}")
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    markdown_parts.append(f"- {item}")
                    continue

                if field_name == "位置轨迹":
                    item_copy = item.copy()
                    main_part = item_copy.pop("场景名称", "")
                    details = [main_part]
                    for key, value in item_copy.items():
                        details.append(f"{key}：{value}")
                    markdown_parts.append(f"- {'-'.join(details)}")
                elif field_name == "关键事件记录":
                    chapter_num = str(item.get('章节', '')).replace('第', '').replace('章', '')
                    markdown_parts.append(f"- 第{chapter_num}章：[{item.get('类型', '')}] {item.get('摘要', '')}")
                elif field_name == "关系网":
                    markdown_parts.append(f"- {item.get('对象', '')}：{item.get('关系', '')},关系强度[{item.get('关系强度', '')}],互动频率[{item.get('互动频率', '')}]")
                else: # For 持有物品, 技术能力, etc.
                    for key, value in item.items():
                        markdown_parts.append(f"- {key}：{value}")
    
    # 移除空行，并确保每个角色块之间有且仅有一个空行
    filtered_parts = [p for p in markdown_parts if p.strip()]
    return "\n".join(filtered_parts)

def _json_to_markdown_foreshadowing(fs_data: Dict[str, Any]) -> str:
    """将单个伏笔JSON对象转换为Markdown字符串。"""
    markdown_str = f"ID: {fs_data.get('ID', '')}\n"
    markdown_str += f"内容: {fs_data.get('内容', '')}\n"
    if '伏笔最后章节' in fs_data:
        markdown_str += f"伏笔最后章节: {fs_data.get('伏笔最后章节', '')}\n"
    return markdown_str

def save_store(filepath: str, collection_name: str, data: Dict[str, Any]) -> bool:
    """将数据存储保存到Markdown文件，并确保排序正确。"""
    md_path = get_store_path(filepath, collection_name)
    
    items = list(data.values())

    # --- 新增：根据集合名称进行不同的排序 ---
    if collection_name == "character_state_collection":
        def character_sort_key(item):
            # 提取权重等级，如果不存在则默认为0
            base_info = item.get('基础信息', {})
            weight_str = base_info.get('角色权重', '0')
            weight_match = re.search(r'(\d+)', weight_str)
            weight = int(weight_match.group(1)) if weight_match else 0

            # 提取ID的数字部分
            id_match = re.search(r'ID(\d+)', item.get("ID", ""))
            item_id_num = int(id_match.group(1)) if id_match else float('inf')

            # 仅按ID升序排序
            return item_id_num
        items.sort(key=character_sort_key)
        
    elif collection_name == "foreshadowing_collection":
        # 定义伏笔类型优先级
        type_priority = {"MF": 0, "AF": 1, "CF": 2, "SF": 3, "YF": 4}

        def foreshadowing_sort_key(item):
            item_id = item.get("ID", "")
            match = re.search(r'([A-Z]+)(\d+)', item_id)
            if match:
                prefix = match.group(1)
                num = int(match.group(2))
                # 优先按类型优先级，其次按数字ID升序
                return (type_priority.get(prefix, 99), num)
            return (99, float('inf')) # 未匹配的放到最后
        items.sort(key=foreshadowing_sort_key)
    # --- 排序逻辑结束 ---

    try:
        markdown_parts = []
        for item_data in items:
            if collection_name == "character_state_collection":
                markdown_parts.append(_json_to_markdown_character(item_data))
            elif collection_name == "foreshadowing_collection":
                markdown_parts.append(_json_to_markdown_foreshadowing(item_data))
        
        separator = "\n---\n"
        md_content = separator.join(markdown_parts)

        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        logging.info(f"数据已成功保存到: {md_path}")
        return True
    except IOError as e:
        logging.error(f"保存Markdown文件失败 {md_path}: {e}")
        return False

def _markdown_to_json(markdown_text: str, collection_name: str) -> Dict[str, Any]:
    """将特定格式的Markdown文本解析回JSON对象（字典）。"""
    json_data = {}
    if collection_name == "foreshadowing_collection":
        items = markdown_text.strip().split('---')
        for item_str in items:
            if not item_str.strip(): continue
            item_data = {}
            item_id = ""
            for line in item_str.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    if key == 'ID':
                        item_id = value
                    item_data[key] = value
            if item_id:
                json_data[item_id] = item_data
    elif collection_name == "character_state_collection":
        character_blocks = markdown_text.strip().split('---')
        for block in character_blocks:
            if not block.strip(): continue
            parsed_char = _final_perfect_parser(block)
            if parsed_char and "ID" in parsed_char:
                json_data[parsed_char["ID"]] = parsed_char
    return json_data

def load_store(filepath: str, collection_name: str) -> Dict[str, Any]:
    """从Markdown文件加载数据存储"""
    md_path = get_store_path(filepath, collection_name)
    if not os.path.exists(md_path):
        return {}
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return _markdown_to_json(content, collection_name)
    except IOError as e:
        logging.error(f"加载Markdown文件失败 {md_path}: {e}")
        return {}

def update_item_in_store(filepath: str, collection_name: str, item_id: str, new_data: Dict[str, Any]) -> bool:
    """更新Markdown存储中的单个条目"""
    store = load_store(filepath, collection_name)
    store[item_id] = new_data
    return save_store(filepath, collection_name, store)

def get_all_items_from_store(filepath: str, collection_name: str) -> List[Dict[str, Any]]:
    """从存储中获取所有条目。"""
    store = load_store(filepath, collection_name)
    return list(store.values())

def get_item_from_store(filepath: str, collection_name: str, item_id: str) -> Optional[Dict[str, Any]]:
    """从存储中根据 ID 获取单个条目。"""
    store = load_store(filepath, collection_name)
    return store.get(item_id)

def delete_item_from_store(filepath: str, collection_name: str, item_id: str) -> bool:
    """从存储中删除一个条目。"""
    store = load_store(filepath, collection_name)
    if item_id in store:
        del store[item_id]
        return save_store(filepath, collection_name, store)
    return True

def _final_perfect_parser(character_block: str) -> dict:
    """解析单个角色的Markdown块。"""
    lines = character_block.strip().split('\n')
    if not lines: return None
    
    top_level_match = re.match(r'(ID\d+)：([^\n]+)', lines[0])
    if not top_level_match: return None
    
    char_id, char_name = top_level_match.group(1), top_level_match.group(2).strip()
    parsed_data = {"ID": char_id, "名称": char_name}
    
    current_section = ""
    
    for line in lines[1:]:
        line = line.strip()
        if not line: continue

        section_match = re.match(r'^([^：\s]+)：$', line)
        if section_match:
            current_section = section_match.group(1)
            if current_section in ["基础信息", "生命状态", "势力特征", "行为模式/决策偏好", "语言风格/对话关键词", "情感线状态"]:
                parsed_data[current_section] = {}
            else:
                parsed_data[current_section] = []
            continue

        if not current_section: continue

        line = line.lstrip('-').strip()
        
        if current_section == "基础信息" and '：' in line:
            key, value = line.split('：', 1)
            parsed_data.setdefault("基础信息", {})[key.strip()] = value.strip()
            continue
        elif isinstance(parsed_data.get(current_section), list):
            item_dict = {}
            if current_section == "位置轨迹":
                parts = line.split('-')
                item_dict["场景名称"] = parts[0].strip()
                for part in parts[1:]:
                    if '：' in part:
                        key, value = part.split('：', 1)
                        item_dict[key.strip()] = value.strip()
            elif current_section == "关键事件记录":
                match = re.match(r'第([^：]+)：\[([^\]]+)\]\s*(.+)', line)
                if match: item_dict = {"章节": f"第{match.group(1).strip()}", "类型": match.group(2).strip(), "摘要": match.group(3).strip()}
            elif current_section == "关系网":
                match = re.match(r'([^:]+):\s*([^,]+),关系强度\[([^\]]+)\],互动频率\[([^\]]+)\]', line)
                if match: item_dict = {"对象": match.group(1).strip(), "关系": match.group(2).strip(), "关系强度": match.group(3).strip(), "互动频率": match.group(4).strip()}
            else: # 持有物品, 技术能力
                if '：' in line:
                    parts = line.split('：', 1)
                    item_dict = {parts[0].strip(): parts[1].strip()}
            if item_dict: parsed_data[current_section].append(item_dict)

        elif isinstance(parsed_data.get(current_section), dict):
            if '：' in line:
                key, value = line.split('：', 1)
                key, value = key.strip(), value.strip()
                # Handle nested '势力归属'
                if key == "势力归属":
                    parsed_data[current_section][key] = {}
                elif line.startswith('  - '): # Check for indentation for sub-items
                    sub_key, sub_value = line.lstrip('- ').split('：', 1)
                    if "势力归属" in parsed_data[current_section]:
                       parsed_data[current_section]["势力归属"][sub_key.strip()] = sub_value.strip()
                else:
                    parsed_data[current_section][key] = value
    return parsed_data

def save_json_store(filepath: str, collection_name: str, data: Dict[str, Any]) -> bool:
    """
    将数据存储保存到文件。
    这是 save_store 的别名，用于兼容旧的调用。
    """
    return save_store(filepath, collection_name, data)
