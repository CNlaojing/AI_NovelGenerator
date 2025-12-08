# novel_generator/rewrite.py
# -*- coding: utf-8 -*-
"""
伏笔内容处理模块，用于章节草稿生成前的准备工作
"""
import os
import re
import traceback  # 添加traceback模块导入
from typing import Dict, List, Tuple

from llm_adapters import create_llm_adapter, BaseLLMAdapter
from utils import read_file
from prompt_definitions import chapter_rewrite_prompt
from novel_generator.common import invoke_with_cleaning
from novel_generator.json_utils import load_store # Replace vectorstore with json_utils


def extract_chapter_foreshadowing(blueprint_text: str, chapter_number: int) -> str:
    """
    从章节目录中提取指定章节的伏笔条目内容，优化提取逻辑
    """
    try:
        chapter_pattern = f"第{chapter_number}章.*?(?=第{chapter_number+1}章|$)"
        chapter_match = re.search(chapter_pattern, blueprint_text, re.DOTALL)
        if not chapter_match:
            # This function does not have log_func, so we print
            print(f"无法在章节目录中找到第{chapter_number}章")
            return "无"
            
        chapter_content = chapter_match.group(0)
        foreshadow_lines = []
        in_foreshadow = False
        
        for line in chapter_content.splitlines():
            line = line.strip()
            if '├─伏笔条目：' in line:
                in_foreshadow = True
                continue
            
            if in_foreshadow:
                if line.startswith('├─') or line.startswith('└─'):
                    if '伏笔' not in line:
                        break
                elif line.startswith('│'):
                    line = line.lstrip('│├└─ ')
                    if line and ('-' in line):
                        foreshadow_lines.append(line)

        return '\n'.join(foreshadow_lines) if foreshadow_lines else "无"
            
    except Exception as e:
        print(f"提取章节伏笔信息时出错: {str(e)}")
        return "无"


def parse_foreshadowing(foreshadowing: str) -> List[Dict]:
    """
    解析伏笔条目内容，提取伏笔ID、类型、标题和状态
    """
    foreshadows = []
    
    for line in foreshadowing.split('\n'):
        if '-' in line:
            # 匹配伏笔ID和类型
            id_type_match = re.search(r'([A-Z]F\d{3})\(([^)]+)\)', line)
            if not id_type_match:
                continue
                
            fid = id_type_match.group(1)
            f_type = id_type_match.group(2)
            
            # 分割伏笔内容
            parts = line.split('-')
            if len(parts) < 3:
                continue
                
            title = parts[1].strip()
            status = parts[2].strip()
            
            foreshadows.append({
                'id': fid,
                'type': f_type,
                'title': title,
                'status': status
            })
    
    return foreshadows


def process_foreshadowing_context(
    filepath: str,
    foreshadowing: str,
    log_func=None
) -> str:
    """
    处理伏笔内容，从伏笔状态JSON文件中检索历史，生成用于章节草稿的伏笔上下文。
    """
    def _log(message):
        if log_func:
            log_func(message)
        else:
            print(message)

    try:
        if not foreshadowing or foreshadowing.strip() == "无":
            _log("  -> 当前章节无伏笔条目，跳过。")
            return "（无相关伏笔记录）"

        # 1. 解析当前章节的伏笔信息
        _log("  -> 正在解析当前章节伏笔信息...")
        current_chapter_foreshadows = parse_foreshadowing(foreshadowing)
        if not current_chapter_foreshadows:
            _log("  -> 未找到有效伏笔条目。")
            return "（未找到有效伏笔条目）"

        # 2. 加载伏笔状态JSON文件
        _log("  -> 正在加载 `伏笔状态.md`...")
        foreshadowing_store = load_store(filepath, "foreshadowing_collection")
        if not foreshadowing_store:
            _log("  -> `伏笔状态.md` 为空或不存在。")
            return "（伏笔状态文件为空或不存在）"

        # 3. 检索并格式化历史内容
        historical_results = []
        for fs in current_chapter_foreshadows:
            fs_id = fs['id']
            status = fs['status']
            
            # 只处理非“埋设”状态的伏笔，因为它们应该有历史记录
            if status != '埋设':
                if fs_id in foreshadowing_store:
                    fs_data = foreshadowing_store[fs_id]
                    history_content = fs_data.get("内容", "无历史内容记录。")
                    
                    # 构建用于提示词的上下文条目
                    formatted_entry = (
                        f"伏笔ID: {fs_id}\n"
                        f"  - 标题: {fs.get('title', '未知标题')}\n"
                        f"  - 本章状态: {status}\n"
                        f"  - 历史内容总结: {history_content}"
                    )
                    historical_results.append(formatted_entry)
                    _log(f"    ✅ 找到伏笔 {fs_id} 的历史: \"{history_content[:50]}...\"")
                else:
                    _log(f"    ⚠️ 未在 `伏笔状态.md` 中找到伏笔 {fs_id} 的历史记录。")
            else:
                _log(f"    ℹ️ 跳过新埋设的伏笔 {fs_id}。")

        # 4. 组合最终的上下文
        if not historical_results:
            _log("  -> 未找到任何需要引用的历史伏笔记录。")
            return "（无相关历史伏笔记录）"
            
        final_context = "--- 伏笔历史参考 ---\n" + "\n\n".join(historical_results)
        _log("  -> 成功构建伏笔历史上下文。")
        return final_context

    except Exception as e:
        _log(f"  -> ❌ 处理伏笔内容时出错: {str(e)}")
        _log(traceback.format_exc())
        return f"（处理伏笔内容出错: {str(e)}）"


def get_foreshadow_type(fid: str) -> str:
    """根据伏笔ID获取类型名称"""
    type_map = {
        'MF': '主线伏笔',
        'SF': '支线伏笔',
        'AF': '暗线伏笔',
        'CF': '人物伏笔',
        'YF': '一般伏笔'
    }
    prefix = fid[:2]
    return type_map.get(prefix, '未知类型')


def rewrite_chapter(
    current_text: str,
    filepath: str,
    novel_number: int,
    llm_adapter: BaseLLMAdapter,
    log_func=None,
    log_stream=True,
    check_interrupted=None
):
    """
    改写章节内容。这是一个生成器函数，会 yield LLM 返回的每个块。
    
    Args:
        current_text: 原始文本/提示词
        filepath: 文件保存路径
        novel_number: 章节编号 
        llm_adapter: 一个配置好的LLM适配器实例
        log_func: 日志记录函数
    Yields:
        改写后文本的块
    """
    try:
        if not llm_adapter:
            raise ValueError("rewrite_chapter 需要一个有效的 llm_adapter 实例。")

        # current_text 已经是完整的提示词，直接使用
        # if log_func:
        #     log_func("发送到 LLM 的提示词 (改写章节):\n" + current_text)
        
        from novel_generator.common import invoke_stream_with_cleaning
        # 直接使用传入的适配器进行流式调用
        for chunk in invoke_stream_with_cleaning(llm_adapter, current_text, log_func=log_func, log_stream=log_stream, check_interrupted=check_interrupted):
            if chunk:
                yield chunk
        
    except Exception as e:
        error_msg = f"改写章节时出错: {str(e)}"
        if log_func:
            log_func(error_msg)
            log_func(traceback.format_exc())
        # 重新抛出异常，以便上层的 execute_with_polling 能够捕获并处理
        raise
