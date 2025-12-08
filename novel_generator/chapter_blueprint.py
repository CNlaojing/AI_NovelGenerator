# novel_generator/chapter_blueprint.py
# -*- coding: utf-8 -*-
import os
import re
import json  # 添加json导入
import threading

from novel_generator.common import invoke_stream_with_cleaning
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
                    # logging.debug(f"找到章节: {chapter_num}") # 添加日志记录
                    chapter_numbers.append(chapter_num)
                except ValueError:
                    # logging.warning(f"无法将章节号转换为整数: {match.group(1)}")
                    pass
                except Exception as e:
                    # logging.warning(f"解析章节 {match.group(1)} 时出错: {str(e)}")
                    continue
                
        if not chapter_numbers:
            # logging.info("未找到任何有效章节")
            return 0, [], []
            
        last_chapter = max(chapter_numbers)
        chapter_numbers = sorted(chapter_numbers)
        # logging.info(f"分析完成：最新章节 = {last_chapter}, 共{len(chapter_numbers)}章")
        return last_chapter, chapter_numbers, content
        
    except Exception as e:
        print(f"分析目录状态时出错: {str(e)}")
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
        # 修正后的正则表达式，更具鲁棒性，能处理多种格式
        # 例如: #=== 第1卷...第1章 至 第130章 ===
        # 或: 第一卷《卷名》第1章 至 第130章
        volume_pattern = r'第\s*([一二三四五六七八九十\d]+)\s*卷.*?第\s*(\d+)\s*章\s*至\s*第\s*(\d+)\s*章'
        matches = re.finditer(volume_pattern, content, re.IGNORECASE)
        
        # logging.info(f"使用正则表达式 '{volume_pattern}' 在 分卷大纲.txt 中查找匹配项...")
        
        for match in matches:
            volume_str = match.group(1)
            start_chap_str = match.group(2)
            end_chap_str = match.group(3)
            
            # logging.info(f"找到匹配: 卷='{volume_str}', 起始='{start_chap_str}', 结束='{end_chap_str}'")
            volume_num = match.group(1)
            # 将中文数字转换为阿拉伯数字
            vol_num = 0
            try:
                # 尝试直接转为整数 (处理 "1", "2" 等)
                vol_num = int(volume_str)
            except ValueError:
                # 如果失败，则处理中文数字
                chinese_to_arabic = {
                    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, 
                    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10
                    # 可根据需要扩展
                }
                vol_num = chinese_to_arabic.get(volume_str, 0)

            if vol_num == 0:
                print(f"无法解析卷号 '{volume_str}'，跳过此条目。")
                continue

            start_chap = int(start_chap_str)
            end_chap = int(end_chap_str)
            volume_ranges.append({
                'volume': vol_num,
                'start': start_chap,
                'end': end_chap
            })
            
        # 按卷号排序
        volume_ranges.sort(key=lambda x: x['volume'])
        return volume_ranges
        
    except Exception as e:
        print(f"分析分卷范围时出错: {str(e)}")
        return []

