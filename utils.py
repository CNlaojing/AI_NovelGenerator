# utils.py
# -*- coding: utf-8 -*-
import os
import json

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
