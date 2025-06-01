# novel_generator/chapter_blueprint.py
# -*- coding: utf-8 -*-
import os
import logging
import re
import json  # 添加json导入
import threading

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 创建logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from novel_generator.common import invoke_with_cleaning
from llm_adapters import create_llm_adapter
from novel_generator.volume import extract_volume_outline
from prompt_definitions import chapter_blueprint_prompt
from utils import read_file, save_string_to_txt, clear_file_content

def analyze_directory_status(filepath: str) -> tuple:
    """分析目录文件状态，返回最新章节号"""
    try:
        directory_file = os.path.join(filepath, "章节目录.txt")
        if not os.path.exists(directory_file):
            return 0, [], []
            
        content = read_file(directory_file)
        if not content:
            return 0, [], []
            
        # 匹配章节标题，例如 "第1章" 或 "第10章"
        chapter_pattern = r'^第(\d+)章'
        lines = content.splitlines()
        chapter_numbers = [] # 初始化章节号列表
        for line in lines:
            match = re.match(chapter_pattern, line.strip())
            if match:
                try:
                    chapter_num = int(match.group(1))
                    logging.debug(f"Found chapter: {chapter_num}") # 添加日志记录
                    chapter_numbers.append(chapter_num)
                except ValueError:
                    logging.warning(f"无法将章节号转换为整数: {match.group(1)}")
                except Exception as e:
                    logging.warning(f"解析章节 {match.group(1)} 时出错: {str(e)}")
                    continue
                
        if not chapter_numbers:
            logging.info("未找到任何有效章节")
            return 0, [], []
            
        last_chapter = max(chapter_numbers)
        chapter_numbers = sorted(chapter_numbers)
        logging.info(f"分析完成：最新章节 = {last_chapter}, 共{len(chapter_numbers)}章")
        return last_chapter, chapter_numbers, content
        
    except Exception as e:
        logging.error(f"分析目录状态时出错: {str(e)}")
        return 0, [], []

def analyze_volume_range(filepath: str) -> list:
    """
    分析分卷章节范围
    返回: [{'volume': 卷号, 'start': 起始章节, 'end': 结束章节}, ...]
    """
    try:
        volume_file = os.path.join(filepath, "分卷大纲.txt")
        if not os.path.exists(volume_file):
            return []
            
        content = read_file(volume_file)
        if not content:
            return []
            
        # 匹配格式如: 第一卷《卷名》第1章 至 第10章
        volume_ranges = []
        volume_pattern = r'第([一二三四五六七八九十]|\d+)卷.*?第(\d+)章.*?至.*?第(\d+)章'
        matches = re.finditer(volume_pattern, content, re.DOTALL)
        
        for match in matches:
            volume_num = match.group(1)
            # 将中文数字转换为阿拉伯数字
            if volume_num.isdigit():
                vol_num = int(volume_num)
            else:
                chinese_nums = "一二三四五六七八九十"
                vol_num = chinese_nums.index(volume_num) + 1
                
            start_chap = int(match.group(2))
            end_chap = int(match.group(3))
            volume_ranges.append({
                'volume': vol_num,
                'start': start_chap,
                'end': end_chap
            })
            
        # 按卷号排序
        volume_ranges.sort(key=lambda x: x['volume'])
        return volume_ranges
        
    except Exception as e:
        logging.error(f"分析分卷范围时出错: {str(e)}")
        return []

def find_current_volume(chapter_number: int, volume_ranges: list) -> tuple:
    """
    查找指定章节所在的卷号及是否在卷尾
    返回: (当前卷号, 是否卷尾)
    """
    if not volume_ranges:
        return 1, False
        
    for vol_info in volume_ranges:
        if vol_info['start'] <= chapter_number <= vol_info['end']:
            return vol_info['volume'], (chapter_number == vol_info['end'])
            
    # 如果章节号超出所有已定义卷的范围，返回最后一卷+1
    if chapter_number > volume_ranges[-1]['end']:
        return volume_ranges[-1]['volume'] + 1, False
        
    # 如果章节号小于第一卷的起始章节，返回第一卷
    return 1, False

def get_volume_progress(filepath: str) -> tuple:
    """
    获取当前卷的进度信息
    返回：(当前卷号, 最新章节号, 当前卷起始章节, 当前卷结束章节, 是否在卷尾, 是否当前卷已完整生成)
    """
    try:
        # 获取最新章节号和已生成章节列表
        last_chapter, existing_chapters, _ = analyze_directory_status(filepath)
        
        # 获取分卷范围
        volume_ranges = analyze_volume_range(filepath)
        if not volume_ranges:
            return 1, 0, 1, 0, False, False
            
        # 找到当前章节所在卷
        current_vol, is_volume_end = find_current_volume(last_chapter, volume_ranges)
        
        # 获取当前卷的起始和结束章节
        current_vol_info = next(
            (v for v in volume_ranges if v['volume'] == current_vol), 
            None
        )
        
        if current_vol_info:
            # 检查当前卷的所有章节是否都已完整生成
            expected_chapters = set(range(current_vol_info['start'], current_vol_info['end'] + 1))
            completed_chapters = set(int(x) for x in existing_chapters)
            is_volume_complete = expected_chapters.issubset(completed_chapters)
            
            return (
                current_vol,
                last_chapter,
                current_vol_info['start'],
                current_vol_info['end'],
                is_volume_end,
                is_volume_complete  # 新增返回值：是否卷内完整
            )
        
        if last_chapter == 0:
            first_vol = volume_ranges[0]
            return 1, 0, first_vol['start'], first_vol['end'], False, False
        else:
            last_vol = volume_ranges[-1]
            next_start = last_vol['end'] + 1
            estimated_end = next_start + (last_vol['end'] - last_vol['start'])
            return current_vol, last_chapter, next_start, estimated_end, False, False
            
    except Exception as e:
        logging.error(f"获取卷进度时出错: {str(e)}")
        return 1, 0, 1, 0, False, False

def analyze_chapter_status(filepath):
    """
    占位函数：分析章节状态，返回 (last_chapter, current_vol, is_volume_end)
    你可以根据实际需求完善此函数逻辑。
    """
    # 默认返回0, 1, True，防止UI报错
    return 0, 1, True

