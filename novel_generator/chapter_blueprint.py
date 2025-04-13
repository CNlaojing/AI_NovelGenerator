# -*- coding: utf-8 -*-
import os
import logging
import re
from novel_generator.common import invoke_with_cleaning
from llm_adapters import create_llm_adapter
from novel_generator.volume import extract_volume_outline  # 添加这一行
from prompt_definitions import chapter_blueprint_prompt, chunked_chapter_blueprint_prompt
from utils import read_file, save_string_to_txt, clear_file_content

def analyze_directory_status(filepath: str) -> tuple:
    """分析目录文件状态，返回最新章节号"""
    try:
        directory_file = os.path.join(filepath, "Novel_directory.txt")
        if not os.path.exists(directory_file):
            return 0, [], []
            
        content = read_file(directory_file)
        if not content:
            return 0, [], []
            
        # 查找所有章节号并转换为整数
        chapter_numbers = []
        for match in re.finditer(r'第(\d+)章.*?(?=第\d+章|$)', content, re.DOTALL):
            try:
                chapter_num = int(match.group(1))
                chapter_info = match.group(0)
                # 检查是否包含完整章节信息(至少要有标题和分类信息)
                if '├─本章定位：' in chapter_info and '└─本章简述：' in chapter_info:
                    chapter_numbers.append(chapter_num)
            except:
                continue
                
        if not chapter_numbers:
            return 0, [], []
            
        last_chapter = max(chapter_numbers)
        chapter_numbers = sorted(chapter_numbers)  # 确保有序
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
        volume_file = os.path.join(filepath, "Novel_Volume.txt")
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
    save_interval: int = 5  # 每生成多少章保存一次
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
    directory_file = os.path.join(filepath, "Novel_directory.txt")
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

            # 分段生成当前卷内容
            current_start = start_chapter
            while current_start <= vol['end']:
                current_end = min(current_start + save_interval - 1, vol['end'])
                
                try:
                    # 生成一段章节内容
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
                        user_guidance=user_guidance
                    )
                    
                    if result:
                        generated_content += ("\n\n" if generated_content else "") + result
                        chapters_generated += (current_end - current_start + 1)
                        
                        # 保存当前进度
                        final_content = existing_content
                        if generated_content:
                            if final_content:
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
    user_guidance: str = ""
) -> str:
    """生成指定卷的章节内容"""
    logging.info(f"开始生成第{volume_number}卷章节目录 (第{start_chapter}-{end_chapter}章)...")
    
    try:
        # 1. 读取必要的输入文件
        novel_setting = read_file(os.path.join(filepath, "Novel_architecture.txt"))
        volume_file = os.path.join(filepath, "Novel_Volume.txt")
        volume_outline_full = read_file(volume_file)
        if not volume_outline_full:
            raise ValueError("找不到分卷大纲文件或文件为空")

        # 2. 提取当前卷的大纲内容
        volume_outline = extract_volume_outline(volume_outline_full, volume_number)
        if not volume_outline:
            raise ValueError(f"无法找到第{volume_number}卷的大纲内容")

        # 3. 读取最新3章的章节目录
        directory_file = os.path.join(filepath, "Novel_directory.txt")
        full_chapter_list = read_file(directory_file) if os.path.exists(directory_file) else ""
        chapter_list = get_last_n_chapters(full_chapter_list, 3)
        
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
        prompt = chunked_chapter_blueprint_prompt.format(
            user_guidance=user_guidance,
            novel_architecture=novel_setting,
            volume_outline=volume_outline,  # 使用当前卷的大纲
            volume_number=volume_number,
            x=start_chapter,
            y=end_chapter,
            chapter_list=chapter_list,  # 使用最新3章目录
            n=start_chapter,
            m=end_chapter
        )
        
        logging.info("调用LLM生成内容...")
        # 6. 调用LLM生成内容
        result = invoke_with_cleaning(llm, prompt)
        if not result:
            raise ValueError("生成结果为空")
            
        logging.info("章节目录生成完成")
        return result

    except Exception as e:
        logging.error(f"生成章节目录时出错: {str(e)}")
        return ""
