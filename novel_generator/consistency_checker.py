# consistency_checker.py
# -*- coding: utf-8 -*-
import os
import logging
import re
import datetime
import traceback
import threading
from tkinter import messagebox
from llm_adapters import create_llm_adapter
from novel_generator.common import invoke_with_cleaning
from prompt_definitions import Chapter_Review_prompt
from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.volume import extract_volume_outline
from utils import read_file, save_string_to_txt, clear_file_content
from embedding_adapters import create_embedding_adapter
from novel_generator.vectorstore_utils import load_vector_store

def do_consistency_check(self, *args, **kwargs):
    """
    Wrapper function for consistency checking
    """
    # 获取所有必要的参数
    filepath = self.filepath_var.get().strip()
    novel_number = self.safe_get_int(self.chapter_num_var, 1)
    Review_text = self.chapter_result.get("0.0", "end").strip()
    
    # 从文件中读取全局摘要，而不是从UI控件中获取
    global_summary = ""
    global_summary_file = os.path.join(filepath, "前情摘要.txt")
    if os.path.exists(global_summary_file):
        try:
            global_summary = read_file(global_summary_file)
        except Exception as e:
            self.safe_log(f"读取前情摘要文件时出错: {str(e)}")
    
    # 从文件中读取角色状态，而不是从UI控件中获取
    character_state = ""
    character_state_file = os.path.join(filepath, "待用角色.txt")
    if os.path.exists(character_state_file):
        try:
            character_state = read_file(character_state_file)
        except Exception as e:
            self.safe_log(f"读取角色状态文件时出错: {str(e)}")

    # 获取小说设定中的章节字数和类型
    word_number = 3000  # 默认值
    genre = "奇幻"  # 默认值
    novel_setting_file = os.path.join(filepath, "小说设定.txt")
    if os.path.exists(novel_setting_file):
        try:
            novel_setting = read_file(novel_setting_file)
            word_number_pattern = re.compile(r'每章(\d+)字', re.MULTILINE)
            word_number_match = word_number_pattern.search(novel_setting)
            if word_number_match:
                word_number = int(word_number_match.group(1))
            
            # 提取小说类型，只获取类型而不包含篇幅信息
            genre_match = re.search(r"类型：([^,，]+)", novel_setting)
            if genre_match:
                genre = genre_match.group(1).strip()
        except Exception as e:
            self.safe_log(f"读取小说设定文件时出错: {str(e)}")

    api_key = self.api_key_var.get().strip()
    base_url = self.base_url_var.get().strip()
    model_name = self.model_name_var.get().strip()
    temperature = self.temperature_var.get()
    interface_format = self.interface_format_var.get().strip()
    max_tokens = self.max_tokens_var.get()
    timeout = self.safe_get_int(self.timeout_var, 600)

    # 清空并保存审校结果到指定文件
    output_file_path = os.path.join(filepath, "一致性审校.txt")
    clear_file_content(output_file_path)
    
    # 获取章节信息
    directory_file = os.path.join(filepath, "章节目录.txt")
    chapter_title = f"第{novel_number}章"
    chapter_info = {
        'chapter_role': '常规章节',
        'chapter_purpose': '推进主线',
        'suspense_type': '信息差型',
        'emotion_evolution': '焦虑-震惊-坚定',
        'foreshadow': '',  # 先初始化为空
        'plot_twist_level': 'Lv.1',
        'chapter_summary': '章节简述'
    }
    
    if os.path.exists(directory_file):
        try:
            content = read_file(directory_file)
            # 使用正则匹配准确提取章节标题
            title_pattern = f"第{novel_number}章\\s+([^\\n]+)"
            title_match = re.search(title_pattern, content)
            if title_match:
                chapter_title = f"第{novel_number}章 {title_match.group(1)}"
            
            # 获取其他章节信息
            chapter_info = get_chapter_info_from_blueprint(content, novel_number) or chapter_info

            # 从原始目录文本中提取伏笔信息
            pattern = f"第{novel_number}章.*?伏笔条目：.*?(?=\n[^\\n│])"
            match = re.search(pattern, content, re.DOTALL)
            if match:
                raw_text = match.group(0)
                foreshadow_pattern = r"├─伏笔条目：\n((?:│[└├]─.*\n?)*)"
                foreshadow_match = re.search(foreshadow_pattern, raw_text)
                if foreshadow_match:
                    operations = foreshadow_match.group(1).strip()
                    formatted_lines = []
                    for line in operations.split('\n'):
                        line = line.strip()
                        if line and not line.startswith("伏笔条目"):
                            line = line.replace("│├─", "").replace("│└─", "").strip()
                            if line:
                                formatted_lines.append(line)
                    if formatted_lines:
                        chapter_info['foreshadow'] = "\n".join(formatted_lines)
        except Exception as e:
            self.safe_log(f"解析章节信息时出错: {str(e)}")
            self.safe_log(traceback.format_exc())

    # 获取分卷大纲
    volume_outline = ""
    try:
        if os.path.exists(os.path.join(filepath, "分卷大纲.txt")):
            with open(os.path.join(filepath, "分卷大纲.txt"), 'r', encoding='utf-8') as f:
                volume_content = f.read()
                for match in re.finditer(r'第(\d+)卷.*?第(\d+)章.*?第(\d+)章', volume_content):
                    if int(match.group(2)) <= novel_number <= int(match.group(3)):
                        volume_outline = extract_volume_outline(volume_content, int(match.group(1)))
                        break
    except Exception as e:
        self.safe_log(f"获取分卷大纲时出错: {str(e)}")
        volume_outline = ""

    # 提取最近的剧情要点
    plot_arcs = extract_recent_plot_arcs(filepath, 2000, novel_number)
    
    # 从伏笔向量库中提取伏笔记录
    knowledge_context = ""
    try:
        # 提取本章伏笔编号
        foreshadowing_ids = []
        if chapter_info.get('foreshadow'):
            # 从伏笔条目中提取伏笔编号
            for line in chapter_info['foreshadow'].split('\n'):
                # 匹配伏笔编号（如MF001, SF001等）
                fb_id_match = re.search(r'([A-Z]F\d+)', line)
                if fb_id_match:
                    foreshadowing_ids.append(fb_id_match.group(1))
        
        if foreshadowing_ids:
            self.safe_log(f"本章伏笔编号: {foreshadowing_ids}")
            
            # 加载伏笔向量库
            embedding_adapter = create_embedding_adapter(
                interface_format="openai",
                api_key=api_key,
                base_url=base_url,
                model_name="text-embedding-ada-002"
            )
            
            vectorstore = load_vector_store(embedding_adapter, filepath, collection_name="foreshadowing_collection")
            
            if vectorstore:
                self.safe_log("成功加载伏笔向量库，开始检索伏笔历史记录")
                
                for fb_id in foreshadowing_ids:
                    # 使用精确的元数据查询
                    results = vectorstore.get(
                        where={"id": fb_id},
                        include=["metadatas", "documents"]
                    )
                    
                    if results and results.get('ids'):
                        # 按章节号排序，获取最新的记录
                        entries = list(zip(results['ids'], results['metadatas'], results['documents']))
                        entries.sort(key=lambda x: x[1].get('chapter', 0), reverse=True)
                        latest_entry = entries[0]
                        
                        metadata = latest_entry[1]
                        content = latest_entry[2]
                        
                        # 格式化伏笔记录
                        entry = f"伏笔编号: {metadata.get('id', '未知')}\n"
                        entry += f"伏笔内容: {content}\n"
                        chapter_metadata_value = metadata.get('chapter', 0)
                        if str(chapter_metadata_value) != '0':
                            entry += f"伏笔最后章节：{chapter_metadata_value}\n\n\n"
                        
                        knowledge_context += entry
                        self.safe_log(f"成功检索伏笔 {fb_id} 的历史记录")
                
                if not knowledge_context:
                    knowledge_context = "(未找到相关伏笔历史记录)\n"
            else:
                knowledge_context = "(向量库未初始化)\n"
                self.safe_log("警告：向量库未初始化，无法检索伏笔历史记录")
        else:
            knowledge_context = "(未找到伏笔编号)\n"
            self.safe_log("未找到伏笔编号，无法检索伏笔历史记录")
    except Exception as e:
        self.safe_log(f"提取伏笔记录时出错: {str(e)}")
        knowledge_context = f"(检索伏笔历史记录时出错: {str(e)})\n"
    
    # 获取用户指导内容
    user_guidance = ""
    try:
        # 从主界面获取内容指导编辑框的内容
        if hasattr(self, 'user_guide_text'):
            user_guidance = self.user_guide_text.get("0.0", "end").strip()
        elif hasattr(self.master, 'user_guide_text'):
            user_guidance = self.master.user_guide_text.get("0.0", "end").strip()
    except Exception as e:
        self.safe_log(f"获取用户指导内容时出错: {str(e)}")
    
    # 构建提示词
    prompt = Chapter_Review_prompt.format(
        novel_number=novel_number,
        chapter_title=chapter_title,  # 使用更准确提取的章节标题
        word_number=word_number,  # 添加章节字数
        genre=genre,  # 添加小说类型
        chapter_role=chapter_info['chapter_role'],
        chapter_purpose=chapter_info['chapter_purpose'],
        suspense_type=chapter_info['suspense_type'],
        emotion_evolution=chapter_info['emotion_evolution'],
        foreshadowing=chapter_info.get('foreshadow', '无伏笔'),
        plot_twist_level=chapter_info['plot_twist_level'],
        chapter_summary=chapter_info['chapter_summary'][:75],
        global_summary=global_summary,
        character_state=character_state,
        volume_outline=volume_outline,
        Review_text=Review_text,  # 使用传入的编辑框内容
        plot_points=plot_arcs,  # 添加处理后的剧情要点，使用正确的参数名
        knowledge_context=knowledge_context,  # 添加伏笔记录
        user_guidance=user_guidance  # 添加用户指导
    )
    
    # 显示提示词弹窗
    import customtkinter as ctk
    import tkinter as tk
    
    prompt_dialog = ctk.CTkToplevel(self.master)
    prompt_dialog.title("一致性审校提示词")
    prompt_dialog.geometry("900x700")
    prompt_dialog.transient(self.master)
    prompt_dialog.grab_set()
    prompt_dialog.attributes('-topmost', True)  # 设置为置顶窗口
    
    # 禁止最小化窗口
    prompt_dialog.protocol("WM_ICONIFY_WINDOW", lambda: prompt_dialog.deiconify())
    # 初始化用户确认标志
    prompt_dialog.user_confirmed = False
    
    # 创建提示词编辑框
    prompt_text = ctk.CTkTextbox(prompt_dialog, wrap="word", font=("Microsoft YaHei", 12))
    prompt_text.pack(fill="both", expand=True, padx=10, pady=(10, 5))
    prompt_text.insert("0.0", prompt)
    
    # 创建字数统计标签
    word_count_var = tk.StringVar(value=f"当前字数: {len(prompt)}")
    word_count_label = ctk.CTkLabel(prompt_dialog, textvariable=word_count_var, font=("Microsoft YaHei", 12))
    word_count_label.pack(pady=(0, 5))
    
    # 更新字数统计的函数
    def update_word_count(event=None):
        current_text = prompt_text.get("0.0", "end")
        word_count_var.set(f"当前字数: {len(current_text)}")
    
    # 绑定文本变化事件
    prompt_text.bind("<KeyRelease>", update_word_count)
    
    # 确认按钮点击处理
    def handle_confirm_click():
        nonlocal prompt
        # 获取编辑后的提示词
        prompt = prompt_text.get("0.0", "end").strip()
        # 设置确认标志
        prompt_dialog.user_confirmed = True
        prompt_dialog.destroy()
    
    # 取消按钮点击处理
    def handle_cancel_click():
        # 设置取消标志
        prompt_dialog.user_confirmed = False
        prompt_dialog.destroy()
        self.safe_log("❌ 一致性审校已取消")
        return None
    
    # 底部按钮区域
    btn_frame = ctk.CTkFrame(prompt_dialog)
    btn_frame.pack(pady=10)
    
    ctk.CTkButton(
        btn_frame, 
        text="确认", 
        command=handle_confirm_click,
        width=100,
        font=("Microsoft YaHei", 12)
    ).pack(side="left", padx=10)
    
    ctk.CTkButton(
        btn_frame, 
        text="取消", 
        command=handle_cancel_click,
        width=100,
        font=("Microsoft YaHei", 12)
    ).pack(side="left", padx=10)
    
    # 定义使用提示词处理的函数
    def process_with_prompt():
        # 创建一个标志，用于标记是否已经处理完成
        processing_done = threading.Event()
        result_container = [None]  # 使用列表存储结果，以便在回调中修改
        
        def process_task():
            try:
                # 调用一致性检查函数
                result = check_consistency(
                    character_state=character_state,
                    global_summary=global_summary,
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    temperature=temperature,
                    interface_format=interface_format,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    filepath=filepath,
                    novel_number=novel_number,
                    Review_text=Review_text,
                    word_number=word_number,
                    custom_prompt=prompt  # 传递自定义提示词
                )
                
                # 将结果保存到文件
                save_string_to_txt(result, output_file_path)
                result_container[0] = result
                
                # 在主线程中更新UI
                self.master.after(0, lambda: self.safe_log("✅ 一致性审校完成，结果已保存到 一致性审校.txt"))
            except Exception as e:
                self.master.after(0, lambda: self.safe_log(f"❌ 一致性审校出错: {str(e)}"))
            finally:
                processing_done.set()
        
        # 在新线程中执行任务
        threading.Thread(target=process_task, daemon=True).start()
        
        # 返回结果
        return result_container[0]
    
    # 定义使用提示词处理的函数
    def process_with_prompt():
        # 创建一个标志，用于标记是否已经处理完成
        processing_done = threading.Event()
        result_container = [None]  # 使用列表存储结果，以便在回调中修改
        
        def process_task():
            try:
                # 调用一致性检查函数
                result = check_consistency(
                    character_state=character_state,
                    global_summary=global_summary,
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    temperature=temperature,
                    interface_format=interface_format,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    filepath=filepath,
                    novel_number=novel_number,
                    Review_text=Review_text,
                    word_number=word_number,
                    custom_prompt=prompt  # 传递自定义提示词
                )
                
                # 将结果保存到文件
                save_string_to_txt(result, output_file_path)
                result_container[0] = result
                
                # 在主线程中更新UI
                self.master.after(0, lambda: self.safe_log("✅ 一致性审校完成，结果已保存到 一致性审校.txt"))
            except Exception as e:
                self.master.after(0, lambda: self.safe_log(f"❌ 一致性审校出错: {str(e)}"))
            finally:
                processing_done.set()
        
        # 在新线程中执行任务
        threading.Thread(target=process_task, daemon=True).start()
        
        # 返回结果
        return result_container[0]
    
    # 等待用户操作
    prompt_dialog.wait_window()
    
    # 如果用户点击了确认，则会执行process_with_prompt
    # 如果用户点击了取消，则不会执行
    if hasattr(prompt_dialog, 'user_confirmed') and prompt_dialog.user_confirmed:
        return process_with_prompt()
    else:
        return None
    return None

