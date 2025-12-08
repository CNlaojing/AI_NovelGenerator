# -*- coding: utf-8 -*-
import os
from novel_generator.common import invoke_stream_with_cleaning, format_character_info
from llm_adapters import create_llm_adapter
from prompt_definitions import (
    volume_outline_prompt,
    subsequent_volume_prompt,
    final_volume_prompt,
    volume_design_format
)
from utils import read_file, save_string_to_txt, clear_file_content
from novel_generator.json_utils import load_store # 替换导入
import re

def parse_architecture_file(architecture_content: str) -> dict:
    """
    解析“小说设定.txt”文件内容，提取五个核心模块。
    """
    keys = [
        "volume_mission_statement", "worldview_and_conflict", "plotline_and_progression",
        "core_characters", "narrative_style"
    ]
    parsed_data = {key: "" for key in keys}

    # 使用 '---' 分割文件内容，并处理前后可能存在的空行
    # 分隔符是独立一行且前后可能有空格的 '---'
    blocks = re.split(r'^\s*---\s*$', architecture_content, flags=re.MULTILINE)
    
    # 第一个块是文件头，我们忽略它
    if not blocks or not blocks[0].strip().startswith("#==="):
        print("警告: 解析小说设定文件失败，未找到预期的文件头。")
        return {key: architecture_content for key in keys}

    module_contents = [block.strip() for block in blocks[1:]]
    
    # 应该有5个模块
    if len(module_contents) < 5:
        print(f"警告: 解析小说设定文件失败，模块数量不足 ({len(module_contents)}/5)。将使用完整内容作为每个模块的输入。")
        return {key: architecture_content for key in keys}

    # 将解析出的模块内容赋值给对应的键
    parsed_data["volume_mission_statement"] = module_contents[0]
    parsed_data["worldview_and_conflict"] = module_contents[1]
    parsed_data["plotline_and_progression"] = module_contents[2]
    parsed_data["core_characters"] = module_contents[3]
    parsed_data["narrative_style"] = module_contents[4]
            
    return parsed_data

def _chinese_to_int(s: str) -> int:
    """A simple converter for Chinese numerals up to 99, commonly used in volume/chapter numbers."""
    if not s or not isinstance(s, str):
        return 0
    if s.isdigit():
        return int(s)
    
    s = s.strip()
    num_map = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    
    if len(s) == 1:
        return num_map.get(s, 0)
        
    if s.startswith('十'):
        if len(s) == 1:
            return 10
        return 10 + num_map.get(s[1], 0)
        
    if s.endswith('十'):
        if len(s) == 2:
            return num_map.get(s[0], 0) * 10
        return 0 # Invalid format like '一二十'
        
    if '十' in s:
        parts = s.split('十')
        if len(parts) == 2 and parts[0] and parts[1]:
            return num_map.get(parts[0], 0) * 10 + num_map.get(parts[1], 0)
            
    return 0 # Fallback for more complex numbers or invalid strings

def extract_single_volume_data(full_text: str, volume_number: int) -> str:
    """
    Extracts data for a single volume from a text block by finding all volume headers
    and slicing the text between the target volume's header and the next one.
    This function is designed to work with the specific format '● 第X卷'.
    It now handles optional whitespace and more complex Chinese numerals.
    """
    if not full_text or not isinstance(full_text, str):
        return ""

    # Improved pattern: handles optional space, captures Chinese numerals or digits
    header_pattern = r"(?m)^●\s*第\s*([一二三四五六七八九十\d]+)\s*卷.*"
    
    matches = []

    # Find all volume headers and their positions
    for match in re.finditer(header_pattern, full_text):
        vol_str = match.group(1)
        vol_num = _chinese_to_int(vol_str)
        if vol_num > 0:
            matches.append({'num': vol_num, 'start': match.start()})

    if not matches:
        # If no headers are found, it might not be a multi-volume text block.
        # This could be a warning, but for now, we assume it's a single block of text
        # and return nothing, as the caller expects per-volume data.
        return ""

    # Sort matches by their start position in the text
    matches.sort(key=lambda x: x['start'])

    content_start = -1
    content_end = len(full_text)

    # Find the start of our target volume and the start of the next volume
    for i, match in enumerate(matches):
        if match['num'] == volume_number:
            content_start = match['start']
            # The end is the start of the next volume, or the end of the string if it's the last one
            if i + 1 < len(matches):
                content_end = matches[i+1]['start']
            break
    
    if content_start != -1:
        # Return the slice of text for the target volume
        return full_text[content_start:content_end].strip()
    else:
        # This case happens if the requested volume number doesn't exist in the text
        print(f"警告: 在多卷文本块中未找到第 {volume_number} 卷的内容。")
        return ""