def Chapter_blueprint_generate(
    interface_format: str,
    api_key: str,
    base_url: str,
    llm_model: str,
    number_of_chapters: int,
    filepath: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: int = 600,
    user_guidance: str = "",
    start_from_volume: int = None,  # 指定从哪一卷开始生成
    generate_single: bool = False,  # 是否仅生成单卷
    save_interval: int = 20,  # 每生成多少章保存一次
    main_character: str = ""  # 添加主要角色信息参数
) -> str:
    """根据小说架构生成章节目录大纲"""
    logging.info("开始生成章节目录...")
    
    # 1. 确定生成范围
    last_chapter, existing_chapters, existing_content = analyze_directory_status(filepath)
    volumes = analyze_volume_range(filepath)
    
    # 2. 确定起始点
    if start_from_volume is not None:
        current_vol = start_from_volume
    else:
        current_vol = 1 if last_chapter == 0 else find_current_volume(last_chapter, volumes)[0]
    
    # 3. 查找目标卷的范围
    target_volumes = []
    if generate_single:
        vol_info = next((v for v in volumes if v['volume'] == current_vol), None)
        if vol_info:
            target_volumes = [vol_info]
    else:
        target_volumes = [v for v in volumes if v['volume'] >= current_vol]

    if not target_volumes:
        raise ValueError(f"找不到卷号{current_vol}的范围信息")
        
    # 4. 读取现有内容
    directory_file = os.path.join(filepath, "章节目录.txt")
    existing_content = read_file(directory_file) if os.path.exists(directory_file) else ""

    # 5. 逐卷生成内容
    generated_content = ""
    chapters_generated = 0  # 记录已生成章节数
    
    for vol in target_volumes:
        try:
            if existing_chapters:
                valid_chapters = [x for x in existing_chapters if x <= vol['end']]
                start_chapter = max(valid_chapters) + 1 if valid_chapters else vol['start']
            else:
                start_chapter = vol['start']

            if start_chapter > vol['end']:
                continue

            # 计算本次请求的目标结束章节
            target_end_request = start_chapter + number_of_chapters - 1
            logging.info(f"请求生成 {number_of_chapters} 章，从 {start_chapter} 到 {target_end_request} (卷结束于 {vol['end']})")

            # 分段生成当前卷内容
            current_start = start_chapter
            # 修改循环条件：同时检查卷结束和请求结束
            while current_start <= vol['end'] and current_start <= target_end_request:
                # 修改 current_end 计算：取请求结束、卷结束和间隔结束的最小值
                current_end = min(current_start + save_interval - 1, vol['end'], target_end_request)
                
                try:
                    # 生成一段章节内容
                    # 获取伏笔状态
                    foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
                    current_state = read_file(foreshadow_file) if os.path.exists(foreshadow_file) else ""
                    foreshadow_info = get_max_foreshadow_numbers(current_state, vol['volume'], current_start, current_end)
                    
                    result = generate_volume_chapters(
                        interface_format=interface_format,
                        api_key=api_key,
                        base_url=base_url,
                        llm_model=llm_model,
                        filepath=filepath,
                        volume_number=vol['volume'],
                        start_chapter=current_start,
                        end_chapter=current_end,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=timeout,
                        user_guidance=user_guidance,
                        main_character=main_character
                    )
                    
                    if result:
                        # 立即更新伏笔状态（在保存章节目录之前）
                        foreshadow_state = update_foreshadowing_state(result, filepath)
                        if foreshadow_state:
                            foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
                            clear_file_content(foreshadow_file)
                            save_string_to_txt(foreshadow_state, foreshadow_file)
                            logging.info("已更新伏笔状态")

                        # 更新生成的内容
                        generated_content += ("\n\n" if generated_content else "") + result
                        chapters_generated += (current_end - current_start + 1)
                        
                        # 保存章节目录
                        final_content = existing_content
                        if generated_content:
                            if (final_content):
                                final_content += "\n\n"
                            final_content += generated_content
                            
                        clear_file_content(directory_file)
                        save_string_to_txt(final_content, directory_file)
                        logging.info(f"已生成并保存至第{current_end}章")
                        
                except Exception as e:
                    logging.error(f"生成第{current_start}-{current_end}章时出错: {str(e)}")
                    # 保存已生成的内容
                    if generated_content:
                        final_content = existing_content + ("\n\n" if existing_content else "") + generated_content
                        clear_file_content(directory_file)
                        save_string_to_txt(final_content, directory_file)
                    raise
                
                current_start = current_end + 1
            
            logging.info(f"第{vol['volume']}卷章节目录生成完成")
                
        except Exception as e:
            logging.error(f"生成第{vol['volume']}卷内容时出错: {str(e)}")
            raise ValueError(f"生成第{vol['volume']}卷章节目录时发生错误: {str(e)}")

    # 6. 返回完整内容
    final_content = existing_content
    if generated_content:
        if final_content:
            final_content += "\n\n"
        final_content += generated_content
        
    return final_content

def get_last_n_chapters(content: str, n: int = 3) -> str:
    """获取最新的n章章节目录内容"""
    try:
        if not content:
            return ""
        
        chapters = []
        pattern = r"第\d+章.*?(?=第\d+章|$)"
        
        # 使用正则表达式匹配所有章节
        for match in re.finditer(pattern, content, re.DOTALL):
            chapters.append(match.group(0).strip())
        
        # 返回最后n章
        return "\n\n".join(chapters[-n:]) if chapters else ""
            
    except Exception as e:
        logging.error(f"获取最新{n}章目录时出错: {str(e)}")
        return ""

def get_max_foreshadow_numbers(current_state: str, volume_number: int, start_chapter: int, end_chapter: int) -> str:
    """获取每种类型的最大伏笔编号（包括已回收的）"""
    max_numbers = {
        '一般伏笔': 0,
        '暗线伏笔': 0,
        '主线伏笔': 0,
        '支线伏笔': 0,
        '人物伏笔': 0
    }
    type_abbr = {
        '一般伏笔': 'YF',
        '暗线伏笔': 'AF',
        '主线伏笔': 'MF',
        '支线伏笔': 'SF',
        '人物伏笔': 'CF'
    }
    
    try:
        logging.info("=== 开始分析最大伏笔编号 ===")
        # 从内容中匹配所有伏笔编号，包括已回收的
        all_fids = re.findall(r'[〇]?([A-Z]F)(\d{3})', current_state)
        logging.debug(f"找到 {len(all_fids)} 个伏笔编号")
        
        for prefix, num in all_fids:
            for type_name, abbr in type_abbr.items():
                if prefix == abbr:
                    current_num = int(num)
                    max_numbers[type_name] = max(max_numbers[type_name], current_num)
                    logging.debug(f"更新 {type_name} 最大编号: {current_num}")
        
        # 构建输出格式
        result = ["各类型已有伏笔最大编号："]
        for type_name, max_num in max_numbers.items():
            if max_num > 0:  # 只显示有编号的类型
                result.append(f"{type_name} {type_abbr[type_name]}：{type_abbr[type_name]}{max_num:03d}")
                
        logging.info("=== 完成最大伏笔编号分析 ===")
        return "\n".join(result)

    except Exception as e:
        logging.error(f"计算最大伏笔编号时出错: {str(e)}")
        return "各类型已有伏笔最大编号：\n(处理出错)"