def extract_recent_plot_arcs(filepath: str, max_chars: int = 2000, chapter_num: int = None) -> str:
    """提取最近的剧情要点
    
    Args:
        filepath: 项目路径
        max_chars: 最大字符数限制
        chapter_num: 当前章节号，如果提供，将尝试提取前一章的剧情要点
        
    Returns:
        提取的剧情要点字符串
    """
    try:
        plot_arcs_file = os.path.join(filepath, "剧情要点.txt")
        if not os.path.exists(plot_arcs_file):
            return ""
            
        with open(plot_arcs_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        if not content:
            return ""
        
        # 如果提供了章节号，尝试提取前一章的剧情要点
        if chapter_num is not None and chapter_num > 1:
            prev_chapter = chapter_num - 1
            # 尝试多种模式匹配前一章的剧情要点（包含标题行）
            title_patterns = [
                rf"(第{prev_chapter}章.*?剧情要点：[\s\S]*?)(?=第{chapter_num}章|===|$)",  # 标准格式（包含标题）
                rf"(第{prev_chapter}章.*?剧情要点[：:][\s\S]*?)(?=第{chapter_num}章|===|$)",  # 兼容冒号格式（包含标题）
                rf"(第{prev_chapter}章[\s\S]*?)(?=第{chapter_num}章|===|$)"  # 宽松匹配（包含标题）
            ]
            
            # 先尝试包含标题的匹配
            for pattern in title_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match and match.group(1).strip():
                    return match.group(1).strip()
                    
            # 如果包含标题的匹配失败，尝试不包含标题的匹配（向后兼容）
            content_patterns = [
                rf"第{prev_chapter}章.*?剧情要点：([\s\S]*?)(?=第{chapter_num}章|===|$)",  # 标准格式（不包含标题）
                rf"第{prev_chapter}章.*?剧情要点[：:]([\s\S]*?)(?=第{chapter_num}章|===|$)",  # 兼容冒号格式（不包含标题）
            ]
            
            for pattern in content_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match and match.group(1).strip():
                    # 提取标题行并添加到内容前面
                    title_match = re.search(rf"(第{prev_chapter}章.*?剧情要点[：:])", content)
                    if title_match:
                        return f"{title_match.group(1)}\n{match.group(1).strip()}"
                    return match.group(1).strip()
            
            # 如果上述模式都没匹配到，尝试匹配整个章节块
            chapter_block_pattern = rf"第{prev_chapter}章[\s\S]*?(?=第{chapter_num}章|===|$)"
            block_match = re.search(chapter_block_pattern, content)
            if block_match:
                return block_match.group(0).strip()
        
        # 如果没有提供章节号或无法找到特定章节的剧情要点，则使用原来的逻辑
        # 分割内容为条目
        entries = content.split("\n=== ")
        valid_entries = []
        
        # 从后向前处理条目
        current_length = 0
        for entry in reversed(entries):
            if not entry.strip():
                continue
                
            # 只保留包含关键信息的条目
            if any(key in entry for key in ["章", "剧情要点", "审校", "核心功能", "伏笔设计", "颠覆指数", "[关键问题]"]):
                entry_text = f"=== {entry}" if not entry.startswith("===") else entry
                entry_length = len(entry_text)
                
                if current_length + entry_length <= max_chars:
                    valid_entries.insert(0, entry_text)
                    current_length += entry_length
                else:
                    break
                    
        return "\n".join(valid_entries)
    except Exception as e:
        logging.error(f"提取剧情要点时出错: {str(e)}")
        return ""

def check_consistency(
    character_state: str,
    global_summary: str, 
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    interface_format: str,
    max_tokens: int,
    timeout: int,
    filepath: str = "",
    novel_number: int = 1,
    Review_text: str = "",  # 添加新参数，直接接收主界面编辑框内容
    word_number: int = 3000,
    custom_prompt: str = None  # 添加自定义提示词参数
) -> str:
    """检查章节内容与已有设定的一致性"""
    
    logging.info("=== 开始一致性审校 ===")
    logging.info(f"开始校验第{novel_number}章内容...")

    try:
        # 检查传入的文本内容
        if not Review_text or not Review_text.strip():
            msg = "错误：当前编辑框内容为空，无法进行一致性审校"
            logging.warning(msg)
            return msg

        # 获取章节信息
        directory_file = os.path.join(filepath, "章节目录.txt")
        chapter_title = f"第{novel_number}章"
        chapter_info = {
            'chapter_role': '常规章节',
            'chapter_purpose': '推进主线',
            'suspense_type': '信息差型',
            'emotion_evolution': '焦虑-震惊-坚定',
            'foreshadow': '',  # 先初始化为空
            'plot_twist_level': 'Lv.1',
            'chapter_summary': '章节简述'
        }
        
        if os.path.exists(directory_file):
            try:
                content = read_file(directory_file)
                # 使用正则匹配准确提取章节标题
                title_pattern = f"第{novel_number}章\\s+([^\\n]+)"
                title_match = re.search(title_pattern, content)
                if title_match:
                    chapter_title = f"第{novel_number}章 {title_match.group(1)}"
                
                # 获取其他章节信息
                chapter_info = get_chapter_info_from_blueprint(content, novel_number) or chapter_info

                # 从原始目录文本中提取伏笔信息
                pattern = f"第{novel_number}章.*?伏笔条目：.*?(?=\n[^\\n│])"
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    raw_text = match.group(0)
                    foreshadow_pattern = r"├─伏笔条目：\n((?:│[└├]─.*\n?)*)"
                    foreshadow_match = re.search(foreshadow_pattern, raw_text)
                    if foreshadow_match:
                        operations = foreshadow_match.group(1).strip()
                        formatted_lines = []
                        for line in operations.split('\n'):
                            line = line.strip()
                            if line and not line.startswith("伏笔条目"):
                                line = line.replace("│├─", "").replace("│└─", "").strip()
                                if line:
                                    formatted_lines.append(line)
                        if formatted_lines:
                            chapter_info['foreshadow'] = "\n".join(formatted_lines)
            except Exception as e:
                logging.error(f"解析章节信息时出错: {str(e)}")
                logging.error(traceback.format_exc())

        # 获取分卷大纲
        volume_outline = ""
        try:
            if os.path.exists(os.path.join(filepath, "分卷大纲.txt")):
                with open(os.path.join(filepath, "分卷大纲.txt"), 'r', encoding='utf-8') as f:
                    volume_content = f.read()
                    for match in re.finditer(r'第(\d+)卷.*?第(\d+)章.*?第(\d+)章', volume_content):
                        if int(match.group(2)) <= novel_number <= int(match.group(3)):
                            volume_outline = extract_volume_outline(volume_content, int(match.group(1)))
                            break
        except Exception as e:
            logging.error(f"获取分卷大纲时出错: {str(e)}")
            volume_outline = ""

        # 提取最近的剧情要点
        plot_arcs = extract_recent_plot_arcs(filepath, 2000)

        # 调用 LLM 进行审校
        llm_adapter = create_llm_adapter(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            temperature=temperature,
            interface_format=interface_format,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        # 从伏笔向量库中提取伏笔记录
        knowledge_context = ""
        try:
            # 提取本章伏笔编号
            foreshadowing_ids = []
            if chapter_info.get('foreshadow'):
                # 从伏笔条目中提取伏笔编号
                for line in chapter_info['foreshadow'].split('\n'):
                    # 匹配伏笔编号（如MF001, SF001等）
                    fb_id_match = re.search(r'([A-Z]F\d+)', line)
                    if fb_id_match:
                        foreshadowing_ids.append(fb_id_match.group(1))
            
            if foreshadowing_ids:
                logging.info(f"本章伏笔编号: {foreshadowing_ids}")
                
                # 加载伏笔向量库
                embedding_adapter = create_embedding_adapter(
                    interface_format="openai",
                    api_key=api_key,
                    base_url=base_url,
                    model_name="text-embedding-ada-002"
                )
                
                vectorstore = load_vector_store(embedding_adapter, filepath, collection_name="foreshadowing_collection")
                
                if vectorstore:
                    logging.info("成功加载伏笔向量库，开始检索伏笔历史记录")
                    
                    for fb_id in foreshadowing_ids:
                        # 使用精确的元数据查询
                        results = vectorstore.get(
                            where={"id": fb_id},
                            include=["metadatas", "documents"]
                        )
                        
                        if results and results.get('ids'):
                            # 按章节号排序，获取最新的记录
                            entries = list(zip(results['ids'], results['metadatas'], results['documents']))
                            entries.sort(key=lambda x: x[1].get('chapter', 0), reverse=True)
                            latest_entry = entries[0]
                            
                            metadata = latest_entry[1]
                            content = latest_entry[2]
                            
                            # 格式化伏笔记录
                            entry = f"伏笔编号: {metadata.get('id', '未知')}\n"
                            entry += f"伏笔内容: {content}\n"
                            chapter_metadata_value = metadata.get('chapter', 0)
                            if str(chapter_metadata_value) != '0':
                                entry += f"伏笔最后章节：{chapter_metadata_value}\n\n\n"
                            
                            knowledge_context += entry
                            logging.info(f"成功检索伏笔 {fb_id} 的历史记录")
                    
                    if not knowledge_context:
                        knowledge_context = "(未找到相关伏笔历史记录)\n"
                else:
                    knowledge_context = "(向量库未初始化)\n"
                    logging.warning("警告：向量库未初始化，无法检索伏笔历史记录")
            else:
                knowledge_context = "(未找到伏笔编号)\n"
                logging.info("未找到伏笔编号，无法检索伏笔历史记录")
        except Exception as e:
            logging.error(f"提取伏笔记录时出错: {str(e)}")
            knowledge_context = f"(检索伏笔历史记录时出错: {str(e)})\n"

        # 获取用户指导内容
        user_guidance = ""
        try:
            # 从主界面获取内容指导编辑框的内容
            if hasattr(self, 'user_guide_text'):
                user_guidance = self.user_guide_text.get("0.0", "end").strip()
            elif hasattr(self.master, 'user_guide_text'):
                user_guidance = self.master.user_guide_text.get("0.0", "end").strip()
        except Exception as e:
            logging.error(f"获取用户指导内容时出错: {str(e)}")
            
        # 如果提供了自定义提示词，则使用它，否则构建提示词
        if custom_prompt:
            prompt = custom_prompt
        else:
            prompt = Chapter_Review_prompt.format(
                novel_number=novel_number,
                chapter_title=chapter_title,  # 使用更准确提取的章节标题
                word_number=word_number,  # 添加章节字数
                genre=genre,  # 添加小说类型
                chapter_role=chapter_info['chapter_role'],
                chapter_purpose=chapter_info['chapter_purpose'],
                suspense_type=chapter_info['suspense_type'],
                emotion_evolution=chapter_info['emotion_evolution'],
                foreshadowing=chapter_info.get('foreshadow', '无伏笔'),
                plot_twist_level=chapter_info['plot_twist_level'],
                chapter_summary=chapter_info['chapter_summary'][:75],
                global_summary=global_summary,
                character_state=character_state,
                volume_outline=volume_outline,
                Review_text=Review_text,  # 使用传入的编辑框内容
                plot_points=plot_arcs,  # 添加处理后的剧情要点，使用正确的参数名
                knowledge_context=knowledge_context,  # 添加伏笔记录
                user_guidance=user_guidance  # 添加用户指导
            )

        logging.info("发送审校请求到LLM...")
        result = invoke_with_cleaning(llm_adapter, prompt)
        
        if result and result.strip():
            logging.info("=== 完成一致性审校 ===")
            
            # 保存审校结果
            try:
                plot_arcs_file = os.path.join(filepath, "剧情要点.txt")
                with open(plot_arcs_file, 'a', encoding='utf-8') as f:
                    if "无明显冲突" not in result:  # 只有存在冲突时才记录
                        f.write(f"\n=== 第{novel_number}章审校记录 ===\n")
                        f.write(f"审校时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write("发现的问题：\n")
                        
                        # 处理每个冲突条目
                        conflict_lines = []
                        for line in result.split('\n'):
                            if any(key in line for key in ["[冲突", "[伏笔", "[角色", "[大纲"]):
                                # 确保每个条目都有适当的缩进和格式
                                formatted_line = line.strip()
                                if not formatted_line.startswith('-'):
                                    formatted_line = f"- {formatted_line}"
                                conflict_lines.append(formatted_line)
                        
                        if conflict_lines:  # 只有实际有冲突内容时才写入
                            f.write('\n'.join(conflict_lines))
                            f.write("\n\n")  # 添加额外空行作为分隔
            except Exception as e:
                logging.error(f"写入剧情要点文件时出错: {str(e)}")  # 修复括号
            
            # 直接统计 Review_text 的字数，因为它就是需要审校的内容
            # 标记是在提示词模板中添加的，不在原始的 Review_text 中
            actual_review_text_len = len(Review_text.strip())
            
            # 检查字数是否达标
            if actual_review_text_len < word_number / 10:  # 如果审校内容太短
                logging.info(f"审校结果字数较少，可能需要更详细的审校。当前字数：{actual_review_text_len}，目标字数：{word_number}")
            
            return result
            
        return "审校未返回有效结果"
            
    except Exception as e:
        error_msg = f"审校过程出错: {str(e)}"
        logging.error(error_msg)
        return error_msg