def get_high_weight_characters(filepath: str, llm_adapter, weight_threshold: int = 91) -> str:
    """
    从角色状态JSON文件和角色数据库.txt中检索权重大于等于指定阈值的所有角色状态，
    并能同时处理新旧两种格式。
    
    参数:
        filepath: 项目文件路径
        llm_adapter: LLM适配器 (保留以兼容接口，但在此函数中未使用)
        weight_threshold: 权重阈值，默认为91
    
    返回:
        str: 权重大于等于指定阈值的角色状态内容，如果没有则返回空字符串
    """
    high_weight_characters = []
    processed_ids = set()

    # 1. 首先处理新的JSON格式数据
    try:
        character_store = load_store(filepath, "character_state_collection")
        if character_store:
            for char_id, char_data in character_store.items():
                try:
                    if not isinstance(char_data, dict): continue

                    weight_str = "0"
                    if '基础信息' in char_data and '角色权重' in char_data['基础信息']:
                        weight_str = char_data['基础信息']['角色权重']
                    elif 'weight' in char_data:
                        weight_str = char_data['weight']
                    
                    weight_match = re.search(r'\d+', str(weight_str))
                    actual_weight = int(weight_match.group(0)) if weight_match else 0
                    
                    if actual_weight >= weight_threshold:
                        character_name = char_data.get('名称', '未知角色')
                        print(f"找到高权重角色 (JSON源): {character_name} (ID: {char_id}, 权重: {actual_weight})")
                        
                        formatted_info = format_character_info(char_data)
                        if formatted_info:
                            high_weight_characters.append(formatted_info)
                            processed_ids.add(char_id)
                        else:
                            print(f"警告: 角色 {char_id} 的JSON数据为空或格式化失败。")

                except (ValueError, TypeError) as e:
                    print(f"解析角色 {char_id} 的JSON权重时出错: {e}")
                    continue
    except Exception as e:
        print(f"获取高权重角色状态 (JSON源) 时出错: {e}")

    # 2. 接着处理旧的.txt格式数据，以补充可能缺失的信息
    try:
        db_file = os.path.join(filepath, "角色数据库.txt")
        if os.path.exists(db_file):
            content = read_file(db_file)
            # 使用正则表达式分割每个角色的条目
            character_entries = re.split(r'\n(?=ID\d{4}：)', content)
            for entry in character_entries:
                if not entry.strip(): continue
                
                id_match = re.match(r'(ID\d{4})', entry)
                if not id_match: continue
                
                char_id = id_match.group(1)
                if char_id in processed_ids: continue # 如果已处理过，则跳过

                weight_match = re.search(r'角色权重：(\d+)', entry)
                actual_weight = int(weight_match.group(1)) if weight_match else 0

                if actual_weight >= weight_threshold:
                    name_match = re.match(r'ID\d{4}：(.*?)\n', entry)
                    character_name = name_match.group(1).strip() if name_match else '未知角色'
                    print(f"找到高权重角色 (TXT源): {character_name} (ID: {char_id}, 权重: {actual_weight})")
                    
                    # 对于旧格式，我们直接使用其原始文本内容
                    high_weight_characters.append(entry.strip())
                    processed_ids.add(char_id)

    except Exception as e:
        print(f"获取高权重角色状态 (TXT源) 时出错: {e}")

    # 3. 返回最终结果
    if high_weight_characters:
        result = "\n\n---\n\n".join(high_weight_characters)
        print(f"成功检索到 {len(high_weight_characters)} 个权重≥{weight_threshold}的角色状态")
        return result
    else:
        print(f"没有找到权重大于等于{weight_threshold}的角色")
        return ""

