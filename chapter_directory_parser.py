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
      "foreshadowing": str,      # 伏笔操作
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
    foreshadow_pattern = re.compile(r'^├─伏笔操作：\s*\(?(.+?)\)?$')  # 匹配括号内容
    twist_pattern = re.compile(r'^├─颠覆指数：\s*Lv\.(\d+)\s*$')
    summary_pattern = re.compile(r'^└─本章简述：\s*\(?(.+?)\)?$')  # 匹配括号内容

    for chunk in chunks:
        lines = chunk.strip().splitlines()
        if not lines:
            continue

        chapter_number   = None
        chapter_title    = ""
        chapter_role     = ""
        chapter_purpose  = ""
        suspense_type   = ""
        emotion_evolution = ""
        foreshadowing    = ""
        plot_twist_level = ""
        chapter_summary  = ""

        # 修改章节识别逻辑
        for line in lines:
            chapter_num, title = find_chapter_match(line)
            if chapter_num is not None:
                chapter_number = chapter_num
                chapter_title = title
                break

        if chapter_number is None:
            continue

        # 从后面的行匹配其他字段
        for line in lines[1:]:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # 修改匹配逻辑以应对新格式
            m_role = role_pattern.match(line_stripped)
            if m_role:
                chapter_role = m_role.group(1).strip()
                continue

            m_purpose = purpose_pattern.match(line_stripped)
            if m_purpose:
                chapter_purpose = m_purpose.group(1).strip()
                continue

            m_suspense = suspense_pattern.match(line_stripped)
            if m_suspense:
                # 确保悬念类型在预定义范围内
                suspense_value = m_suspense.group(1).strip()
                valid_types = ["信息差型", "道德抉择型", "倒计时型", "谜题型"]
                suspense_type = suspense_value if suspense_value in valid_types else "信息差型"
                continue

            m_emotion = emotion_pattern.match(line_stripped)
            if m_emotion:
                emotion_evolution = m_emotion.group(1).strip()
                continue

            m_foreshadow = foreshadow_pattern.match(line_stripped)
            if m_foreshadow:
                # 规范化伏笔操作格式：编号+类型+关键对象
                foreshadow_text = m_foreshadow.group(1).strip()
                if not re.match(r'^\d+.*', foreshadow_text):
                    foreshadow_text = f"1.{foreshadow_text}"
                foreshadowing = foreshadow_text
                continue

            m_twist = twist_pattern.match(line_stripped)
            if m_twist:
                # 确保颠覆指数在1-5之间
                level = int(m_twist.group(1))
                plot_twist_level = f"Lv.{min(max(level, 1), 5)}"
                continue

            m_summary = summary_pattern.match(line_stripped)
            if m_summary:
                # 限制简述字数
                summary_text = m_summary.group(1).strip()
                chapter_summary = summary_text[:75]
                continue

        results.append({
            "chapter_number": chapter_number,
            "chapter_title": chapter_title,
            "chapter_role": chapter_role,
            "chapter_purpose": chapter_purpose,
            "suspense_type": suspense_type,
            "emotion_evolution": emotion_evolution,
            "foreshadowing": foreshadowing,
            "plot_twist_level": plot_twist_level,
            "chapter_summary": chapter_summary
        })

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
        "emotion_evolution": "焦虑→震惊→坚定",
        "foreshadowing": "1.新埋设.无",
        "plot_twist_level": "Lv.1",
        "chapter_summary": "常规剧情推进"
    }