def find_current_volume(chapter_number: int, volume_ranges: list) -> tuple:
    """
    查找指定章节所在的卷号及是否在卷尾。
    如果章节号为0（尚未开始），则返回第一卷的信息。
    返回: (当前卷号, 是否卷尾)
    """
    if not volume_ranges:
        return 1, False

    if chapter_number == 0:
        return 1, False

    for vol_info in volume_ranges:
        if vol_info['start'] <= chapter_number <= vol_info['end']:
            # 找到章节所在的卷
            is_end = (chapter_number == vol_info['end'])
            # logging.debug(f"章节 {chapter_number} 在第 {vol_info['volume']} 卷 ({vol_info['start']}-{vol_info['end']}) 内。是否卷尾: {is_end}")
            return vol_info['volume'], is_end
            
    # 如果章节号大于所有已定义的卷范围，则认为属于新的一卷
    # 检查章节号是否大于最后一个定义卷的结束章节
    if volume_ranges and chapter_number > volume_ranges[-1]['end']:
        # logging.debug(f"章节 {chapter_number} 超出所有定义范围，认定为新的一卷 (大于第 {volume_ranges[-1]['volume']} 卷)。")
        return volume_ranges[-1]['volume'] + 1, False
        
    # 如果循环结束仍未找到，说明章节号可能位于卷之间的间隙，或者是一个未定义的范围
    # 在这种情况下，不应默认返回第一卷，而是应该记录一个更明确的警告
    print(f"无法为章节 {chapter_number} 在已定义的卷范围 {volume_ranges} 中找到对应的卷。请检查 分卷大纲.txt 的配置。")
    # 返回一个明确的错误指示或默认值，这里我们暂时返回卷1，但日志是关键
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
        print(f"获取卷进度时出错: {str(e)}")
        return 1, 0, 1, 0, False, False

def analyze_chapter_status(filepath):
    """
    占位函数：分析章节状态，返回 (last_chapter, current_vol, is_volume_end)
    你可以根据实际需求完善此函数逻辑。
    """
    # 默认返回0, 1, True，防止UI报错
    return 0, 1, True

def Chapter_blueprint_generate(
    llm_adapter,
    number_of_chapters: int,
    filepath: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: int = 600,
    user_guidance: str = "",
    start_from_volume: int = None,  # 此参数在新逻辑中不再直接使用，但保留以兼容旧调用
    generate_single: bool = False,  # 行为被 number_of_chapters 驱动
    save_interval: int = 20,
    main_character: str = "",
    log_func=None,
    custom_prompt: str = None
) -> str:
    """根据小说架构和指定的章节数量，智能、跨卷地生成章节目录大纲。"""
    def _log(message):
        if log_func:
            log_func(message)
        else:
            print(message)

    _log("开始生成章节目录...")

    # 1. 分析当前状态
    last_chapter, _, _ = analyze_directory_status(filepath)
    volumes = analyze_volume_range(filepath)
    if not volumes:
        raise ValueError("分卷大纲.txt 为空或格式不正确，无法确定章节范围。")

    directory_file = os.path.join(filepath, "章节目录.txt")
    
    chapters_generated_total = 0
    chapters_to_generate_total = number_of_chapters

    # 2. 主生成循环，由需要生成的总章数驱动
    while chapters_generated_total < chapters_to_generate_total:
        # 确定当前批次的起始章节
        current_start_chapter = last_chapter + 1 + chapters_generated_total

        # 找到该章节所属的卷
        current_vol_info = next((v for v in volumes if v['start'] <= current_start_chapter <= v['end']), None)
        if not current_vol_info:
            _log(f"❌ 错误：无法为章节 {current_start_chapter} 找到对应的分卷信息。请检查 分卷大纲.txt。")
            break # 无法继续，中断循环

        current_vol_num = current_vol_info['volume']
        current_vol_end = current_vol_info['end']
        
        # 计算本批次可以生成的章节数
        remaining_in_task = chapters_to_generate_total - chapters_generated_total
        remaining_in_volume = current_vol_end - current_start_chapter + 1
        
        # 本次调用要生成的章节数，不能超过save_interval、卷的剩余容量和任务的剩余需求
        chapters_in_this_batch = min(save_interval, remaining_in_volume, remaining_in_task)
        if chapters_in_this_batch <= 0:
            _log(f"第 {current_vol_num} 卷没有更多需要生成的章节，或任务已完成。")
            break

        current_end_chapter = current_start_chapter + chapters_in_this_batch - 1
        _log(f"计划在第 {current_vol_num} 卷中生成 {chapters_in_this_batch} 章 (从 {current_start_chapter} 到 {current_end_chapter})")

        try:
            # 3. 调用LLM生成一个批次的章节蓝图
            result = generate_volume_chapters(
                llm_adapter=llm_adapter,
                filepath=filepath,
                volume_number=current_vol_num,
                start_chapter=current_start_chapter,
                end_chapter=current_end_chapter,
                user_guidance=user_guidance,
                main_character=main_character,
                log_func=log_func,
                is_incremental=True, # 总是增量模式
                custom_prompt=custom_prompt
            )
            
            if result:
                # 4. 更新伏笔状态
                foreshadow_state = update_foreshadowing_state(result, filepath, log_func=log_func)
                if foreshadow_state:
                    foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
                    save_string_to_txt(foreshadow_state, foreshadow_file)
                    _log("已更新伏笔状态")

                # 5. 追加保存到目录文件
                with open(directory_file, 'a', encoding='utf-8') as f:
                    # 确保文件不是空的，并且与前一节之间有空行分隔
                    if f.tell() > 0:
                        f.write("\n\n")
                    f.write(result)
                
                chapters_generated_total += chapters_in_this_batch
                _log(f"已生成并保存至第 {current_end_chapter} 章。累计生成: {chapters_generated_total}/{chapters_to_generate_total}")
            else:
                _log(f"❌ LLM未能为章节 {current_start_chapter}-{current_end_chapter} 生成有效内容，中止任务。")
                break

        except Exception as e:
            _log(f"❌ 生成第 {current_start_chapter}-{current_end_chapter} 章时出错: {str(e)}")
            raise
        
        # 如果是单次增量生成模式，则完成一个批次后就退出循环
        if generate_single:
            _log("单次增量生成模式完成，已停止。")
            break

    _log(f"章节目录生成完成。总共生成了 {chapters_generated_total} 章。")
    return read_file(directory_file)

