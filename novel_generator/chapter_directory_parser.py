# chapter_blueprint_parser.py
# -*- coding: utf-8 -*-
import re
import logging

def parse_chapter_blueprint(blueprint_text: str):
    """
    解析整份章节蓝图文本，返回一个列表，每个元素是一个 dict：
    {
      "chapter_number": int,
      "chapter_title": str,
      "chapter_role": str,       # 本章定位
      "chapter_purpose": str,    # 核心作用
      "suspense_type": str,     # 悬念类型
      "emotion_evolution": str,  # 情绪演变
      "foreshadowing": str,      # 伏笔条目
      "plot_twist_level": str,   # 颠覆指数
      "chapter_summary": str     # 本章简述
    }
    """

    # 先按空行进行分块，以免多章之间混淆
    chunks = re.split(r'\n\s*\n', blueprint_text.strip())
    results = []

    # 更新章节标题的匹配模式，支持多种格式
    chapter_patterns = [
        r'#+ 第\s*(\d+)\s*章\s*[《\[](.*?)[》\]]',  # 匹配 ##### 第1章 《标题》
        r'第\s*(\d+)\s*章\s*[《\[](.*?)[》\]]',     # 匹配 第1章 《标题》
        r'第\s*(\d+)\s*章\s*[:：-]\s*[《\[](.*?)[》\]]',  # 匹配 第1章: 《标题》
        r'第\s*(\d+)\s*章\s*[:：-]?\s*(.*?)$'       # 匹配其他格式
    ]
    
    # 从一系列模式中尝试匹配
    def find_chapter_match(line):
        for pattern in chapter_patterns:
            match = re.match(pattern, line.strip())
            if match:
                return int(match.group(1)), match.group(2).strip()
        return None, None

    # 更新正则表达式以适应新格式
    role_pattern = re.compile(r'^├─本章定位：\s*(.+)$')  
    purpose_pattern = re.compile(r'^├─核心作用：\s*\(?(.+?)\)?$')  # 匹配括号内容
    suspense_pattern = re.compile(r'^├─悬念类型：\s*(.+)$')
    emotion_pattern = re.compile(r'^├─情绪演变：\s*(.+)$')
    foreshadow_pattern = re.compile(r'^├─伏笔条目：')  # Modified: Only match the start, ignore content on this line
    twist_pattern = re.compile(r'^├─颠覆指数：\s*Lv\.(\d+)\s*$')
    summary_pattern = re.compile(r'^└─本章简述：\s*(.+)$')
    foreshadow_item_pattern = re.compile(r'^│[└├]─(.+)$') # Pattern for individual foreshadowing lines

    for chunk in chunks:
        lines = chunk.strip().splitlines()
        if not lines:
            continue

        chapter_data = {
            "chapter_number": None,
            "chapter_title": "",
            "chapter_role": "",
            "chapter_purpose": "",
            "suspense_type": "",
            "emotion_evolution": "",
            "foreshadowing": [], # Changed to list to hold multiple items
            "plot_twist_level": "",
            "chapter_summary": ""
        }
        
        in_foreshadow_section = False # Flag to track if we are parsing foreshadowing lines

        # Find chapter number and title first
        for i, line in enumerate(lines):
            chapter_num, title = find_chapter_match(line)
            if chapter_num is not None:
                chapter_data["chapter_number"] = chapter_num
                chapter_data["chapter_title"] = title
                start_index = i + 1 # Start parsing details from the next line
                break
        else: # If no chapter line found in chunk
            continue 
            
        # Parse details from subsequent lines
        for line in lines[start_index:]:
            line_stripped = line.strip()
            if not line_stripped:
                in_foreshadow_section = False # Blank line ends foreshadow section
                continue

            # Check if it's the start of the foreshadowing section
            # Check if it's the start of the foreshadowing section
            # Use re.search as the line might have trailing spaces
            if foreshadow_pattern.search(line_stripped):
                in_foreshadow_section = True
                continue # Move to the next line to look for items

            # If in foreshadowing section, try to match item lines
            if in_foreshadow_section:
                m_foreshadow_item = foreshadow_item_pattern.match(line_stripped)
                if m_foreshadow_item:
                    chapter_data["foreshadowing"].append(m_foreshadow_item.group(1).strip())
                    continue # Continue checking for more foreshadowing items
                else:
                    # If a line doesn't match the item pattern, assume foreshadowing section ended
                    in_foreshadow_section = False
                    # Fall through to check other patterns for this line

            # Check other patterns only if not continuing foreshadowing
            m_role = role_pattern.match(line_stripped)
            if m_role:
                chapter_data["chapter_role"] = m_role.group(1).strip()
                continue

            m_purpose = purpose_pattern.match(line_stripped)
            if m_purpose:
                chapter_data["chapter_purpose"] = m_purpose.group(1).strip()
                continue

            m_suspense = suspense_pattern.match(line_stripped)
            if m_suspense:
                suspense_value = m_suspense.group(1).strip()
                valid_types = ["信息差型", "道德抉择型", "倒计时型", "谜题型"]
                chapter_data["suspense_type"] = suspense_value if suspense_value in valid_types else "信息差型"
                continue

            m_emotion = emotion_pattern.match(line_stripped)
            if m_emotion:
                chapter_data["emotion_evolution"] = m_emotion.group(1).strip()
                continue

            m_twist = twist_pattern.match(line_stripped)
            if m_twist:
                level = int(m_twist.group(1))
                chapter_data["plot_twist_level"] = f"Lv.{min(max(level, 1), 5)}"
                continue

            m_summary = summary_pattern.match(line_stripped)
            if m_summary:
                summary_text = m_summary.group(1).strip()
                chapter_data["chapter_summary"] = summary_text[:150] # Increased limit slightly
                continue
                
        # Join foreshadowing list into a single string for now, or keep as list if needed downstream
        chapter_data["foreshadowing"] = "\n".join(chapter_data["foreshadowing"])
        results.append(chapter_data)

    # 按照 chapter_number 排序后返回
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
    
    # 返回默认值
    return {
        "chapter_number": target_chapter_number,
        "chapter_title": f"第{target_chapter_number}章",
        "chapter_role": "常规章节",
        "chapter_purpose": "推进主线",
        "suspense_type": "信息差型",
        "emotion_evolution": "焦虑-震惊-坚定",
        "foreshadowing": "伏笔",
        "plot_twist_level": "Lv.3",
        "chapter_summary": "常规剧情推进"
    }
