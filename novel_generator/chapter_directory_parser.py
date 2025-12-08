# chapter_blueprint_parser.py
# -*- coding: utf-8 -*-
import re
import logging
import os
from utils import read_file

# --- New Helper Functions ---

def get_chapter_blueprint_text(directory_content, chapter_number):
    """
    Extracts the full text block for a specific chapter from the directory content.
    """
    # Regex to match from "第X章" until the next "第Y章" or end of file
    pattern = re.compile(rf"^第{chapter_number}章.*?(?=^第\d+章|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(directory_content)
    if match:
        return match.group(0).strip()
    return f"（未找到第{chapter_number}章的章节目录）"

def get_plot_points(filepath, chap_num):
    """
    Gets the plot points from the previous chapter.
    """
    plot_points = ""
    if chap_num > 1:
        plot_points_file = os.path.join(filepath, "剧情要点.txt")
        if os.path.exists(plot_points_file):
            content = read_file(plot_points_file)
            pattern = rf"(##\s*第\s*{chap_num-1}\s*章[\s\S]*?)(?=\n##\s*第|$)"
            match = re.search(pattern, content)
            if match:
                plot_points = match.group(1).strip()
    return plot_points

def get_volume_outline(filepath, chap_num):
    """
    Gets the volume outline for the current chapter.
    """
    volume_outline = ""
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    if os.path.exists(volume_file):
        from novel_generator.volume import extract_volume_outline, find_volume_for_chapter
        volume_content = read_file(volume_file)
        actual_volume_number = find_volume_for_chapter(volume_content, chap_num)
        volume_outline = extract_volume_outline(volume_content, actual_volume_number)
    return volume_outline

# --- Existing Functions ---

def parse_chapter_blueprint(blueprint_text: str):
    """
    解析整份章节蓝图文本，返回一个列表，每个元素是一个 dict。
    此函数经过重构，以支持更详细、多行的章节格式。
    """
    # 使用正则表达式按章节标题分割文本块
    # 这个模式会匹配 "第X章" 并向前看到下一个 "第X章" 或文件末尾
    chapter_chunks = re.split(r'(?=^第\s*\d+\s*章)', blueprint_text.strip(), flags=re.MULTILINE)
    results = []

    # 定义用于提取各个字段的正则表达式
    # re.DOTALL 使得 '.' 可以匹配换行符，非常适合多行字段
    patterns = {
        "chapter_role": re.compile(r'├─本章定位：(.*?)(?=├─|└─)', re.DOTALL),
        "chapter_purpose": re.compile(r'├─核心作用：(.*?)(?=├─|└─)', re.DOTALL),
        "narrative_perspective": re.compile(r'├─叙事视角：(.*?)(?=├─|└─)', re.DOTALL),
        "scene_setting": re.compile(r'├─场景设定：(.*?)(?=├─|└─)', re.DOTALL),
        "characters_and_motives": re.compile(r'├─出场角色与动机：(.*?)(?=├─|└─)', re.DOTALL),
        "plot_脈络": re.compile(r'├─情节脉络（起-承-转-合）：(.*?)(?=├─|└─)', re.DOTALL),
        "suspense_type": re.compile(r'├─悬念类型：(.*?)(?=├─|└─)', re.DOTALL),
        "emotion_evolution": re.compile(r'├─情绪演变：(.*?)(?=├─|└─)', re.DOTALL),
        "foreshadowing": re.compile(r'├─伏笔条目：(.*?)├─颠覆指数', re.DOTALL),
        "plot_twist_level": re.compile(r'├─颠覆指数：(.*?)(?=└─)', re.DOTALL),
        "chapter_summary": re.compile(r'└─本章简述：(.*)', re.DOTALL)
    }

    for chunk in chapter_chunks:
        if not chunk.strip():
            continue

        lines = chunk.split('\n')
        first_line = lines[0].strip()

        # 从第一行提取章节号和标题
        title_match = re.match(r'第\s*(\d+)\s*章\s*(.*)', first_line)
        if not title_match:
            continue
        
        chapter_number = int(title_match.group(1))
        
        # 清理标题
        title = title_match.group(2).strip()
        if title.startswith('-'):
            title = title[1:].lstrip()
        if (title.startswith('[') and title.endswith(']')) or \
           (title.startswith('《') and title.endswith('》')):
            title = title[1:-1]
        
        chapter_data = {
            "chapter_number": chapter_number,
            "chapter_title": title.strip(),
            "chapter_role": "",
            "chapter_purpose": "",
            "narrative_perspective": "",
            "scene_setting": "",
            "characters_and_motives": "",
            "plot_脈络": "",
            "suspense_type": "",
            "emotion_evolution": "",
            "foreshadowing": "",
            "plot_twist_level": "",
            "chapter_summary": ""
        }

        # 遍历所有模式，从文本块中提取信息
        for key, pattern in patterns.items():
            match = pattern.search(chunk)
            if match:
                # 清理提取到的文本：去除首尾的空白符和多余的装饰性字符
                content = match.group(1).strip()
                # 对于多行字段，进一步清理每行的前导字符
                lines = [re.sub(r'^[│├└─\s]+', '', line) for line in content.split('\n')]
                chapter_data[key] = '\n'.join(lines).strip()

        # 特殊处理伏笔，保留其原始格式
        foreshadow_match = patterns["foreshadowing"].search(chunk)
        if foreshadow_match:
            # 只移除外层的空白，保留内部的缩进和格式
            chapter_data["foreshadowing"] = foreshadow_match.group(1).strip()

        results.append(chapter_data)

    # 按照 chapter_number 排序后返回
    if results:
        results.sort(key=lambda x: x["chapter_number"])
    return results


def get_chapter_info_from_blueprint(blueprint_text: str, target_chapter_number: int):
    """
    在已经加载好的章节蓝图文本中，找到对应章号的结构化信息，返回一个 dict。
    若找不到则返回一个默认的结构。
    """
    try:
        # 预处理文本，移除多余的空行和特殊字符
        cleaned_text = re.sub(r'\n\s*\n+', '\n\n', blueprint_text.strip())
        
        # 分卷标记模式
        volume_pattern = r'#{1,6}\s*第[一二三四五六七八九十]卷'
        
        # 按卷分割文本（如果有分卷标记）
        volume_sections = re.split(volume_pattern, cleaned_text)
        
        # 在所有分卷中查找目标章节
        all_chapters = []
        for section in volume_sections:
            chapters = parse_chapter_blueprint(section)
            all_chapters.extend(chapters)
            
        # 查找目标章节
        target_chapter = next(
            (ch for ch in all_chapters if ch["chapter_number"] == target_chapter_number), 
            None
        )
        
        if target_chapter:
            return target_chapter
            
    except Exception as e:
        logging.error(f"解析章节 {target_chapter_number} 信息时出错: {str(e)}")
    
    # 如果找不到，返回 None
    return None

def get_next_chapter_info_from_blueprint(filepath: str, current_chapter_number: int):
    """
    获取下一章节的信息。
    """
    next_chapter_number = current_chapter_number + 1
    
    # 确定下一章所属的卷
    volume_number = 1
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    if os.path.exists(volume_file):
        with open(volume_file, 'r', encoding='utf-8') as f:
            volume_content = f.read()
            for match in re.finditer(r'第(\d+)卷.*?第(\d+)章.*?第(\d+)章', volume_content):
                if int(match.group(2)) <= next_chapter_number <= int(match.group(3)):
                    volume_number = int(match.group(1))
                    break
    
    # 构建下一章蓝图文件的路径
    blueprint_filename = f"第{next_chapter_number}章-章节目录.txt"
    blueprint_path = os.path.join(filepath, f"第{volume_number}卷", blueprint_filename)
    
    if os.path.exists(blueprint_path):
        blueprint_text = read_file(blueprint_path)
        # 因为文件只包含一章，所以直接解析
        chapters = parse_chapter_blueprint(blueprint_text)
        if chapters:
            return chapters[0]

    # 如果文件不存在或解析失败，返回默认值
    return {
        "chapter_number": next_chapter_number,
        "chapter_title": f"第{next_chapter_number}章",
        "chapter_role": "常规章节",
        "chapter_purpose": "推进主线",
        "suspense_type": "信息差型",
        "emotion_evolution": "焦虑-震惊-坚定",
        "foreshadowing": "伏笔",
        "plot_twist_level": "Lv.3",
        "chapter_summary": "常规剧情推进"
    }