def get_last_n_chapters(content: str, n: int = 3) -> str:
    """获取最新的n章章节目录内容"""
    try:
        if not content:
            return ""
        
        # 改进的正则表达式，确保只匹配行首的“第X章”
        # re.MULTILINE 让 ^ 匹配每行的开头
        # re.DOTALL 让 . 可以匹配换行符
        pattern = r"^第\d+章.*?(?=^第\d+章|\Z)"
        
        chapters = [match.group(0).strip() for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL)]
        
        # logging.info(f"使用改进的正则分割章节，共找到 {len(chapters)} 章。")
        
        # 返回最后n章
        last_n_chapters = chapters[-n:]
        # logging.info(f"提取最后 {n} 章，实际提取到 {len(last_n_chapters)} 章。")
        return "\n\n".join(last_n_chapters)
            
    except Exception as e:
        print(f"获取最新{n}章目录时出错: {str(e)}")
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
        # logging.info("=== 开始分析最大伏笔编号 ===")
        # 从内容中匹配所有伏笔编号，包括已回收的
        all_fids = re.findall(r'[〇]?([A-Z]F)(\d{3})', current_state)
        # logging.debug(f"找到 {len(all_fids)} 个伏笔编号")
        
        for prefix, num in all_fids:
            for type_name, abbr in type_abbr.items():
                if prefix == abbr:
                    current_num = int(num)
                    max_numbers[type_name] = max(max_numbers[type_name], current_num)
                    # logging.debug(f"更新 {type_name} 最大编号: {current_num}")
        
        # 构建输出格式
        result = ["各类型已有伏笔最大编号："]
        for type_name, max_num in max_numbers.items():
            if max_num > 0:  # 只显示有编号的类型
                result.append(f"{type_name} {type_abbr[type_name]}：{type_abbr[type_name]}{max_num:03d}")
                
        # logging.info("=== 完成最大伏笔编号分析 ===")
        return "\n".join(result)

    except Exception as e:
        print(f"计算最大伏笔编号时出错: {str(e)}")
        return "各类型已有伏笔最大编号：\n(处理出错)"

