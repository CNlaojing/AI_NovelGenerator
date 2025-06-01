# ui/generation_handlers.py
# -*- coding: utf-8 -*-
import os
import logging
import threading
import tkinter as tk
import json
import re
import time
from tkinter import messagebox, filedialog
import customtkinter as ctk
import traceback
from utils import read_file, save_string_to_txt, clear_file_content
from llm_adapters import create_llm_adapter
from embedding_adapters import create_embedding_adapter
from novel_generator.common import invoke_with_cleaning
from novel_generator.architecture import Novel_architecture_generate
from novel_generator.volume import Novel_volume_generate
from novel_generator.blueprint import Chapter_blueprint_generate
from novel_generator.chapter import generate_chapter_draft
from novel_generator.finalization import finalize_chapter, enrich_chapter_text
from novel_generator.knowledge import import_knowledge_file
from novel_generator.chapter_directory_parser import parse_chapter_blueprint, get_chapter_info_from_blueprint
from embedding_adapters import create_embedding_adapter
from novel_generator.vectorstore_utils import load_vector_store

# 屏蔽 LLM 相关 DEBUG 日志
for noisy_logger in [
    "openai", "openai._base_client", "httpcore", "httpcore.connection", "httpcore.http11", "httpx"
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

def import_knowledge_handler(self):
    """
    Handle importing knowledge files into the vector store
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("Warning", "Please select a save path first")
        return

    def task():
        try:
            # Get file to import
            file_path = filedialog.askopenfilename(
                title="Select Knowledge File",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if not file_path:
                return

            self.safe_log(f"Importing knowledge from {os.path.basename(file_path)}")
            
            # Create embedding adapter
            embedding_adapter = create_embedding_adapter(
                interface_format=self.embedding_interface_format_var.get(),
                api_key=self.embedding_api_key_var.get(),
                base_url=self.embedding_url_var.get(),
                model_name=self.embedding_model_name_var.get()
            )
            
            # Import the knowledge file
            import_knowledge_file(
                embedding_adapter=embedding_adapter,
                file_path=file_path,
                filepath=filepath
            )
            
            self.safe_log("✅ Knowledge imported successfully")
        except Exception as e:
            self.handle_exception(f"Error importing knowledge: {str(e)}")
    
    threading.Thread(target=task, daemon=True).start()
from novel_generator.vectorstore_utils import clear_vector_store

def clear_vectorstore_handler(self):
    """
    处理清理向量存储的UI函数
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        try:
            if not messagebox.askyesno("确认", "确定要清理向量存储吗？此操作不可逆"):
                return
                
            self.safe_log("开始清理向量存储...")
            
            # 创建嵌入适配器
            embedding_adapter = create_embedding_adapter(
                interface_format=self.embedding_interface_format_var.get(),
                api_key=self.embedding_api_key_var.get(),
                base_url=self.embedding_url_var.get(),
                model_name=self.embedding_model_name_var.get()
            )
            
            # 清理向量存储
            clear_vector_store(embedding_adapter, filepath)
            self.safe_log("✅ 向量存储已清理")
        except Exception as e:
            self.handle_exception(f"清理向量存储时出错: {str(e)}")
    
    threading.Thread(target=task, daemon=True).start()
from novel_generator.volume import get_current_volume_info  # 添加这一行
from novel_generator.chapter_blueprint import (
    analyze_directory_status,
    analyze_volume_range,
    find_current_volume,
    get_volume_progress,
    analyze_chapter_status,  # 补充此行
    update_foreshadowing_state  # 添加此行
)
from novel_generator.consistency_checker import check_consistency

def do_consistency_check(self, *args, **kwargs):
    """
    Wrapper function for consistency checking
    """
    # 调用 consistency_checker.py 中的 do_consistency_check 函数
    from novel_generator.consistency_checker import do_consistency_check as cc_do_consistency_check
    
    # 将 self 对象传递给 consistency_checker 中的函数
    return cc_do_consistency_check(self)
from novel_generator.rewrite import rewrite_chapter  # 添加导入

# 检查是否定义了 generate_volume_ui，如果没有则补充一个空实现，防止 ImportError

def generate_volume_ui(self):
    """
    分卷大纲生成UI
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def show_dialog():
        """显示生成对话框"""
        try:
            # 获取当前分卷信息
            from novel_generator.volume import get_current_volume_info
            current_vol, total_vols, remaining_vols = get_current_volume_info(filepath, self.safe_get_int(self.volume_count_var, 3))
            
            dialog = ctk.CTkToplevel(self.master)
            dialog.title("分卷大纲生成")
            dialog.geometry("400x250")
            dialog.transient(self.master)
            dialog.grab_set()
            
            # 创建角色数量输入变量
            character_count_var = tk.StringVar(value="8")
            
            # 删除直接生成按钮点击处理函数
            
            # 先生成主要角色按钮点击处理
            def handle_generate_characters_click():
                # 在关闭对话框前保存当前卷数和角色数量
                next_vol = current_vol + 1 if current_vol > 0 else 1
                character_count = int(character_count_var.get())
                dialog.destroy()
                self.disable_button_safe(self.btn_generate_volume)
                
                def characters_generation_thread(vol_num, char_count):
                    try:
                        
                        # 创建LLM适配器
                        interface_format = self.interface_format_var.get().strip()
                        api_key = self.api_key_var.get().strip()
                        base_url = self.base_url_var.get().strip()
                        model_name = self.model_name_var.get().strip()
                        temperature = self.temperature_var.get()
                        max_tokens = self.max_tokens_var.get()
                        timeout_val = self.safe_get_int(self.timeout_var, 600)
                        
                        llm_adapter = create_llm_adapter(
                            interface_format=interface_format,
                            base_url=base_url,
                            model_name=model_name,
                            api_key=api_key,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            timeout=timeout_val
                        )
                        
                        # 读取小说设定
                        novel_setting_file = os.path.join(filepath, "小说设定.txt")
                        if not os.path.exists(novel_setting_file):
                            self.safe_log("❌ 请先生成小说架构(小说设定.txt)")
                            return
                        novel_setting = read_file(novel_setting_file)
                        
                        # 准备提示词参数
                        topic = self.topic_text.get("0.0", "end").strip()
                        user_guidance = self.user_guide_text.get("0.0", "end").strip()
                        number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
                        word_number = self.safe_get_int(self.word_number_var, 3000)
                        volume_count = self.safe_get_int(self.volume_count_var, 3)
                        
                        # 读取分卷大纲（如果存在）
                        volume_file = os.path.join(filepath, "分卷大纲.txt")
                        volume_outline = ""
                        if (os.path.exists(volume_file)):
                            volume_content = read_file(volume_file)
                            if volume_content.strip():
                                volume_outline = volume_content
                        
                        # 使用create_character_state_prompt生成角色
                        from prompt_definitions import create_character_state_prompt, character_1_prompt
                        prompt = create_character_state_prompt.format(
                            genre=self.genre_var.get(),
                            volume_count=volume_count,
                            num_chapters=number_of_chapters,
                            word_number=word_number,
                            topic=topic,
                            user_guidance=user_guidance,
                            novel_setting=novel_setting,
                            volume_outline=volume_outline,
                            num_characters=char_count,
                            character_prompt=character_1_prompt,
                            volume_number=next_vol  # 添加 volume_number 参数
                        )
                        
                        if char_count == 0:
                            self.safe_log("ℹ️ 用户选择不生成角色，跳过LLM角色生成。")
                            characters = ""
                        else:
                            self.safe_log(f"开始生成{char_count}个第一卷主要角色...")
                            characters = invoke_with_cleaning(llm_adapter, prompt)
                            
                            if not characters.strip():
                                self.safe_log("❌ 角色生成失败")
                                return
                        
                        # 显示编辑提示词对话框
                        show_prompt_editor(characters)
                        
                    except Exception as e:
                        self.safe_log(f"❌ 生成角色时发生错误: {str(e)}")
                    finally:
                        self.enable_button_safe(self.btn_generate_volume)
                
                thread = threading.Thread(target=characters_generation_thread, args=(next_vol, character_count), daemon=True)
                thread.start()
                logging.info(f"已启动角色生成线程: {thread.ident}")
            
            # 显示提示词编辑器
            def show_prompt_editor(characters):
                editor_dialog = ctk.CTkToplevel(self.master)
                editor_dialog.title("编辑分卷大纲生成提示词")
                editor_dialog.geometry("800x600")
                editor_dialog.transient(self.master)
                editor_dialog.grab_set()
                
                # 准备volume_outline_prompt
                from prompt_definitions import volume_outline_prompt, volume_design_format
                topic = self.topic_text.get("0.0", "end").strip()
                user_guidance = self.user_guide_text.get("0.0", "end").strip()
                number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
                word_number = self.safe_get_int(self.word_number_var, 3000)
                volume_count = self.safe_get_int(self.volume_count_var, 3)
                
                # 读取小说设定
                novel_setting_file = os.path.join(filepath, "小说设定.txt")
                novel_setting = read_file(novel_setting_file)
                
                # 读取角色状态（如果存在）
                character_state_file = os.path.join(filepath, "角色状态.txt")
                character_state = ""
                if os.path.exists(character_state_file):
                    character_state = read_file(character_state_file)
                
                # 准备提示词
                genre = self.genre_var.get()
                
                # 处理核心人物信息
                characters_involved_detail = ""
                characters_involved_list_str = self.characters_involved_var.get()
                if characters_involved_list_str:
                    # 同时支持中文逗号和英文逗号作为分隔符
                    # 使用正则表达式替换所有中文逗号为英文逗号，然后用英文逗号分割
                    processed_list_str = characters_involved_list_str.replace('，', ',')
                    characters_involved_list = [name.strip() for name in processed_list_str.split(',') if name.strip()]
                    if characters_involved_list:
                        character_lib_path = os.path.join(filepath, "角色库")
                        for char_name in characters_involved_list:
                            # 在角色库的所有子文件夹中查找角色文件
                            found_char_file = False
                            if os.path.exists(character_lib_path) and os.path.isdir(character_lib_path):
                                for category_dir in os.listdir(character_lib_path):
                                    category_path = os.path.join(character_lib_path, category_dir)
                                    if os.path.isdir(category_path):
                                        char_file_path = os.path.join(category_path, f"{char_name}.txt")
                                        if os.path.exists(char_file_path):
                                            try:
                                                with open(char_file_path, 'r', encoding='utf-8') as f_char:
                                                    characters_involved_detail += f"{f_char.read()}\n\n"
                                                self.safe_log(f"✅ 成功读取角色文件: {char_file_path}")
                                                found_char_file = True
                                                break  # 找到文件后跳出循环
                                            except Exception as e_read_char:
                                                self.safe_log(f"❌ 读取角色文件 {char_file_path} 失败: {e_read_char}")
                                                characters_involved_detail += f"(无法读取角色文件内容)\n\n"
                                                found_char_file = True
                                                break  # 找到文件后跳出循环
                            
                            if not found_char_file:
                                self.safe_log(f"⚠️ 角色文件不存在: 在角色库中未找到 {char_name}.txt")
                                characters_involved_detail += f"(角色文件不存在)\n\n"
                    else:
                        self.safe_log("ℹ️ UI中未指定核心人物或格式不正确。")
                else:
                    self.safe_log("ℹ️ UI中未指定核心人物。")
                
                prompt = volume_outline_prompt.format(
                    topic=topic,
                    user_guidance=user_guidance,
                    novel_setting=novel_setting,
                    character_state=character_state,
                    setting_characters=characters,  # 使用生成的角色
                    characters_involved=characters_involved_detail,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    genre=genre, # 添加 genre 参数
                    volume_number=1,  # 添加 volume_number 参数
                    volume_design_format=volume_design_format,  # 添加 volume_design_format 参数
                    x=1,  # 第一卷从第1章开始
                    y=number_of_chapters // volume_count + (1 if number_of_chapters % volume_count > 0 else 0)  # 第一卷结束章节
                )
                
                # 创建提示词编辑框
                prompt_text = ctk.CTkTextbox(editor_dialog, wrap="word", font=("Microsoft YaHei", 12))
                prompt_text.pack(fill="both", expand=True, padx=10, pady=10)
                prompt_text.insert("0.0", prompt)
                
                # 确认按钮点击处理
                def handle_confirm_click():
                    # 先获取文本内容，再销毁对话框
                    prompt_content = prompt_text.get("0.0", "end").strip()
                    editor_dialog.destroy()
                    generate_with_custom_prompt(prompt_content)
                
                # 底部按钮区域
                btn_frame = ctk.CTkFrame(editor_dialog)
                btn_frame.pack(pady=10)
                
                ctk.CTkButton(
                    btn_frame,
                    text="确认生成",
                    command=handle_confirm_click,
                    font=("Microsoft YaHei", 12)
                ).pack(side="left", padx=10)
                
                ctk.CTkButton(
                    btn_frame,
                    text="取消",
                    command=editor_dialog.destroy,
                    font=("Microsoft YaHei", 12)
                ).pack(side="left", padx=10)

                word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 12))
                word_count_label.pack(side="right", padx=10)

                def update_word_count(event=None):
                    text = prompt_text.get("1.0", "end-1c") # Use end-1c to exclude the last newline
                    words = len(text) # Count characters as words for Chinese
                    word_count_label.configure(text=f"字数: {words}")

                prompt_text.bind("<KeyRelease>", update_word_count)
                update_word_count() # Initial count
            
            # 使用自定义提示词生成分卷大纲
            def generate_with_custom_prompt(custom_prompt):
                self.disable_button_safe(self.btn_generate_volume)
                
                # 在关闭对话框前保存当前卷数
                next_vol = current_vol + 1 if current_vol > 0 else 1
                
                def custom_generation_thread(vol_num):
                    try:
                        
                        # 创建LLM适配器
                        interface_format = self.interface_format_var.get().strip()
                        api_key = self.api_key_var.get().strip()
                        base_url = self.base_url_var.get().strip()
                        model_name = self.model_name_var.get().strip()
                        temperature = self.temperature_var.get()
                        max_tokens = self.max_tokens_var.get()
                        timeout_val = self.safe_get_int(self.timeout_var, 600)
                        
                        llm_adapter = create_llm_adapter(
                            interface_format=interface_format,
                            base_url=base_url,
                            model_name=model_name,
                            api_key=api_key,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            timeout=timeout_val
                        )
                        
                        self.safe_log(f"开始使用自定义提示词生成第{vol_num}卷大纲...")
                        outline = invoke_with_cleaning(llm_adapter, custom_prompt)
                        
                        if not outline.strip():
                            self.safe_log("❌ 分卷大纲生成失败：未获得有效内容")
                            return
                        
                        # 保存分卷大纲
                        volume_file = os.path.join(filepath, "分卷大纲.txt")
                        volume_title = "" if vol_num < total_vols else "终章"
                        
                        # 计算章节分布
                        number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
                        volume_count = self.safe_get_int(self.volume_count_var, 3)
                        chapters_per_volume = number_of_chapters // volume_count
                        remaining_chapters = number_of_chapters % volume_count
                        
                        # 计算当前卷的章节范围
                        extra_chapter = 1 if vol_num <= remaining_chapters else 0
                        start_chap = 1 + (vol_num - 1) * chapters_per_volume + min(vol_num - 1, remaining_chapters)
                        end_chap = start_chap + chapters_per_volume + extra_chapter - 1
                        
                        new_volume = f"\n\n#=== 第{vol_num}卷{volume_title}  第{start_chap}章 至 第{end_chap}章 ===\n{outline}"
                        
                        # 以追加模式保存新的分卷大纲
                        with open(volume_file, "a", encoding="utf-8") as f:
                            f.write(new_volume)
                        
                        self.safe_log(f"✅ 第{next_vol}卷大纲已生成并保存")
                        
                    except Exception as e:
                        self.safe_log(f"❌ 生成分卷大纲时发生错误: {str(e)}")
                    finally:
                        self.enable_button_safe(self.btn_generate_volume)
                
                thread = threading.Thread(target=custom_generation_thread, args=(next_vol,), daemon=True)
                thread.start()
                logging.info(f"已启动自定义提示词分卷生成线程: {thread.ident}")
            
            # UI组件设置
            if current_vol == 0:
                info_text = "分析小说设定给出主要角色后再生成第一卷大纲\n"
                btn2_text = "生成主要角色并弹出提示词"
            else:
                info_text = f"当前进度\n\n已生成 {current_vol}/{total_vols} 卷"

            info_label = ctk.CTkLabel(
                dialog,
                text=f"{info_text}",
                font=("Microsoft YaHei", 12)
            )
            info_label.pack(pady=10)
            
            # 只有在生成第一卷时显示角色数量输入框
            if (current_vol == 0):
                input_frame = ctk.CTkFrame(dialog)
                input_frame.pack(pady=5)
                
                ctk.CTkLabel(
                    input_frame,
                    text="主要角色数量：",
                    font=("Microsoft YaHei", 12)
                ).pack(side="left", padx=5)
                
                ctk.CTkEntry(
                    input_frame,
                    textvariable=character_count_var,
                    width=50,
                    font=("Microsoft YaHei", 12)
                ).pack(side="left", padx=5)

            btn_frame = ctk.CTkFrame(dialog)
            btn_frame.pack(pady=5)

            # 只有在生成第一卷时显示生成角色按钮
            if (current_vol == 0):
                ctk.CTkButton(
                    btn_frame,
                    text=btn2_text,
                    command=handle_generate_characters_click,
                    font=("Microsoft YaHei", 12),
                    width=200
                ).pack(pady=5)
            else:
                # 非第一卷时的生成按钮
                def open_subsequent_volume_prompt():
                    dialog.destroy() # 关闭当前的确认窗口
                    show_subsequent_volume_prompt(current_vol + 1)

                ctk.CTkButton(
                    btn_frame,
                    text=f"生成第{current_vol + 1}卷大纲",
                    command=open_subsequent_volume_prompt,
                    font=("Microsoft YaHei", 12),
                    width=200
                ).pack(pady=5)
                
                # 显示后续卷提示词编辑器
                def show_subsequent_volume_prompt(vol_num):
                    editor_dialog = ctk.CTkToplevel(self.master)
                    editor_dialog.title(f"编辑第{vol_num}卷大纲生成提示词")
                    editor_dialog.geometry("800x600")
                    editor_dialog.transient(self.master)
                    editor_dialog.grab_set()
                    
                    # 准备subsequent_volume_prompt
                    from prompt_definitions import subsequent_volume_prompt, final_volume_prompt, volume_design_format
                    topic = self.topic_text.get("0.0", "end").strip()
                    user_guidance = self.user_guide_text.get("0.0", "end").strip()
                    number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
                    word_number = self.safe_get_int(self.word_number_var, 3000)
                    volume_count = self.safe_get_int(self.volume_count_var, 3)
                    
                    # 读取小说设定
                    novel_setting_file = os.path.join(filepath, "小说设定.txt")
                    novel_setting = read_file(novel_setting_file)
                    
                    # 读取角色状态（如果存在）
                    character_state_file = os.path.join(filepath, "角色状态.txt")
                    character_state = ""
                    if os.path.exists(character_state_file):
                        character_state = read_file(character_state_file)
                    
                    # 读取分卷大纲（如果存在）
                    volume_file = os.path.join(filepath, "分卷大纲.txt")
                    previous_volume_outline = ""
                    if os.path.exists(volume_file):
                        volume_content = read_file(volume_file)
                        if volume_content.strip():
                            from novel_generator.volume import extract_volume_outline
                            previous_volume_outline = extract_volume_outline(volume_content, vol_num - 1)
                    
                    # 创建一个新的对话框，让用户输入权重值并显示当前进度
                    weight_dialog = ctk.CTkToplevel(self.master)
                    weight_dialog.title(f"设置角色权重")
                    weight_dialog.geometry("400x200")
                    weight_dialog.transient(editor_dialog)
                    weight_dialog.grab_set()
                    
                    # 显示当前进度
                    progress_label = ctk.CTkLabel(
                        weight_dialog,
                        text=f"当前进度：已生成 {current_vol}/{total_vols} 卷",
                        font=("Microsoft YaHei", 12)
                    )
                    progress_label.pack(pady=(20, 5))
                    
                    # 创建权重输入框
                    weight_frame = ctk.CTkFrame(weight_dialog)
                    weight_frame.pack(pady=10)
                    
                    weight_label = ctk.CTkLabel(
                        weight_frame,
                        text="检索向量库内大于",
                        font=("Microsoft YaHei", 12)
                    )
                    weight_label.pack(side="left", padx=5)
                    
                    weight_var = tk.StringVar(value="91")
                    weight_entry = ctk.CTkEntry(
                        weight_frame,
                        textvariable=weight_var,
                        width=50,
                        font=("Microsoft YaHei", 12)
                    )
                    weight_entry.pack(side="left", padx=5)
                    
                    weight_label2 = ctk.CTkLabel(
                        weight_frame,
                        text="权重的角色",
                        font=("Microsoft YaHei", 12)
                    )
                    weight_label2.pack(side="left", padx=5)
                    
                    # 按钮区域
                    btn_frame = ctk.CTkFrame(weight_dialog)
                    btn_frame.pack(pady=20)
                    
                    def handle_generate_click():
                        try:
                            weight_value = int(weight_var.get())
                            if weight_value < 0 or weight_value > 100:
                                messagebox.showwarning("警告", "权重值应在0-100之间")
                                return
                                
                            weight_dialog.destroy()
                            
                            # 创建LLM适配器
                            interface_format = self.interface_format_var.get().strip()
                            api_key = self.api_key_var.get().strip()
                            base_url = self.base_url_var.get().strip()
                            model_name = self.model_name_var.get().strip()
                            temperature = self.temperature_var.get()
                            max_tokens = self.max_tokens_var.get()
                            timeout_val = self.safe_get_int(self.timeout_var, 600)
                            
                            llm_adapter = create_llm_adapter(
                                interface_format=interface_format,
                                base_url=base_url,
                                model_name=model_name,
                                api_key=api_key,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                timeout=timeout_val
                            )
                            
                            # 修改get_high_weight_characters函数调用，传入用户指定的权重值
                            from novel_generator.volume import get_high_weight_characters
                            setting_characters = ""
                            try:
                                # 使用自定义权重值获取角色
                                self.safe_log(f"正在检索权重大于{weight_value}的角色...")
                                setting_characters = get_high_weight_characters(filepath, llm_adapter, weight_value)
                            except Exception as e:
                                self.safe_log(f"获取高权重角色时出错: {str(e)}")
                            
                            # 计算章节分布
                            chapters_per_volume = number_of_chapters // volume_count
                            remaining_chapters = number_of_chapters % volume_count
                            extra_chapter = 1 if vol_num <= remaining_chapters else 0
                            start_chap = 1 + (vol_num - 1) * chapters_per_volume + min(vol_num - 1, remaining_chapters)
                            end_chap = start_chap + chapters_per_volume + extra_chapter - 1
                            
                            # 继续处理提示词和显示编辑器
                            continue_with_prompt_editor(setting_characters, start_chap, end_chap)
                            
                        except ValueError:
                            messagebox.showerror("错误", "请输入有效的权重数值")
                    
                    ctk.CTkButton(
                        btn_frame,
                        text=f"生成第{vol_num}卷大纲",
                        command=handle_generate_click,
                        font=("Microsoft YaHei", 12),
                        width=150
                    ).pack(side="left", padx=10)
                    
                    ctk.CTkButton(
                        btn_frame,
                        text="退出",
                        command=weight_dialog.destroy,
                        font=("Microsoft YaHei", 12),
                        width=100
                    ).pack(side="left", padx=10)
                    
                    # 定义继续处理提示词和显示编辑器的函数
                    def continue_with_prompt_editor(setting_characters, start_chap, end_chap):
                        # 准备提示词
                        genre = self.genre_var.get()
                        
                        # 处理核心人物信息
                        characters_involved_detail = ""
                        characters_involved_list_str = self.characters_involved_var.get()
                        if characters_involved_list_str:
                            # 同时支持中文逗号和英文逗号作为分隔符
                            # 使用正则表达式替换所有中文逗号为英文逗号，然后用英文逗号分割
                            processed_list_str = characters_involved_list_str.replace('，', ',')
                            characters_involved_list = [name.strip() for name in processed_list_str.split(',') if name.strip()]
                            if characters_involved_list:
                                character_lib_path = os.path.join(filepath, "角色库")
                                for char_name in characters_involved_list:
                                    # 在角色库的所有子文件夹中查找角色文件
                                    found_char_file = False
                                    if os.path.exists(character_lib_path) and os.path.isdir(character_lib_path):
                                        for category_dir in os.listdir(character_lib_path):
                                            category_path = os.path.join(character_lib_path, category_dir)
                                            if os.path.isdir(category_path):
                                                char_file_path = os.path.join(category_path, f"{char_name}.txt")
                                                if os.path.exists(char_file_path):
                                                    try:
                                                        with open(char_file_path, 'r', encoding='utf-8') as f_char:
                                                            characters_involved_detail += f"{f_char.read()}\n\n"
                                                        self.safe_log(f"✅ 成功读取角色文件: {char_file_path}")
                                                        found_char_file = True
                                                        break  # 找到文件后跳出循环
                                                    except Exception as e_read_char:
                                                        self.safe_log(f"❌ 读取角色文件 {char_file_path} 失败: {e_read_char}")
                                                        characters_involved_detail += f"(无法读取角色文件内容)\n\n"
                                                        found_char_file = True
                                                        break  # 找到文件后跳出循环
                                    
                                    if not found_char_file:
                                        self.safe_log(f"⚠️ 角色文件不存在: 在角色库中未找到 {char_name}.txt")
                                        characters_involved_detail += f"(角色文件不存在)\n\n"
                            else:
                                self.safe_log("ℹ️ UI中未指定核心人物或格式不正确。")
                        else:
                            self.safe_log("ℹ️ UI中未指定核心人物。")
                        
                        # 判断是否是最终卷
                        if vol_num == volume_count:
                            prompt = final_volume_prompt.format(
                                topic=topic,
                                user_guidance=user_guidance,
                                novel_setting=novel_setting,
                                character_state=character_state,
                                characters_involved=characters_involved_detail,
                                previous_volume_outline=previous_volume_outline,
                                number_of_chapters=number_of_chapters,
                                word_number=word_number,
                                Total_volume_number=volume_count,
                                volume_number=vol_num,
                                genre=genre,
                                volume_design_format=volume_design_format,
                                x=start_chap
                            )
                        else:
                            prompt = subsequent_volume_prompt.format(
                                topic=topic,
                                user_guidance=user_guidance,
                                novel_setting=novel_setting,
                                character_state=character_state,
                                characters_involved=characters_involved_detail,
                                previous_volume_outline=previous_volume_outline,
                                setting_characters=setting_characters,
                                number_of_chapters=number_of_chapters,
                                word_number=word_number,
                                Total_volume_number=volume_count,
                                volume_number=vol_num,
                                genre=genre,
                                volume_design_format=volume_design_format,
                                x=start_chap,
                                y=end_chap
                            )
                        
                        # 创建提示词编辑框
                        prompt_text = ctk.CTkTextbox(editor_dialog, wrap="word", font=("Microsoft YaHei", 12))
                        prompt_text.pack(fill="both", expand=True, padx=10, pady=10)
                        prompt_text.insert("0.0", prompt)
                        
                        # 确认按钮点击处理
                        def handle_confirm_click():
                            # 先获取文本内容，再销毁对话框
                            prompt_content = prompt_text.get("0.0", "end").strip()
                            editor_dialog.destroy()
                            generate_with_custom_prompt(prompt_content)
                        
                        # 底部按钮区域
                        btn_frame = ctk.CTkFrame(editor_dialog)
                        btn_frame.pack(pady=10)
                        
                        ctk.CTkButton(
                            btn_frame,
                            text="确认生成",
                            command=handle_confirm_click,
                            font=("Microsoft YaHei", 12)
                        ).pack(side="left", padx=10)
                        
                        ctk.CTkButton(
                            btn_frame,
                            text="取消",
                            command=editor_dialog.destroy,
                            font=("Microsoft YaHei", 12)
                        ).pack(side="left", padx=10)

                        word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 12))
                        word_count_label.pack(side="right", padx=10)

                        def update_word_count(event=None):
                            text = prompt_text.get("1.0", "end-1c")
                            words = len(text)
                            word_count_label.configure(text=f"字数: {words}")

                        prompt_text.bind("<KeyRelease>", update_word_count)
                        update_word_count() # Initial count

            # 退出按钮放在底部
            exit_frame = ctk.CTkFrame(dialog)
            exit_frame.pack(pady=5)
            ctk.CTkButton(
                exit_frame,
                text="退出",
                command=dialog.destroy,
                font=("Microsoft YaHei", 12),
                width=100
            ).pack()

        except Exception as e:
            self.safe_log(f"❌ 显示分卷大纲生成对话框时出错: {str(e)}")
            self.enable_button_safe(self.btn_generate_volume)

    # 删除了do_generate_volume函数，因为不再需要直接生成第一卷大纲的功能

    def main_task():
        """主任务函数"""
        try:
            volume_count = self.safe_get_int(self.volume_count_var, 3)
            show_dialog()
            
        except Exception as e:
            self.safe_log(f"❌ 检查分卷大纲状态时发生错误: {str(e)}")
            self.enable_button_safe(self.btn_generate_volume)

    threading.Thread(target=main_task, daemon=True).start()

def rewrite_chapter_ui(self):
    """
    章节重写UI界面
    """
    self.disable_button_safe(self.btn_rewrite_chapter) # 问题1：禁用按钮
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
    
    # 获取当前章节号 (从章节编辑框获取)
    chapter_num_str = self.chapter_num_var.get().strip()
    if not chapter_num_str:
        messagebox.showwarning("警告", "请先输入要改写的章节号")
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
    try:
        chapter_num = int(chapter_num_str)
    except ValueError:
        messagebox.showerror("错误", "无效的章节号")
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
        
    # Determine the chapter file path (for saving later)
    chapter_file = os.path.join(filepath, "chapters", f"chapter_{chapter_num}.txt")
    # Check for old format filename if the new one doesn't exist, but don't return if neither exists yet
    chapter_file_to_read = chapter_file # Default to new path
    if not os.path.exists(chapter_file):
        chapter_file_old_format = os.path.join(filepath, f"第{chapter_num}章.txt")
        if os.path.exists(chapter_file_old_format):
            chapter_file_to_read = chapter_file_old_format # Use old path if it exists

    # 获取当前章节内容，优先使用编辑框内容
    chapter_content = "" # Use chapter_content variable name
    if hasattr(self, "chapter_result"):
        chapter_content = self.chapter_result.get("0.0", "end").strip()
    
    # 如果编辑框内容为空，尝试从文件读取
    if not chapter_content and os.path.exists(chapter_file_to_read):
        chapter_content = read_file(chapter_file_to_read)

    if not chapter_content.strip():
        self.safe_log(f"❌ 第 {chapter_num} 章内容为空，无法改写。请在编辑框中输入内容或确保章节文件存在且不为空。")
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
    
    # 获取章节信息
    directory_file = os.path.join(filepath, "章节目录.txt")
    directory_content = ""
    if os.path.exists(directory_file):
        with open(directory_file, 'r', encoding='utf-8') as f:
            directory_content = f.read()
    else:
        self.safe_log(f"警告: 未找到章节目录文件 {directory_file}，将使用默认章节信息。")

    # 提取章节信息 (兼容两种格式)
    chapter_title = f"第{chapter_num}章"
    chapter_role = "常规章节"
    chapter_purpose = "推进主线"
    suspense_type = "信息差型"
    emotion_evolution = "焦虑-震惊-坚定"
    foreshadowing = ""
    plot_twist_level = "Lv.2"
    chapter_summary = ""
    found_chapter_details = False

    # 尝试第一种格式 (新格式)
    chapter_pattern_new = re.compile(
        r"^第(\d+)章\s*《([^》]+)》\s*【章节作用】(.*?)\s*【章节目的】(.*?)\s*【悬念类型】(.*?)\s*【情绪演变】(.*?)\s*【伏笔类型】(.*?)\s*【反转级别】(.*?)\s*【章节梗概】(.*)", 
        re.MULTILINE
    )
    for match in chapter_pattern_new.finditer(directory_content):
        if int(match.group(1)) == chapter_num:
            chapter_title = match.group(2).strip()
            chapter_role = match.group(3).strip()
            chapter_purpose = match.group(4).strip()
            suspense_type = match.group(5).strip()
            emotion_evolution = match.group(6).strip()
            foreshadowing = match.group(7).strip()
            plot_twist_level = match.group(8).strip()
            chapter_summary = match.group(9).strip()
            found_chapter_details = True
            break
    
    # 如果第一种格式未匹配到，尝试第二种格式 (旧格式)
    if not found_chapter_details:
        chapter_pattern_old = re.compile(r'第\s*(\d+)\s*章\s*([^\n]+).*?├─本章定位：\s*([^\n]+).*?├─核心作用：\s*([^\n]+).*?├─悬念类型：\s*([^\n]+).*?├─情绪演变：\s*([^\n]+).*?├─伏笔条目：([\s\S]*?)├─颠覆指数：\s*([^\n]+).*?└─本章简述：\s*([^\n]+)', re.DOTALL)
        for match in chapter_pattern_old.finditer(directory_content):
            if int(match.group(1)) == chapter_num:
                chapter_title = match.group(2).strip()
                chapter_role = match.group(3).strip()
                chapter_purpose = match.group(4).strip()
                suspense_type = match.group(5).strip()
                emotion_evolution = match.group(6).strip()
                foreshadowing = match.group(7).strip()
                plot_twist_level = match.group(8).strip()
                chapter_summary = match.group(9).strip()
                found_chapter_details = True
                break

    if not found_chapter_details and os.path.exists(directory_file):
        self.safe_log(f"警告: 未在章节目录中找到第 {chapter_num} 章的详细信息，将使用默认值。")

    # 获取小说设定
    novel_setting_file = os.path.join(filepath, "小说设定.txt")
    novel_setting = ""
    if os.path.exists(novel_setting_file):
        with open(novel_setting_file, 'r', encoding='utf-8') as f:
            novel_setting = f.read()
    else:
        messagebox.showerror("错误", f"小说设定文件 {novel_setting_file} 不存在！")
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
        
    # 获取前情摘要
    global_summary_file = os.path.join(filepath, "前情摘要.txt")
    global_summary = ""
    if os.path.exists(global_summary_file):
        with open(global_summary_file, 'r', encoding='utf-8') as f:
            global_summary = f.read()
    
    # 获取分卷大纲
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    volume_content = ""
    if os.path.exists(volume_file):
        with open(volume_file, 'r', encoding='utf-8') as f:
            volume_content = f.read()
    
    # 确定当前章节所属的卷
    volume_number = 1 # 默认第一卷
    found_volume_for_chapter = False
    for i in range(1, 100): # 假设不超过99卷
        pattern = rf"#=== 第{i}卷.*?第(\d+)章 至 第(\d+)章"
        match_vol = re.search(pattern, volume_content)
        if match_vol:
            start_chap_vol = int(match_vol.group(1))
            end_chap_vol = int(match_vol.group(2))
            if start_chap_vol <= chapter_num <= end_chap_vol:
                volume_number = i
                found_volume_for_chapter = True
                break
    if not found_volume_for_chapter:
        self.safe_log(f"警告: 未能在分卷大纲中明确找到第 {chapter_num} 章所属卷，默认为第 {volume_number} 卷。")

    # 提取当前卷大纲
    from novel_generator.volume import extract_volume_outline
    volume_outline = extract_volume_outline(volume_content, volume_number)
    
    # 获取用户指导
    user_guidance = self.user_guide_text.get("0.0", "end").strip()
    
    # 获取小说类型
    genre = "奇幻" # 默认值
    genre_pattern = re.compile(r'类型：\s*([^\n]+)', re.MULTILINE)
    genre_match = genre_pattern.search(novel_setting)
    if genre_match:
        genre = genre_match.group(1).strip()
    
    # 获取小说主题
    topic = "" # 默认值
    topic_pattern = re.compile(r'主题：\s*([^\n]+)', re.MULTILINE)
    topic_match = topic_pattern.search(novel_setting)
    if topic_match:
        topic = topic_match.group(1).strip()
    
    # 获取章节字数
    word_number = 3000 # 默认值
    word_number_pattern = re.compile(r'每章(\d+)字', re.MULTILINE)
    word_number_match = word_number_pattern.search(novel_setting)
    if word_number_match:
        word_number = int(word_number_match.group(1))
    
    # 读取一致性审校文件内容
    consistency_review = ""
    consistency_review_file = os.path.join(filepath, "一致性审校.txt")
    if os.path.exists(consistency_review_file):
        try:
            consistency_review = read_file(consistency_review_file)
        except Exception as e:
            self.safe_log(f"读取一致性审校文件时出错: {str(e)}")
    
    # 构建提示词
    # 问题2：此处的 prompt_text 是最终发送给 LLM 的提示词，日志行为符合预期
    from prompt_definitions import chapter_rewrite_prompt
    prompt_text = chapter_rewrite_prompt.format(
        novel_number=chapter_num,
        chapter_title=chapter_title,
        word_number=word_number,
        genre=genre,
        chapter_role=chapter_role,
        chapter_purpose=chapter_purpose,
        suspense_type=suspense_type,
        emotion_evolution=emotion_evolution,
        foreshadowing=foreshadowing,
        plot_twist_level=plot_twist_level,
        chapter_summary=chapter_summary,
        user_guidance=user_guidance,
        volume_outline=volume_outline,
        global_summary=global_summary,
        一致性审校=consistency_review,
        raw_draft=chapter_content
    )
    
    # 显示提示词编辑器
    self.show_rewrite_prompt_editor(prompt_text, chapter_num, filepath, chapter_file)

def show_rewrite_prompt_editor(self, prompt_text, chapter_num, filepath, chapter_file_path):
    """显示章节改写提示词编辑器"""
    dialog = ctk.CTkToplevel(self.master)
    dialog.title("编辑改写提示词")
    dialog.geometry("800x600")
    dialog.transient(self.master)  # 使弹窗相对于主窗口
    dialog.grab_set()  # 使弹窗成为模态窗口，阻止与主窗口交互

    # 定义取消操作
    def on_cancel():
        dialog.destroy()
        self.safe_log("❌ 用户取消了章节改写请求。")
        self.enable_button_safe(self.btn_rewrite_chapter) # 问题1：用户取消时恢复按钮

    # 将窗口关闭按钮也绑定到 on_cancel
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    
    textbox = ctk.CTkTextbox(dialog, wrap="word")
    textbox.pack(fill="both", expand=True, padx=10, pady=10)
    textbox.insert("0.0", prompt_text)
    
    def on_confirm():
        modified_prompt = textbox.get("0.0", "end")
        dialog.destroy()
        self.execute_chapter_rewrite(modified_prompt, chapter_num, filepath, chapter_file_path) # Pass chapter_file_path

    btn_frame = ctk.CTkFrame(dialog)
    btn_frame.pack(pady=10)

    ctk.CTkButton(btn_frame, text="确认改写", command=on_confirm).pack(side="left", padx=5)
    ctk.CTkButton(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=5)

    word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 12))
    word_count_label.pack(side="right", padx=10)

    def update_word_count(event=None):
        text = textbox.get("1.0", "end-1c")
        words = len(text)
        word_count_label.configure(text=f"字数: {words}")

    textbox.bind("<KeyRelease>", update_word_count)
    update_word_count() # Initial count


def execute_chapter_rewrite(self, prompt, chapter_num, filepath, chapter_file_path):
    """执行章节改写"""
    self.safe_log(f"开始改写第{chapter_num}章...")
    
    def rewrite_thread():
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)

            # 获取 Embedding 配置
            embedding_interface_format = self.embedding_interface_format_var.get().strip()
            embedding_api_key = self.embedding_api_key_var.get().strip()
            embedding_base_url = self.embedding_url_var.get().strip()
            embedding_model_name = self.embedding_model_name_var.get().strip()
            
            from novel_generator.rewrite import rewrite_chapter # 修改导入
            # 注意：rewrite_chapter 函数的参数与 rewrite_chapter_content 可能不同
            # 这里假设 rewrite_chapter 需要 current_text, filepath, novel_number
            # 您可能需要根据 rewrite_chapter 函数的实际定义调整参数
            # 获取当前章节内容，这里用 chapter_content (即 prompt) 作为示例，实际可能需要从文件读取
            # The 'prompt' here is actually the modified prompt for rewriting, not the original chapter content.
            # The rewrite_chapter function in novel_generator.rewrite should handle getting the original content if needed, or accept it.
            # Based on the parameters, current_text=prompt seems to be what was intended for the LLM call.
            # The core issue is updating UI and saving. The call to rewrite_chapter itself is assumed to be mostly correct for generation.
            
            rewritten_content = rewrite_chapter(
                current_text=prompt, # This 'prompt' is the full text sent to LLM for rewriting
                filepath=filepath,
                novel_number=chapter_num,
                # LLM parameters
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_val,
                # Embedding parameters
                embedding_interface_format=embedding_interface_format,
                embedding_api_key=embedding_api_key,
                embedding_base_url=embedding_base_url,
                embedding_model_name=embedding_model_name
            ) # 修改函数调用
            
            if rewritten_content:
                # 更新UI中的章节内容 (内容编辑框编辑框)
                self.chapter_result.delete("0.0", "end") # Corrected widget name
                self.chapter_result.insert("0.0", rewritten_content) # Corrected widget name
                
                # 保存改写后的内容到文件
                try:
                    # Ensure the directory exists if chapter_file_path includes subdirectories like 'chapters'
                    os.makedirs(os.path.dirname(chapter_file_path), exist_ok=True)
                    save_string_to_txt(rewritten_content, chapter_file_path)
                    self.safe_log(f"✅ 第{chapter_num}章改写完成并已保存到 {os.path.basename(chapter_file_path)}")
                except Exception as e_save:
                    self.safe_log(f"❌ 第{chapter_num}章改写内容保存失败: {str(e_save)}")
            else:
                self.safe_log(f"❌ 第{chapter_num}章改写失败")
        except Exception as e:
            self.handle_exception(f"章节改写时出错: {str(e)}")
        finally:
            self.enable_button_safe(self.btn_rewrite_chapter) # 问题1：在线程结束时启用按钮
    
    threading.Thread(target=rewrite_thread, daemon=True).start()

def show_plot_arcs_ui(self):
    """
    显示剧情要点UI界面
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        try:
            # 创建剧情要点展示窗口
            dialog = ctk.CTkToplevel(self.master)
            dialog.title("剧情要点展示")
            dialog.geometry("800x600")
            
            # 添加剧情要点展示组件
            text_box = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 12))
            text_box.pack(fill="both", expand=True, padx=10, pady=10)
            
            # 读取并显示剧情要点文件
            plot_points_file = os.path.join(filepath, "剧情要点.txt")
            if os.path.exists(plot_points_file):
                with open(plot_points_file, 'r', encoding='utf-8') as f:
                    text_box.insert("0.0", f.read())
            else:
                text_box.insert("0.0", "未找到剧情要点文件")
                
        except Exception as e:
            self.handle_exception(f"显示剧情要点时出错: {str(e)}")
    
    threading.Thread(target=task, daemon=True).start()