def get_chapter_content(fid: str, chapter_num: int, filepath: str) -> dict:
    """从章节目录中获取指定章节的标题和伏笔条目内容"""
    try:
        # 确保参数类型正确
        if isinstance(chapter_num, str) and isinstance(fid, int):
            # 如果参数顺序颠倒，交换它们
            logging.debug(f"参数顺序颠倒，交换参数: chapter_num={fid}, fid={chapter_num}")
            chapter_num, fid = fid, chapter_num
            
        logging.debug(f"获取第{chapter_num}章中伏笔 {fid} 的相关内容")
        # 检查filepath是否已经是完整路径
        if os.path.isdir(filepath):
            # 如果是目录，则拼接文件名
            directory_file = os.path.join(filepath, "章节目录.txt")
        else:
            # 如果已经是完整路径，则直接使用
            directory_file = filepath
            
        logging.debug(f"使用文件路径: {directory_file}")
        if not os.path.exists(directory_file):
            logging.error(f"章节目录文件不存在: {directory_file}")
            return {'title': '', 'foreshadow': '', 'description': ''}
            
        content = read_file(directory_file)
        
        if not content:
            logging.error("章节目录文件为空")
            return {'title': '', 'foreshadow': '', 'description': ''}
            
        # 1. 统一处理换行符
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        
        # 2. 精确提取目标章节的内容 - 使用当前章节和下一章节的起始标记
        chapter_start_pattern = f"^第{chapter_num}章"
        next_chapter_start_pattern = f"^第{chapter_num + 1}章"

        start_pos = -1
        end_pos = len(content)

        lines = content.split('\n')
        for i, line in enumerate(lines):
            if re.match(chapter_start_pattern, line.strip()):
                # 计算精确的字符起始位置
                start_pos = content.find(line)
                logging.debug(f"找到第{chapter_num}章的起始行 {i+1}，位置: {start_pos}")
                # 找到起始位置后，继续查找下一章的起始位置
                for j in range(i + 1, len(lines)):
                    if re.match(next_chapter_start_pattern, lines[j].strip()):
                        # 计算精确的字符结束位置（下一章的起始位置）
                        end_pos = content.find(lines[j])
                        logging.debug(f"找到第{chapter_num + 1}章的起始行 {j+1}，位置: {end_pos}")
                        break
                break # 找到当前章节起始位置后就跳出外层循环

        if start_pos == -1:
            logging.error(f"无法找到第{chapter_num}章的起始标记")
            return {'title': '', 'foreshadow': '', 'description': ''}

        # 提取当前章节的完整内容
        chapter_content = content[start_pos:end_pos].strip()
        logging.debug(f"收集到第{chapter_num}章内容（从 {start_pos} 到 {end_pos}），长度: {len(chapter_content)}字符")
        # 添加更详细的日志记录，用于调试特定章节
        if chapter_num == 25:
            logging.debug(f"-- DEBUG Chapter 25 Content --\n{chapter_content}\n-- END DEBUG Chapter 25 Content --")

        # 3. 获取章节标题
        title_match = re.match(r"第\d+章\s+([^\n]+)", chapter_content)
        chapter_title = title_match.group(1) if title_match else ""
        logging.debug(f"章节标题: {chapter_title}")
        
        # 4. 在章节内容中查找伏笔ID
        # 首先尝试在伏笔条目部分查找
        foreshadow_section_match = re.search(r"├─伏笔条目：\n([\s\S]*?)(?=├─颠覆指数|└─本章简述)", chapter_content)
        
        if (foreshadow_section_match):
            foreshadow_section = foreshadow_section_match.group(1)
            logging.debug(f"找到伏笔条目部分，长度: {len(foreshadow_section)}字符")
            
            # 使用正则表达式查找特定伏笔ID的行
            fid_pattern = f"[│├└─\s]*{re.escape(fid)}[^\n]*"
            fid_match = re.search(fid_pattern, foreshadow_section)
            
            if (fid_match):
                foreshadow_line = fid_match.group(0).strip()
                # 清理行首的特殊字符
                clean_line = re.sub(r'^[│├└─\s]+', '', foreshadow_line)
                logging.debug(f"在第{chapter_num}章伏笔条目部分找到伏笔 {fid}: {clean_line}")
                return {
                    'title': chapter_title or f"第{chapter_num}章",
                    'foreshadow': clean_line,
                    'description': clean_line
                }
        
        # 如果在伏笔条目部分没找到，尝试在整个章节内容中逐行查找
        chapter_lines = chapter_content.split('\n')
        for line in chapter_lines:
            # 确保只匹配包含伏笔ID且看起来像伏笔条目的行
            if fid in line and re.search(r'-(埋设|触发|强化|回收|悬置)-', line):
                # 清理行首的特殊字符
                clean_line = re.sub(r'^[│├└─\s]+', '', line.strip())
                logging.debug(f"在第{chapter_num}章内容中找到伏笔 {fid}: {clean_line}")
                return {
                    'title': chapter_title or f"第{chapter_num}章",
                    'foreshadow': clean_line,
                    'description': clean_line
                }
        
        # 如果在章节内容中未找到，则返回空结果，不再进行全局搜索
        logging.error(f"在第{chapter_num}章内容中未找到伏笔 {fid}")
        return {'title': chapter_title or f"第{chapter_num}章", 'foreshadow': '', 'description': ''}
        
    except Exception as e:
        logging.error(f"获取章节内容时出错: {str(e)}")
        return {'title': '', 'foreshadow': '', 'description': ''}
        
        # 在收集到的章节内容中查找伏笔条目
        if chapter_lines:
            chapter_section = "\n".join(chapter_lines)
            logging.debug(f"提取到第{chapter_num}章的完整内容，长度: {len(chapter_section)}字符")
            
            # 在章节内容中查找伏笔条目段落
            foreshadow_section = None
            in_foreshadow = False
            foreshadow_lines = []
            
            for line in chapter_lines:
                if "伏笔条目：" in line or "├─伏笔条目：" in line:
                    in_foreshadow = True
                    continue
                elif in_foreshadow and (line.startswith("├─") or line.startswith("└─")) and "伏笔" not in line:
                    # 已经到了下一个段落，结束收集
                    break
                elif in_foreshadow:
                    foreshadow_lines.append(line)
            
            if foreshadow_lines:
                foreshadow_section = "\n".join(foreshadow_lines)
                logging.debug(f"提取到第{chapter_num}章的伏笔条目段落，长度: {len(foreshadow_section)}字符")
                
                # 在伏笔段落中查找特定伏笔ID
                for line in foreshadow_lines:
                    if fid in line:
                        clean_line = re.sub(r'^[│├└─\\s]+', '', line.strip())
                        logging.debug(f"在第{chapter_num}章伏笔段落中找到伏笔ID {fid}: {clean_line}")
                        return {
                            'title': title,
                            'foreshadow': clean_line,
                            'description': clean_line
                        }
        
        # 2. 尝试查找特定格式的章节引用
        chapter_fid_patterns = [
            f"-第{chapter_num}章：{fid}",  # 标准格式
            f"-第{chapter_num}章:{fid}",   # 无空格格式
            f"第{chapter_num}章.*?{fid}"   # 宽松格式
        ]
        
        for pattern in chapter_fid_patterns:
            chapter_fid_lines = [line for line in lines if re.search(pattern, line)]
            if chapter_fid_lines:
                clean_line = re.sub(r'^[│├└─\\s]+', '', chapter_fid_lines[0].strip())
                logging.debug(f"使用模式 '{pattern}' 精确匹配到第{chapter_num}章的{fid}伏笔条目: {clean_line}")
                return {
                    'title': title,
                    'foreshadow': clean_line,
                    'description': clean_line
                }
        
        # 如果精确匹配失败，尝试更宽松的匹配
        for line in lines:
            if fid in line and ("伏笔" in line or "埋设" in line or "触发" in line or "强化" in line or "回收" in line):
                clean_line = re.sub(r'^[│├└─\\s]+', '', line.strip())
                # 检查这一行是否与特定章节相关
                line_index = lines.index(line)
                prev_lines = '\n'.join(lines[max(0, line_index-20):line_index])
                next_lines = '\n'.join(lines[line_index:min(line_index+20, len(lines))])
                
                # 更严格的章节匹配条件
                chapter_markers = [f"第{chapter_num}章", f"-第{chapter_num}章：", f"-第{chapter_num}章"]
                if any(marker in prev_lines for marker in chapter_markers) or any(marker in line for marker in chapter_markers):
                    chapter_specific_lines.append(clean_line)
                    logging.debug(f"在第{chapter_num}章相关内容中找到伏笔 {fid} 条目: {clean_line}")
                else:
                    general_lines.append(clean_line)
        
        # 优先使用与特定章节相关的行
        if chapter_specific_lines:
            logging.debug(f"使用第{chapter_num}章特定的伏笔条目: {chapter_specific_lines[0]}")
            return {
                'title': title,
                'foreshadow': chapter_specific_lines[0],
                'description': chapter_specific_lines[0]
            }
        elif general_lines:
            logging.debug(f"在整个文件中找到伏笔 {fid} 条目: {general_lines[0]}")
            return {
                'title': title,
                'foreshadow': general_lines[0],
                'description': general_lines[0]
            }
                
        # 方法4.5: 尝试更宽松的全文搜索
        # 只要包含伏笔ID的行，不要求包含特定关键词
        chapter_specific_lines = []
        general_lines = []
        
        for line in lines:
            if fid in line:
                clean_line = re.sub(r'^[│├└─\\s]+', '', line.strip())
                # 检查这一行是否与特定章节相关
                prev_lines = '\n'.join(lines[max(0, lines.index(line)-10):lines.index(line)])
                if f"第{chapter_num}章" in prev_lines or f"-第{chapter_num}章" in prev_lines:
                    chapter_specific_lines.append(clean_line)
                    logging.debug(f"在第{chapter_num}章相关内容中找到包含 {fid} 的行: {clean_line}")
                else:
                    general_lines.append(clean_line)
        
        # 优先使用与特定章节相关的行
        if chapter_specific_lines:
            logging.debug(f"使用第{chapter_num}章特定的包含 {fid} 的行: {chapter_specific_lines[0]}")
            return {
                'title': title,
                'foreshadow': chapter_specific_lines[0],
                'description': chapter_specific_lines[0]
            }
        elif general_lines:
            logging.debug(f"在全文中找到包含 {fid} 的行: {general_lines[0]}")
            return {
                'title': title,
                'foreshadow': general_lines[0],
                'description': general_lines[0]
            }
        
        # 方法5: 最后尝试使用更宽松的模式在整个章节内容中搜索
        pattern = f".*{re.escape(fid)}.*"
        match = re.search(pattern, chapter_content, re.DOTALL)
        if match:
            foreshadow_line = match.group(0).strip()
            # 清理行首的特殊字符和多余的空白
            clean_line = re.sub(r'^[│├└─\\s]+', '', foreshadow_line)
            clean_line = re.sub(r'\s+', ' ', clean_line).strip()
            logging.debug(f"使用宽松模式在章节内容中找到伏笔 {fid} 条目: {clean_line}")
            return {
                'title': title,
                'foreshadow': clean_line,
                'description': clean_line
            }
        
        # 如果所有方法都失败，返回空结果
        logging.debug(f"在第{chapter_num}章中未找到伏笔ID: {fid}")
        return {'title': title, 'foreshadow': '', 'description': ''}
        
    except Exception as e:
        logging.error(f"获取章节内容时出错: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return {'title': '', 'foreshadow': '', 'description': ''}

def get_foreshadowing_list(current_state: str, start_chapter: int, end_chapter: int, filepath: str) -> str:
    """
    获取需要在指定章节范围内回收的伏笔列表，格式化输出每个伏笔的状态及伏笔简介
    按照新格式输出，每个伏笔的每个章节状态都单独列出，包含完整的伏笔条目内容
    格式示例：
    支线伏笔：
    编号（类型）：标题（第x章前必须回收）
    -第x章：完整的伏笔条目内容
    -第x章：完整的伏笔条目内容
    """
    must_recover_dict = {}  # 使用字典存储伏笔信息，以FID为键
    current_type = None
    current_fid = None  # 当前处理的伏笔ID

    try:
        logging.info(f"=== 开始分析需要在第{start_chapter}-{end_chapter}章回收的伏笔 ===")
        for line in current_state.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.endswith('：'):  # 类型行
                current_type = line[:-1]
                current_fid = None # 新类型开始，重置当前FID
                logging.debug(f"处理伏笔类型: {current_type}")
            elif not line.startswith('-') and '：' in line and not line.startswith('〇'):  # 未回收的伏笔标题行
                fid_match = re.search(r'([A-Z]F\d{3})', line)
                deadline_match = re.search(r'（第(\d+)章前必须回收）', line)
                if fid_match and deadline_match:
                    deadline = int(deadline_match.group(1))
                    if start_chapter <= deadline <= end_chapter:
                        fid = fid_match.group(1)
                        current_fid = fid # 设置当前处理的FID
                        if fid not in must_recover_dict:
                            title = line.split('：')[1].split('（')[0].strip()
                            must_recover_dict[fid] = {
                                'type': current_type,
                                'fid': fid,
                                'title': title,
                                'deadline': deadline,
                                'states': []
                            }
                            logging.debug(f"找到需回收伏笔: {fid} - {title} (第{deadline}章前)")
                        # 即使FID已存在，也设置current_fid，以便后续状态能关联
                    else:
                        current_fid = None # 不在回收范围内，重置当前FID
                else:
                    current_fid = None # 格式不匹配，重置当前FID
            elif line.startswith('-'): # 状态行
                if current_fid is not None and current_fid in must_recover_dict:
                    current_foreshadow = must_recover_dict[current_fid]
                    state = line[1:].strip()
                    chapter_match = re.search(r'第(\d+)章', state)
                    if chapter_match:
                        chapter_num = int(chapter_match.group(1))
                        # 检查是否已经存在相同章节的状态，避免重复
                        if not any(s['chapter'] == chapter_num and s['state'] == state for s in current_foreshadow['states']):
                            current_foreshadow['states'].append({
                                'state': state,
                                'chapter': chapter_num
                            })
                            logging.debug(f"添加状态: {current_foreshadow['fid']} - {state}")
            else:
                 # 其他类型的行（如已回收的伏笔标题行），重置当前FID
                 current_fid = None

        must_recover = list(must_recover_dict.values()) # 从字典转换为列表

        if not must_recover:
            logging.info("未找到需要回收的伏笔")
            return ""

        # 构建输出格式
        result = []
        type_order = ['暗线伏笔', '人物伏笔', '主线伏笔', '支线伏笔', '一般伏笔']

        for type_name in type_order:
            # 直接从must_recover列表中筛选当前类型
            type_foreshadows = [f for f in must_recover if f['type'] == type_name]
            if not type_foreshadows:
                continue

            result.append(f"{type_name}：")
            # 按FID排序，保证输出顺序一致性
            type_foreshadows.sort(key=lambda x: x['fid'])
            
            for f in type_foreshadows:
                # 无需再次去重，字典已保证唯一性
                result.append(f"{f['fid']}（{type_name}）：{f['title']} （第{f['deadline']}章前必须回收）")
                
                # 按章节号升序排序所有状态
                sorted_states = sorted(f['states'], key=lambda x: x['chapter'])
                
                # 记录已处理的章节，避免重复输出
                processed_chapters = set()
                
                # 获取每个章节的详细伏笔内容
                for state in sorted_states:
                    chapter_num = state['chapter']
                    
                    # 跳过已处理的相同章节
                    if chapter_num in processed_chapters:
                        continue
                    processed_chapters.add(chapter_num)
                    
                    chapter_content = get_chapter_content(f['fid'], chapter_num, filepath)
                    
                    # 从状态文本中提取状态类型
                    state_text = state['state']
                    state_type_match = re.search(r'(埋设|触发|强化|回收|悬置)', state_text)
                    state_type = state_type_match.group(1) if state_type_match else "未知状态"
                    
                    if chapter_content['foreshadow'] and len(chapter_content['foreshadow'].strip()) > 0:
                        # 使用新格式：-第X章：完整伏笔条目
                        result.append(f"-第{chapter_num}章：{chapter_content['foreshadow']}")
                    else:
                        # 如果无法从章节内容中获取，则构造一个标准格式的伏笔条目
                        # 格式：FID(类型)-标题-状态-简介（第X章前必须回收）
                        description = ""
                        # 尝试从状态文本中提取描述
                        desc_match = re.search(r'{}-.*?-(埋设|触发|强化|回收|悬置)-(.*?)(?:（|$)'.format(f['fid']), state_text)
                        if desc_match:
                            description = desc_match.group(2).strip()
                        
                        if not description:
                            # 如果没有描述，使用一个通用描述
                            description = f"在第{chapter_num}章{state_type}了关于{f['title']}的情节"
                            
                        result.append(f"-第{chapter_num}章：{f['fid']}({type_name})-{f['title']}-{state_type}-{description}（第{f['deadline']}章前必须回收）")
                
                result.append("")  # 每个伏笔后加空行

        return "\n".join(result).strip()

    except Exception as e:
        logging.error(f"分析需回收伏笔列表时出错: {str(e)}")
        return ""

def get_unrecovered_foreshadowing(current_state: str) -> str:
    """获取未回收的伏笔状态（只包含未回收的伏笔）"""
    foreshadow_dict = {}
    current_type = None
    current_fid = None
    
    try:
        logging.info("=== 开始解析未回收伏笔状态 ===")
        
        for line in current_state.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            if line.endswith('：'):  # 类型行
                current_type = line[:-1]  # 移除冒号
                current_fid = None  # 重置当前伏笔ID
                foreshadow_dict[current_type] = {}
                logging.debug(f"处理伏笔类型: {current_type}")
                
            elif current_type and '：' in line and not line.startswith('-'):  # 伏笔标题行
                # 跳过已回收的伏笔（以〇开头的行）
                if line.startswith('〇'):
                    logging.debug(f"跳过已回收的伏笔: {line}")
                    current_fid = None  # 重置当前伏笔ID
                    continue
                    
                parts = line.split('：', 1)
                fid_part = parts[0].lstrip('〇')
                title_part = parts[1] if len(parts) > 1 else ""
                
                fid_match = re.search(r'([A-Z]F\d{3})', fid_part)
                if fid_match:
                    current_fid = fid_match.group(1)  # 记录当前处理的伏笔ID
                    deadline_match = re.search(r'（第(\d+)章前必须回收）', title_part)
                    title = title_part.split('（')[0].strip()
                    
                    # 只保存未回收的伏笔
                    foreshadow_dict[current_type][current_fid] = {
                        'title': title,
                        'deadline': int(deadline_match.group(1)) if deadline_match else None,
                        'states': [],
                        'recovered': False
                    }
                    logging.debug(f"添加未回收伏笔: {current_fid} - {title}")
                
            elif line.startswith('-') and current_type and current_fid:  # 状态行
                # 只有当前有效伏笔ID时才添加状态
                state = line.replace('-', '').strip()
                if state not in foreshadow_dict[current_type][current_fid]['states']:
                    foreshadow_dict[current_type][current_fid]['states'].append(state)
                    logging.debug(f"添加状态到 {current_fid}: {state}")

        # 构建输出结果
        result = []
        type_order = [
            ('暗线伏笔', 'AF'), 
            ('人物伏笔', 'CF'), 
            ('主线伏笔', 'MF'),
            ('支线伏笔', 'SF'),
            ('一般伏笔', 'YF')
        ]

        for type_display, type_prefix in type_order:
            if not any(k.startswith(type_display) for k in foreshadow_dict.keys()):
                continue
                
            result.append(f"{type_display}：")
            for type_name, fids in sorted(foreshadow_dict.items()):
                if not type_name.startswith(type_display):
                    continue
                    
                sorted_fids = sorted(fids.items(), key=lambda x: int(re.search(r'\d+', x[0]).group()))
                for fid, info in sorted_fids:
                    if not fid.startswith(type_prefix):
                        continue
                        
                    deadline_text = f"（第{info['deadline']}章前必须回收）" if info.get('deadline') else ""
                    result.append(f"{fid}（{type_display}）：{info['title']} {deadline_text}")
                    
                    for state in sort_states_by_chapter(info['states']):
                        result.append(f"- {state}")
                    result.append("")  # 每个伏笔后加一空行
            
            result.append("")  # 每个类型后加一空行
        
        logging.info(f"成功处理 {sum(len(v) for v in foreshadow_dict.values())} 个未回收伏笔")
        return '\n'.join(result[:-1])  # 移除最后一个空行

    except Exception as e:
        logging.error(f"解析伏笔状态出错: {str(e)}")
        return ""

def sort_states_by_chapter(states: list) -> list:
    """按章节号对状态列表进行排序"""
    try:
        def get_chapter_number(state: str) -> int:
            match = re.search(r'第(\d+)章', state)
            return int(match.group(1)) if match else 0
        return sorted(states, key=get_chapter_number)
    except Exception as e:
        logging.error(f"状态排序时出错: {str(e)}")
        return states

def update_foreshadowing_state(content: str, filepath: str, force_rescan: bool = False) -> str:
    """
    更新伏笔状态
    Args:
        content: 章节内容
        filepath: 文件路径
        force_rescan: 是否强制重新扫描（初始化时使用）
    """
    try:
        logging.info("=== 开始更新伏笔状态 ===")
        
        # 按照伏笔类型分组存储
        foreshadow_dict = {}
        recovered_ids = set()

        # 如果是强制重新扫描，则不读取现有状态文件
        foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
        current_state = "" if force_rescan else (read_file(foreshadow_file) if os.path.exists(foreshadow_file) else "")
        
        # 1. 先读取并保留现有状态文件中的所有信息
        current_type = None
        if current_state:
            logging.info("=== 解析现有状态文件 ===")
            for line in current_state.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                if line.endswith('：'):  # 类型行
                    current_type = line[:-1]
                    if current_type not in foreshadow_dict:
                        foreshadow_dict[current_type] = {}
                elif current_type and '：' in line and not line.startswith('-'):  # 伏笔标题行
                    parts = line.split('：', 1)
                    fid_part = parts[0].lstrip('〇')
                    title_part = parts[1] if len(parts) > 1 else ""
                    
                    fid_match = re.search(r'([A-Z]F\d{3})', fid_part)
                    if fid_match:
                        fid = fid_match.group(1)
                        if line.startswith('〇'):
                            recovered_ids.add(fid)
                        deadline_match = re.search(r'（第(\d+)章前必须回收）', title_part)
                        title = title_part.split('（')[0].strip()
                        
                        # 关键修改：保留原有所有伏笔信息
                        if fid not in foreshadow_dict[current_type]:
                            foreshadow_dict[current_type][fid] = {
                                'title': title,
                                'deadline': int(deadline_match.group(1)) if deadline_match else None,
                                'states': [],
                                'recovered': line.startswith('〇')
                            }
                elif line.startswith('-'):  # 状态行
                    if current_type and foreshadow_dict[current_type]:
                        last_fid = list(foreshadow_dict[current_type].keys())[-1]
                        state = line[1:].strip()
                        if state not in foreshadow_dict[current_type][last_fid]['states']:
                            foreshadow_dict[current_type][last_fid]['states'].append(state)

        # 2. 解析新章节内容中的伏笔
        chapter_matches = []
        current_chapter = None
        current_text = []
        
        for line in content.splitlines():
            if re.match(r'^第\d+章\s+', line):
                # 如果找到新章节，保存之前的章节
                if current_chapter:
                    chapter_matches.append({
                        'chapter': current_chapter,
                        'text': '\n'.join(current_text)
                    })
                # 开始新章节
                current_chapter = line
                current_text = [line]
            elif current_chapter:
                current_text.append(line)
        
        # 保存最后一章
        if current_chapter:
            chapter_matches.append({
                'chapter': current_chapter,
                'text': '\n'.join(current_text)
            })
            
        logging.info(f"找到 {len(chapter_matches)} 个章节")
        
        for chapter_info in chapter_matches:
            chapter_text = chapter_info['text']
            try:
                chapter_match = re.search(r'第(\d+)章', chapter_info['chapter'])
                if not chapter_match:
                    logging.warning("无法提取章节号，跳过此章节")
                    continue
                
                chapter_num = int(chapter_match.group(1))
                logging.info(f"\n处理第{chapter_num}章的伏笔")
                
                # 提取伏笔条目部分
                foreshadow_section = None
                section_start = False
                section_lines = []
                
                for line in chapter_text.splitlines():
                    if '├─伏笔条目：' in line:
                        section_start = True
                        continue
                    elif section_start and (line.startswith('├─') or line.startswith('└─')):
                        break
                    elif section_start:
                        section_lines.append(line)
                
                if section_lines:
                    foreshadow_section = '\n'.join(section_lines)
                
                if not foreshadow_section:
                    logging.warning(f"第{chapter_num}章未找到伏笔条目部分")
                    continue

                foreshadow_lines = [line.strip().lstrip('│├└') for line in foreshadow_section.splitlines() if line.strip()]
                logging.info(f"找到 {len(foreshadow_lines)} 行伏笔条目")
                
                for line in foreshadow_lines:
                    if not line or '-' not in line:
                        continue

                    try:
                        parts = [p.strip() for p in line.split('-')]
                        if len(parts) < 3:
                            logging.warning(f"伏笔格式不正确，跳过: {line}")
                            continue

                        fid_part = parts[0]
                        title = parts[1]
                        action = parts[2]
                        content_part = parts[3] if len(parts) > 3 else ""
                        
                        fid_match = re.search(r'([A-Z]F\d{3})', fid_part)
                        type_match = re.search(r'\((.*?伏笔)\)', fid_part)

                        # 新增：提取 deadline
                        deadline = None
                        deadline_match = re.search(r'（第(\d+)章前必须回收）', line)
                        if deadline_match:
                            deadline = int(deadline_match.group(1))
                        elif re.search(r'（第(\d+)章前必须回收）', content_part):
                            deadline = int(re.search(r'（第(\d+)章前必须回收）', content_part).group(1))

                        if not (fid_match and type_match):
                            logging.warning(f"无法解析伏笔ID或类型: {line}")
                            continue

                        fid = fid_match.group(1)
                        ftype = type_match.group(1)

                        if ftype not in foreshadow_dict:
                            foreshadow_dict[ftype] = {}
                            logging.debug(f"新增伏笔类型: {ftype}")

                        # 初始化或更新伏笔信息
                        if fid not in foreshadow_dict[ftype]:
                            foreshadow_dict[ftype][fid] = {
                                'title': title,
                                'deadline': deadline,
                                'states': [],
                                'recovered': False
                            }
                            logging.debug(f"新增伏笔: {fid} - {title}")

                        # 若已存在但未设置deadline，则补充
                        if deadline and not foreshadow_dict[ftype][fid].get('deadline'):
                            foreshadow_dict[ftype][fid]['deadline'] = deadline

                        state = f"{action}：第{chapter_num}章"
                        if state not in foreshadow_dict[ftype][fid]['states']:
                            foreshadow_dict[ftype][fid]['states'].append(state)
                            logging.debug(f"更新伏笔状态: {fid} - {state}")

                        if '回收' in action:
                            foreshadow_dict[ftype][fid]['recovered'] = True
                            recovered_ids.add(fid)
                            logging.debug(f"标记伏笔已回收: {fid}")

                    except Exception as e:
                        logging.error(f"处理伏笔行出错: {line}\n错误: {str(e)}")
                        continue

            except Exception as e:
                logging.error(f"处理第{chapter_num if 'chapter_num' in locals() else '?'}章出错: {str(e)}")
                continue

        # 3. 生成最终文本
        result = []
        for type_name in sorted(foreshadow_dict.keys()):
            if not foreshadow_dict[type_name]:
                continue
                
            result.append(f"{type_name}：")
            
            # 处理所有伏笔，按编号排序
            all_fids = sorted(foreshadow_dict[type_name].items())
            for fid, info in all_fids:
                prefix = "〇" if info['recovered'] or fid in recovered_ids else ""
                # 修正：始终拼接 deadline 信息
                deadline = f"（第{info['deadline']}章前必须回收）" if info.get('deadline') else ""
                result.append(f"{prefix}{fid}（{type_name}）：{info['title']} {deadline}".rstrip())
                
                # 添加所有状态信息（修改这里的排序逻辑）
                sorted_states = sort_states_by_chapter(info['states'])
                for state in sorted_states:
                    result.append(f"- {state}")
                result.append("")  # 每个伏笔后加空行
            
            result.append("")  # 每个类型后加空行

        # 4. 保存结果
        final_content = "\n".join(result).strip()
        clear_file_content(foreshadow_file)
        save_string_to_txt(final_content, foreshadow_file)
        
        return final_content

    except Exception as e:
        logging.error(f"更新伏笔状态时出错: {str(e)}")
        raise

def generate_volume_chapters(
    interface_format: str,
    api_key: str,
    base_url: str,
    llm_model: str,
    filepath: str,
    volume_number: int,
    start_chapter: int,
    end_chapter: int,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: int = 600,
    user_guidance: str = "",
    main_character: str = ""
) -> str:
    """生成指定卷的章节内容"""
    logging.info(f"开始生成第{volume_number}卷章节目录 (第{start_chapter}-{end_chapter}章)...")
    
    try:
        # 读取配置文件获取基本参数
        config_file = "config.json"
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # 从配置中获取小说基本参数
        other_params = config.get("other_params", {})
        genre = other_params.get("genre", "玄幻")
        total_volume_number = other_params.get("volume_count", 3)
        number_of_chapters = other_params.get("num_chapters", 100)  # 修改：使用配置文件中的总章节数
        word_number = other_params.get("word_number", 3000)

        # 1. 读取必要的输入文件
        novel_setting = read_file(os.path.join(filepath, "小说设定.txt"))
        volume_file = os.path.join(filepath, "分卷大纲.txt")
        volume_outline_full = read_file(volume_file)
        if not volume_outline_full:
            raise ValueError("找不到分卷大纲文件或文件为空")

        # 2. 提取当前卷的大纲内容
        volume_outline = extract_volume_outline(volume_outline_full, volume_number)
        if not volume_outline:
            raise ValueError(f"无法找到第{volume_number}卷的大纲内容")

        # 3. 读取最新3章的章节目录
        directory_file = os.path.join(filepath, "章节目录.txt")
        full_chapter_list = read_file(directory_file) if os.path.exists(directory_file) else ""
        chapter_list = get_last_n_chapters(full_chapter_list, 3)
        
        # 读取伏笔状态
        foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
        current_state = read_file(foreshadow_file) if os.path.exists(foreshadow_file) else ""
        
        # 获取最大伏笔编号和必须回收伏笔
        max_numbers = get_max_foreshadow_numbers(current_state, volume_number, start_chapter, end_chapter)
        
        # 获取未回收的伏笔状态
        unrecovered_state = get_unrecovered_foreshadowing(current_state)
        
        # 修改获取必须回收的伏笔列表，范围从第1章到end_chapter
        foreshadowing_list = get_foreshadowing_list(current_state, 1, end_chapter, filepath)
        
        # 4. 初始化LLM适配器
        llm = create_llm_adapter(
            api_key=api_key,
            base_url=base_url,
            interface_format=interface_format,
            model_name=llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        logging.info("构造生成提示词...")
        # 5. 构造提示词
        prompt = chapter_blueprint_prompt.format(
            genre=genre,
            Total_volume_number=total_volume_number,
            number_of_chapters=number_of_chapters,  # 修改：使用总章节数
            word_number=word_number,
            user_guidance=user_guidance,
            novel_architecture=novel_setting,
            volume_outline=volume_outline,
            volume_number=volume_number,
            x=start_chapter,  # 章节范围起点
            y=end_chapter,    # 章节范围终点
            chapter_list=chapter_list,
            n=start_chapter,  # 确保n也使用正确的起始章节号
            m=end_chapter,    # 确保m也使用正确的结束章节号
            Foreshadowing_state=unrecovered_state,
            Foreshadowing_number=max_numbers,
            Foreshadowing_list=foreshadowing_list,
            main_character=main_character  # 添加主要角色信息
        )
        
        logging.info("调用LLM生成内容...")
        # 6. 调用LLM生成内容并处理
        # 显示提示词编辑器 - 修复对话框实现
        def show_prompt_editor(prompt_text, callback):
            import tkinter as tk
            import customtkinter as ctk  # 使用 customtkinter 替代 ttk
            
            dialog = ctk.CTkToplevel()
            dialog.title("编辑章节生成提示词")
            dialog.geometry("800x600")
            
            # 使用 CTkTextbox 替代 ttk.Text
            textbox = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 12))
            textbox.pack(fill="both", expand=True, padx=10, pady=10)
            textbox.insert("1.0", prompt_text)
            
            btn_frame = ctk.CTkFrame(dialog)
            btn_frame.pack(pady=10)
            
            def on_confirm():
                modified_prompt = textbox.get("1.0", "end-1c")
                dialog.destroy()
                callback(modified_prompt)
                
            def on_cancel():
                dialog.destroy()
                callback(None)
                
            # 使用 CTkButton 替代 ttk.Button
            ctk.CTkButton(
                btn_frame, 
                text="确认生成", 
                command=on_confirm,
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=5)
            
            ctk.CTkButton(
                btn_frame, 
                text="取消", 
                command=on_cancel,
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=5)
            
            # 使用 CTkLabel 替代 ttk.Label
            word_count_label = ctk.CTkLabel(
                btn_frame, 
                text="字数: 0",
                font=("Microsoft YaHei", 12)
            )
            word_count_label.pack(side="right", padx=10)
            
            def update_word_count(event=None):
                text = textbox.get("1.0", "end-1c")
                words = len(text)
                word_count_label.configure(text=f"字数: {words}")
            
            textbox.bind("<KeyRelease>", update_word_count)
            update_word_count()
            
            dialog.protocol("WM_DELETE_WINDOW", on_cancel)
            dialog.transient(dialog.master)
            dialog.grab_set()
        
        # 异步调用LLM
        def async_llm_call(prompt, callback):
            def llm_thread():
                try:
                    result = invoke_with_cleaning(llm, prompt)
                    if not result or not result.strip():
                        raise ValueError("LLM返回内容为空")
                        
                    # 先保存章节目录
                    directory_file = os.path.join(filepath, "章节目录.txt")
                    existing_content = read_file(directory_file) if os.path.exists(directory_file) else ""
                    new_content = existing_content + ("\n\n" if existing_content else "") + result
                    clear_file_content(directory_file)
                    save_string_to_txt(new_content, directory_file)
                    
                    # 再更新伏笔状态
                    try:
                        foreshadow_state = update_foreshadowing_state(result, filepath)
                        if foreshadow_state:
                            foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
                            clear_file_content(foreshadow_file)
                            save_string_to_txt(foreshadow_state, foreshadow_file)
                    except Exception as e:
                        logging.error(f"更新伏笔状态失败: {str(e)}")
                        
                    callback(result)
                except Exception as e:
                    callback(None, str(e))
            
            import threading
            thread = threading.Thread(target=llm_thread)
            thread.daemon = True
            thread.start()
        
        # 构建提示词
        prompt = chapter_blueprint_prompt.format(
            genre=genre,
            Total_volume_number=total_volume_number,
            number_of_chapters=number_of_chapters,
            word_number=word_number,
            user_guidance=user_guidance,
            novel_architecture=novel_setting,
            volume_outline=volume_outline,
            volume_number=volume_number,
            x=start_chapter,
            y=end_chapter,
            chapter_list=chapter_list,
            n=start_chapter,
            m=end_chapter,
            Foreshadowing_state=unrecovered_state,
            Foreshadowing_number=max_numbers,
            Foreshadowing_list=foreshadowing_list,
            main_character=main_character
        )
        
        # 创建异步结果变量和事件
        result_data = {"content": None, "error": None}
        completion_event = threading.Event()
        
        def on_prompt_edit(edited_prompt):
            if edited_prompt is None:
                result_data["error"] = "用户取消了生成"
                completion_event.set()
                return
                
            def on_llm_complete(result, error=None):
                if error:
                    result_data["error"] = error
                else:
                    result_data["content"] = result
                completion_event.set()
                
            async_llm_call(edited_prompt, on_llm_complete)
        
        # 显示提示词编辑器
        show_prompt_editor(prompt, on_prompt_edit)
        
        # 等待完成
        completion_event.wait()
        
        if result_data["error"]:
            raise ValueError(result_data["error"])
            
        return result_data["content"]

    except Exception as e:
        error_msg = f"生成章节内容时出错: {str(e)}"
        logging.error(error_msg)
        raise ValueError(error_msg)

def get_latest_chapters(directory_content: str, num_chapters: int) -> str:
    """
    从章节目录中提取最近 N 章的内容
    
    Args:
        directory_content: 章节目录内容
        num_chapters: 要提取的最近章节数量
        
    Returns:
        str: 合并后的章节内容文本
    """
    # 按章节分割内容
    chapters = []
    current_chapter = ""
    
    # 支持新旧两种格式
    # 新格式: 第X章《标题》【章节作用】...
    # 旧格式: 第X章 标题 ├─本章定位...
    for line in directory_content.splitlines():
        # 检测新的章节开始
        if line.startswith('第') and ('章' in line):
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = line
        elif current_chapter:
            current_chapter += '\n' + line
            
    # 添加最后一个章节
    if current_chapter:
        chapters.append(current_chapter)
        
    # 获取最近的N章
    latest_chapters = chapters[-num_chapters:] if num_chapters > 0 else chapters
    
    # 合并章节内容
    return '\n\n'.join(latest_chapters)