def get_chapter_content(fid: str, chapter_num: int, filepath: str) -> dict:
    """从章节目录中获取指定章节的标题和伏笔条目内容"""
    try:
        # 确保参数类型正确
        if isinstance(chapter_num, str) and isinstance(fid, int):
            # 如果参数顺序颠倒，交换它们
            # logging.debug(f"参数顺序颠倒，交换参数: chapter_num={fid}, fid={chapter_num}")
            chapter_num, fid = fid, chapter_num
            
        # logging.debug(f"获取第{chapter_num}章中伏笔 {fid} 的相关内容")
        # 检查filepath是否已经是完整路径
        if os.path.isdir(filepath):
            # 如果是目录，则拼接文件名
            directory_file = os.path.join(filepath, "章节目录.txt")
        else:
            # 如果已经是完整路径，则直接使用
            directory_file = filepath
            
        # logging.debug(f"使用文件路径: {directory_file}")
        if not os.path.exists(directory_file):
            print(f"章节目录文件不存在: {directory_file}")
            return {'title': '', 'foreshadow': '', 'description': ''}
            
        content = read_file(directory_file)
        
        if not content:
            print("章节目录文件为空")
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
                # logging.debug(f"找到第{chapter_num}章的起始行 {i+1}，位置: {start_pos}")
                # 找到起始位置后，继续查找下一章的起始位置
                for j in range(i + 1, len(lines)):
                    if re.match(next_chapter_start_pattern, lines[j].strip()):
                        # 计算精确的字符结束位置（下一章的起始位置）
                        end_pos = content.find(lines[j])
                        # logging.debug(f"找到第{chapter_num + 1}章的起始行 {j+1}，位置: {end_pos}")
                        break
                break # 找到当前章节起始位置后就跳出外层循环

        if start_pos == -1:
            print(f"无法找到第{chapter_num}章的起始标记")
            return {'title': '', 'foreshadow': '', 'description': ''}

        # 提取当前章节的完整内容
        chapter_content = content[start_pos:end_pos].strip()
        # logging.debug(f"收集到第{chapter_num}章内容（从 {start_pos} 到 {end_pos}），长度: {len(chapter_content)}字符")
        # 添加更详细的日志记录，用于调试特定章节
        if chapter_num == 25:
            print(f"-- DEBUG Chapter 25 Content --\n{chapter_content}\n-- END DEBUG Chapter 25 Content --")

        # 3. 获取章节标题
        title_match = re.match(r"第\d+章\s+([^\n]+)", chapter_content)
        chapter_title = title_match.group(1) if title_match else ""
        # logging.debug(f"章节标题: {chapter_title}")
        
        # 4. 在章节内容中查找伏笔ID
        # 首先尝试在伏笔条目部分查找
        foreshadow_section_match = re.search(r"├─伏笔条目：\n([\s\S]*?)(?=├─颠覆指数|└─本章简述)", chapter_content)
        
        if (foreshadow_section_match):
            foreshadow_section = foreshadow_section_match.group(1)
            # logging.debug(f"找到伏笔条目部分，长度: {len(foreshadow_section)}字符")
            
            # 使用正则表达式查找特定伏笔ID的行 (使用 \\s 避免 SyntaxWarning)
            fid_pattern = f"[│├└─\\s]*{re.escape(fid)}[^\n]*"
            fid_match = re.search(fid_pattern, foreshadow_section)
            
            if (fid_match):
                foreshadow_line = fid_match.group(0).strip()
                # 清理行首的特殊字符
                clean_line = re.sub(r'^[│├└─\s]+', '', foreshadow_line)
                # logging.debug(f"在第{chapter_num}章伏笔条目部分找到伏笔 {fid}: {clean_line}")
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
                # logging.debug(f"在第{chapter_num}章内容中找到伏笔 {fid}: {clean_line}")
                return {
                    'title': chapter_title or f"第{chapter_num}章",
                    'foreshadow': clean_line,
                    'description': clean_line
                }
        
        # 如果在章节内容中未找到，则返回空结果，不再进行全局搜索
        print(f"在第{chapter_num}章内容中未找到伏笔 {fid}")
        return {'title': chapter_title or f"第{chapter_num}章", 'foreshadow': '', 'description': ''}
        
    except Exception as e:
        print(f"获取章节内容时出错: {str(e)}")
        return {'title': '', 'foreshadow': '', 'description': ''}

