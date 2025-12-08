# utils.py
# -*- coding: utf-8 -*-
import os
import json
import re

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