def Novel_volume_generate(
    llm_adapter,
    topic: str,
    filepath: str,
    number_of_chapters: int,
    word_number: int,
    volume_count: int,
    user_guidance: str = "",
    characters_involved: str = "",
    start_from_volume: int = None,
    generate_single: bool = False,
    num_characters: int = 8,
    character_prompt: str = "",
    genre: str = "",
    character_weight_threshold: int = 91,
    log_func=None
) -> str:
    """
    生成分卷大纲，兼容原版分卷文件名和内容格式
    """
    def _log(message):
        if log_func:
            log_func(message)
        else:
            print(message)

    _log(f"开始生成小说分卷，计划分为{volume_count}卷...")
    # 分卷文件名与原版保持一致
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    novel_setting_file = os.path.join(filepath, "小说设定.txt")
    if not os.path.exists(novel_setting_file):
        raise FileNotFoundError("请先生成小说架构(小说设定.txt)")
    novel_setting = read_file(novel_setting_file)
    # 解析小说设定文件
    parsed_setting = parse_architecture_file(novel_setting)

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
            # 过滤掉分割后可能产生的空字符串
            all_volumes = [v for v in content.split("\n\n") if v.strip()]
            for vol in all_volumes:
                if vol.strip().startswith("#=== 第") and "卷" in vol:
                    try:
                        vol_num = int(vol.split("第")[1].split("卷")[0])
                        # 如果设置了起始卷，并且当前卷号大于等于起始卷，则截断
                        if start_from_volume is not None and vol_num >= start_from_volume:
                            _log(f"将从第 {start_from_volume} 卷开始重新生成，已移除内存中该卷及其后续内容。")
                            break
                        existing_volume_outlines.append(vol)
                        current_volume = max(current_volume, vol_num)
                    except:
                        pass
    # 设置起始卷数
    if start_from_volume is not None:
        current_volume = start_from_volume - 1
    elif current_volume >= volume_count:
        _log("所有分卷已生成完成")
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
    # 生成分卷大纲
    volume_outlines = existing_volume_outlines.copy()
    previous_outline = existing_volume_outlines[-1] if existing_volume_outlines else ""
    end_volume = current_volume + 1 if generate_single else volume_count
    for i in range(current_volume, end_volume):
        try:
            _log(f"生成第{i+1}卷大纲...")
            volume_to_generate = i + 1
            start_chap, end_chap = volume_chapters[i]

            # --- Create a volume-specific settings dictionary for the prompt ---
            prompt_settings = parsed_setting.copy()
            _log(f"为第 {volume_to_generate} 卷提取专属设定内容...")
            for key in ["volume_mission_statement", "plotline_and_progression", "narrative_style"]:
                full_text = prompt_settings.get(key, "")
                volume_specific_text = extract_single_volume_data(full_text, volume_to_generate)
                prompt_settings[key] = volume_specific_text
                if full_text and not volume_specific_text:
                     _log(f"警告: 未能从模块 '{key}' 中提取第 {volume_to_generate} 卷的特定内容。")

            # 构造提示词
            if i == 0:
                # 如果提供了角色提示词，则生成角色
                setting_characters = ""
                if character_prompt and num_characters > 0:
                    _log(f"生成{num_characters}个主要角色...")
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
                    # if log_func:
                    #     log_func("发送到 LLM 的提示词:\n" + char_prompt)
                    
                    setting_characters = ""
                    for chunk in invoke_stream_with_cleaning(llm_adapter, char_prompt, log_func=log_func):
                        if chunk:
                            setting_characters += chunk
                    _log("角色生成完成")
                
                prompt = volume_outline_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    setting_characters=setting_characters,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    volume_number=i+1,
                    genre=genre,
                    volume_design_format=volume_design_format,
                    **prompt_settings
                )
            elif i == volume_count - 1:
                prompt = final_volume_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    character_state=character_state,
                    characters_involved=characters_involved,
                    previous_volume_outline=previous_outline,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    volume_number=i+1,
                    genre=genre,
                    volume_design_format=volume_design_format,
                    **prompt_settings
                )
            else:
                # 从角色状态向量库中检索权重大于等于91的角色状态
                setting_characters = get_high_weight_characters(filepath, llm_adapter, weight_threshold=character_weight_threshold)
                
                prompt = subsequent_volume_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    characters_involved=characters_involved,
                    previous_volume_outline=previous_outline,
                    setting_characters=setting_characters,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    volume_number=i+1,
                    genre=genre,
                    volume_design_format=volume_design_format,
                    **prompt_settings
                )
            # if log_func:
            #     log_func("发送到 LLM 的提示词:\n" + prompt)
            
            outline = ""
            for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, log_func=log_func):
                if chunk:
                    outline += chunk
            if not outline.strip():
                raise Exception(f"第{i+1}卷大纲生成失败")

            # 从生成的大纲中动态提取真实的章节范围
            # 增强的正则表达式，以适应LLM可能产生的格式变化（例如，可选的空格和markdown列表标记）
            distribution_match = re.search(r'五、\s*(?:叙事与章节规划|章节分布)[\s\S]*?(?:[\*\-]\s*)?(?:章节范围|章节分布)\s*[:：]\s*第(\d+)章\s*-\s*第(\d+)章', outline, re.DOTALL)
            
            if distribution_match:
                try:
                    real_start_chap = int(distribution_match.group(1))
                    real_end_chap = int(distribution_match.group(2))
                    _log(f"从生成的大纲中成功提取第 {i+1} 卷的真实章节范围: {real_start_chap}-{real_end_chap}")
                except (ValueError, IndexError):
                    _log(f"❌ 解析第 {i+1} 卷大纲中的章节范围失败，尽管找到了匹配项。请检查生成内容的格式。")
                    raise ValueError(f"无法从生成的大纲中解析第 {i+1} 卷的章节范围数字。")
            else:
                _log(f"❌ 在第 {i+1} 卷生成的大纲中未能找到'五、叙事与章节规划'下的'章节范围'。无法创建分卷头。")
                raise ValueError(f"无法从生成的大纲中找到第 {i+1} 卷的章节范围信息。")

            volume_title = "终章" if i == volume_count - 1 else ""
            new_volume = f"#=== 第{i+1}卷{volume_title}  第{real_start_chap}章 至 第{real_end_chap}章 ===\n{outline}"
            volume_outlines.append(new_volume)
            previous_outline = outline
            # 每生成一卷就保存一次
            current_content = "\n\n".join(volume_outlines) + "\n"
            save_string_to_txt(current_content, volume_file)
            _log(f"第{i+1}卷大纲已生成并保存")
        except Exception as e:
            _log(f"生成第{i+1}卷大纲时出错: {str(e)}")
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
        print(f"提取分卷大纲时出错: {str(e)}")
        return ""