def get_unrecovered_foreshadowing(current_state: str, filepath: str) -> str:
    """获取未回收的伏笔状态并组织完整的伏笔条目"""
    try:
        # logging.info("=== 开始解析未回收伏笔状态并获取完整条目 ===")
        
        # 初始化结果字典和当前伏笔ID
        result_dict = {}
        current_type = None
        current_fid = None  # 添加 current_fid 的定义
        
        # 1. 从伏笔状态.txt中提取未回收的伏笔
        for line in current_state.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            if line.endswith('：'):  # 类型行
                current_type = line[:-1]
                if current_type not in result_dict:
                    result_dict[current_type] = {}
                continue
                
            # 只处理未回收的伏笔（不以〇开头的伏笔标题行）
            if not line.startswith('〇') and '：' in line and not line.startswith('-'):
                fid_match = re.search(r'([A-Z]F\d{3})', line)
                title_match = re.search(r'：(.*?)（', line) if '（' in line else re.search(r'：(.*)$', line)
                deadline_match = re.search(r'（第(\d+)章前必须回收）', line)
                
                if fid_match and title_match:
                    current_fid = fid_match.group(1)  # 更新当前处理的伏笔ID
                    title = title_match.group(1).strip()
                    deadline = deadline_match.group() if deadline_match else ""
                    
                    if current_type:
                        result_dict[current_type][current_fid] = {
                            'title': title,
                            'deadline': deadline,
                            'states': []
                        }
                        
            elif line.startswith('-') and current_type:
                # 提取状态和章节号
                state_match = re.search(r'([^：]+)：第(\d+)章', line[1:].strip())
                if state_match:
                    for fid in result_dict[current_type]:
                        if fid == current_fid:  # 使用上一个处理的伏笔ID
                            result_dict[current_type][fid]['states'].append({
                                'state': state_match.group(1),
                                'chapter': int(state_match.group(2))
                            })

        # 2. 生成结果文本
        result = []
        type_order = ['暗线伏笔', '人物伏笔', '主线伏笔', '支线伏笔', '一般伏笔']
        
        for type_name in type_order:
            if type_name not in result_dict or not result_dict[type_name]:
                continue
                
            result.append(f"{type_name}：")
            for fid, info in sorted(result_dict[type_name].items()):
                # 添加伏笔ID和标题行
                result.append(f"{fid}：")
                
                # 按章节号排序获取每个状态的完整伏笔条目
                for state in sorted(info['states'], key=lambda x: x['chapter']):
                    chapter_content = get_chapter_content(fid, state['chapter'], filepath)
                    if chapter_content['foreshadow']:
                        result.append(f"第{state['chapter']}章：{chapter_content['foreshadow']}")
                
                result.append("")  # 每个伏笔后空一行
            
            result.append("")  # 每个类型后空一行
        
        final_result = "\n".join(result).strip()
        # logging.info(f"成功整理 {sum(len(fids) for fids in result_dict.values())} 个未回收伏笔的完整条目")
        return final_result

    except Exception as e:
        print(f"获取未回收伏笔状态和完整条目时出错: {str(e)}")
        return ""

def sort_states_by_chapter(states: list) -> list:
    """按章节号对状态列表进行排序"""
    try:
        def get_chapter_number(state: str) -> int:
            match = re.search(r'第(\d+)章', state)
            return int(match.group(1)) if match else 0
        return sorted(states, key=get_chapter_number)
    except Exception as e:
        print(f"状态排序时出错: {str(e)}")
        return states

