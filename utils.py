# utils.py
# -*- coding: utf-8 -*-
import os
import json
import re
from datetime import datetime

def read_file(filepath: str) -> str:
    """读取文件内容"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return ""

def append_text_to_file(text_to_append: str, file_path: str):
    """在文件末尾追加文本(带换行)。若文本非空且无换行，则自动加换行。"""
    if text_to_append and not text_to_append.startswith('\n'):
        text_to_append = '\n' + text_to_append

    try:
        with open(file_path, 'a', encoding='utf-8') as file:
            file.write(text_to_append)
    except IOError as e:
        print(f"[append_text_to_file] 发生错误：{e}")

def clear_file_content(filepath: str) -> None:
    """清空文件内容"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("")
    except Exception as e:
        raise Exception(f"清空文件失败: {str(e)}")

def save_string_to_txt(content: str, filepath: str) -> None:
    """保存字符串到文件"""
    try:
        # 获取文件所在的目录
        dir_path = os.path.dirname(filepath)
        # 如果目录不存在，则创建它
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
            
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        raise Exception(f"保存文件失败: {str(e)}")

def save_data_to_json(data: dict, file_path: str) -> bool:
    """将数据保存到 JSON 文件。"""
    try:
        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"[save_data_to_json] 保存数据到JSON文件时出错: {e}")
        return False

def ensure_unix_lf(text: str) -> str:
    """确保文本使用Unix风格的换行符"""
    return text.replace('\r\n', '\n').replace('\r', '\n')

def strip_markdown_fences(text: str) -> str:
    """移除AI输出中常见的Markdown代码块围栏。"""
    if not text:
        return ""
    return re.sub(r'^\s*```[a-zA-Z0-9_-]*\s*$|^\s*```\s*$', '', text, flags=re.MULTILINE)

def normalize_generated_text(text: str) -> str:
    """
    对AI生成文本做基础、安全的版式修复。
    只处理换行和代码块围栏等低风险问题，不做语义猜测。
    """
    if text is None:
        return ""

    normalized = ensure_unix_lf(str(text)).replace('\ufeff', '')
    normalized = strip_markdown_fences(normalized)
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)
    return normalized.strip()

def save_failed_generation_sample(project_path: str, sample_name: str, content: str, extension: str = "txt") -> str:
    """将校验失败的AI原始输出保存到调试目录，便于排查。"""
    debug_dir = os.path.join(project_path, "debug", "failed_generations")
    os.makedirs(debug_dir, exist_ok=True)

    safe_extension = extension.lstrip('.') or "txt"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(debug_dir, f"{sample_name}_失败样本_{timestamp}.{safe_extension}")
    save_string_to_txt(content or "", file_path)
    return file_path

def normalize_chapter_directory_text(text: str) -> str:
    """对章节目录文本做低风险版式规范化。"""
    normalized = normalize_generated_text(text)
    if not normalized:
        return ""

    # 避免章节标题被压在同一行，且排除“第X章前必须回收”这种正文描述。
    normalized = re.sub(
        r'(?<!\n)(第\s*\d+\s*章)(?=\s*(?!前)(?:\[|《|【|「|[A-Za-z0-9\u4e00-\u9fff]))',
        r'\n\1',
        normalized
    )

    top_level_fields = [
        "本章定位", "核心作用", "叙事视角", "场景设定", "出场角色与动机",
        "情节脉络（起-承-转-合）", "悬念类型", "情绪演变", "伏笔条目", "颠覆指数", "本章简述"
    ]
    top_level_pattern = "|".join(re.escape(field) for field in top_level_fields)
    normalized = re.sub(
        rf'(?<!\n)([├└]─(?:{top_level_pattern})：)',
        r'\n\1',
        normalized
    )

    normalized = re.sub(r'(?<!\n)(│[├└]─)', r'\n\1', normalized)
    normalized = re.sub(r'\n{3,}', '\n\n', normalized).strip()
    return normalized

def validate_chapter_directory_text(text: str, start_chapter: int = None, end_chapter: int = None) -> tuple:
    """校验章节目录是否满足后续解析的基本要求。"""
    normalized = normalize_chapter_directory_text(text)
    if not normalized:
        return False, "章节目录内容为空"

    if re.search(
        r'[^\n](第\s*\d+\s*章)(?=\s*(?!前)(?:\[|《|【|「|[A-Za-z0-9\u4e00-\u9fff]))',
        normalized
    ):
        return False, "检测到未独占一行的章节标题"

    chapter_matches = list(re.finditer(r'^第\s*(\d+)\s*章\b.*$', normalized, re.MULTILINE))
    if not chapter_matches:
        return False, "未找到任何章节标题"

    chapter_numbers = [int(match.group(1)) for match in chapter_matches]
    if start_chapter is not None and end_chapter is not None:
        expected_numbers = list(range(start_chapter, end_chapter + 1))
        if chapter_numbers != expected_numbers:
            return False, f"章节号不连续或范围不匹配，实际为 {chapter_numbers}，预期为 {expected_numbers}"

    required_fields = ["├─本章定位：", "├─核心作用：", "├─伏笔条目：", "├─颠覆指数：", "└─本章简述："]
    for index, match in enumerate(chapter_matches):
        chunk_start = match.start()
        chunk_end = chapter_matches[index + 1].start() if index + 1 < len(chapter_matches) else len(normalized)
        chapter_chunk = normalized[chunk_start:chunk_end]
        missing_fields = [field for field in required_fields if field not in chapter_chunk]
        if missing_fields:
            return False, f"第{chapter_numbers[index]}章缺少关键字段: {', '.join(missing_fields)}"

    return True, "章节目录格式校验通过"