# 检查是否定义了 finalize_chapter_ui，如果没有则补充一个空实现，防止 ImportError

def finalize_chapter_ui(self):
    """
    章节定稿UI界面 - 执行新的四步定稿流程
    """
    logging.info("--- 按照四步定稿流程定稿 ---")
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return
    self.disable_button_safe(self.btn_finalize_chapter)
    confirm = messagebox.askyesno("确认", "确定要执行章节定稿流程吗？\n这将依次执行：\n1. 更新前情摘要\n2. 向量化角色状态\n3. 向量化伏笔内容\n4. 提取剧情要点")
    if not confirm:
        logging.info("--- User cancelled chapter finalization ---")
        self.enable_button_safe(self.btn_finalize_chapter)
        self.safe_log("❌ 用户取消了章节定稿流程。")
        return

    # 执行四步定稿流程
    def execute_finalization_steps():
        def task():
            try:
                chap_num = self.safe_get_int(self.chapter_num_var, 1)
                self.safe_log(f"🚀 开始执行第 {chap_num} 章定稿流程...")

                # --- 准备工作 ---
                self.safe_log("  [0/4] 准备输入数据...")
                chapter_file = os.path.join(filepath, "chapters", f"chapter_{chap_num}.txt")
                summary_file = os.path.join(filepath, "前情摘要.txt")
                character_state_file = os.path.join(filepath, "角色状态.txt")
                plot_points_file = os.path.join(filepath, "剧情要点.txt") # 修复路径，直接使用项目根目录下的剧情要点文件
                directory_file = os.path.join(filepath, "章节目录.txt")

                # 优先使用编辑框内容作为章节正文
                if hasattr(self, "chapter_result"):
                    chapter_text = self.chapter_result.get("0.0", "end").strip()
                else:
                    # 如果UI编辑框没有内容，则尝试从文件读取
                    if os.path.exists(chapter_file):
                        chapter_text = read_file(chapter_file)
                    else:
                        chapter_text = ""

                if not chapter_text.strip():
                    self.safe_log(f"❌ 第 {chap_num} 章内容为空，无法定稿。请在编辑框中输入内容或确保章节文件存在且不为空。")
                    return

                global_summary = read_file(summary_file)
                old_character_state = read_file(character_state_file)
                directory_content = read_file(directory_file)
                chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
                if not chapter_info:
                    self.safe_log(f"❌ 未能在章节目录中找到第 {chap_num} 章的信息。")
                    # 允许继续，但后续步骤可能缺少信息

                chapter_title = chapter_info.get('chapter_title', f"第{chap_num}章") if chapter_info else f"第{chap_num}章"
                foreshadowing_str = chapter_info.get('foreshadowing', "") if chapter_info else ""
                character_names_str = chapter_info.get('characters_involved', "") if chapter_info else "" # Assuming 'characters_involved' holds the names

                # --- 导入所需模块和提示词 ---
                try:
                    from prompt_definitions import (summary_prompt, update_character_state_prompt,
                                                    foreshadowing_processing_prompt,
                                                    plot_points_extraction_prompt)
                    from novel_generator.common import invoke_llm # Assuming invoke_llm exists and works
                    from novel_generator.knowledge import process_and_vectorize_foreshadowing, process_and_vectorize_characters # 已实现
                except ImportError as e:
                    self.handle_exception(f"定稿流程中导入错误: {e}. 请确保所有依赖项和函数已正确实现。")
                    return

                from llm_adapters import create_llm_adapter
                from embedding_adapters import create_embedding_adapter
                from novel_generator.vectorstore_utils import load_vector_store, get_relevant_context_from_vector_store # Assuming these exist

                # --- 创建 LLM 和 Embedding 适配器 ---
                llm_adapter = create_llm_adapter(
                    interface_format=self.interface_format_var.get(),
                    api_key=self.api_key_var.get(),
                    base_url=self.base_url_var.get(),
                    model_name=self.model_name_var.get(),
                    temperature=self.temperature_var.get(),
                    max_tokens=self.max_tokens_var.get(),
                    timeout=self.timeout_var.get()
                )
                embedding_adapter = create_embedding_adapter(
                    interface_format=self.embedding_interface_format_var.get(),
                    api_key=self.embedding_api_key_var.get(),
                    base_url=self.embedding_api_key_var.get(),
                    model_name=self.embedding_model_name_var.get()
                )
                vectorstore = None # Initialize to None as the novel_collection load is removed
                # vectorstore = load_vector_store(embedding_adapter, filepath) # Removed due to missing collection_name and likely related to deleted novel_collection

                if not llm_adapter:
                    self.safe_log("❌ LLM适配器创建失败，无法执行定稿流程。")
                    return

                # --- 步骤 1: 更新前情摘要 --- 
                self.safe_log("  [1/4] 正在更新前情摘要...")
                summary_update_prompt = summary_prompt.format(chapter_text=chapter_text, global_summary=global_summary)
                # 输出提示词到终端
                logging.info("==============================前情摘要更新提示词==============================:\n" + summary_update_prompt)
                
                # 使用异步方式调用LLM更新前情摘要
                from novel_generator.common import invoke_llm_async
                import threading
                
                # 创建一个事件对象，用于等待异步操作完成
                summary_update_done = threading.Event()
                new_summary = None
                
                # 定义回调函数
                def on_summary_update_done(result, error=None):
                    nonlocal new_summary
                    if error:
                        logging.error(f"更新前情摘要时出错: {error}")
                        new_summary = ""
                    else:
                        new_summary = result
                    summary_update_done.set()
                
                # 异步调用LLM
                invoke_llm_async(llm_adapter, summary_update_prompt, on_summary_update_done)
                
                # 等待异步操作完成，但不阻塞UI线程
                summary_update_done.wait() # 直接等待完成
                
                if not summary_update_done.is_set():
                    self.safe_log("    ⚠️ 更新前情摘要超时，将在后台继续处理。")
                    # 继续执行后续步骤
                elif new_summary:
                    save_string_to_txt(new_summary, summary_file)
                    self.safe_log("    ✅ 前情摘要已更新。")
                else:
                    self.safe_log("    ⚠️ 更新前情摘要失败。")
                    # 继续执行后续步骤

                # --- 步骤 2: 更新角色状态 --- 
                self.safe_log("  [2/4] 正在更新角色状态...")
                
                # 使用异步方式调用update_character_states函数更新角色状态
                try:
                    from novel_generator.common import update_character_states_async
                    import threading
                    
                    # 创建一个事件对象，用于等待异步操作完成
                    character_update_done = threading.Event()
                    update_result = None
                    
                    # 定义回调函数
                    def on_character_update_done(result):
                        nonlocal update_result
                        update_result = result
                        character_update_done.set()
                    
                    # 异步调用角色状态更新函数
                    update_character_states_async(
                        chapter_text=chapter_text,
                        chapter_title=f"第{chap_num}章",
                        chap_num=chap_num,
                        filepath=filepath,
                        llm_adapter=llm_adapter,
                        embedding_adapter=embedding_adapter,
                        callback=on_character_update_done
                    )
                    
                    # 等待异步操作完成，但不阻塞UI线程
                    # 移除读秒逻辑，直接等待完成
                    character_update_done.wait()
                    
                    # 读取最新的角色状态文件内容
                    new_character_state = read_file(character_state_file)
                    
                    if not character_update_done.is_set():
                        self.safe_log("    ⚠️ 更新角色状态超时，将在后台继续处理。")
                        new_character_state = old_character_state
                    elif not new_character_state or not new_character_state.strip():
                        # 如果文件为空，则保持原有内容不变
                        new_character_state = old_character_state
                        error_msg = update_result.get('message', '未知错误') if update_result else '未知错误'
                        self.safe_log(f"    ⚠️ 更新角色状态失败: {error_msg}")
                    else:
                        self.safe_log("    ✅ 角色状态和角色数据库已更新。")
                except Exception as e:
                    self.safe_log(f"    ⚠️ 更新角色状态时出错: {str(e)}")
                    new_character_state = old_character_state

                # --- 步骤 4: 向量化伏笔内容 --- 
                self.safe_log("  [3/4] 正在处理和向量化伏笔内容...")
                # 输出伏笔信息到终端
                logging.info(f"本章伏笔信息: {foreshadowing_str}")
                # 检查向量库是否存在，如果不存在则初始化
                if embedding_adapter and not vectorstore:
                    from novel_generator.vectorstore_utils import init_vector_store
                    logging.info("向量库不存在，尝试初始化新的向量库...")
                    # 使用章节文本初始化向量库
                    vectorstore = init_vector_store(embedding_adapter, [chapter_text], filepath, collection_name="foreshadowing_collection")
                    if vectorstore:
                        logging.info("成功初始化新的向量库")
                    else:
                        logging.warning("初始化向量库失败")
                
                if vectorstore and foreshadowing_str:
                    try:
                        logging.info("开始调用伏笔内容处理和向量化函数...")
                        # 详细记录伏笔信息
                        logging.info(f"章节编号：第{chap_num}章《{chapter_title}》")
                        logging.info(f"本章涉及伏笔编号列表：\n{foreshadowing_str}")
                        
                        # 构建章节信息字典，包含必要的伏笔信息
                        chapter_info = {
                            'novel_number': chap_num,
                            'chapter_title': chapter_title,
                            'foreshadowing': foreshadowing_str
                        }
                        
                        # 使用异步方式处理和向量化伏笔内容
                        import threading
                        
                        # 创建一个事件对象，用于等待异步操作完成
                        foreshadowing_done = threading.Event()
                        foreshadowing_result = None
                        
                        # 定义异步处理函数
                        def process_foreshadowing_async():
                            try:
                                # 调用伏笔处理函数，传入正确的参数，包括嵌入适配器和LLM适配器
                                process_and_vectorize_foreshadowing(
                                    chapter_text=chapter_text,
                                    chapter_info=chapter_info,
                                    filepath=filepath,
                                    embedding_adapter=embedding_adapter,
                                    llm_adapter=llm_adapter
                                )
                                foreshadowing_done.set()
                            except Exception as e:
                                logging.error(f"处理和向量化伏笔内容时出错: {e}")
                                foreshadowing_done.set()
                        
                        # 启动异步处理线程
                        threading.Thread(target=process_foreshadowing_async, daemon=True).start()
                        
                        # 等待异步操作完成，但不阻塞UI线程
                        # 移除读秒逻辑，直接等待完成
                        foreshadowing_done.wait()
                        
                        if not foreshadowing_done.is_set():
                            self.safe_log("    ⚠️ 处理和向量化伏笔内容超时，将在后台继续处理。")
                        else:
                            self.safe_log("    ✅ 伏笔内容处理和向量化完成。")
                    except Exception as e:
                        self.safe_log(f"    ⚠️ 处理和向量化伏笔内容时出错: {e}")
                elif not embedding_adapter:
                    self.safe_log("    ℹ️ 未配置Embedding适配器，跳过伏笔向量化。")
                elif not vectorstore:
                    self.safe_log("    ℹ️ 向量库初始化失败，跳过伏笔向量化。")
                else:
                    self.safe_log("    ℹ️ 本章无伏笔信息，跳过伏笔向量化。")

                # 角色状态向量化步骤已完全移除

                # --- 步骤 5: 提取剧情要点 --- 
                self.safe_log("  [4/4] 正在提取剧情要点...")
                
                # 获取下一章大纲
                next_chapter_outline = ""
                try:
                    directory_file = os.path.join(filepath, "章节目录.txt")
                    if os.path.exists(directory_file):
                        directory_content = read_file(directory_file)
                        if directory_content:
                            next_chapter_pattern = rf"第{chap_num + 1}章.*?(?=第{chap_num + 2}章|$)"
                            next_chapter_match = re.search(next_chapter_pattern, directory_content, re.DOTALL)
                            if next_chapter_match:
                                next_chapter_outline = next_chapter_match.group(0).strip()
                                self.safe_log(f"已找到下一章大纲: {next_chapter_outline[:100]}...")
                            else:
                                self.safe_log(f"未找到第{chap_num + 1}章大纲内容")
                except Exception as e:
                    self.safe_log(f"获取下一章大纲时出错: {str(e)}")
                    next_chapter_outline = ""
                
                plot_points_prompt = plot_points_extraction_prompt.format(
                    novel_number=chap_num,
                    chapter_title=chapter_title,
                    chapter_text=chapter_text,
                    next_chapter_outline=next_chapter_outline  # 添加下一章大纲
                )
                # 输出提示词到终端
                logging.info("剧情要点提取提示词:\n" + plot_points_prompt)
                
                # 使用异步方式调用LLM提取剧情要点
                from novel_generator.common import invoke_llm_async
                import threading
                
                # 创建一个事件对象，用于等待异步操作完成
                plot_points_done = threading.Event()
                plot_points = None
                
                # 定义回调函数
                def on_plot_points_done(result, error=None):
                    nonlocal plot_points
                    if error:
                        logging.error(f"提取剧情要点时出错: {error}")
                        plot_points = ""
                    else:
                        plot_points = result
                    plot_points_done.set()
                
                # 异步调用LLM
                invoke_llm_async(llm_adapter, plot_points_prompt, on_plot_points_done)
                
                # 等待异步操作完成，但不阻塞UI线程
                # 移除读秒逻辑，直接等待完成
                plot_points_done.wait()
                
                if not plot_points_done.is_set():
                    self.safe_log("    ⚠️ 提取剧情要点超时，将在后台继续处理。")
                    # 继续执行后续步骤
                elif plot_points:
                    # 检查文件是否存在，如果不存在则创建
                    if not os.path.exists(plot_points_file):
                        with open(plot_points_file, 'w', encoding='utf-8') as f:
                            pass
                    
                    # 读取现有内容
                    existing_content = ""
                    if os.path.exists(plot_points_file):
                        with open(plot_points_file, 'r', encoding='utf-8') as f:
                            existing_content = f.read()
                    
                    # 构建章节标题标记，用于查找和替换
                    chapter_header = f"## 第 {chap_num} 章 《{chapter_title}》"
                    chapter_pattern = re.compile(f"\n\n## 第 {chap_num} 章.*?(?=\n\n## 第|$)", re.DOTALL)
                    
                    # 检查是否已存在该章节的剧情要点
                    if chapter_pattern.search(existing_content):
                        # 删除已存在的该章节剧情要点
                        existing_content = chapter_pattern.sub("", existing_content)
                        self.safe_log(f"    🔄 已删除第 {chap_num} 章现有剧情要点。")
                    
                    # 添加新的剧情要点
                    new_content = existing_content.rstrip() + f"\n\n{chapter_header}\n{plot_points}"
                    
                    # 写入文件
                    with open(plot_points_file, 'w', encoding="utf-8") as f:
                        f.write(new_content)
                    
                    self.safe_log("    ✅ 剧情要点已提取并更新到文件。")
                else:
                    self.safe_log("    ⚠️ 提取剧情要点失败。")

                self.safe_log(f"✅ 第 {chap_num} 章定稿流程全部完成！")
                # 定稿成功后用编辑框内容覆盖章节txt文件
                if hasattr(self, "chapter_result"):
                    with open(chapter_file, "w", encoding="utf-8") as f:
                        f.write(self.chapter_result.get("0.0", "end").strip())

                # 定稿成功后，自动增加章节号并保存配置
                next_chapter = int(chap_num) + 1
                self.chapter_num_var.set(str(next_chapter))
                
                # 保存更新后的章节号到配置文件
                try:
                    config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
                    if os.path.exists(config_file):
                        with open(config_file, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                        
                        # 更新章节号
                        if 'novel_params' not in config:
                            config['novel_params'] = {}
                        config['novel_params']['current_chapter'] = next_chapter
                        
                        # 保存配置
                        with open(config_file, 'w', encoding='utf-8') as f:
                            json.dump(config, f, ensure_ascii=False, indent=4)
                        
                        logging.info(f"章节号已更新为：{next_chapter}，配置已保存")
                            
                except Exception as e:
                    logging.error(f"保存配置文件时出错: {str(e)}")

            except ImportError as e:
                self.handle_exception(f"定稿流程中导入错误: {e}. 请确保所有依赖项和函数已正确实现。")
            except Exception as e:
                self.handle_exception(f"执行定稿流程时出错: {str(e)}")
            finally:
                self.enable_button_safe(self.btn_finalize_chapter)

        threading.Thread(target=task, daemon=True).start()

    # 直接开始执行流程
    execute_finalization_steps()

def extract_character_ids_from_chapters(filepath, extract_chapters, weight_threshold):
    """从前N章中提取权重大于等于阈值的角色ID"""
    character_ids = []
    try:
        # 检查角色数据库.txt是否存在
        character_db_file = os.path.join(filepath, "角色数据库.txt")
        if os.path.exists(character_db_file):
            # 读取角色数据库内容
            character_db_content = read_file(character_db_file)
            
            # 从章节目录中获取前N章信息
            directory_file = os.path.join(filepath, "章节目录.txt")
            if os.path.exists(directory_file):
                directory_content = read_file(directory_file)
                
                # 提取前N章的章节内容
                try:
                    from novel_generator.chapter_blueprint import get_latest_chapters
                    chapters_content = get_latest_chapters(directory_content, extract_chapters)
                except ImportError:
                    # 如果导入失败，记录错误但继续处理
                    logging.error("无法导入get_latest_chapters函数，将使用全部章节内容")
                    chapters_content = directory_content
                
                # 修改：使用更精确的正则表达式匹配角色表格行
                id_pattern = re.compile(r'\|\s*(ID\d+)\s*\|\s*([^|]+?)\s*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|', re.MULTILINE)
                matches = id_pattern.finditer(character_db_content)
                
                found_characters = 0
                for match in matches:
                    char_id = match.group(1)
                    char_name = match.group(2).strip()
                    try:
                        char_weight = int(match.group(3).strip())
                        logging.info(f"检查角色: {char_name} (ID: {char_id}, 权重: {char_weight})")
                        
                        # 检查权重是否符合要求
                        if char_weight >= weight_threshold:
                            found_characters += 1
                            logging.info(f"发现符合条件的角色: {char_name} (ID: {char_id}, 权重: {char_weight})")
                            
                            # 修改：将所有符合权重条件的角色都添加到列表中
                            # 不再检查角色是否在前N章中出现，因为这个检查不准确
                            # 根据用户需求，只要角色权重符合条件，就应该被检索出来
                            character_ids.append(char_id)
                            logging.info(f"✅ 添加符合条件的角色: {char_name} (ID: {char_id}, 权重: {char_weight})")
                        else:
                            logging.debug(f"跳过低权重角色: {char_name} (权重: {char_weight} < {weight_threshold})")
                            
                    except ValueError:
                        logging.warning(f"角色 {char_name} 的权重值无效，将跳过")
                        continue
                
                logging.info(f"完成角色检查，找到 {found_characters} 个符合权重条件的角色")
                
    except Exception as e:
        logging.error(f"提取角色ID时出错: {str(e)}")
        logging.debug(traceback.format_exc())
    
    return character_ids

def retrieve_character_states(filepath, character_ids):
    """从向量库中检索角色状态"""
    character_states = []
    try:
        # 创建嵌入适配器
        embedding_adapter = create_embedding_adapter(
            interface_format="openai",  # 默认使用openai格式
            api_key="",
            base_url="",
            model_name="text-embedding-ada-002"
        )
        
        # 加载角色状态向量库
        from novel_generator.vectorstore_utils import load_vector_store
        vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
        
        if vectorstore:
            for char_id in character_ids:
                try:
                    # 使用角色ID查询向量库
                    retrieved_docs = vectorstore.get(where={"character_id": char_id}, include=["metadatas", "documents"])
                    
                    if retrieved_docs and retrieved_docs.get('ids'):
                        # 找到最新的角色状态
                        latest_chapter = -1
                        latest_doc = ""
                        
                        for i, doc_id in enumerate(retrieved_docs['ids']):
                            metadata = retrieved_docs['metadatas'][i]
                            # 确认这是角色状态类型的文档
                            if metadata.get('type') == "character_state":
                                doc_chapter = metadata.get('chapter', -1)
                                
                                if doc_chapter > latest_chapter:
                                    latest_chapter = doc_chapter
                                    latest_doc = retrieved_docs['documents'][i]
                        
                        if latest_doc:
                            character_states.append(latest_doc)
                            logging.info(f"从向量库中检索到角色 {char_id} 的状态")
                except Exception as e:
                    logging.error(f"检索角色 {char_id} 的状态时出错: {str(e)}")
    except Exception as e:
        logging.error(f"检索角色状态时出错: {str(e)}")
    
    return character_states

def generate_novel_architecture_ui(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        confirm = messagebox.askyesno("确认", "确定要生成小说架构吗？")
        if not confirm:
            self.enable_button_safe(self.btn_generate_architecture)
            return

        self.disable_button_safe(self.btn_generate_architecture)
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)

            topic = self.topic_text.get("0.0", "end").strip()
            genre = self.genre_var.get().strip()
            num_chapters = self.safe_get_int(self.num_chapters_var, 10)
            word_number = self.safe_get_int(self.word_number_var, 3000)
            # 获取内容指导
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            self.safe_log("开始生成小说架构...")
            try:
                Novel_architecture_generate(
                    interface_format=interface_format,
                    api_key=api_key,
                    base_url=base_url,
                    llm_model=model_name,
                    topic=topic,
                    genre=genre,
                    number_of_chapters=num_chapters,
                    word_number=word_number,
                    filepath=filepath,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_val,
                    user_guidance=user_guidance  # 添加内容指导参数
                )
                self.safe_log("✅ 小说架构生成完成。请在 'Novel Architecture' 标签页查看或编辑。")
            except PermissionError as e:
                error_msg = f"文件访问权限错误: {str(e)}\n请关闭所有可能正在使用相关文件的应用程序，然后重试。\n如果问题仍然存在，请尝试重启应用程序或计算机。"
                self.safe_log(f"❌ {error_msg}")
                raise Exception(error_msg)
        except Exception:
            self.handle_exception("生成小说架构时出错")
        finally:
            self.enable_button_safe(self.btn_generate_architecture)
    threading.Thread(target=task, daemon=True).start()

def generate_chapter_blueprint_ui(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return
        
    def show_dialog():
        try:
            # 先扫描现有章节目录并更新伏笔状态
            directory_file = os.path.join(filepath, "章节目录.txt")
            if (os.path.exists(directory_file)):
                # 读取现有章节目录内容
                content = read_file(directory_file)
                if content.strip():
                    # 初始化/更新伏笔状态
                    try:
                        self.safe_log("正在扫描现有章节目录，更新伏笔状态...")
                        foreshadow_state = update_foreshadowing_state(content, filepath, force_rescan=True)
                        if foreshadow_state:
                            foreshadow_file = os.path.join(filepath, "伏笔状态.txt")
                            clear_file_content(foreshadow_file)
                            save_string_to_txt(foreshadow_state, foreshadow_file)
                            self.safe_log("✅ 已完成伏笔状态重新初始化")
                        else:
                            self.safe_log("❌ 伏笔状态更新失败：未生成有效状态")
                            return
                    except Exception as e:
                        self.safe_log(f"❌ 伏笔状态初始化失败: {str(e)}")
                        return

            from novel_generator.chapter_blueprint import get_volume_progress, analyze_volume_range
            current_vol, last_chapter, start_chap, end_chap, is_last, is_complete = get_volume_progress(filepath)
            volumes = analyze_volume_range(filepath)
            if not volumes:
                messagebox.showwarning("警告", "请先生成分卷大纲")
                return
            volume_count = self.safe_get_int(self.volume_count_var, 3)
            _, existing_chapters, _ = analyze_directory_status(filepath)
            current_vol_info = next((v for v in volumes if v['volume'] == current_vol), None)
            if not current_vol_info:
                messagebox.showerror("错误", f"无法获取第{current_vol}卷信息")
                return

            dialog = ctk.CTkToplevel(self.master)
            dialog.title("章节目录生成")
            dialog.geometry("480x350")
            dialog.transient(self.master)
            dialog.grab_set()

            # 章节数量输入
            entry_frame = ctk.CTkFrame(dialog)
            entry_frame.pack(pady=(20, 0))
            ctk.CTkLabel(entry_frame, text="准备生成章节数量：", font=("Microsoft YaHei", 12)).pack(side="left")
            chapter_count_var = ctk.StringVar(value="20")  # UI输入框的默认值
            chapter_count_entry = ctk.CTkEntry(entry_frame, textvariable=chapter_count_var, width=60)
            chapter_count_entry.pack(side="left", padx=(0, 10))

            # 生成进度提示
            if last_chapter == 0:
                progress_text = "当前尚未生成任何章节。"
            else:
                progress_text = f"当前已生成至第{last_chapter}章。"
            ctk.CTkLabel(dialog, text=progress_text, font=("Microsoft YaHei", 12), text_color="#888888").pack(pady=(5, 0))

            # 状态判断
            if last_chapter == 0 or (is_complete and is_last):
                # 新开始或刚好生成完某卷
                info_text = "准备生成章节目录"
                btn1_text = "生成所填数量章节目录"
                btn2_text = f"生成第{current_vol if last_chapter == 0 else current_vol + 1}卷章节目录"
                btn2_vol = current_vol if last_chapter == 0 else current_vol + 1
                btn2_mode = "volume"
            elif not is_complete:
                # 已有章节未满一卷
                info_text = f"当前进度：第{current_vol}卷 第{last_chapter}章（本卷共{current_vol_info['end'] - current_vol_info['start'] + 1}章）"
                btn1_text = "生成所填数量章节目录"
                btn2_text = f"继续生成第{current_vol}卷章节目录"
                btn2_vol = current_vol
                btn2_mode = "volume"
            else:
                info_text = f"当前进度：第{current_vol}卷 第{last_chapter}章"
                btn1_text = "生成所填数量章节目录"
                btn2_text = f"生成第{current_vol + 1}卷章节目录"
                btn2_vol = current_vol + 1
                btn2_mode = "volume"

            ctk.CTkLabel(dialog, text=info_text, font=("Microsoft YaHei", 12)).pack(pady=(10, 0))
            
            # 添加角色状态提取相关UI
            char_frame = ctk.CTkFrame(dialog)
            char_frame.pack(pady=(10, 0))
            
            ctk.CTkLabel(
                char_frame,
                text="提取前",
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=5)
            
            # 默认提取前10章
            chapter_extract_var = ctk.StringVar(value="10")
            chapter_extract_entry = ctk.CTkEntry(
                char_frame,
                textvariable=chapter_extract_var,
                width=40,
                font=("Microsoft YaHei", 12)
            )
            chapter_extract_entry.pack(side="left", padx=5)
            
            ctk.CTkLabel(
                char_frame,
                text="章有出场，且权重大于",
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=5)
            
            # 默认权重为80
            weight_var = ctk.StringVar(value="80")
            weight_entry = ctk.CTkEntry(
                char_frame,
                textvariable=weight_var,
                width=40,
                font=("Microsoft YaHei", 12)
            )
            weight_entry.pack(side="left", padx=5)
            
            ctk.CTkLabel(
                char_frame,
                text="的角色状态",
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=5)

            btn_frame = ctk.CTkFrame(dialog)
            btn_frame.pack(pady=20)

            def handle_increment():
                dialog.destroy()
                self.disable_button_safe(self.btn_generate_directory)
                def generation_thread():
                    try:
                        # 从 chapter_count_var 获取用户输入的章节数
                        add_chapter_count = self.safe_get_int(chapter_count_var, 20)  # 从UI获取用户输入值
                        interface_format = self.interface_format_var.get().strip()
                        api_key = self.api_key_var.get().strip()
                        base_url = self.base_url_var.get().strip()
                        model_name = self.model_name_var.get().strip()
                        temperature = self.temperature_var.get()
                        max_tokens = self.safe_get_int(self.max_tokens_var, 2048)
                        timeout_val = self.safe_get_int(self.timeout_var, 600)
                        user_guidance = self.user_guide_text.get("0.0", "end").strip()
                        
                        # 获取角色提取相关参数
                        extract_chapters = self.safe_get_int(chapter_extract_var, 10)
                        weight_threshold = self.safe_get_int(weight_var, 80)
                        
                        self.safe_log(f"开始生成{add_chapter_count}章章节目录...")
                        
                        # 提取角色状态
                        main_character = ""
                        try:
                            # 检查角色数据库.txt是否存在
                            character_db_file = os.path.join(filepath, "角色数据库.txt")
                            if os.path.exists(character_db_file):
                                self.safe_log(f"正在从角色数据库提取前{extract_chapters}章有出场且权重≥{weight_threshold}的角色...")
                                
                                # 读取角色数据库内容
                                character_db_content = read_file(character_db_file)
                                
                                # 从章节目录中获取前N章信息
                                directory_file = os.path.join(filepath, "章节目录.txt")
                                if os.path.exists(directory_file):
                                    directory_content = read_file(directory_file)
                                    
                                    # 提取前N章的章节内容
                                    from novel_generator.chapter_blueprint import get_latest_chapters
                                    chapters_content = get_latest_chapters(directory_content, extract_chapters)
                                    
                                    # 从章节内容中提取角色ID
                                    character_ids = []
                                    # 匹配角色索引表中的行，提取ID和权重
                                    id_pattern = re.compile(r'\| (ID\d+) \| ([^|]+) \|.*\| (\d+) \|', re.MULTILINE)
                                    for match in id_pattern.finditer(character_db_content):
                                        char_id = match.group(1)
                                        char_name = match.group(2).strip()
                                        char_weight = int(match.group(3).strip())
                                        
                                        # 检查权重是否符合要求
                                        if char_weight >= weight_threshold:
                                            # 移除检查角色是否在前N章中出现的条件
                                            # 只要角色权重符合条件，就将其添加到列表中
                                            character_ids.append(char_id)
                                            self.safe_log(f"找到符合条件的角色: {char_name} (ID: {char_id}, 权重: {char_weight})")
                                    
                                    # 如果找到了符合条件的角色ID，从向量库中检索角色信息
                                    if character_ids:
                                        # 创建LLM适配器和嵌入适配器
                                        llm_adapter = create_llm_adapter(
                                            interface_format=interface_format,
                                            api_key=api_key,
                                            base_url=base_url,
                                            model_name=model_name,
                                            temperature=temperature,
                                            max_tokens=max_tokens,
                                            timeout=timeout_val
                                        )
                                        
                                        # 创建嵌入适配器
                                        embedding_adapter = create_embedding_adapter(
                                            interface_format=self.embedding_interface_format_var.get(),
                                            api_key=self.embedding_api_key_var.get(),
                                            base_url=self.embedding_api_key_var.get(),
                                            model_name=self.embedding_model_name_var.get()
                                        )
                                        
                                        # 加载角色状态向量库
                                        from novel_generator.vectorstore_utils import load_vector_store
                                        vectorstore = load_vector_store(embedding_adapter, filepath, "character_state_collection")
                                        
                                        if vectorstore:
                                            character_states = []
                                            for char_id in character_ids:
                                                try:
                                                    # 使用角色ID查询向量库
                                                    retrieved_docs = vectorstore.get(where={"character_id": char_id}, include=["metadatas", "documents"])
                                                    
                                                    if retrieved_docs and retrieved_docs.get('ids'):
                                                        # 找到最新的角色状态
                                                        latest_chapter = -1
                                                        latest_doc = ""
                                                        
                                                        for i, doc_id in enumerate(retrieved_docs['ids']):
                                                            metadata = retrieved_docs['metadatas'][i]
                                                            # 确认这是角色状态类型的文档
                                                            if metadata.get('type') == "character_state":
                                                                doc_chapter = metadata.get('chapter', -1)
                                                                
                                                                if doc_chapter > latest_chapter:
                                                                    latest_chapter = doc_chapter
                                                                    latest_doc = retrieved_docs['documents'][i]
                                                        
                                                        if latest_doc:
                                                            character_states.append(latest_doc)
                                                            self.safe_log(f"从向量库中检索到角色 {char_id} 的状态")
                                                except Exception as e:
                                                    self.safe_log(f"检索角色 {char_id} 的状态时出错: {str(e)}")
                                            
                                            # 将检索到的角色状态组合成字符串
                                            if character_states:
                                                main_character = "\n\n".join(character_states)
                                                self.safe_log(f"成功检索到 {len(character_states)} 个符合条件的角色状态")
                                            else:
                                                self.safe_log("未找到符合条件的角色状态")
                                        else:
                                            self.safe_log("角色状态向量库不存在或加载失败")
                                    else:
                                        self.safe_log(f"未找到前{extract_chapters}章中权重≥{weight_threshold}的角色")
                                else:
                                    self.safe_log("章节目录文件不存在，无法提取角色信息")
                            else:
                                self.safe_log("角色数据库.txt文件不存在，无法提取角色信息")
                        except Exception as e:
                            self.safe_log(f"提取角色状态时出错: {str(e)}")
                        
                        try:
                            # 先分析章节目录，获取已有最大章节号
                            last_chapter_before, existing_chapters, _ = analyze_directory_status(filepath)
                            # 生成新的章节范围
                            start_chapter = last_chapter_before + 1 if last_chapter_before > 0 else 1
                            end_chapter = start_chapter + add_chapter_count - 1  # 确保使用输入的数量
                            
                            # 计算当前卷号
                            volumes = analyze_volume_range(filepath)
                            if volumes:
                                current_vol = find_current_volume(start_chapter, volumes)[0]
                            else:
                                current_vol = 1
                            
                            # 修改这里：使用用户输入的章节数量
                            from novel_generator.chapter_blueprint import Chapter_blueprint_generate
                            result = Chapter_blueprint_generate(
                                interface_format=interface_format,
                                api_key=api_key,
                                base_url=base_url,
                                llm_model=model_name,
                                filepath=filepath,
                                number_of_chapters=add_chapter_count,  # 这里已经用用户输入的章节数
                                temperature=temperature,
                                max_tokens=max_tokens,
                                timeout=timeout_val,
                                user_guidance=user_guidance,
                                # 修正：当按数量生成时，不指定卷号，且只生成单次（即用户指定的数量）
                                start_from_volume=current_vol if btn2_mode == "volume" else None,
                                generate_single=True, # 无论按卷还是按数量，都只生成一次调用所需的章节
                                save_interval=add_chapter_count,
                                main_character=main_character  # 添加主要角色信息
                            )

                            # 生成后获取最新章节号
                            last_chapter_after, _, _ = analyze_directory_status(filepath)
                            if result:
                                self.safe_log("✅ 章节目录生成完成")
                            else:
                                self.safe_log("❌ 章节目录生成失败")
                            # 判断是否已生成所需数量，生成完所填数量后重新弹出生成窗口
                            if last_chapter_after - last_chapter_before >= add_chapter_count:
                                self.safe_log("已生成指定数量的章节目录，重新弹出生成选项窗口。")
                                # 直接调用 show_dialog 重新弹出选项窗口
                                self.master.after(0, show_dialog)
                        except Exception as e:
                            err_str = str(e).lower()
                            self.safe_log(f"❌ 章节目录生成时发生错误: {str(e)}")
                            if "timeout" in err_str or "request timed out" in err_str:
                                self.safe_log("⚠️ LLM接口调用超时，请尝试减少生成章节数或检查网络/接口状态。")
                            if "connection error" in err_str:
                                self.safe_log("⚠️ LLM接口连接失败，请检查网络或接口地址。")
                                messagebox.showerror("连接错误", "LLM接口连接失败，请检查网络或接口地址。", parent=self.master)
                        finally:
                            self.enable_button_safe(self.btn_generate_directory)
                    finally:
                        self.enable_button_safe(self.btn_generate_directory)
                threading.Thread(target=generation_thread, daemon=True).start()

            def handle_volume():
                dialog.destroy()
                self.disable_button_safe(self.btn_generate_directory)
                def generation_thread():
                    try:
                        add_chapter_count = self.safe_get_int(chapter_count_var, 5)
                        interface_format = self.interface_format_var.get().strip()
                        api_key = self.api_key_var.get().strip()
                        base_url = self.base_url_var.get().strip()
                        model_name = self.model_name_var.get().strip()
                        temperature = self.temperature_var.get()
                        max_tokens = self.max_tokens_var.get()
                        timeout_val = self.safe_get_int(self.timeout_var, 600)
                        user_guidance = self.user_guide_text.get("0.0", "end").strip()
                        # 获取角色提取相关参数
                        extract_chapters = self.safe_get_int(chapter_extract_var, 10)
                        weight_threshold = self.safe_get_int(weight_var, 80)
                        self.safe_log("开始整卷生成章节目录...")
                        from novel_generator.chapter_blueprint import Chapter_blueprint_generate
                        try:
                            # 提取角色状态信息
                            main_character = ""
                            try:
                                # 获取角色提取参数
                                extract_chapters = self.safe_get_int(chapter_extract_var, 5)
                                weight_threshold = self.safe_get_int(weight_var, 80)
                                
                                # 提取角色状态
                                if os.path.exists(os.path.join(filepath, "角色数据库.txt")):
                                    if os.path.exists(os.path.join(filepath, "章节目录.txt")):
                                        # 提取角色ID
                                        character_ids = extract_character_ids_from_chapters(
                                            filepath, extract_chapters, weight_threshold
                                        )
                                        if character_ids:
                                            self.safe_log(f"从前{extract_chapters}章中提取到{len(character_ids)}个角色ID")
                                            # 从向量库检索角色状态
                                            character_states = retrieve_character_states(filepath, character_ids)
                                            # 将检索到的角色状态组合成字符串
                                            if character_states:
                                                main_character = "\n\n".join(character_states)
                                                self.safe_log(f"成功检索到 {len(character_states)} 个符合条件的角色状态")
                                            else:
                                                self.safe_log("未找到符合条件的角色状态")
                                        else:
                                            self.safe_log(f"未找到前{extract_chapters}章中权重≥{weight_threshold}的角色")
                                    else:
                                        self.safe_log("章节目录文件不存在，无法提取角色信息")
                                else:
                                    self.safe_log("角色数据库.txt文件不存在，无法提取角色信息")
                            except Exception as e:
                                self.safe_log(f"提取角色状态时出错: {str(e)}")
                            
                            result = Chapter_blueprint_generate(
                                interface_format=interface_format,
                                api_key=api_key,
                                base_url=base_url,
                                llm_model=model_name,
                                number_of_chapters=add_chapter_count,
                                filepath=filepath,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                timeout=timeout_val,
                                user_guidance=user_guidance,
                                start_from_volume=btn2_vol,
                                generate_single=True,
                                main_character=main_character
                            )
                            if result:
                                self.safe_log("✅ 章节目录生成完成")
                            else:
                                self.safe_log("❌ 章节目录生成失败")
                        except Exception as e:
                            err_str = str(e).lower()
                            self.safe_log(f"❌ 章节目录生成时发生错误: {str(e)}")
                            if "timeout" in err_str or "request timed out" in err_str:
                                self.safe_log("⚠️ LLM接口调用超时，请尝试减少生成章节数或检查网络/接口状态。")
                            if "connection error" in err_str:
                                self.safe_log("⚠️ LLM接口连接失败，请检查网络或接口地址。")
                            if "connection error" in err_str:
                                messagebox.showerror("连接错误", "LLM接口连接失败，请检查网络或接口地址。", parent=self.master)
                        finally:
                            self.enable_button_safe(self.btn_generate_directory)
                    finally:
                        self.enable_button_safe(self.btn_generate_directory)
                threading.Thread(target=generation_thread, daemon=True).start()

            ctk.CTkButton(
                btn_frame,
                text=btn1_text,
                command=handle_increment,
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=10)

            ctk.CTkButton(
                btn_frame,
                text="退出",
                command=lambda: dialog.destroy(),
                font=("Microsoft YaHei", 12)
            ).pack(side="left", padx=10)

            # 推荐提示
            tips = (
                "提示：\n"
                "使用 DeepSeek，推荐每次生成20章以下；\n"
                "使用 Claude 或 Gemini，推荐每次生成40章以下。"
            )
            ctk.CTkLabel(dialog, text=tips, font=("Microsoft YaHei", 11), text_color="#888888", justify="left").pack(pady=(5, 0))

        except Exception as e:
            self.safe_log(f"❌ 显示章节目录生成对话框时出错: {str(e)}")
            self.enable_button_safe(self.btn_generate_directory)

    threading.Thread(target=show_dialog, daemon=True).start()

def generate_blueprint_chapters(self, start_from_volume: int, generate_single: bool):
    """执行章节目录生成任务"""
    filepath = self.filepath_var.get().strip()
    self.disable_button_safe(self.btn_generate_directory)
    
    def task():
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            self.safe_log(f"开始生成{'当前卷' if generate_single else '所有卷'}章节目录...")
            result = Chapter_blueprint_generate(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                llm_model=model_name,
                number_of_chapters=number_of_chapters,
                filepath=filepath,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_val,
                user_guidance=user_guidance,
                start_from_volume=start_from_volume,
                generate_single=generate_single
            )
            
            if result:
                self.safe_log("✅ 章节目录生成完成")
                # 检查是否需要继续生成
                last_chapter, current_vol, is_volume_end = analyze_chapter_status(filepath)
                volume_count = self.safe_get_int(self.volume_count_var, 3)
                
                if current_vol < volume_count and (is_volume_end or not generate_single):
                    self.master.after(1000, lambda: self.show_blueprint_dialog())
            else:
                self.safe_log("❌ 章节目录生成失败")

        except Exception as e:
            self.safe_log(f"❌ 生成章节目录时发生错误: {str(e)}")
        finally:
            self.enable_button_safe(self.btn_generate_directory)

    threading.Thread(target=task, daemon=True).start()

def generate_chapter_draft_ui(self):
    logging.info("--- generate_chapter_draft_ui function entered ---")
    # 确保日志级别设置为 INFO，以显示详细的日志信息
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    
    filepath = self.filepath_var.get().strip()
    if not filepath:
        self.enable_button_safe(self.btn_generate_chapter)
        messagebox.showwarning("警告", "请先选择保存文件路径")
        root_logger.setLevel(original_level)  # 恢复原始日志级别
        return
    self.disable_button_safe(self.btn_generate_chapter)
    confirm = messagebox.askyesno("确认", "确定要生成章节草稿吗？")
    if not confirm:
        logging.info("--- User cancelled chapter draft generation ---")
        self.enable_button_safe(self.btn_generate_chapter)
        self.safe_log("❌ 用户取消了草稿生成请求。")
        root_logger.setLevel(original_level)  # 恢复原始日志级别
        return
    
    # 创建提示词编辑对话框
    def show_prompt_editor(prompt_text):
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("编辑章节提示词")
        dialog.geometry("800x600")
        dialog.transient(self.master)  # 使弹窗相对于主窗口
        dialog.grab_set()  # 使弹窗成为模态窗口，阻止与主窗口交互

        # 定义取消操作
        def on_cancel():
            dialog.destroy()
            self.enable_button_safe(self.btn_generate_chapter) # 重新启用生成按钮
            self.safe_log("❌ 用户取消了草稿生成请求。")

        # 将窗口关闭按钮也绑定到 on_cancel
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        
        textbox = ctk.CTkTextbox(dialog, wrap="word")
        textbox.pack(fill="both", expand=True, padx=10, pady=10)
        textbox.insert("0.0", prompt_text)
        
        def on_confirm():
            modified_prompt = textbox.get("0.0", "end")
            dialog.destroy()
            generate_draft(modified_prompt)
            
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=10)

        ctk.CTkButton(btn_frame, text="确认生成", command=on_confirm).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=5)

        word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 12))
        word_count_label.pack(side="right", padx=10)

        def update_word_count(event=None):
            text = textbox.get("1.0", "end-1c")
            words = len(text)
            word_count_label.configure(text=f"字数: {words}")

        textbox.bind("<KeyRelease>", update_word_count)
        update_word_count() # Initial count
    
    # 生成草稿
    def generate_draft(prompt_text):
        def task():
            try:
                chap_num = self.safe_get_int(self.chapter_num_var, 1)
                self.safe_log(f"开始生成章节草稿...")
                
                self.safe_log(f"正在为第 {chap_num} 章生成草稿，将使用用户编辑后的提示词...")
                # 使用用户编辑后的提示词
                from novel_generator.common import invoke_with_cleaning
                from llm_adapters import create_llm_adapter
                self.safe_log("创建LLM适配器并使用用户编辑后的提示词生成章节草稿...")
                
                # 创建LLM适配器
                llm_adapter = create_llm_adapter(
                    interface_format=self.interface_format_var.get(),
                    base_url=self.base_url_var.get(),
                    model_name=self.model_name_var.get(),
                    api_key=self.api_key_var.get(),
                    temperature=self.temperature_var.get(),
                    max_tokens=self.max_tokens_var.get(),
                    timeout=self.timeout_var.get()
                )
                
                # 记录最终使用的提示词到日志
                self.safe_log("\n==================================================\n发送到 LLM 的提示词:\n--------------------------------------------------\n\n" + prompt_text + "\n--------------------------------------------------")
                
                # 使用用户编辑后的提示词生成章节草稿
                draft_text = invoke_with_cleaning(llm_adapter, prompt_text)
                self.safe_log("章节草稿生成完成")
                
                # 保存章节草稿到文件
                os.makedirs(os.path.join(filepath, "chapters"), exist_ok=True)
                chapter_file = os.path.join(filepath, "chapters", f"chapter_{chap_num}.txt")
                from utils import clear_file_content, save_string_to_txt
                clear_file_content(chapter_file)
                save_string_to_txt(draft_text, chapter_file)
                self.safe_log(f"章节草稿已保存到 {chapter_file}")
                
                if draft_text:
                    self.safe_log(f"✅ 第{chap_num}章草稿生成完成。请在左侧查看或编辑。")
                    # 保存章节草稿到文件
                    try:
                        chapter_filename = f"chapter_{chap_num}.txt"
                        chapter_dir = os.path.join(filepath, "chapters")
                        os.makedirs(chapter_dir, exist_ok=True)
                        chapter_file_path = os.path.join(chapter_dir, chapter_filename)
                        save_string_to_txt(draft_text, chapter_file_path)
                        self.safe_log(f"✅ 第{chap_num}章草稿已保存到 {chapter_file_path}")
                    except Exception as e_save:
                        self.handle_exception(f"保存第{chap_num}章草稿时出错: {str(e_save)}")
                    self.master.after(0, lambda: self.show_chapter_in_textbox(draft_text))
                else:
                    self.safe_log("⚠️ 本章草稿生成失败或无内容。")
            except Exception as e:
                self.handle_exception(f"生成章节草稿时出错: {str(e)}")
            finally:
                # 恢复原始日志级别
                root_logger.setLevel(original_level)
                self.enable_button_safe(self.btn_generate_chapter)
        
        threading.Thread(target=task, daemon=True).start()
    
    # 获取初始提示词
    def get_initial_prompt():
        try:
            chap_num = self.safe_get_int(self.chapter_num_var, 1)
            from novel_generator.chapter import build_chapter_prompt
            from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
            
            directory_content = ""
            directory_file = os.path.join(filepath, "章节目录.txt")
            if os.path.exists(directory_file):
                directory_content = read_file(directory_file)
            
            chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)

            # 获取小说设定
            novel_setting_file = os.path.join(filepath, "小说设定.txt")
            novel_setting = read_file(novel_setting_file) if os.path.exists(novel_setting_file) else ""

            # 获取前情摘要
            global_summary_file = os.path.join(filepath, "前情摘要.txt")
            global_summary = read_file(global_summary_file) if os.path.exists(global_summary_file) else ""
            if not global_summary:
                self.safe_log(f"警告: 未找到 前情摘要.txt 文件或文件为空，路径: {global_summary_file}")

            # 获取角色状态
            character_state_file = os.path.join(filepath, "角色状态.txt")
            character_state = read_file(character_state_file) if os.path.exists(character_state_file) else ""
            if not character_state:
                self.safe_log(f"警告: 未找到 角色状态.txt 文件或文件为空，路径: {character_state_file}")

            # 获取分卷大纲
            volume_outline = ""
            volume_content = ""
            actual_volume_number_for_prompt = 1 # Default to 1
            volume_file = os.path.join(filepath, "分卷大纲.txt")
            if os.path.exists(volume_file):
                from novel_generator.volume import extract_volume_outline
                volume_content = read_file(volume_file)
                # Helper function to find volume number from outline content
                def find_actual_volume_number(outline_content: str, current_chapter_num: int) -> int:
                    vol_num_to_use = 1
                    try:
                        for line in outline_content.splitlines():
                            match = re.search(r"#===\s*第(\d+)卷.*?\s+第(\d+)章\s*至\s*第(\d+)章\s*===", line)
                            if match:
                                v_num = int(match.group(1))
                                s_chap = int(match.group(2))
                                e_chap = int(match.group(3))
                                if s_chap <= current_chapter_num <= e_chap:
                                    vol_num_to_use = v_num
                                    break
                    except Exception as e_find_vol:
                        self.safe_log(f"从分卷大纲确定卷号时出错: {e_find_vol}")
                    return vol_num_to_use
                
                actual_volume_number_for_prompt = find_actual_volume_number(volume_content, chap_num)
                volume_outline = extract_volume_outline(volume_content, actual_volume_number_for_prompt)
            
            # 获取伏笔编号并从向量库检索伏笔历史记录
            foreshadowing_ids = []
            if chapter_info and 'foreshadowing' in chapter_info and chapter_info['foreshadowing']:
                # 从伏笔字符串中提取伏笔ID
                pattern = r'[A-Z]F\d+'
                foreshadowing_ids = re.findall(pattern, chapter_info['foreshadowing'])
                # 对伏笔编号进行去重
                if foreshadowing_ids:
                    foreshadowing_ids = list(set(foreshadowing_ids))
                self.safe_log(f"从章节信息中提取到伏笔编号 (去重后): {foreshadowing_ids}")

            # 从向量库检索伏笔历史记录
            knowledge_context = ""
            if foreshadowing_ids:
                try:
                    # 修改：移除这里的create_embedding_adapter导入，因为已经在文件顶部导入过了
                    # 使用已导入的create_embedding_adapter
                    # 创建embedding适配器
                    logging.info(f"正在创建embedding适配器，准备检索伏笔编号: {foreshadowing_ids}")
                    embedding_adapter = create_embedding_adapter(
                        interface_format=self.embedding_interface_format_var.get(),
                        api_key=self.embedding_api_key_var.get(),
                        base_url=self.embedding_url_var.get(),
                        model_name=self.embedding_model_name_var.get()
                    )
                    
                    if embedding_adapter is None:
                        logging.warning("embedding适配器创建失败，将跳过伏笔历史检索")
                        knowledge_context = "(embedding适配器创建失败，无法检索伏笔历史记录)\n"
                    else:
                        # 加载伏笔向量库（使用专门的collection_name）
                        logging.info("正在加载伏笔向量库...")
                        from novel_generator.vectorstore_utils import load_vector_store
                        vectorstore = load_vector_store(embedding_adapter, filepath, collection_name="foreshadowing_collection")
                        
                        if vectorstore:
                            logging.info("成功加载向量库，开始检索伏笔历史...")
                            # 检索伏笔历史记录
                            # 使用循环单独检索每个伏笔ID，与knowledge.py中的格式保持一致
                            retrieved_ids = []
                            retrieved_metadatas = []
                            retrieved_documents = []
                            
                            for fb_id in foreshadowing_ids:
                                result = vectorstore.get(
                                    where={"id": fb_id},
                                    include=["metadatas", "documents"]
                                )
                                if result and result.get('ids'):
                                    retrieved_ids.extend(result.get('ids'))
                                    retrieved_metadatas.extend(result.get('metadatas'))
                                    retrieved_documents.extend(result.get('documents'))
                            
                            # 构建检索结果字典
                            retrieved_foreshadowings = {
                                'ids': retrieved_ids,
                                'metadatas': retrieved_metadatas,
                                'documents': retrieved_documents
                            }
                            
                            # 处理检索结果
                            if retrieved_foreshadowings and retrieved_foreshadowings.get('ids'):
                                for i, doc_id in enumerate(retrieved_foreshadowings['ids']):
                                    if i < len(retrieved_foreshadowings['metadatas']):
                                        metadata = retrieved_foreshadowings['metadatas'][i]
                                        content = retrieved_foreshadowings['documents'][i]
                                        
                                        # 格式化伏笔条目
                                        entry = f"伏笔编号: {metadata.get('id', '未知')}\n"
                                        entry += f"伏笔内容: {content}\n"
                                        chapter_metadata_value = metadata.get('chapter', 0)
                                        if str(chapter_metadata_value) != '0':
                                            entry += f"伏笔最后章节：{chapter_metadata_value}\n\n"
                                        
                                        knowledge_context += entry
                            
                            self.safe_log(f"成功检索到 {len(retrieved_foreshadowings['ids'])} 条伏笔历史记录")
                        else:
                            knowledge_context += "(向量库未初始化)\n"
                            self.safe_log("警告：向量库未初始化，无法检索伏笔历史记录")
                except Exception as e:
                    knowledge_context += f"(检索伏笔历史记录时出错)\n"
                    self.safe_log(f"错误：检索伏笔历史记录时出错: {str(e)}")
            else:
                knowledge_context += "(未找到伏笔编号)\n"
                self.safe_log("警告：未找到伏笔编号，无法检索伏笔历史记录")

            # 使用character_generator.py模块生成角色信息
            self.safe_log("使用character_generator.py模块生成角色信息...")
            from novel_generator.character_generator import generate_characters_for_draft
            from llm_adapters import create_llm_adapter
            # 已在上面导入了create_embedding_adapter，此处不需要重复导入
            
            # 从章节信息中获取章节标题和角色
            chapter_title_value = ""
            chapter_role_value = ""
            if chapter_info:
                if 'chapter_title' in chapter_info:
                    chapter_title_value = chapter_info['chapter_title']
                if 'chapter_role' in chapter_info:
                    chapter_role_value = chapter_info['chapter_role']
            
            # 获取章节信息中的其他必要参数，如果不存在则使用默认值
            chapter_purpose_value = ""
            suspense_type_value = ""
            emotion_evolution_value = ""
            foreshadowing_value = ""
            plot_twist_level_value = ""
            chapter_summary_value = ""
            
            if chapter_info:
                if 'chapter_purpose' in chapter_info:
                    chapter_purpose_value = chapter_info['chapter_purpose']
                if 'suspense_type' in chapter_info:
                    suspense_type_value = chapter_info['suspense_type']
                if 'emotion_evolution' in chapter_info:
                    emotion_evolution_value = chapter_info['emotion_evolution']
                if 'foreshadowing' in chapter_info:
                    # 如果foreshadowing是列表，将其转换为字符串
                    if isinstance(chapter_info['foreshadowing'], list):
                        foreshadowing_value = "\n".join(chapter_info['foreshadowing'])
                    else:
                        foreshadowing_value = chapter_info['foreshadowing']
                if 'plot_twist_level' in chapter_info:
                    plot_twist_level_value = chapter_info['plot_twist_level']
                if 'chapter_summary' in chapter_info:
                    chapter_summary_value = chapter_info['chapter_summary']
            
            # 创建LLM适配器
            llm_adapter = create_llm_adapter(
                interface_format=self.interface_format_var.get(),
                base_url=self.base_url_var.get(),
                model_name=self.model_name_var.get(),
                api_key=self.api_key_var.get(),
                temperature=self.temperature_var.get(),
                max_tokens=self.max_tokens_var.get(),
                timeout=self.safe_get_int(self.timeout_var, 600)
            )
            
            # 创建嵌入适配器
            embedding_adapter = None
            try:
                if self.embedding_api_key_var.get():  # 只有在提供了API密钥时才创建嵌入适配器
                    embedding_adapter = create_embedding_adapter(
                        interface_format=self.embedding_interface_format_var.get(),
                        base_url=self.embedding_url_var.get(),
                        model_name=self.embedding_model_name_var.get(),
                        api_key=self.embedding_api_key_var.get()
                    )
                else:
                    self.safe_log("未提供嵌入API密钥，将跳过角色状态检索功能")
            except Exception as e:
                self.safe_log(f"创建嵌入适配器失败: {str(e)}，将跳过角色状态检索功能")
            
            # 准备章节信息字典
            chapter_info_dict = {
                'novel_number': chap_num,
                'chapter_title': chapter_title_value,
                'chapter_role': chapter_role_value,
                'chapter_purpose': chapter_purpose_value,
                'suspense_type': suspense_type_value,
                'emotion_evolution': emotion_evolution_value,
                'foreshadowing': foreshadowing_value,
                'plot_twist_level': plot_twist_level_value,
                'chapter_summary': chapter_summary_value,
                'genre': self.genre_var.get(),
                'volume_count': self.volume_count_var.get() if hasattr(self, 'volume_count_var') else 3,
                'num_chapters': self.num_chapters_var.get() if hasattr(self, 'num_chapters_var') else 30,
                'volume_number': actual_volume_number_for_prompt,
                'word_number': self.word_number_var.get() if hasattr(self, 'word_number_var') else 3000,
                'topic': self.topic_var.get(),
                'user_guidance': self.user_guide_text.get("0.0", "end").strip(),
                'global_summary': global_summary,
                'plot_points': "",  # 可以添加前一章内容
                'volume_outline': volume_outline,
                'knowledge_context': knowledge_context  # 添加伏笔历史记录到章节信息字典
            }
            
            # 使用character_generator.py模块生成角色信息
            try:
                # 确保embedding_adapter已经正确创建
                if embedding_adapter is None and self.embedding_api_key_var.get():
                    try:
                        self.safe_log("尝试重新创建嵌入适配器...")
                        embedding_adapter = create_embedding_adapter(
                            interface_format=self.embedding_interface_format_var.get(),
                            base_url=self.embedding_url_var.get(),
                            model_name=self.embedding_model_name_var.get(),
                            api_key=self.embedding_api_key_var.get()
                        )
                        self.safe_log("嵌入适配器创建成功")
                    except Exception as e_embed:
                        self.safe_log(f"创建嵌入适配器失败: {str(e_embed)}，将跳过角色状态检索功能")
                
                # 检查embedding_adapter是否成功创建
                if embedding_adapter is not None:
                    self.safe_log("使用嵌入适配器调用generate_characters_for_draft函数...")
                else:
                    self.safe_log("警告：嵌入适配器为None，角色状态检索功能可能受限")
                
                setting_characters = generate_characters_for_draft(chapter_info_dict, filepath, llm_adapter, embedding_adapter)
                if setting_characters:
                    self.safe_log(f"✅ 使用character_generator.py模块生成角色信息成功: {setting_characters[:200]}...")
                else:
                    self.safe_log("❌ 使用character_generator.py模块生成角色信息失败: 返回内容为空")
                    setting_characters = ""
            except Exception as e:
                self.safe_log(f"❌ 使用character_generator.py模块生成角色信息失败: {str(e)}")
                setting_characters = ""

            self.safe_log("已完成伏笔历史记录检索和格式化")

            # 获取上一章的剧情要点（如果存在）
            plot_points = ""
            if chap_num > 1:
                plot_points_file = os.path.join(filepath, "剧情要点.txt")
                if os.path.exists(plot_points_file):
                    with open(plot_points_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # 尝试多种模式匹配前一章的剧情要点（包含标题行）
                        title_patterns = [
                            rf"(第{chap_num-1}章.*?剧情要点：[\s\S]*?)(?=第{chap_num}章|===|$)",  # 标准格式（包含标题）
                            rf"(第{chap_num-1}章.*?剧情要点[：:][\s\S]*?)(?=第{chap_num}章|===|$)",  # 兼容冒号格式（包含标题）
                            rf"(第{chap_num-1}章[\s\S]*?)(?=第{chap_num}章|===|$)"  # 宽松匹配（包含标题）
                        ]
                        
                        found_plot_points = False
                        
                        # 先尝试包含标题的匹配
                        for pattern in title_patterns:
                            match = re.search(pattern, content, re.IGNORECASE)
                            if match and match.group(1).strip():
                                plot_points = match.group(1).strip()
                                self.safe_log(f"✅ 成功提取上一章剧情要点（包含标题）: {plot_points[:100]}...")
                                found_plot_points = True
                                break
                                
                        # 如果包含标题的匹配失败，尝试不包含标题的匹配（向后兼容）
                        if not found_plot_points:
                            content_patterns = [
                                rf"第{chap_num-1}章.*?剧情要点：([\s\S]*?)(?=第{chap_num}章|===|$)",  # 标准格式（不包含标题）
                                rf"第{chap_num-1}章.*?剧情要点[：:](.*?)(?=第{chap_num}章|===|$)"  # 兼容冒号格式（不包含标题）
                            ]
                            
                            for pattern in content_patterns:
                                match = re.search(pattern, content, re.IGNORECASE)
                                if match and match.group(1).strip():
                                    # 提取标题行并添加到内容前面
                                    title_match = re.search(rf"(第{chap_num-1}章.*?剧情要点[：:])", content)
                                    if title_match:
                                        plot_points = f"{title_match.group(1)}\n{match.group(1).strip()}"
                                    else:
                                        plot_points = match.group(1).strip()
                                    self.safe_log(f"✅ 成功提取上一章剧情要点: {plot_points[:100]}...")
                                    found_plot_points = True
                                    break
                        
                        # 如果上述模式都没匹配到，尝试匹配整个章节块
                        if not found_plot_points:
                            chapter_block_pattern = rf"第{chap_num-1}章[\s\S]*?(?=第{chap_num}章|===|$)"
                            block_match = re.search(chapter_block_pattern, content)
                            if block_match:
                                plot_points = block_match.group(0).strip()
                                self.safe_log(f"✅ 使用章节块提取上一章剧情要点: {plot_points[:100]}...")
                            else:
                                self.safe_log(f"⚠️ 未找到第{chap_num-1}章的剧情要点")


            # 从UI获取核心人物列表并读取角色文件内容
            characters_involved_detail = ""
            characters_involved_list_str = self.characters_involved_var.get()
            if characters_involved_list_str:
                # 同时支持中文逗号和英文逗号作为分隔符
                # 使用正则表达式替换所有中文逗号为英文逗号，然后用英文逗号分割
                processed_list_str = characters_involved_list_str.replace('，', ',')
                characters_involved_list = [name.strip() for name in processed_list_str.split(',') if name.strip()]
                if characters_involved_list:
                    character_lib_path = os.path.join(filepath, "角色库")
                    for char_name in characters_involved_list:
                        # 在角色库的所有子文件夹中查找角色文件
                        found_char_file = False
                        if os.path.exists(character_lib_path) and os.path.isdir(character_lib_path):
                            for category_dir in os.listdir(character_lib_path):
                                category_path = os.path.join(character_lib_path, category_dir)
                                if os.path.isdir(category_path):
                                    char_file_path = os.path.join(category_path, f"{char_name}.txt")
                                    if os.path.exists(char_file_path):
                                        try:
                                            with open(char_file_path, 'r', encoding='utf-8') as f_char:
                                                characters_involved_detail += f"{f_char.read()}\n\n"
                                            self.safe_log(f"✅ 成功读取角色文件: {char_file_path}")
                                            found_char_file = True
                                            break  # 找到文件后跳出循环
                                        except Exception as e_read_char:
                                            self.safe_log(f"❌ 读取角色文件 {char_file_path} 失败: {e_read_char}")
                                            characters_involved_detail += f"(无法读取角色文件内容)\n\n"
                                            found_char_file = True
                                            break  # 找到文件后跳出循环
                        
                        if not found_char_file:
                            self.safe_log(f"⚠️ 角色文件不存在: 在角色库中未找到 {char_name}.txt")
                            characters_involved_detail += f"(角色文件不存在)\n\n"
                else:
                    self.safe_log("ℹ️ UI中未指定核心人物或格式不正确。")
            else:
                self.safe_log("ℹ️ UI中未指定核心人物。")

            # 添加日志记录
            self.safe_log(f"[DEBUG] characters_involved: {self.characters_involved_var.get()}")
            self.safe_log(f"[DEBUG] characters_involved_detail: {characters_involved_detail}")

            # 创建包含所有参数的字典
            chapter_info_dict = {
                'novel_setting': novel_setting,
                'character_state': character_state,
                'global_summary': global_summary,
                'setting_characters': setting_characters if setting_characters else "",
                'prev_chapter_content': self.prev_chapter_content_var.get() if hasattr(self, 'prev_chapter_content_var') else "",
                'novel_number': chap_num,
                'chapter_title': chapter_info.get('chapter_title', '') if chapter_info else '',
                'chapter_role': chapter_info.get('chapter_role', '') if chapter_info else '',
                'chapter_purpose': chapter_info.get('chapter_purpose', '') if chapter_info else '',
                'suspense_type': chapter_info.get('suspense_type', '') if chapter_info else '',
                'emotion_evolution': chapter_info.get('emotion_evolution', '') if chapter_info else '',
                'foreshadowing': chapter_info.get('foreshadowing', '') if chapter_info else '',
                'plot_twist_level': chapter_info.get('plot_twist_level', '') if chapter_info else '',
                'chapter_summary': chapter_info.get('chapter_summary', '') if chapter_info else '',
                'characters_involved': self.characters_involved_var.get(),
                'characters_involved_detail': characters_involved_detail,
                'key_items': self.key_items_var.get(),
                'scene_location': self.scene_location_var.get(),
                'time_constraint': self.time_constraint_var.get(),
                'knowledge_context': knowledge_context,
                'word_number': self.safe_get_int(self.word_number_var, 3000),
                'volume_outline': volume_outline,
                'user_guidance': self.user_guide_text.get("0.0", "end").strip() if hasattr(self, 'user_guide_text') else "",
                'genre': self.genre_var.get() if hasattr(self, 'genre_var') else "",
                'topic': self.topic_var.get() if hasattr(self, 'topic_var') else "",
                'plot_points': plot_points
            }
            
            # 调用 build_chapter_prompt 函数，传递字典和文件路径
            return build_chapter_prompt(chapter_info_dict, filepath)
            
        except Exception as e:
            self.handle_exception(f"构建初始提示词时出错: {str(e)}")
            self.safe_log(f"❌ 构建初始提示词失败: {traceback.format_exc()}") # Log detailed error
            return ""
    
    # Ensure button is re-enabled even if prompt generation fails
    initial_prompt = ""
    try:
        initial_prompt = get_initial_prompt()
    finally:
        if not initial_prompt:
            self.safe_log("ℹ️ 未能生成初始提示词，请检查设置或错误日志。")
            self.enable_button_safe(self.btn_generate_chapter)
        else:
            # 弹出提示词编辑窗口，让用户修改后再调用 LLM
            show_prompt_editor(initial_prompt)