def update_foreshadowing_state(content: str, filepath: str, force_rescan: bool = False, log_func=None) -> str:
    """
    更新伏笔状态
    Args:
        content: 章节内容
        filepath: 文件路径
        force_rescan: 是否强制重新扫描（初始化时使用）
    """
    def _log(message):
        if log_func:
            log_func(message)
        else:
            print(message)

    try:
        _log("=== 开始更新伏笔状态 ===")
        
        # 按照伏笔类型分组存储
        foreshadow_dict = {}
        recovered_ids = set()

        # 如果是强制重新扫描，则不读取现有状态文件
        foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
        current_state = "" if force_rescan else (read_file(foreshadow_file) if os.path.exists(foreshadow_file) else "")
        
        # 1. 先读取并保留现有状态文件中的所有信息
        current_type = None
        if current_state:
            _log("=== 解析现有状态文件 ===")
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
                'text': '\n'.join(current_text)  # 修复这里的字符串拼接
            })
            
        _log(f"找到 {len(chapter_matches)} 个章节")
        
        for chapter_info in chapter_matches:
            chapter_text = chapter_info['text']
            try:
                chapter_match = re.search(r'第(\d+)章', chapter_info['chapter'])
                if not chapter_match:
                    _log("无法提取章节号，跳过此章节")
                    continue
                
                chapter_num = int(chapter_match.group(1))
                _log(f"\n处理第{chapter_num}章的伏笔")
                
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
                    _log(f"第{chapter_num}章未找到伏笔条目部分")
                    continue

                foreshadow_lines = [line.strip().lstrip('│├└') for line in foreshadow_section.splitlines() if line.strip()]
                _log(f"找到 {len(foreshadow_lines)} 行伏笔条目")
                
                for line in foreshadow_lines:
                    if not line or '-' not in line:
                        continue

                    try:
                        parts = [p.strip() for p in line.split('-')]
                        if len(parts) < 3:
                            _log(f"伏笔格式不正确，跳过: {line}")
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
                            _log(f"无法解析伏笔ID或类型: {line}")
                            continue

                        fid = fid_match.group(1)
                        ftype = type_match.group(1)

                        if ftype not in foreshadow_dict:
                            foreshadow_dict[ftype] = {}
                            # _log(f"新增伏笔类型: {ftype}")

                        # 初始化或更新伏笔信息
                        if fid not in foreshadow_dict[ftype]:
                            foreshadow_dict[ftype][fid] = {
                                'title': title,
                                'deadline': deadline,
                                'states': [],
                                'recovered': False
                            }
                            # _log(f"新增伏笔: {fid} - {title}")

                        # 若已存在但未设置deadline，则补充
                        if deadline and not foreshadow_dict[ftype][fid].get('deadline'):
                            foreshadow_dict[ftype][fid]['deadline'] = deadline

                        state = f"{action}：第{chapter_num}章"
                        if state not in foreshadow_dict[ftype][fid]['states']:
                            foreshadow_dict[ftype][fid]['states'].append(state)
                            # _log(f"更新伏笔状态: {fid} - {state}")

                        if '回收' in action:
                            foreshadow_dict[ftype][fid]['recovered'] = True
                            recovered_ids.add(fid)
                            # _log(f"标记伏笔已回收: {fid}")

                    except Exception as e:
                        _log(f"处理伏笔行出错: {line}\n错误: {str(e)}")
                        continue

            except Exception as e:
                _log(f"处理第{chapter_num if 'chapter_num' in locals() else '?'}章出错: {str(e)}")
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

        # 如果没有找到任何伏笔，则创建一个空的模板文件，以避免UI流程中断
        if not final_content:
            _log("未发现任何伏笔信息，将创建空的伏笔状态文件。")
            final_content = """一般伏笔：

暗线伏笔：

主线伏笔：

支线伏笔：

人物伏笔：
"""

        clear_file_content(foreshadow_file)
        save_string_to_txt(final_content, foreshadow_file)
        
        return final_content

    except Exception as e:
        _log(f"更新伏笔状态时出错: {str(e)}")
        raise