def normalize_volume_outline_text(text: str) -> str:
    """对分卷大纲文本做低风险版式规范化。"""
    normalized = normalize_generated_text(text)
    if not normalized:
        return ""

    normalized = re.sub(r'(?<!\n)([一二三四五六七八九十]+、)', r'\n\1', normalized)
    normalized = re.sub(r'(?<!\n)(\*\s+)', r'\n\1', normalized)
    normalized = re.sub(r'章节范围\s*[:：]\s*第\s*(\d+)\s*章\s*至\s*第\s*(\d+)\s*章', r'章节范围：第\1章-第\2章', normalized)
    normalized = re.sub(r'章节范围\s*[:：]\s*第\s*(\d+)\s*章\s*[—\-~]+\s*第\s*(\d+)\s*章', r'章节范围：第\1章-第\2章', normalized)
    normalized = re.sub(r'\n{3,}', '\n\n', normalized).strip()
    return normalized

def extract_volume_outline_range(text: str) -> tuple:
    """从分卷大纲中提取章节范围。"""
    normalized = normalize_volume_outline_text(text)
    patterns = [
        r'章节范围\s*[:：]\s*第\s*(\d+)\s*章\s*[-—~至]+\s*第\s*(\d+)\s*章',
        r'章节范围\s*[:：]\s*(\d+)\s*[-—~至]+\s*(\d+)',
        r'章节分布\s*[:：]\s*第\s*(\d+)\s*章\s*[-—~至]+\s*第\s*(\d+)\s*章',
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.DOTALL)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, None

def validate_volume_outline_text(text: str, expected_volume_number: int = None) -> tuple:
    """校验分卷大纲是否包含关键结构。"""
    normalized = normalize_volume_outline_text(text)
    if not normalized:
        return False, "分卷大纲内容为空"

    required_sections = ["一、分卷使命", "二、世界观与冲突", "三、情节线与主角进程", "四、核心角色发展", "五、叙事与章节规划"]
    missing_sections = [section for section in required_sections if section not in normalized]
    if missing_sections:
        return False, f"分卷大纲缺少关键模块: {', '.join(missing_sections)}"

    start_chap, end_chap = extract_volume_outline_range(normalized)
    if start_chap is None or end_chap is None:
        return False, "未找到可解析的章节范围"
    if start_chap > end_chap:
        return False, f"章节范围无效: 第{start_chap}章-第{end_chap}章"

    if expected_volume_number is not None:
        heading_patterns = [
            rf'===\s*第\s*{expected_volume_number}\s*卷',
            rf'#===\s*第\s*{expected_volume_number}\s*卷',
        ]
        if not any(re.search(pattern, normalized) for pattern in heading_patterns):
            return False, f"未找到第{expected_volume_number}卷标题"

    return True, "分卷大纲格式校验通过"

def reformat_novel_text(
    text: str,
    indent: bool = True,
    lines_between_paragraphs: int = 0,
    remove_extra_spaces: bool = True
) -> str:
    """
    根据设定的规则重新排版小说文本。

    Args:
        text (str): 原始小说文本。
        indent (bool): 是否在段首添加两个全角空格。
        lines_between_paragraphs (int): 段落之间的空行数量。
        remove_extra_spaces (bool): 是否移除段落内多余的空格。

    Returns:
        str: 排版后的小说文本。
    """
    if not text or not text.strip():
        return ""

    # 1. 预处理：确保换行符统一，并移除首尾空白
    processed_text = ensure_unix_lf(text).strip()

    # 3. 分割成段落并处理
    paragraphs = processed_text.split('\n')
    formatted_paragraphs = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue

        # 4. 移除多余空格 (保留中文引号旁的空格)
        if remove_extra_spaces:
            # 移除普通多余空格，但保留引号和文字之间的单个空格
            p = re.sub(r'(?<![“])\s+(?![”])', '', p).strip()

        # 5. 段首缩进
        if indent:
            # 移除原有的判断条件，对所有段落都应用缩进
            p = '　　' + p

        formatted_paragraphs.append(p)

    # 6. 组合最终文本
    paragraph_separator = '\n' * (lines_between_paragraphs + 1)
    return paragraph_separator.join(formatted_paragraphs)