def find_volume_for_chapter(volume_content: str, chapter_number: int) -> int:
    """
    根据分卷大纲内容和章节号，找到该章节所属的卷号。
    优先从'五、章节分布'中的'【章节范围】'提取范围，如果失败则回退到解析卷头。
    """
    if not volume_content:
        return 1  # 默认为第一卷

    # 将内容按卷分割
    volume_blocks = re.split(r'(?=#=== 第\d+卷)', volume_content)

    for block in volume_blocks:
        if not block.strip():
            continue

        # 提取卷号
        volume_num_match = re.search(r'#===\s*第(\d+)卷', block)
        if not volume_num_match:
            continue
        volume_num = int(volume_num_match.group(1))

        start_chap, end_chap = None, None

        # 优先尝试从 "五、章节分布" 提取章节范围
        distribution_match = re.search(r'五、章节分布.*?【章节范围】：第(\d+)章\s*-\s*第(\d+)章', block, re.DOTALL)
        if distribution_match:
            try:
                start_chap = int(distribution_match.group(1))
                end_chap = int(distribution_match.group(2))
                print(f"从卷 {volume_num} 的'章节分布'中成功提取章节范围: {start_chap}-{end_chap}")
            except (ValueError, IndexError):
                print(f"解析卷 {volume_num} 的'章节分布'范围失败。")
                start_chap, end_chap = None, None
        
        # 如果从 "章节分布" 提取失败，则回退到解析卷头
        if start_chap is None or end_chap is None:
            header_match = re.search(r'#===\s*第\d+卷.*?第(\d+)章\s*至\s*第(\d+)章', block, re.DOTALL)
            if header_match:
                try:
                    start_chap = int(header_match.group(1))
                    end_chap = int(header_match.group(2))
                    print(f"从卷 {volume_num} 的卷头成功提取章节范围: {start_chap}-{end_chap}")
                except (ValueError, IndexError):
                    print(f"解析卷 {volume_num} 的卷头范围失败。")
                    continue # 如果卷头也解析失败，则跳过此卷

        # 检查章节号是否在范围内
        if start_chap is not None and end_chap is not None:
            if start_chap <= chapter_number <= end_chap:
                return volume_num

    # 如果遍历所有卷都未找到，则发出警告并返回1
    print(f"在分卷大纲中未找到章节 {chapter_number} 所属的卷，将默认为第1卷。")
    return 1