def prepare_chapter_blueprint_prompt(
    filepath: str,
    volume_number: int,
    start_chapter: int,
    end_chapter: int,
    user_guidance: str = "",
    main_character: str = "",
    is_incremental: bool = False
) -> str:
    """仅准备用于章节目录生成的提示词，不调用LLM"""
    # logging.info(f"准备章节目录生成提示词 (第{start_chapter}-{end_chapter}章)...")
    try:
        # 读取项目基本信息文件
        config_file = os.path.join(filepath, "基本信息.json")
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            # 如果文件不存在，使用默认值
            config = {}

        genre = config.get("genre", "玄幻")
        total_volume_number = int(config.get("volume_count", 3))
        number_of_chapters = int(config.get("num_chapters", 100))
        word_number = int(config.get("word_number", 3000))

        novel_setting = read_file(os.path.join(filepath, "小说设定.txt"))
        volume_outline = ""
        # 无论是否增量模式，都尝试加载正确的卷大纲
        # logging.info(f"为第 {volume_number} 卷加载大纲。")
        volume_file = os.path.join(filepath, "分卷大纲.txt")
        volume_outline_full = read_file(volume_file)
        if not volume_outline_full:
            volume_outline = "(分卷大纲文件不存在或为空)"
            print(volume_outline)
        else:
            volume_outline = extract_volume_outline(volume_outline_full, volume_number)
            if not volume_outline:
                volume_outline = f"(未能从分卷大纲.txt中提取到第 {volume_number} 卷的大纲内容)"
                print(volume_outline)

        directory_file = os.path.join(filepath, "章节目录.txt")
        full_chapter_list = read_file(directory_file) if os.path.exists(directory_file) else ""
        chapter_list = get_last_n_chapters(full_chapter_list, 3)
        
        foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
        current_state = read_file(foreshadow_file) if os.path.exists(foreshadow_file) else ""
        
        max_numbers = get_max_foreshadow_numbers(current_state, volume_number, start_chapter, end_chapter)
        unrecovered_state = get_unrecovered_foreshadowing(current_state, filepath)
        
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
            main_character=main_character
        )
        return prompt
    except Exception as e:
        error_msg = f"准备章节目录提示词时出错: {str(e)}"
        print(error_msg)
        raise ValueError(error_msg)

def generate_volume_chapters(
    llm_adapter,
    filepath: str,
    volume_number: int,
    start_chapter: int,
    end_chapter: int,
    user_guidance: str = "",
    main_character: str = "",
    log_func=None,
    is_incremental: bool = False,
    custom_prompt: str = None  # 新增参数，用于接收外部传入的提示词
) -> str:
    """生成指定卷的章节内容"""
    def _log(message, stream=False):
        if log_func:
            log_func(message, stream=stream)
        else:
            print(message, end='' if stream else '\n')

    _log(f"开始生成章节目录 (第{start_chapter}-{end_chapter}章)...")
    
    try:
        prompt = custom_prompt
        if not prompt:
            _log("未提供自定义提示词，将内部生成。")
            prompt = prepare_chapter_blueprint_prompt(
                filepath=filepath,
                volume_number=volume_number,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                user_guidance=user_guidance,
                main_character=main_character,
                is_incremental=is_incremental
            )

        llm = llm_adapter
        
        _log("调用LLM生成内容...")
        # if log_func:
        #     log_func("发送到 LLM 的提示词:\n" + prompt)
        #     log_func("\nLLM 返回内容:")

        result = ""
        for chunk in invoke_stream_with_cleaning(llm, prompt, log_func=log_func, log_stream=False):
            if chunk:
                result += chunk
                _log(chunk, stream=True)
        _log("\n")

        if not result or not result.strip():
            raise ValueError("LLM返回内容为空")

        return result

    except Exception as e:
        error_msg = f"生成章节内容时出错: {str(e)}"
        _log(error_msg)
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
