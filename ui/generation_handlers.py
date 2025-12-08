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
from utils import read_file, save_string_to_txt, clear_file_content, reformat_novel_text
from config_manager import clear_project_continue_state
from llm_adapters import create_llm_adapter
from novel_generator.common import invoke_with_cleaning, get_chapter_filepath, execute_with_polling
from novel_generator.architecture import Novel_architecture_generate
from novel_generator.volume import Novel_volume_generate, parse_architecture_file
from novel_generator.blueprint import Chapter_blueprint_generate
from novel_generator.chapter import generate_chapter_draft
from novel_generator.finalization import finalize_chapter, enrich_chapter_text
# from novel_generator.knowledge import import_knowledge_file # [DEPRECATED]
from novel_generator.chapter_directory_parser import (
    parse_chapter_blueprint, 
    get_chapter_info_from_blueprint,
    get_chapter_blueprint_text,
    get_plot_points,
    get_volume_outline
)
# from novel_generator.vectorstore_utils import load_vector_store # [REMOVED]

def extract_volume_specific_module_content(module_content, volume_number):
    """
    从模块的完整文本中提取特定卷的内容。
    例如，从“模块一”内容中，仅提取“第一卷”的内容。
    """
    # 为1-20卷创建中文数字映射
    volume_map = {
        1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
        11: "十一", 12: "十二", 13: "十三", 14: "十四", 15: "十五", 16: "十六", 17: "十七", 18: "十八", 19: "十九", 20: "二十"
    }
    
    chinese_numeral = volume_map.get(volume_number)
    if not chinese_numeral:
        logging.warning(f"无法找到第 {volume_number} 卷的中文数字映射。")
        return f"(无法找到第 {volume_number} 卷的中文数字)"

    # 正则表达式，用于查找以 "● 第X卷" 开头，直到下一个 "● 第" 或文件末尾的块。
    # 这种方法更稳健，因为它不依赖于换行符或行首。
    # 使用 re.DOTALL 使 `.` 可以匹配换行符。
    pattern = re.compile(
        rf"●\s*第{chinese_numeral}卷.*?(?=●\s*第|$)",
        re.DOTALL
    )
    
    match = pattern.search(module_content)
    
    if match:
        return match.group(0).strip()
    else:
        logging.warning(f"在模块内容中未能找到第 {volume_number} 卷 (第{chinese_numeral}卷) 的内容。")
        return f"(未能在模块中找到第 {volume_number} 卷的内容)"

# 屏蔽 LLM 相关 DEBUG 日志
for noisy_logger in [
    "openai", "openai._base_client", "httpcore", "httpcore.connection", "httpcore.http11", "httpx"
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

def import_knowledge_handler(self):
    """
    [已弃用] 处理将知识文件导入向量库的功能。
    此功能已被移除，因为项目已迁移到JSON文件存储。
    """
    messagebox.showinfo("功能已移除", "“导入知识”功能已在项目迁移到JSON存储后被移除。")
    self.safe_log("INFO: User attempted to use the deprecated 'Import Knowledge' feature.")

def clear_vectorstore_handler(self):
    """
    处理清理JSON存储的UI函数
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        try:
            if not messagebox.askyesno("确认", "确定要清理角色和伏笔状态吗？\n此操作将删除以下文件，且不可逆：\n- 角色状态.md\n- 伏笔状态.md"):
                return
                
            self.safe_log("开始清理角色和伏笔状态JSON文件...")
            
            character_json_path = os.path.join(filepath, "定稿内容", "角色状态.md")
            foreshadowing_json_path = os.path.join(filepath, "定稿内容", "伏笔状态.md")
            
            files_deleted = False
            if os.path.exists(character_json_path):
                os.remove(character_json_path)
                self.safe_log(f"✅ 已删除: {os.path.basename(character_json_path)}")
                files_deleted = True

            if os.path.exists(foreshadowing_json_path):
                os.remove(foreshadowing_json_path)
                self.safe_log(f"✅ 已删除: {os.path.basename(foreshadowing_json_path)}")
                files_deleted = True

            if files_deleted:
                self.safe_log("✅ 状态文件清理完成。")
            else:
                self.safe_log("ℹ️ 未找到需要清理的状态文件。")

        except Exception as e:
            self.handle_exception(f"清理状态文件时出错: {str(e)}")
    
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


def repair_character_database(self):
    """
    [重构] 修复角色数据库.txt的处理函数。
    直接从 角色状态.md 读取数据，并在内存中处理，然后生成最终的 .txt 文件。
    不再使用中间文件和复杂的正则表达式解析。
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        try:
            if not messagebox.askyesno("确认", "确定要根据最新的角色状态文件 (角色状态.md) 重新生成角色数据库吗？"):
                return
                
            self.safe_log("开始修复角色数据库...")
            
            # 1. 读取并解析角色状态Markdown文件
            from novel_generator.character_state_updater import parse_character_state_md, update_character_db_txt
            from utils import read_file
            
            character_md_path = os.path.join(filepath, "定稿内容", "角色状态.md")
            if not os.path.exists(character_md_path):
                self.safe_log(f"❌ 角色状态文件不存在: {character_md_path}")
                messagebox.showerror("错误", "角色状态文件 (角色状态.md) 不存在。")
                return

            md_content = read_file(character_md_path)
            if not md_content or not md_content.strip():
                self.safe_log("❌ 角色状态文件 (角色状态.md) 为空。修复中止。")
                messagebox.showerror("错误", "角色状态文件 (角色状态.md) 为空。")
                return
            
            character_store = parse_character_state_md(md_content)
            
            if not character_store:
                self.safe_log("❌ 无法从 角色状态.md 中解析出任何角色数据。请检查文件格式。")
                messagebox.showerror("错误", "无法从 角色状态.md 中解析出任何角色数据。请检查文件格式。")
                return

            self.safe_log(f"✅ 成功从Markdown文件加载 {len(character_store)} 个角色状态。")
            
            # 2. 直接在内存中处理数据并生成文件内容
            db_file_path = os.path.join(filepath, "角色数据库.txt")
            
            # 调用统一的、健壮的数据库生成函数
            update_character_db_txt(db_file_path, character_store, self.safe_log)
            
            self.safe_log("✅ 成功修复角色数据库.txt")
            messagebox.showinfo("成功", "角色数据库已根据最新的Markdown数据成功修复。")

        except Exception as e:
            self.handle_exception(f"修复角色数据库时出错: {str(e)}")
            logging.error(traceback.format_exc())
    
    threading.Thread(target=task, daemon=True).start()
            
def do_consistency_check(self, *args, **kwargs):
    """
    Wrapper function for consistency checking that now includes a word count dialog and a prompt editor.
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    chap_num_str = self.chapter_num_var.get().strip()
    if not chap_num_str:
        messagebox.showwarning("警告", "请输入要审校的章节号")
        return
        
    try:
        chap_num = int(chap_num_str)
    except ValueError:
        messagebox.showerror("错误", "无效的章节号")
        return

    # --- 新增：调用辅助函数获取并校验内容 ---
    review_text_body = self._get_content_for_processing(chap_num, "一致性审校", check_word_count=False)
    if review_text_body is None:
        # 如果返回 None，说明用户取消了操作或内容为空
        self.enable_button_safe(self.btn_check_consistency)
        return
    # --- 结束新增 ---

    self.disable_button_safe(self.btn_check_consistency)

    def show_word_count_dialog(self):
        """First, show a dialog to get the word count range."""
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("设置审校字数范围")
        dialog.geometry("400x180")  # 增加宽度和高度
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.attributes('-topmost', True)
        dialog.resizable(False, False) # 禁止调整大小

        result = {"min": None, "max": None}

        # --- 自动计算默认值 ---
        base_word_count = self.safe_get_int(self.word_number_var, 3000)
        default_min = int(base_word_count * 0.8)
        default_max = int(base_word_count * 1.5)

        frame = ctk.CTkFrame(dialog)
        frame.pack(pady=20, padx=20, fill="x", expand=True)
        frame.grid_columnconfigure(1, weight=1) # 让输入框可以扩展

        ctk.CTkLabel(frame, text="不少于:").grid(row=0, column=0, padx=(10, 5), pady=10)
        min_var = ctk.StringVar(value=str(default_min))
        min_entry = ctk.CTkEntry(frame, textvariable=min_var)
        min_entry.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkLabel(frame, text="字").grid(row=0, column=2, padx=(5, 10), pady=10)

        ctk.CTkLabel(frame, text="不大于:").grid(row=1, column=0, padx=(10, 5), pady=10)
        max_var = ctk.StringVar(value=str(default_max))
        max_entry = ctk.CTkEntry(frame, textvariable=max_var)
        max_entry.grid(row=1, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkLabel(frame, text="字").grid(row=1, column=2, padx=(5, 10), pady=10)

        def on_confirm():
            try:
                min_val = int(min_var.get())
                max_val = int(max_var.get())
                if min_val <= 0 or max_val <= 0:
                    messagebox.showerror("错误", "字数必须是正整数。", parent=dialog)
                    return
                if min_val > max_val:
                    messagebox.showerror("错误", "字数下限不能大于上限。", parent=dialog)
                    return
                result["min"] = min_val
                result["max"] = max_val
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的整数。", parent=dialog)

        def on_cancel():
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=(0, 10), padx=20, fill="x", expand=True)
        btn_frame.grid_columnconfigure((0, 1), weight=1) # 让两个按钮平分空间

        ctk.CTkButton(btn_frame, text="确认", command=on_confirm).grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        ctk.CTkButton(btn_frame, text="取消", command=on_cancel).grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        
        # Wait for the dialog to close
        self.master.wait_window(dialog)
        return result["min"], result["max"]

    def prepare_prompt_data_async(gui_app, word_min, word_max, chap_num, review_text_body):
        """
        Runs in a background thread.
        Performs heavy I/O operations (file reading, vector search)
        and returns the data in a dictionary.
        """
        try:
            gui_app.safe_log(f"后台：正在为第 {chap_num} 章准备数据...")
            
            # Perform all non-UI data gathering here
            filepath = gui_app.filepath_var.get().strip() # This is safe as it's just reading a variable
            directory_file = os.path.join(filepath, "章节目录.txt")
            directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""
            
            chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
            current_chapter_blueprint = get_chapter_blueprint_text(directory_content, chap_num)
            next_chapter_blueprint = get_chapter_blueprint_text(directory_content, chap_num + 1)
            
            global_summary_file = os.path.join(filepath, "前情摘要.txt")
            global_summary = read_file(global_summary_file) if os.path.exists(global_summary_file) else ""
            
            volume_outline = get_volume_outline(filepath, chap_num)
            plot_points = get_plot_points(filepath, chap_num)
            
            # 使用已经获取和校验过的内容 (review_text_body)
            # 为待审校文本添加章节标题
            header = gui_app._get_formatted_chapter_header(chap_num, filepath)
            review_text = f"{header}\n{review_text_body}"

            # --- Knowledge Context Retrieval (heavy part) ---
            knowledge_context = "(无相关伏笔历史记录)"
            foreshadowing_ids = []
            if current_chapter_blueprint:
                # 1. Isolate the foreshadowing block first to avoid capturing IDs from other sections
                # 修复：使用更精确的正则表达式来界定区块结束
                foreshadowing_block_match = re.search(r'├─伏笔条目：([\s\S]*?)(?=\n[├└]─[\u4e00-\u9fa5]|\Z)', current_chapter_blueprint)
                if foreshadowing_block_match:
                    foreshadowing_block = foreshadowing_block_match.group(1)
                    # 2. Find all potential IDs within that block
                    all_ids_in_block = re.findall(r'([A-Z]{1,2}F\d+)', foreshadowing_block)
                    # 3. Get a unique, sorted list of IDs
                    if all_ids_in_block:
                        foreshadowing_ids = sorted(list(set(all_ids_in_block)))

            if foreshadowing_ids:
                from novel_generator.json_utils import load_store
                foreshadowing_store = load_store(filepath, "foreshadowing_collection")
                if foreshadowing_store:
                    retrieved_entries = []
                    for fb_id in foreshadowing_ids:
                        if fb_id in foreshadowing_store:
                            fb_data = foreshadowing_store[fb_id]
                            content = fb_data.get("内容", "无内容记录")
                            retrieved_entries.append(f"伏笔 {fb_id} 的历史内容:\n{content}")
                    if retrieved_entries:
                        knowledge_context = "\n\n".join(retrieved_entries)
                else:
                    gui_app.safe_log("ℹ️ 伏笔状态文件 (伏笔状态.md) 不存在或为空。")

            # Package all data for the main thread
            data_package = {
                "chapter_info": chapter_info,
                "current_chapter_blueprint": current_chapter_blueprint,
                "next_chapter_blueprint": next_chapter_blueprint,
                "global_summary": global_summary,
                "volume_outline": volume_outline,
                "plot_points": plot_points,
                "review_text": review_text,
                "knowledge_context": knowledge_context,
                "word_min": word_min,
                "word_max": word_max
            }
            
            # Schedule the UI part to run on the main thread
            gui_app.master.after(0, lambda: build_prompt_and_show_editor(gui_app, data_package, chap_num))

        except Exception as e:
            gui_app.handle_exception(f"后台准备数据时出错: {str(e)}")
            gui_app.enable_button_safe(gui_app.btn_check_consistency)

    def build_prompt_and_show_editor(gui_app, data, chap_num):
        """
        Runs in the main thread.
        Receives data from the background thread, gets UI values,
        builds the final prompt, and shows the editor.
        """
        try:
            gui_app.safe_log("主线程：正在构建最终提示词...")
            from prompt_definitions import Chapter_Review_prompt

            # Get values from UI components now, in the main thread
            genre = gui_app.genre_var.get()
            user_guidance = gui_app.user_guide_text.get("0.0", "end").strip()
            word_number = gui_app.safe_get_int(gui_app.word_number_var, 3000)
            
            chapter_info = data.get("chapter_info", {})
            chapter_title = chapter_info.get('chapter_title', f"第{chap_num}章")
            
            plot_twist_level = re.search(r"├─颠覆指数：\s*(.*?)\n", data["current_chapter_blueprint"])
            plot_twist_level = plot_twist_level.group(1).strip() if plot_twist_level else "Lv.1"

            # Format the final prompt
            prompt_text = Chapter_Review_prompt.format(
                novel_number=chap_num,
                chapter_title=chapter_title,
                word_number=word_number,
                genre=genre,
                user_guidance=user_guidance,
                current_chapter_blueprint=data["current_chapter_blueprint"],
                next_chapter_blueprint=data["next_chapter_blueprint"],
                volume_outline=data["volume_outline"],
                global_summary=data["global_summary"],
                plot_points=data["plot_points"],
                knowledge_context=data["knowledge_context"],
                Review_text=data["review_text"],
                plot_twist_level=plot_twist_level,
                章节字数=len(data["review_text"]),
                字数下限=data["word_min"],
                字数上限=data["word_max"]
            )

            if not prompt_text:
                gui_app.safe_log("❌ 无法生成审校提示词，请检查日志。")
                gui_app.enable_button_safe(gui_app.btn_check_consistency)
                return

            # Now, show the editor
            show_consistency_prompt_editor(gui_app, prompt_text, chap_num)

        except Exception as e:
            gui_app.handle_exception(f"构建提示词或显示编辑器时出错: {str(e)}")
            gui_app.enable_button_safe(gui_app.btn_check_consistency)

    def show_consistency_prompt_editor(self, prompt_text, chap_num):
        """Show a dialog to edit the consistency check prompt."""
        dialog = ctk.CTkToplevel(self.master)
        dialog.title(f"编辑第 {chap_num} 章一致性审校提示词")
        dialog.geometry("800x600")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.attributes('-topmost', True)

        textbox = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 14))
        textbox.pack(fill="both", expand=True, padx=10, pady=10)
        textbox.insert("0.0", prompt_text)

        def on_confirm():
            modified_prompt = textbox.get("0.0", "end").strip()
            dialog.destroy()
            execute_check(self, modified_prompt, chap_num)

        def on_close():
            """Unified close handler to re-enable the button."""
            dialog.destroy()
            self.enable_button_safe(self.btn_check_consistency)
            self.safe_log("ℹ️ 一致性审校已取消。")

        # Bind both the window close button and the cancel button to on_close
        dialog.protocol("WM_DELETE_WINDOW", on_close)

        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="确认审校", command=on_confirm).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消", command=on_close).pack(side="left", padx=5)

        word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 14))
        word_count_label.pack(side="right", padx=10)

        def update_word_count(event=None):
            text = textbox.get("1.0", "end-1c")
            words = len(text)
            word_count_label.configure(text=f"字数: {words}")

        textbox.bind("<KeyRelease>", update_word_count)
        update_word_count() # Initial count

    def execute_check(self, prompt, chap_num):
        """Execute the consistency check with the custom prompt."""
        def task_wrapper():
            try:
                from novel_generator.consistency_checker import do_consistency_check as cc_do_consistency_check
                from utils import save_string_to_txt

                def consistency_check_task(llm_adapter, **kwargs):
                    text = ""
                    logger = kwargs.get('log_func', self.safe_log)
                    check_interrupted = kwargs.get('check_interrupted')
                    for chunk in cc_do_consistency_check(self, custom_prompt=prompt, llm_adapter=llm_adapter, log_stream=False, log_func=logger, check_interrupted=check_interrupted):
                        text += chunk
                    return text

                full_result = execute_with_polling(
                    gui_app=self,
                    step_name="一致性审校",
                    target_func=consistency_check_task,
                    log_func=self.safe_log,
                    adapter_callback=None,
                    check_interrupted=None,
                    context_info=f"第 {chap_num} 章",
                    is_manual_call=True
                )
                
                if full_result and full_result.strip():
                    filepath = self.filepath_var.get().strip()
                    output_file_path = os.path.join(filepath, "一致性审校.txt")
                    save_string_to_txt(full_result, output_file_path)
                    self.safe_log(f"\n✅ 一致性审校完成，结果已保存到 {os.path.basename(output_file_path)}")
                    self.master.after(0, self.show_consistency_check_results_ui)
                else:
                    self.safe_log("\n⚠️ 一致性审校未返回任何内容。")

            except Exception as e:
                self.safe_log(f"❌ 一致性审校流程因错误中断: {e}")
            finally:
                self.enable_button_safe(self.btn_check_consistency)
        
        threading.Thread(target=task_wrapper, daemon=True).start()

    # --- New Thread-Safe Process ---

    def start_process():
        # 1. Show word count dialog (main thread, blocking)
        word_min, word_max = show_word_count_dialog(self)

        # 2. If user confirms, start background data preparation
        if word_min is not None and word_max is not None:
            self.last_review_word_range = (word_min, word_max)
            self.safe_log(f"✅ 已设置字数范围: {word_min} - {word_max} 字。")
            threading.Thread(target=lambda: prepare_prompt_data_async(self, word_min, word_max, chap_num, review_text_body), daemon=True).start()
        else:
            # User cancelled the first dialog
            self.enable_button_safe(self.btn_check_consistency)
            self.safe_log("ℹ️ 一致性审校已取消。")

    # This is the entry point. It's already in the main thread.
    start_process()
from novel_generator.rewrite import rewrite_chapter  # 添加导入

# 检查是否定义了 generate_volume_ui，如果没有则补充一个空实现，防止 ImportError

def generate_volume_ui(self):
    """
    分卷大纲生成UI - 此功能已被工作流引擎取代，保留为空函数以防旧的UI调用出错。
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
            dialog.attributes('-topmost', True)  # 设置为置顶窗口
            
            # 禁止最小化窗口
            dialog.protocol("WM_ICONIFY_WINDOW", lambda: dialog.deiconify())
            
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
                        from novel_generator.common import invoke_stream_with_cleaning, execute_with_polling
                        from prompt_definitions import create_character_state_prompt, character_1_prompt

                        novel_setting_file = os.path.join(filepath, "小说设定.txt")
                        if not os.path.exists(novel_setting_file):
                            self.safe_log("❌ 请先生成小说架构(小说设定.txt)")
                            return
                        novel_setting = read_file(novel_setting_file)
                        topic = self.topic_text.get("0.0", "end").strip()
                        user_guidance = self.user_guide_text.get("0.0", "end").strip()
                        number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
                        word_number = self.safe_get_int(self.word_number_var, 3000)
                        volume_count = self.safe_get_int(self.volume_count_var, 3)
                        volume_file = os.path.join(filepath, "分卷大纲.txt")
                        volume_outline = read_file(volume_file) if os.path.exists(volume_file) else ""
                        
                        prompt = create_character_state_prompt.format(
                            genre=self.genre_var.get(), volume_count=volume_count, num_chapters=number_of_chapters,
                            word_number=word_number, topic=topic, user_guidance=user_guidance, novel_setting=novel_setting,
                            volume_outline=volume_outline, num_characters=char_count, character_prompt=character_1_prompt,
                            volume_number=vol_num
                        )

                        def character_task(llm_adapter, **kwargs):
                            if char_count == 0:
                                self.safe_log("ℹ️ 用户选择不生成角色，跳过LLM角色生成。")
                                return ""
                            return "".join(chunk for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, log_func=self.safe_log))

                        characters = execute_with_polling(
                            gui_app=self, step_name="生成分卷_生成分卷角色", target_func=character_task,
                            log_func=self.safe_log, context_info=f"第 {vol_num} 卷", is_manual_call=True
                        )

                        if characters is not None:
                            show_prompt_editor(characters)
                        else:
                            self.safe_log("❌ 角色生成失败或被中断。")
                            
                    except Exception as e:
                        self.safe_log(f"❌ 生成角色流程时发生错误: {str(e)}")
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
                editor_dialog.attributes('-topmost', True)  # 设置为置顶窗口
                
                # 禁止最小化窗口
                editor_dialog.protocol("WM_ICONIFY_WINDOW", lambda: editor_dialog.deiconify())
                
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
                # 解析小说设定以获取所有模块的完整内容
                full_parsed_setting = parse_architecture_file(novel_setting)
                
                # 为当前卷（第一卷）提取特定模块的内容
                current_volume_number = 1
                parsed_setting = {}
                for key, content in full_parsed_setting.items():
                    if key in ["volume_mission_statement", "plotline_and_progression", "narrative_style"]:
                        parsed_setting[key] = extract_volume_specific_module_content(content, current_volume_number)
                    else:
                        # 对于非分卷模块（如模块二和模块四），直接使用
                        parsed_setting[key] = content
                
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
                    character_state=character_state,
                    setting_characters=characters,  # 使用生成的角色
                    characters_involved=characters_involved_detail,
                    number_of_chapters=number_of_chapters,
                    word_number=word_number,
                    Total_volume_number=volume_count,
                    genre=genre,
                    volume_number=1,
                    volume_design_format=volume_design_format,
                    **parsed_setting
                )
                
                # 创建提示词编辑框
                prompt_text = ctk.CTkTextbox(editor_dialog, wrap="word", font=("Microsoft YaHei", 14))
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
                    font=("Microsoft YaHei", 14)
                ).pack(side="left", padx=10)
                
                ctk.CTkButton(
                    btn_frame,
                    text="取消",
                    command=editor_dialog.destroy,
                    font=("Microsoft YaHei", 14)
                ).pack(side="left", padx=10)

                word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 14))
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
                next_vol = current_vol + 1 if current_vol > 0 else 1
                
                def custom_generation_thread(vol_num):
                    try:
                        from novel_generator.common import invoke_stream_with_cleaning, execute_with_polling

                        def outline_task(llm_adapter, **kwargs):
                            return "".join(chunk for chunk in invoke_stream_with_cleaning(llm_adapter, custom_prompt, log_func=self.safe_log))

                        outline = execute_with_polling(
                            gui_app=self, step_name="生成分卷_生成分卷大纲", target_func=outline_task,
                            log_func=self.safe_log, context_info=f"第 {vol_num} 卷", is_manual_call=True
                        )

                        if not outline or not outline.strip():
                            self.safe_log("❌ 分卷大纲生成失败：未获得有效内容或被中断。")
                            return
                        
                        volume_file = os.path.join(filepath, "分卷大纲.txt")
                        volume_title = "" if vol_num < total_vols else "终章"
                        
                        distribution_match = re.search(r'章节范围\s*[:：]\s*第\s*(\d+)\s*章\s*[-—至]\s*第\s*(\d+)\s*章', outline, re.DOTALL)
                        if not distribution_match:
                            distribution_match = re.search(r'章节范围\s*[:：]\s*(\d+)\s*[-—至]\s*(\d+)', outline, re.DOTALL)
                        
                        if distribution_match:
                            try:
                                real_start_chap = int(distribution_match.group(1))
                                real_end_chap = int(distribution_match.group(2))
                                self.safe_log(f"从生成的大纲中成功提取第 {vol_num} 卷的真实章节范围: {real_start_chap}-{real_end_chap}")
                                new_volume = f"\n\n#=== 第{vol_num}卷{volume_title}  第{real_start_chap}章 至 第{real_end_chap}章 ===\n{outline}"
                            except (ValueError, IndexError):
                                self.safe_log(f"❌ 解析第 {vol_num} 卷大纲中的章节范围失败。")
                                messagebox.showerror("提取失败", f"无法从生成的大纲中解析第 {vol_num} 卷的章节范围数字。")
                                return
                        else:
                            self.safe_log(f"❌ 在第 {vol_num} 卷生成的大纲中未能找到'章节范围'。")
                            messagebox.showerror("提取失败", f"无法从生成的大纲中找到第 {vol_num} 卷的章节范围信息。")
                            return
                        
                        with open(volume_file, "a", encoding="utf-8") as f:
                            f.write(new_volume)
                        
                        self.safe_log(f"✅ 第{vol_num}卷大纲已生成并保存")
                        
                    except Exception as e:
                        self.safe_log(f"❌ 生成分卷大纲流程时发生错误: {str(e)}")
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
                font=("Microsoft YaHei", 14)
            )
            info_label.pack(pady=10)
            
            # 只有在生成第一卷时显示角色数量输入框
            if (current_vol == 0):
                input_frame = ctk.CTkFrame(dialog)
                input_frame.pack(pady=5)
                
                ctk.CTkLabel(
                    input_frame,
                    text="主要角色数量：",
                    font=("Microsoft YaHei", 14)
                ).pack(side="left", padx=5)
                
                ctk.CTkEntry(
                    input_frame,
                    textvariable=character_count_var,
                    width=50,
                    font=("Microsoft YaHei", 14)
                ).pack(side="left", padx=5)

            # 根据当前卷数创建不同的UI
            if (current_vol == 0):
                # 第一卷时显示生成角色按钮
                btn_frame = ctk.CTkFrame(dialog)
                btn_frame.pack(pady=5)
                
                ctk.CTkButton(
                    btn_frame,
                    text=btn2_text,
                    command=handle_generate_characters_click,
                    font=("Microsoft YaHei", 14),
                    width=200
                ).pack(pady=5)
            else:
                # 非第一卷时显示权重输入框
                weight_frame = ctk.CTkFrame(dialog)
                weight_frame.pack(pady=10)
                
                weight_label = ctk.CTkLabel(
                    weight_frame,
                    text="提取大于",
                    font=("Microsoft YaHei", 14)
                )
                weight_label.pack(side="left", padx=5)
                
                weight_var = tk.StringVar(value="91")
                weight_entry = ctk.CTkEntry(
                    weight_frame,
                    textvariable=weight_var,
                    width=50,
                    font=("Microsoft YaHei", 14)
                )
                weight_entry.pack(side="left", padx=5)
                
                weight_label2 = ctk.CTkLabel(
                    weight_frame,
                    text="权重的角色状态至提示词",
                    font=("Microsoft YaHei", 14)
                )
                weight_label2.pack(side="left", padx=5)
                # 非第一卷时的生成按钮
                def open_subsequent_volume_prompt():
                    try:
                        # 验证权重值
                        weight_value = int(weight_var.get())
                        if weight_value < 0 or weight_value > 100:
                            messagebox.showwarning("警告", "权重值应在0-100之间")
                            return
                            
                        dialog.destroy() # 关闭当前的确认窗口
                        show_subsequent_volume_prompt(current_vol + 1, weight_value)
                    except ValueError:
                        messagebox.showerror("错误", "请输入有效的权重数值")
                
                # 将生成按钮放到weight_frame下面
                ctk.CTkButton(
                    dialog,
                    text=f"生成第{current_vol + 1}卷大纲", 
                    command=open_subsequent_volume_prompt,                 
                    font=("Microsoft YaHei", 14),
                    width=200
                ).pack(pady=5)

                # 显示后续卷提示词编辑器
                def show_subsequent_volume_prompt(vol_num, weight_value):
                    editor_dialog = ctk.CTkToplevel(self.master)
                    editor_dialog.title(f"编辑第{vol_num}卷大纲生成提示词")
                    editor_dialog.geometry("800x600")
                    editor_dialog.transient(self.master)
                    editor_dialog.grab_set()
                    editor_dialog.attributes('-topmost', True)  # 设置为置顶窗口
                    
                    # 禁止最小化窗口
                    editor_dialog.protocol("WM_ICONIFY_WINDOW", lambda: editor_dialog.deiconify())
                    
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
                    # 解析小说设定以获取所有模块的完整内容
                    full_parsed_setting = parse_architecture_file(novel_setting)

                    # 为当前卷提取特定模块的内容
                    parsed_setting = {}
                    for key, content in full_parsed_setting.items():
                        if key in ["volume_mission_statement", "plotline_and_progression", "narrative_style"]:
                            parsed_setting[key] = extract_volume_specific_module_content(content, vol_num)
                        else:
                            # 对于非分卷模块（如模块二和模块四），直接使用
                            parsed_setting[key] = content
                    
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
 
                    # 创建LLM适配器
                    interface_format = self.interface_format_var.get().strip()
                    api_key = self.api_key_var.get().strip()
                    base_url = self.base_url_var.get().strip()
                    model_name = self.model_name_var.get().strip()
                    temperature = self.temperature_var.get()
                    max_tokens = self.max_tokens_var.get()
                    timeout_val = self.safe_get_int(self.timeout_var, 600)
                    
                    llm_adapter = self.create_llm_adapter_with_current_config(step_name="生成分卷_生成分卷大纲")
                    if not llm_adapter:
                        self.safe_log("❌ 无法创建LLM适配器，中止后续卷大纲生成。")
                        editor_dialog.destroy()
                        return
                    self.safe_log(f"当前模型配置: {llm_adapter.get_config_name()}")
                    
                    # 使用传入的权重值获取角色
                    from novel_generator.volume import get_high_weight_characters
                    setting_characters = ""
                    try:
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
                                character_state=character_state,
                                characters_involved=characters_involved_detail,
                                previous_volume_outline=previous_volume_outline,
                                number_of_chapters=number_of_chapters,
                                word_number=word_number,
                                Total_volume_number=volume_count,
                                volume_number=vol_num,
                                genre=genre,
                                volume_design_format=volume_design_format,
                                **parsed_setting
                            )
                        else:
                            prompt = subsequent_volume_prompt.format(
                                topic=topic,
                                user_guidance=user_guidance,
                                characters_involved=characters_involved_detail,
                                previous_volume_outline=previous_volume_outline,
                                setting_characters=setting_characters,
                                number_of_chapters=number_of_chapters,
                                word_number=word_number,
                                Total_volume_number=volume_count,
                                volume_number=vol_num,
                                genre=genre,
                                volume_design_format=volume_design_format,
                                **parsed_setting
                            )
                        
                        # 创建提示词编辑框
                        prompt_text = ctk.CTkTextbox(editor_dialog, wrap="word", font=("Microsoft YaHei", 14))
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
                            font=("Microsoft YaHei", 14)
                        ).pack(side="left", padx=10)
                        
                        ctk.CTkButton(
                            btn_frame,
                            text="取消",
                            command=editor_dialog.destroy,
                            font=("Microsoft YaHei", 14)
                        ).pack(side="left", padx=10)

                        word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 14))
                        word_count_label.pack(side="right", padx=10)

                        def update_word_count(event=None):
                            text = prompt_text.get("1.0", "end-1c")
                            words = len(text)
                            word_count_label.configure(text=f"字数: {words}")

                        prompt_text.bind("<KeyRelease>", update_word_count)
                        update_word_count() # Initial count
                    
                    # 调用函数显示提示词编辑器
                    continue_with_prompt_editor(setting_characters, start_chap, end_chap)

            # 退出按钮放在底部
            exit_frame = ctk.CTkFrame(dialog)
            exit_frame.pack(pady=5)
            ctk.CTkButton(
                exit_frame,
                text="退出",
                command=dialog.destroy,
                font=("Microsoft YaHei", 14),
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
    章节重写UI界面 - 此功能已被工作流引擎取代，保留为空函数。
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return
    
    self.disable_button_safe(self.btn_rewrite_chapter) # 问题1：禁用按钮
    
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
        
    # --- 新增：调用辅助函数获取并校验内容 ---
    chapter_content_body = self._get_content_for_processing(chapter_num, "改写章节", check_word_count=False)
    if chapter_content_body is None:
        # 如果返回 None，说明用户取消了操作或内容为空
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
    # --- 结束新增 ---
        
    # 使用新的辅助函数获取标准化的章节文件路径
    chapter_file_path = get_chapter_filepath(filepath, chapter_num)

    # 为待改写文本添加章节标题
    header = self._get_formatted_chapter_header(chapter_num, filepath)
    chapter_content = f"{header}\n{chapter_content_body}"

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
    
    # 获取小说类型章节字数
    word_number = self.safe_get_int(self.word_number_var, 3000)
    genre = self.genre_var.get().strip()

    # 获取小说主题
    topic = "" # 默认值
    topic_pattern = re.compile(r'主题：\s*([^\n]+)', re.MULTILINE)
    topic_match = topic_pattern.search(novel_setting)
    if topic_match:
        topic = topic_match.group(1).strip()
    
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
    from novel_generator.chapter_directory_parser import get_next_chapter_info_from_blueprint
    
    next_chapter_info = get_next_chapter_info_from_blueprint(filepath, chapter_num)

    # 读取并提取当前章节的目录内容
    chapter_blueprint_content = f"（未找到第{chapter_num}章的章节目录）"
    if directory_content:
        # Helper function to extract the full text block for a specific chapter
        def get_chapter_blueprint_text(content, number):
            pattern = re.compile(rf"^第{number}章.*?(?=^第\d+章|\Z)", re.MULTILINE | re.DOTALL)
            match = pattern.search(content)
            return match.group(0).strip() if match else f"（未找到第{number}章的章节目录）"
        chapter_blueprint_content = get_chapter_blueprint_text(directory_content, chapter_num)

    # 新增：获取章节字数
    chapter_word_count = len(chapter_content)
    chars_to_add = word_number - chapter_word_count

    # 获取审校时设定的字数范围
    if hasattr(self, 'last_review_word_range') and self.last_review_word_range:
        word_min, word_max = self.last_review_word_range
        self.safe_log(f"ℹ️ 使用审校时设定的字数范围进行改写: {word_min} - {word_max} 字。")
    else:
        # 如果没有找到，则根据主界面设置动态计算
        try:
            base_word_count = int(self.word_number_var.get())
            word_min = int(base_word_count * 0.8)
            word_max = int(base_word_count * 1.5)
            self.safe_log(f"ℹ️ 未找到审校设定，根据主界面'每章字数'({base_word_count})动态设定改写范围: {word_min} - {word_max} 字。")
        except (ValueError, TypeError):
            # 如果主界面设置也无效，则使用最终的硬编码默认值
            word_min = 3200
            word_max = 4800
            self.safe_log(f"⚠️ 无法获取主界面'每章字数'，使用默认改写范围: {word_min} - {word_max} 字。")

    try:
        prompt_text = chapter_rewrite_prompt.format(
            novel_number=chapter_num,
            chapter_title=chapter_title,
            word_number=word_number,
            genre=genre,
            chapter_blueprint_content=chapter_blueprint_content,
            user_guidance=user_guidance,
            volume_outline=volume_outline,
            global_summary=global_summary,
            一致性审校=consistency_review,
            raw_draft=chapter_content,
            章节字数=chapter_word_count,
            chars_to_add=chars_to_add,
            字数下限=word_min,
            字数上限=word_max,
            # 添加下一章信息的占位符
            next_novel_number=next_chapter_info.get('chapter_number', chapter_num + 1),
            next_chapter_title=next_chapter_info.get('chapter_title', ''),
            next_chapter_role=next_chapter_info.get('chapter_role', ''),
            next_chapter_purpose=next_chapter_info.get('chapter_purpose', ''),
            next_chapter_suspense_type=next_chapter_info.get('suspense_type', ''),
            next_chapter_emotion_evolution=next_chapter_info.get('emotion_evolution', ''),
            next_chapter_foreshadowing=next_chapter_info.get('foreshadowing', ''),
            next_chapter_plot_twist_level=next_chapter_info.get('plot_twist_level', ''),
            next_chapter_summary=next_chapter_info.get('chapter_summary', '')
        )
    except KeyError as e:
        self.handle_exception(f"构建改写提示词时出错：缺少键 {e}。请检查 prompt_definitions.py 中的 chapter_rewrite_prompt 是否包含所有必需的占位符。")
        self.enable_button_safe(self.btn_rewrite_chapter)
        return
    
    # 显示提示词编辑器
    self.show_rewrite_prompt_editor(prompt_text, chapter_num, filepath, chapter_file_path)

def show_rewrite_prompt_editor(self, prompt_text, chapter_num, filepath, chapter_file_path):
    """显示章节改写提示词编辑器"""
    dialog = ctk.CTkToplevel(self.master)
    dialog.title("改写章节提示词")
    dialog.geometry("800x600")
    dialog.transient(self.master)  # 使弹窗相对于主窗口
    dialog.grab_set()  # 使弹窗成为模态窗口，阻止与主窗口交互
    dialog.attributes('-topmost', True)  # 设置为置顶窗口
    
    # 禁止最小化窗口
    dialog.protocol("WM_ICONIFY_WINDOW", lambda: dialog.deiconify())

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

    word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 14))
    word_count_label.pack(side="right", padx=10)

    def update_word_count(event=None):
        text = textbox.get("1.0", "end-1c")
        words = len(text)
        word_count_label.configure(text=f"字数: {words}")

    textbox.bind("<KeyRelease>", update_word_count)
    update_word_count() # Initial count


def _reformat_text_if_needed(self, text):
    """
    Helper function to reformat text if the auto-reformat option is enabled.
    """
    if self.auto_reformat_var.get():
        return reformat_novel_text(text)
    return text

def execute_chapter_rewrite(self, prompt, chapter_num, filepath, chapter_file_path):
    """执行章节改写"""
    self.safe_log(f"开始改写第{chapter_num}章...")

    def rewrite_thread():
        try:
            from novel_generator.rewrite import rewrite_chapter
            from novel_generator.common import execute_with_polling
            from utils import save_string_to_txt

            def rewrite_task(llm_adapter, **kwargs):
                """Core logic for rewriting, to be passed to the polling executor."""
                generator = rewrite_chapter(
                    current_text=prompt,
                    filepath=filepath,
                    novel_number=chapter_num,
                    llm_adapter=llm_adapter,
                    log_func=self.safe_log
                )
                return "".join(chunk for chunk in generator)

            rewritten_content = execute_with_polling(
                gui_app=self,
                step_name="改写章节",
                target_func=rewrite_task,
                log_func=self.safe_log,
                context_info=f"第 {chapter_num} 章",
                is_manual_call=True
            )

            if rewritten_content:
                final_content = self._reformat_text_if_needed(rewritten_content)
                self.chapter_result.delete("0.0", "end")
                self.chapter_result.insert("0.0", final_content)
                
                try:
                    save_string_to_txt(final_content, chapter_file_path)
                    self.safe_log(f"✅ 第{chapter_num}章改写完成并已保存到 {os.path.basename(chapter_file_path)}")
                except Exception as e_save:
                    self.safe_log(f"❌ 第{chapter_num}章改写内容保存失败: {str(e_save)}")
            else:
                self.safe_log(f"❌ 第{chapter_num}章改写失败或返回为空。")
        except Exception as e:
            self.handle_exception(f"章节改写流程出错: {str(e)}")
        finally:
            self.enable_button_safe(self.btn_rewrite_chapter)
    
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
            dialog.geometry("800x650") # Adjusted height for buttons
            dialog.transient(self.master)
            dialog.grab_set()
            dialog.attributes('-topmost', True)  # 设置为置顶窗口
            
            # 禁止最小化窗口
            dialog.protocol("WM_ICONIFY_WINDOW", lambda: dialog.deiconify())
            
            # 添加剧情要点展示组件
            text_box = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 14))
            text_box.pack(fill="both", expand=True, padx=10, pady=10)
            
            # 读取并显示剧情要点文件
            plot_points_file = os.path.join(filepath, "剧情要点.txt")
            if os.path.exists(plot_points_file):
                with open(plot_points_file, 'r', encoding='utf-8') as f:
                    text_box.insert("0.0", f.read())
            else:
                text_box.insert("0.0", "未找到剧情要点文件")

            # 按钮框架
            button_frame = ctk.CTkFrame(dialog)
            button_frame.pack(pady=10)

            # 保存按钮
            def save_content():
                content = text_box.get("0.0", "end-1c")
                try:
                    with open(plot_points_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    self.safe_log(f"✅ 剧情要点已保存到 {plot_points_file}")
                    messagebox.showinfo("成功", "剧情要点已保存", parent=dialog)
                except Exception as e_save:
                    self.safe_log(f"❌ 保存剧情要点失败: {str(e_save)}")
                    messagebox.showerror("错误", f"保存失败: {str(e_save)}", parent=dialog)
            
            save_button = ctk.CTkButton(button_frame, text="保存", command=save_content, font=("Microsoft YaHei", 14))
            save_button.pack(side="left", padx=10)

            # 退出按钮
            exit_button = ctk.CTkButton(button_frame, text="退出", command=dialog.destroy, font=("Microsoft YaHei", 14))
            exit_button.pack(side="left", padx=10)
                
        except Exception as e:
            self.handle_exception(f"显示剧情要点时出错: {str(e)}")
    
    threading.Thread(target=task, daemon=True).start()

def show_consistency_check_results_ui(self):
    """
    显示一致性审校结果UI界面
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        try:
            # 创建一致性审校结果展示窗口
            dialog = ctk.CTkToplevel(self.master)
            dialog.title("一致性审校结果")
            dialog.geometry("800x650") # Adjusted height for buttons
            dialog.transient(self.master)
            dialog.grab_set()
            dialog.attributes('-topmost', True)  # 设置为置顶窗口
            
            # 禁止最小化窗口
            dialog.protocol("WM_ICONIFY_WINDOW", lambda: dialog.deiconify())
            
            # 添加文本展示组件
            text_box = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 14))
            text_box.pack(fill="both", expand=True, padx=10, pady=10)
            
            # 读取并显示一致性审校文件
            consistency_file = os.path.join(filepath, "一致性审校.txt")
            if os.path.exists(consistency_file):
                with open(consistency_file, 'r', encoding='utf-8') as f:
                    text_box.insert("0.0", f.read())
            else:
                text_box.insert("0.0", "未找到一致性审校.txt文件")

            # 按钮框架
            button_frame = ctk.CTkFrame(dialog)
            button_frame.pack(pady=10)

            # 保存按钮
            def save_content():
                content = text_box.get("0.0", "end-1c")
                try:
                    with open(consistency_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    self.safe_log(f"✅ 一致性审校结果已保存到 {consistency_file}")
                    messagebox.showinfo("成功", "一致性审校结果已保存", parent=dialog)
                except Exception as e_save:
                    self.safe_log(f"❌ 保存一致性审校结果失败: {str(e_save)}")
                    messagebox.showerror("错误", f"保存失败: {str(e_save)}", parent=dialog)
            
            save_button = ctk.CTkButton(button_frame, text="保存", command=save_content, font=("Microsoft YaHei", 14))
            save_button.pack(side="left", padx=10)

            # 退出按钮
            exit_button = ctk.CTkButton(button_frame, text="退出", command=dialog.destroy, font=("Microsoft YaHei", 14))
            exit_button.pack(side="left", padx=10)
                
        except Exception as e:
            self.handle_exception(f"显示一致性审校结果时出错: {str(e)}")
    
    threading.Thread(target=task, daemon=True).start()

# 检查是否定义了 finalize_chapter_ui，如果没有则补充一个空实现，防止 ImportError

def finalize_chapter_ui(self):
    """
    章节定稿UI界面 - 此功能已被工作流引擎取代，保留为空函数。
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return
        
    chap_num_str = self.chapter_num_var.get().strip()
    if not chap_num_str:
        messagebox.showwarning("警告", "请输入要定稿的章节号")
        return
    try:
        chap_num = int(chap_num_str)
    except ValueError:
        messagebox.showerror("错误", "无效的章节号")
        return

    # --- 检查内容来源，并调用辅助函数获取并校验内容 ---
    editor_content = self.chapter_result.get("0.0", "end").strip()
    started_with_editor_content = bool(editor_content)
    
    pure_chapter_text = self._get_content_for_processing(chap_num, "章节定稿", check_word_count=True)
    if pure_chapter_text is None:
        return # 用户取消或内容为空
    # --- 结束新增 ---

    logging.info("--- 按照四步定稿流程定稿 ---")
    self.disable_button_safe(self.btn_finalize_chapter)
    confirm = messagebox.askyesno("确认", "确定要执行章节定稿流程吗？\n这将依次执行：\n1. 更新前情摘要\n2. 更新角色状态\n3. 整合伏笔内容\n4. 提取剧情要点")
    if not confirm:
        logging.info("--- User cancelled chapter finalization ---")
        self.enable_button_safe(self.btn_finalize_chapter)
        self.safe_log("❌ 用户取消了章节定稿流程。")
        return

    def execute_finalization_steps(started_with_editor_content):
        def task():
            try:
                from novel_generator.common import execute_with_polling, invoke_stream_with_cleaning
                from novel_generator.character_state_updater import update_character_states
                from novel_generator.knowledge import process_and_store_foreshadowing
                from prompt_definitions import summary_prompt, plot_points_extraction_prompt
                from utils import save_string_to_txt

                self.safe_log(f"🚀 开始执行第 {chap_num} 章定稿流程...")

                # --- 准备工作 ---
                self.safe_log("  [0/4] 准备输入数据...")
                chapter_file = get_chapter_filepath(filepath, chap_num)
                summary_file = os.path.join(filepath, "前情摘要.txt")
                character_state_file = os.path.join(filepath, "角色状态.txt")
                plot_points_file = os.path.join(filepath, "剧情要点.txt")
                directory_file = os.path.join(filepath, "章节目录.txt")

                header = self._get_formatted_chapter_header(chap_num, filepath)
                chapter_text = f"{header}\n{pure_chapter_text}"
                global_summary = read_file(summary_file) if os.path.exists(summary_file) else ""
                directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""

                def get_chapter_blueprint_text(content, number):
                    pattern = re.compile(rf"^第{number}章.*?(?=^第\d+章|\Z)", re.MULTILINE | re.DOTALL)
                    match = pattern.search(content)
                    return match.group(0).strip() if match else ""
                
                current_chapter_blueprint = get_chapter_blueprint_text(directory_content, chap_num)
                if not current_chapter_blueprint:
                    self.safe_log(f"❌ 未能在章节目录中找到第 {chap_num} 章的信息。定稿流程中止。")
                    return

                chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
                plain_title = chapter_info.get('chapter_title', '无标题')
                chapter_title = f"第{chap_num}章 {plain_title}"
                foreshadowing_str = chapter_info.get('foreshadowing', "")

                # --- 步骤 1: 更新前情摘要 ---
                self.safe_log("  [1/4] 正在更新前情摘要...")
                def summary_task(llm_adapter, **kwargs):
                    prompt = summary_prompt.format(chapter_text=chapter_text, global_summary=global_summary)
                    return "".join(chunk for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, log_func=self.safe_log))
                
                new_summary = execute_with_polling(self, "定稿章节_生成章节摘要", summary_task, self.safe_log, context_info=f"第 {chap_num} 章", is_manual_call=True)
                if new_summary and new_summary.strip():
                    save_string_to_txt(new_summary, summary_file)
                    self.safe_log("    ✅ 前情摘要已更新。")
                else:
                    self.safe_log("    ⚠️ 更新前情摘要失败。")

                # --- 步骤 2: 更新角色状态 ---
                self.safe_log("  [2/4] 正在更新角色状态...")
                
                # [DEPRECATED] The async version is no longer needed as polling handles threading.
                # We now call the synchronous version directly within the polling executor.
                def character_task(llm_adapter, **kwargs):
                    # 在此作用域内定义所需变量
                    genre = self.genre_var.get()
                    volume_count = self.safe_get_int(self.volume_count_var, 0)
                    num_chapters = self.safe_get_int(self.num_chapters_var, 0)
                    volume_number = 1
                    volume_file = os.path.join(filepath, "分卷大纲.txt")
                    if os.path.exists(volume_file):
                        from novel_generator.volume import find_volume_for_chapter
                        volume_number = find_volume_for_chapter(read_file(volume_file), chap_num)

                    return update_character_states(
                        chapter_text, chapter_title, chap_num, filepath, llm_adapter,
                        current_chapter_blueprint, self.safe_log,
                        genre, volume_count, num_chapters, volume_number
                    )

                result = execute_with_polling(self, "定稿章节_更新角色状态", character_task, self.safe_log, context_info=f"第 {chap_num} 章", is_manual_call=True)

                if result and result.get("status") == "success":
                    if result.get("character_state", "").strip():
                        self.safe_log("    ✅ 角色状态和角色数据库已更新。")
                    else:
                        self.safe_log("    ℹ️ 角色状态更新成功，但本章未涉及角色状态变化。")
                else:
                    message = result.get("message", "未知错误") if result else "任务被中断或失败"
                    self.safe_log(f"    ⚠️ 更新角色状态失败: {message}")

                # --- 步骤 3: 向量化伏笔内容 ---
                self.safe_log("  [3/4] 正在处理和向量化伏笔内容...")
                if foreshadowing_str:
                    def foreshadow_task(llm_adapter, **kwargs):
                        info = {'novel_number': chap_num, 'chapter_title': chapter_title, 'foreshadowing': foreshadowing_str}
                        done_event = threading.Event()
                        def run():
                            try:
                                process_and_store_foreshadowing(chapter_text, info, filepath, llm_adapter, self.safe_log)
                            finally:
                                done_event.set()
                        threading.Thread(target=run, daemon=True).start()
                        done_event.wait()
                        return True
                    
                    execute_with_polling(self, "定稿章节_整合伏笔", foreshadow_task, self.safe_log, context_info=f"第 {chap_num} 章", is_manual_call=True)
                    self.safe_log("    ✅ 伏笔内容处理和向量化完成。")
                else:
                    self.safe_log("    ℹ️ 本章无伏笔信息，跳过。")

                # --- 步骤 4: 提取剧情要点 ---
                self.safe_log("  [4/4] 正在提取剧情要点...")
                def plot_points_task(llm_adapter, **kwargs):
                    previous_plot_points = ""
                    if chap_num > 1 and os.path.exists(plot_points_file):
                        content = read_file(plot_points_file)
                        match = re.search(rf"(##\s*第\s*{chap_num-1}\s*章[\s\S]*?)(?=\n##\s*第|$)", content)
                        if match: previous_plot_points = match.group(1).strip()
                    
                    prompt = plot_points_extraction_prompt.format(
                        novel_number=chap_num, chapter_title=chapter_title, chapter_text=chapter_text,
                        current_chapter_blueprint=current_chapter_blueprint, global_summary=global_summary,
                        plot_points=previous_plot_points
                    )
                    return "".join(chunk for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, log_func=self.safe_log))

                plot_points = execute_with_polling(self, "定稿章节_提取剧情要点", plot_points_task, self.safe_log, context_info=f"第 {chap_num} 章", is_manual_call=True)
                if plot_points:
                    existing_content = read_file(plot_points_file) if os.path.exists(plot_points_file) else ""
                    header = f"## 第 {chap_num} 章 《{plain_title}》"
                    pattern = re.compile(f"\n\n## 第 {chap_num} 章.*?(?=\n\n## 第|$)", re.DOTALL)
                    if pattern.search(existing_content):
                        existing_content = pattern.sub("", existing_content)
                    new_content = existing_content.rstrip() + f"\n\n{header}\n{plot_points}"
                    save_string_to_txt(new_content, plot_points_file)
                    self.safe_log("    ✅ 剧情要点已提取并更新。")
                else:
                    self.safe_log("    ⚠️ 提取剧情要点失败。")

                self.safe_log(f"✅ 第 {chap_num} 章定稿流程全部完成！")
                
                # --- 新增：根据内容来源决定是否回写文件 ---
                if started_with_editor_content:
                    if hasattr(self, "chapter_result"):
                        final_text = self.chapter_result.get("0.0", "end").strip()
                        reformatted_text = self._reformat_text_if_needed(final_text)
                        save_string_to_txt(reformatted_text, chapter_file)
                        
                        # --- 线程安全UI更新 ---
                        def update_ui_with_reformatted_text():
                            self.chapter_result.delete("0.0", "end")
                            self.chapter_result.insert("0.0", reformatted_text)
                        self.master.after(0, update_ui_with_reformatted_text)
                        # --- 结束线程安全UI更新 ---

                        self.safe_log(f"    ✅ 已将编辑框内容更新至章节文件: {os.path.basename(chapter_file)}")
                else:
                    self.safe_log(f"    ℹ️ 编辑框为空，跳过文件回写以保护原始章节内容。")
                # --- 结束新增 ---

                next_chapter = chap_num + 1
                # --- 线程安全UI更新 ---
                self.master.after(0, lambda: self.chapter_num_var.set(str(next_chapter)))
                # --- 结束线程安全UI更新 ---
                try:
                    from config_manager import load_config, save_config
                    config = load_config()
                    config.setdefault('other_params', {})['chapter_num'] = next_chapter
                    if save_config(config):
                        self.safe_log(f"✅ 章节号已更新为：{next_chapter}，配置已自动保存。")
                except Exception as e:
                    self.safe_log(f"❌ 自动保存配置文件时出错: {str(e)}")

            except Exception as e:
                self.handle_exception(f"执行定稿流程时出错: {str(e)}")
            finally:
                self.enable_button_safe(self.btn_finalize_chapter)

        threading.Thread(target=task, daemon=True).start()
    execute_finalization_steps(started_with_editor_content)

def get_high_weight_characters_from_json(self, filepath, weight_threshold, chapter_range=20):
    """
    直接从 角色状态.md 文件中读取、筛选并格式化权重大于等于阈值的角色信息。
    增加章节范围筛选。
    """
    character_states_text = []
    try:
        from novel_generator.json_utils import load_store
        character_store = load_store(filepath, "character_state_collection")

        if not character_store:
            self.safe_log("ℹ️ 角色状态文件 (角色状态.md) 不存在或为空。")
            return ""

        for char_id, char_data in character_store.items():
            try:
                # --- 更灵活的权重解析，兼容嵌套和非嵌套格式 ---
                weight_str = "0"  # 默认值
                char_name = char_data.get("姓名", f"ID {char_id}") # 提前获取用于日志

                if "基础信息" in char_data and "角色权重" in char_data["基础信息"]:
                    weight_str = char_data["基础信息"]["角色权重"]
                elif "角色权重" in char_data:
                    weight_str = char_data["角色权重"]
                
                weight_match = re.search(r'\d+', str(weight_str))
                if not weight_match:
                    self.safe_log(f"⚠️ 角色 {char_name} 的权重值 '{weight_str}' 无效或未找到，将跳过。")
                    continue
                
                char_weight = int(weight_match.group(0))

                # --- 筛选逻辑 ---
                # 1. 权重筛选
                if char_weight >= weight_threshold:
                    # 2. 章节范围筛选
                    last_chapter_num = 0
                    # 优先从基础信息获取
                    last_chapter_str = char_data.get("基础信息", {}).get("最后出场章节", "")
                    if last_chapter_str:
                        match = re.search(r'\d+', last_chapter_str)
                        if match:
                            last_chapter_num = int(match.group(0))
                    
                    # 如果没有，则从位置轨迹中回退查找
                    if last_chapter_num == 0:
                        location_tracks = char_data.get("位置轨迹", [])
                        if location_tracks:
                            track_chapters = []
                            for track in location_tracks:
                                if isinstance(track, dict):
                                    chap_str = track.get("所在章节", "0")
                                    match = re.search(r'\d+', chap_str)
                                    if match:
                                        track_chapters.append(int(match.group(0)))
                            if track_chapters:
                                last_chapter_num = max(track_chapters)

                    # 获取当前最新章节号
                    all_chars = load_store(filepath, "character_state_collection").values()
                    latest_chap = 0
                    for c in all_chars:
                        lcs = c.get("基础信息", {}).get("最后出场章节", "0")
                        m = re.search(r'\d+', lcs)
                        if m:
                            latest_chap = max(latest_chap, int(m.group(0)))

                    if last_chapter_num >= latest_chap - chapter_range:
                        # --- 更灵活的名称解析，兼容“名称”和“姓名” ---
                        char_name = char_data.get("名称", char_data.get("姓名", "未知"))
                        self.safe_log(f"✅ 提取符合条件的角色: {char_name} (ID: {char_id}, 权重: {char_weight})")

                    # --- 动态、灵活地重组角色状态文本 ---
                    # 修正：直接使用 char_id，因为它已经包含了 "ID"
                    state_text = f"{char_id}：{char_name}\n"
                    # 遍历所有可能的字段并添加到文本中
                    for key, value in char_data.items():
                        # 修正：避免重复打印已在标题行处理的字段
                        if key in ["名称", "姓名", "角色权重", "ID"]:
                            continue
                        if isinstance(value, list):
                            if value:
                                state_text += f"{key}：\n"
                                for item in value:
                                    state_text += f"  - {item}\n"
                        elif isinstance(value, dict):
                             if value:
                                state_text += f"{key}：\n"
                                for sub_key, sub_value in value.items():
                                    state_text += f"  {sub_key}：{sub_value}\n"
                        else:
                            if value:
                                state_text += f"{key}：{value}\n"
                    
                    state_text += f"角色权重：{char_weight}\n"
                    character_states_text.append(state_text)

            except (ValueError, TypeError) as e:
                char_name = char_data.get("姓名", "未知")
                self.safe_log(f"⚠️ 处理角色 {char_name} (ID: {char_id}) 的数据时出错: {e}，将跳过")
                continue
        
        self.safe_log(f"完成角色提取，共找到 {len(character_states_text)} 个符合权重条件的角色。")
        return "\n\n".join(character_states_text)

    except Exception as e:
        self.handle_exception(f"从JSON提取高权重角色时出错: {str(e)}")
        return ""

def generate_novel_architecture_ui(self):
    """
    处理小说架构生成的UI函数，增加了提示词编辑功能。
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    self.disable_button_safe(self.btn_generate_architecture)

    def prepare_and_show_editor():
        """准备组合提示词并显示编辑器"""
        try:
            # 获取所有必要的输入
            topic = self.topic_text.get("0.0", "end").strip()
            genre = self.genre_var.get().strip()

            # --- 输入验证 ---
            if not topic:
                messagebox.showwarning("输入缺失", "请填写“小说主题”后再生成架构。")
                self.enable_button_safe(self.btn_generate_architecture)
                return
            if not genre:
                messagebox.showwarning("输入缺失", "请选择“小说类型”后再生成架构。")
                self.enable_button_safe(self.btn_generate_architecture)
                return
            # --- 验证结束 ---

            total_volume_number = self.safe_get_int(self.volume_count_var, 3)
            num_chapters = self.safe_get_int(self.num_chapters_var, 10)
            word_number = self.safe_get_int(self.word_number_var, 3000)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            # 从 prompt_definitions.py 加载新的五步提示词
            from prompt_definitions import (
                architecture_step1_mission_prompt,
                architecture_step2_worldview_prompt,
                architecture_step3_plot_prompt,
                architecture_step4_character_prompt,
                architecture_step5_style_prompt
            )

            # 将所有prompt拼接起来，让用户有一个整体的感知和编辑入口。
            full_prompt_template = f"""\
# 这是一个组合提示词模板，实际生成时会分步执行。
# 您可以在此一次性编辑所有阶段的输入。

#---PROMPT_SEPARATOR_STEP1---#
# 步骤一：分卷使命宣言
#---PROMPT_SEPARATOR_STEP1---#
{architecture_step1_mission_prompt}

#---PROMPT_SEPARATOR_STEP2---#
# 步骤二：世界观与冲突发生器
#---PROMPT_SEPARATOR_STEP2---#
{architecture_step2_worldview_prompt}

#---PROMPT_SEPARATOR_STEP3---#
# 步骤三：情节线类型与主角进程
#---PROMPT_SEPARATOR_STEP3---#
{architecture_step3_plot_prompt}

#---PROMPT_SEPARATOR_STEP4---#
# 步骤四：角色与核心驱动力
#---PROMPT_SEPARATOR_STEP4---#
{architecture_step4_character_prompt}

#---PROMPT_SEPARATOR_STEP5---#
# 步骤五：叙事风格与最终规划
#---PROMPT_SEPARATOR_STEP5---#
{architecture_step5_style_prompt}
"""
            # 格式化已知变量用于显示，同时用友好提示替换后端占位符
            display_prompt = full_prompt_template.format(
                genre=genre,
                Total_volume_number=total_volume_number,
                number_of_chapters=num_chapters,
                word_number=word_number,
                topic=topic if topic else "（未提供）",
                user_guidance=user_guidance if user_guidance else "（无）",
                # 用友好提示替换后端占位符，避免用户困惑
                step1_result="（此部分将由上一步自动生成）",
                step2_result="（此部分将由上一步自动生成）",
                step3_result="（此部分将由上一步自动生成）",
                step4_result="（此部分将由上一步自动生成）"
            )
            # 清理可能存在的双大括号
            display_prompt = display_prompt.replace("{{", "{").replace("}}", "}")

            # 在主线程中显示编辑器
            self.master.after(0, lambda: show_architecture_prompt_editor(display_prompt))

        except Exception as e:
            self.handle_exception(f"准备小说架构提示词时出错: {str(e)}")
            self.enable_button_safe(self.btn_generate_architecture)

    def show_architecture_prompt_editor(prompt_text):
        """显示一个顶级窗口用于编辑提示词"""
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("编辑小说架构生成提示词")
        dialog.geometry("800x600")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.attributes('-topmost', True)

        textbox = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 14))
        textbox.pack(fill="both", expand=True, padx=10, pady=10)
        textbox.insert("0.0", prompt_text)

        def on_confirm():
            """处理确认按钮点击事件"""
            modified_prompt = textbox.get("0.0", "end").strip()
            dialog.destroy()
            
            # 解析用户修改后的提示词
            prompts = {}
            try:
                prompts['step1'] = re.search(r'#---PROMPT_SEPARATOR_STEP1---#\n(.*?)\n#---PROMPT_SEPARATOR_STEP2---#', modified_prompt, re.DOTALL).group(1).strip()
                prompts['step2'] = re.search(r'#---PROMPT_SEPARATOR_STEP2---#\n(.*?)\n#---PROMPT_SEPARATOR_STEP3---#', modified_prompt, re.DOTALL).group(1).strip()
                prompts['step3'] = re.search(r'#---PROMPT_SEPARATOR_STEP3---#\n(.*?)\n#---PROMPT_SEPARATOR_STEP4---#', modified_prompt, re.DOTALL).group(1).strip()
                prompts['step4'] = re.search(r'#---PROMPT_SEPARATOR_STEP4---#\n(.*?)\n#---PROMPT_SEPARATOR_STEP5---#', modified_prompt, re.DOTALL).group(1).strip()
                prompts['step5'] = re.search(r'#---PROMPT_SEPARATOR_STEP5---#\n(.*)', modified_prompt, re.DOTALL).group(1).strip()

                # 将用户编辑过的提示中的友好提示替换回后端占位符
                for key, prompt in prompts.items():
                    prompts[key] = prompt.replace("（此部分将由上一步自动生成）", "{" + key.replace('step', 'step_') + "result}")
                    # 这是一个小修正，确保占位符格式正确，例如 step1 -> {step1_result}
                    if key == 'step2':
                        prompts[key] = prompt.replace("（此部分将由上一步自动生成）", "{step1_result}")
                    elif key == 'step3':
                        prompts[key] = prompt.replace("（此部分将由上一步自动生成）", "{step1_result}\n{step2_result}")
                    elif key == 'step4':
                        prompts[key] = prompt.replace("（此部分将由上一步自动生成）", "{step1_result}\n{step2_result}\n{step3_result}")
                    elif key == 'step5':
                        prompts[key] = prompt.replace("（此部分将由上一步自动生成）", "{step1_result}\n{step2_result}\n{step3_result}\n{step4_result}")

            except AttributeError:
                messagebox.showerror("错误", "无法解析编辑后的提示词。请确保保留了'#---PROMPT_SEPARATOR_STEP...---#'分隔符。")
                self.enable_button_safe(self.btn_generate_architecture)
                return

            # 启动生成线程
            generate_with_custom_prompts(prompts)

        def on_cancel():
            """处理取消按钮点击事件"""
            dialog.destroy()
            self.enable_button_safe(self.btn_generate_architecture)

        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=10)

        ctk.CTkButton(btn_frame, text="确认生成", command=on_confirm).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=5)

    def generate_with_custom_prompts(prompts):
        """使用用户编辑后的多个提示词执行生成"""
        def task():
            try:
                # 获取通用参数
                topic = self.topic_text.get("0.0", "end").strip()
                genre = self.genre_var.get().strip()
                total_volume_number = self.safe_get_int(self.volume_count_var, 3)
                num_chapters = self.safe_get_int(self.num_chapters_var, 10)
                word_number = self.safe_get_int(self.word_number_var, 3000)
                user_guidance = self.user_guide_text.get("0.0", "end").strip()

                self.safe_log("开始使用自定义提示词生成小说架构...")
                
                # 调用核心生成函数，传入解析后的提示词字典
                Novel_architecture_generate(
                    main_window_instance=self,
                    topic=topic,
                    genre=genre,
                    Total_volume_number=total_volume_number,
                    number_of_chapters=num_chapters,
                    word_number=word_number,
                    filepath=filepath,
                    user_guidance=user_guidance,
                    log_func=self.safe_log,
                    custom_prompts=prompts
                )
                
                final_architecture_file = os.path.join(filepath, "小说设定.txt")
                time.sleep(0.1)
                if os.path.exists(final_architecture_file) and os.path.getsize(final_architecture_file) > 0:
                    self.safe_log("✅ 小说架构生成完成。请在 '小说架构' 标签页查看或编辑。")
                else:
                    self.safe_log("ℹ️ 小说架构生成未完成或失败，请检查以上日志获取详细信息。")
                    
            except PermissionError as e:
                error_msg = f"文件访问权限错误: {str(e)}\n请关闭所有可能正在使用相关文件的应用程序，然后重试。"
                self.safe_log(f"❌ {error_msg}")
            except Exception as e:
                self.handle_exception(f"生成小说架构时出错: {str(e)}")
            finally:
                self.enable_button_safe(self.btn_generate_architecture)
        
        threading.Thread(target=task, daemon=True).start()

    # 启动准备和显示编辑器的线程
    threading.Thread(target=prepare_and_show_editor, daemon=True).start()

def generate_chapter_blueprint_ui(self):
    """
    章节目录生成UI - 此功能已被工作流引擎取代，保留为空函数。
    """
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

            from customtkinter.windows.widgets.scaling import scaling_tracker

            dialog = ctk.CTkToplevel(self.master)
            dialog.title("章节目录生成")
            dialog.geometry("480x350")
            dialog.transient(self.master)
            dialog.grab_set()
            dialog.attributes('-topmost', True)  # 设置为置顶窗口

            def on_dialog_close():
                """Custom close handler to fix the TclError."""
                try:
                    if dialog in scaling_tracker.ScalingTracker.window_dpi_scaling_dict:
                        del scaling_tracker.ScalingTracker.window_dpi_scaling_dict[dialog]
                except Exception:
                    pass  # Ignore errors during cleanup
                dialog.destroy()

            # 禁止最小化窗口
            dialog.protocol("WM_ICONIFY_WINDOW", lambda: dialog.deiconify())
            dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)  # Handle 'X' button

            # 章节数量输入
            entry_frame = ctk.CTkFrame(dialog)
            entry_frame.pack(pady=(20, 0))
            ctk.CTkLabel(entry_frame, text="准备生成章节数量：", font=("Microsoft YaHei", 14)).pack(side="left")
            chapter_count_var = ctk.StringVar(value="20")  # UI输入框的默认值
            chapter_count_entry = ctk.CTkEntry(entry_frame, textvariable=chapter_count_var, width=60)
            chapter_count_entry.pack(side="left", padx=(0, 10))

            # 生成进度提示
            if last_chapter == 0:
                progress_text = "当前尚未生成任何章节。"
            else:
                progress_text = f"当前已生成至第{last_chapter}章。"
            ctk.CTkLabel(dialog, text=progress_text, font=("Microsoft YaHei", 14), text_color="#888888").pack(pady=(5, 0))

            # 1. 获取基本信息
            # get_volume_progress 返回的是基于 last_chapter 的信息
            current_vol_based_on_last, last_chapter, _, _, _, _ = get_volume_progress(filepath)

            # 2. 重新计算下一章的正确卷号
            next_chapter_num = last_chapter + 1
            # 使用 find_current_volume 来确定下一章真正属于哪一卷
            next_volume_num, _ = find_current_volume(next_chapter_num, volumes)
            
            logging.info(f"UI-Dialog: last_chapter={last_chapter}, next_chapter_num={next_chapter_num}, calculated next_volume_num={next_volume_num}")

            # 3. 生成UI文本
            if last_chapter == 0:
                progress_text = "当前尚未生成任何章节。"
                info_text = f"准备从 第{next_volume_num}卷 第{next_chapter_num}章 开始生成"
            else:
                progress_text = f"当前已生成至第{last_chapter}章。"
                info_text = f"准备从 第{next_volume_num}卷 第{next_chapter_num}章 开始生成"

            # 移除旧的标签，避免重复
            for widget in dialog.winfo_children():
                if isinstance(widget, ctk.CTkLabel) and ("当前已生成" in widget.cget("text") or "准备从" in widget.cget("text")):
                    widget.destroy()

            ctk.CTkLabel(dialog, text=progress_text, font=("Microsoft YaHei", 14), text_color="#888888").pack(pady=(5, 0))
            ctk.CTkLabel(dialog, text=info_text, font=("Microsoft YaHei", 14)).pack(pady=(10, 0))

            # 4. 确定按钮行为和文本
            btn1_text = "生成所填数量章节目录"
            btn2_text = f"生成第{next_volume_num}卷章节目录"
            
            # 添加角色状态提取相关UI
            char_frame = ctk.CTkFrame(dialog)
            char_frame.pack(pady=(10, 0))
            
            ctk.CTkLabel(char_frame, text="提取前", font=("Microsoft YaHei", 14)).pack(side="left", padx=5)
            chapter_extract_var = ctk.StringVar(value="20")
            ctk.CTkEntry(char_frame, textvariable=chapter_extract_var, width=40, font=("Microsoft YaHei", 14)).pack(side="left", padx=5)
            ctk.CTkLabel(char_frame, text="章有出场，且权重大于", font=("Microsoft YaHei", 14)).pack(side="left", padx=5)
            weight_var = ctk.StringVar(value="80")
            ctk.CTkEntry(char_frame, textvariable=weight_var, width=40, font=("Microsoft YaHei", 14)).pack(side="left", padx=5)
            ctk.CTkLabel(char_frame, text="的角色状态", font=("Microsoft YaHei", 14)).pack(side="left", padx=5)

            btn_frame = ctk.CTkFrame(dialog)
            btn_frame.pack(pady=20)

            # ==================================================================
            # ===================== 核心逻辑修改区域开始 =====================
            # ==================================================================

            def handle_increment(volume_for_prompt: int):
                """处理增量生成，接收一个明确的卷号"""
                on_dialog_close()
                self.disable_button_safe(self.btn_generate_directory)
                
                # 直接将接收到的正确卷号传递给下一个函数
                prepare_and_show_editor(volume_for_prompt)

            def prepare_and_show_editor(correct_volume_num: int):
                """准备并显示提示词编辑器，接收一个明确的卷号"""
                def task():
                    try:
                        self.safe_log(f"正在为第 {correct_volume_num} 卷准备章节目录生成提示词...")
                        add_chapter_count = self.safe_get_int(chapter_count_var, 20)
                        user_guidance = self.user_guide_text.get("0.0", "end").strip()
                        
                        main_character_info = self.main_character_var.get()
                        try:
                            self.safe_log("开始提取高权重角色状态以供生成...")
                            weight_threshold = self.safe_get_int(weight_var, 80)
                            chapter_range = self.safe_get_int(chapter_extract_var, 20)
                            
                            # 调用新的、可靠的函数
                            high_weight_characters_info = get_high_weight_characters_from_json(self, filepath, weight_threshold, chapter_range)
                            
                            if high_weight_characters_info:
                                # 将检索到的角色信息和主角信息合并
                                main_character_info += "\n\n" + high_weight_characters_info
                                self.safe_log(f"已成功提取并合并高权重角色的状态信息。")
                            else:
                                self.safe_log("未找到符合条件的角色，或提取过程中出错。")

                        except Exception as e:
                            self.safe_log(f"提取角色状态时出错: {str(e)}")
                        
                        main_character = main_character_info # 更新将要传递的参数

                        last_chapter_before, _, _ = analyze_directory_status(filepath)
                        
                        # 从分卷大纲中获取正确的章节范围
                        volumes = analyze_volume_range(filepath)
                        vol_info = next((v for v in volumes if v['volume'] == correct_volume_num), None)
                        
                        start_chapter = last_chapter_before + 1
                        # 结合用户输入和分卷大纲来确定结束章节
                        user_end_chapter = start_chapter + add_chapter_count - 1
                        
                        if vol_info:
                            volume_end_chapter = vol_info['end']
                            # 取用户想要的章节数和当前卷剩余章节数中的较小值
                            end_chapter = min(user_end_chapter, volume_end_chapter)
                            self.safe_log(f"第 {correct_volume_num} 卷结束于 {volume_end_chapter} 章。用户请求生成到 {user_end_chapter} 章。最终生成范围: {start_chapter}-{end_chapter}")
                        else:
                            # 如果找不到分卷信息，则仅根据用户输入来计算
                            self.safe_log(f"警告：无法在分卷大纲中找到第 {correct_volume_num} 卷的信息，将仅根据用户输入生成。")
                            end_chapter = user_end_chapter

                        from novel_generator.chapter_blueprint import prepare_chapter_blueprint_prompt
                        # 直接使用传递进来的 correct_volume_num
                        prompt_text = prepare_chapter_blueprint_prompt(
                            filepath=filepath,
                            volume_number=correct_volume_num,
                            start_chapter=start_chapter,
                            end_chapter=end_chapter,
                            user_guidance=user_guidance,
                            main_character=main_character,
                            is_incremental=True
                        )
                        
                        self.master.after(0, lambda: show_chapter_blueprint_prompt_editor(prompt_text, add_chapter_count, main_character, correct_volume_num))

                    except Exception as e:
                        self.handle_exception(f"准备章节目录提示词时出错: {str(e)}")
                        self.enable_button_safe(self.btn_generate_directory)
                
                threading.Thread(target=task, daemon=True).start()

            def show_chapter_blueprint_prompt_editor(prompt_text, chapter_count, main_character, correct_volume_num):
                """显示提示词编辑器，并持有正确的卷号"""
                from customtkinter.windows.widgets.scaling import scaling_tracker
                editor_dialog = ctk.CTkToplevel(self.master)
                editor_dialog.title("编辑章节目录生成提示词")
                editor_dialog.geometry("800x600")
                editor_dialog.transient(self.master)
                editor_dialog.grab_set()
                editor_dialog.attributes('-topmost', True)

                def on_editor_close():
                    """Custom close handler for the editor to fix the KeyError."""
                    try:
                        if editor_dialog in scaling_tracker.ScalingTracker.window_dpi_scaling_dict:
                            del scaling_tracker.ScalingTracker.window_dpi_scaling_dict[editor_dialog]
                    except Exception:
                        pass  # Ignore errors during cleanup
                    editor_dialog.destroy()

                textbox = ctk.CTkTextbox(editor_dialog, wrap="word", font=("Microsoft YaHei", 14))
                textbox.pack(fill="both", expand=True, padx=10, pady=10)
                textbox.insert("0.0", prompt_text)

                def on_confirm():
                    modified_prompt = textbox.get("0.0", "end").strip()
                    on_editor_close()
                    execute_blueprint_generation_with_prompt(modified_prompt, chapter_count, main_character, correct_volume_num)

                def on_cancel():
                    """统一处理取消和关闭窗口事件"""
                    on_editor_close()
                    self.enable_button_safe(self.btn_generate_directory)
                    self.safe_log("ℹ️ 章节目录生成已取消。")

                editor_dialog.protocol("WM_DELETE_WINDOW", on_cancel)
                
                btn_frame = ctk.CTkFrame(editor_dialog)
                btn_frame.pack(pady=10)
                ctk.CTkButton(btn_frame, text="确认生成", command=on_confirm).pack(side="left", padx=5)
                ctk.CTkButton(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=5)

                # 恢复字数统计功能
                word_count_label = ctk.CTkLabel(btn_frame, text=f"字数: {len(prompt_text)}", font=("Microsoft YaHei", 14))
                word_count_label.pack(side="right", padx=10)
                def update_word_count(event=None):
                    text = textbox.get("1.0", "end-1c")
                    word_count_label.configure(text=f"字数: {len(text)}")
                textbox.bind("<KeyRelease>", update_word_count)


            def execute_blueprint_generation_with_prompt(custom_prompt, chapter_count, main_character, correct_volume_num):
                """执行生成，接收并使用正确的卷号"""
                def task():
                    try:
                        from novel_generator.chapter_blueprint import Chapter_blueprint_generate
                        from novel_generator.common import execute_with_polling

                        def blueprint_task(llm_adapter, **kwargs):
                            user_guidance = self.user_guide_text.get("0.0", "end").strip()
                            return Chapter_blueprint_generate(
                                llm_adapter=llm_adapter,
                                filepath=filepath,
                                number_of_chapters=chapter_count,
                                user_guidance=user_guidance,
                                start_from_volume=correct_volume_num,
                                generate_single=True,
                                save_interval=chapter_count,
                                main_character=main_character,
                                log_func=self.safe_log,
                                custom_prompt=custom_prompt
                            )

                        result = execute_with_polling(
                            gui_app=self,
                            step_name="生成目录_生成章节蓝图",
                            target_func=blueprint_task,
                            log_func=self.safe_log,
                            context_info=f"第 {correct_volume_num} 卷",
                            is_manual_call=True
                        )

                        if result:
                            self.safe_log("✅ 章节目录生成完成")
                            self.master.after(0, show_dialog)
                        else:
                            self.safe_log("❌ 章节目录生成失败或被中断。")
                    except Exception as e:
                        self.handle_exception(f"章节目录生成流程时发生错误: {str(e)}")
                    finally:
                        self.enable_button_safe(self.btn_generate_directory)
                
                threading.Thread(target=task, daemon=True).start()

            def handle_volume(volume_to_generate: int):
                """处理整卷生成，接收一个明确的卷号"""
                dialog.destroy()
                self.disable_button_safe(self.btn_generate_directory)
                def generation_thread():
                    try:
                        # ... (LLM参数和角色提取逻辑不变)
                        
                        from novel_generator.chapter_blueprint import Chapter_blueprint_generate
                        result = Chapter_blueprint_generate(
                            # ... (其他参数)
                            # 关键：使用从UI传递下来的正确卷号
                            start_from_volume=volume_to_generate,
                            generate_single=False, # 整卷生成
                            # ...
                        )
                        # ...
                    finally:
                        self.enable_button_safe(self.btn_generate_directory)
                threading.Thread(target=generation_thread, daemon=True).start()

            # 关键修改：使用 lambda 将计算出的 next_volume_num 绑定到按钮命令
            ctk.CTkButton(
                btn_frame,
                text=btn1_text,
                command=lambda: handle_increment(next_volume_num),
                font=("Microsoft YaHei", 14)
            ).pack(side="left", padx=10)

            # 根据用户反馈，删除“生成整卷”按钮
            # if len(volumes) > 0:
            #     ctk.CTkButton(
            #         btn_frame,
            #         text=btn2_text,
            #         command=lambda: handle_volume(next_volume_num),
            #         font=("Microsoft YaHei", 14)
            #     ).pack(side="left", padx=10)

            ctk.CTkButton(
                btn_frame,
                text="退出",
                command=on_dialog_close,
                font=("Microsoft YaHei", 14)
            ).pack(side="left", padx=10)
            
            # ==================================================================
            # ====================== 核心逻辑修改区域结束 ======================
            # ==================================================================

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
            llm_adapter = self.create_llm_adapter_with_current_config(step_name="生成目录_生成章节蓝图")
            if not llm_adapter:
                self.safe_log("❌ 无法创建LLM适配器，中止章节目录生成。")
                return

            result = Chapter_blueprint_generate(
                llm_adapter=llm_adapter,
                number_of_chapters=number_of_chapters,
                filepath=filepath,
                user_guidance=user_guidance,
                start_from_volume=start_from_volume,
                generate_single=generate_single,
                log_func=self.safe_log
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

def get_initial_prompt(self, for_review=False, num_history_chapters=0, word_count_min=None, word_count_max=None):
    """
    A helper function to build the initial prompt for chapter draft generation or consistency review.
    Now includes logic to fetch historical chapter content and accept word count overrides.
    """
    try:
        filepath = self.filepath_var.get().strip()
        chap_num = self.safe_get_int(self.chapter_num_var, 1)
        
        directory_file = os.path.join(filepath, "章节目录.txt")
        directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""
        
        # Extract full blueprint text for current and next chapters
        current_chapter_blueprint = get_chapter_blueprint_text(directory_content, chap_num)
        next_chapter_blueprint = get_chapter_blueprint_text(directory_content, chap_num + 1)

        # Get novel settings from UI
        topic = self.topic_text.get("0.0", "end").strip()

        # Get global summary
        global_summary_file = os.path.join(filepath, "前情摘要.txt")
        global_summary = read_file(global_summary_file) if os.path.exists(global_summary_file) else ""

        # Get volume outline
        volume_outline = get_volume_outline(filepath, chap_num)

        # Get plot points from the previous chapter
        plot_points = get_plot_points(filepath, chap_num)

        # Get user guidance and genre
        user_guidance = self.user_guide_text.get("0.0", "end").strip()
        genre = self.genre_var.get()

        # Choose the prompt template based on whether it's for draft generation or review
        if for_review:
            from prompt_definitions import Chapter_Review_prompt
            
            # --- Extract details from the current chapter blueprint ---
            def extract_detail(pattern, text):
                match = re.search(pattern, text, re.DOTALL) # Use DOTALL to match across newlines
                return match.group(1).strip() if match else ""

            # Corrected regex to handle potential leading whitespace
            chapter_title_match = re.search(r"^\s*第\d+章\s*《([^》]+)》", current_chapter_blueprint)
            chapter_title = chapter_title_match.group(1).strip() if chapter_title_match else f"第{chap_num}章"
            word_number = self.safe_get_int(self.word_number_var, 3000)
            
            # Use provided word count limits if available, otherwise use defaults from UI or hardcoded values
            final_word_min = word_count_min if word_count_min is not None else self.safe_get_int(self.word_number_var, 2500)
            final_word_max = word_count_max if word_count_max is not None else self.safe_get_int(self.word_number_var, 3500)


            # --- Robust extraction of foreshadowing block ---
            foreshadowing_lines = []
            in_foreshadowing_block = False
            for line in current_chapter_blueprint.splitlines():
                stripped_line = line.strip()
                if stripped_line.startswith("├─伏笔条目："):
                    in_foreshadowing_block = True
                    continue
                if in_foreshadowing_block:
                    if stripped_line.startswith("├─") or stripped_line.startswith("└─"):
                        break
                    foreshadowing_lines.append(line)
            foreshadowing = "\n".join(foreshadowing_lines)
            self.safe_log(f"为审校提取的伏笔块内容:\n---\n{foreshadowing}\n---")
            
            plot_twist_level = extract_detail(r"├─颠覆指数：\s*(.*?)\n", current_chapter_blueprint)


            # Get the text to be reviewed
            review_text = self.chapter_result.get("0.0", "end").strip()
            if not review_text:
                chapter_file_path = get_chapter_filepath(filepath, chap_num)
                if os.path.exists(chapter_file_path):
                    review_text = read_file(chapter_file_path)
                else:
                    self.safe_log(f"❌ 无法获取第 {chap_num} 章的内容进行审校。")
                    return ""
            
            # --- Retrieve Foreshadowing History for Review ---
            knowledge_context = "(无相关伏笔历史记录)"
            try:
                self.safe_log("开始为审校检索伏笔历史记录...")
                
                foreshadowing_ids = []
                if foreshadowing:
                    # --- 修复：在已提取的伏笔块中查找所有ID，然后去重 ---
                    all_ids_in_block = re.findall(r'([A-Z]{1,2}F\d+)', foreshadowing)
                    if all_ids_in_block:
                        foreshadowing_ids = sorted(list(set(all_ids_in_block)))
                else:
                    # 如果连伏笔条目块都找不到，就全局搜索作为最后的保险
                    foreshadowing_ids = sorted(list(set(re.findall(r'([A-Z]{1,2}F\d+)', current_chapter_blueprint))))
                
                if not foreshadowing_ids:
                    self.safe_log("本章无需要检索历史的伏笔。")
                else:
                    self.safe_log(f"需要为审校检索历史的伏笔ID: {foreshadowing_ids}")
                    
                    from novel_generator.json_utils import load_store
                    foreshadowing_store = load_store(filepath, "foreshadowing_collection")
                    if not foreshadowing_store:
                        self.safe_log("⚠️ 伏笔状态JSON文件未找到或加载失败。")
                    else:
                        self.safe_log("✅ 伏笔状态JSON文件加载成功。")
                        retrieved_entries = []
                        for fb_id in foreshadowing_ids:
                            self.safe_log(f"  - 正在查询伏笔ID: {fb_id}")
                            fb_data = foreshadowing_store.get(fb_id)
                            if fb_data:
                                content = fb_data.get("内容", "无内容记录")
                                last_chapter = fb_data.get("伏笔最后章节", "未知")
                                entry_text = f"伏笔编号: {fb_id}\n伏笔内容: {content}\n"
                                if last_chapter != '未知':
                                    entry_text += f"伏笔最后章节：{last_chapter}\n\n"
                                retrieved_entries.append(entry_text)
                                self.safe_log(f"  ✅ 成功检索到伏笔 {fb_id} 的历史记录。")
                            else:
                                self.safe_log(f"  ⚠️ 未能检索到伏笔 {fb_id} 的历史记录。")
                        if retrieved_entries:
                            knowledge_context = "\n".join(retrieved_entries)
            except Exception as e:
                self.safe_log(f"❌ 为审校检索伏笔历史时出错: {str(e)}\n{traceback.format_exc()}")
                knowledge_context = f"(为审校检索伏笔历史时出错: {str(e)})"

            # 新增：获取章节字数
            chapter_word_count = len(review_text)

            prompt = Chapter_Review_prompt.format(
                novel_number=chap_num,
                chapter_title=chapter_title,
                word_number=word_number,
                genre=genre,
                user_guidance=user_guidance,
                current_chapter_blueprint=current_chapter_blueprint,
                next_chapter_blueprint=next_chapter_blueprint,
                volume_outline=volume_outline,
                global_summary=global_summary,
                plot_points=plot_points,
                foreshadowing=foreshadowing,
                knowledge_context=knowledge_context, # Use the retrieved history
                Review_text=review_text,
                plot_twist_level=plot_twist_level,
                章节字数=chapter_word_count, # 新增变量
                字数下限=final_word_min,
                字数上限=final_word_max
            )
        else:
            from prompt_definitions import chapter_draft_prompt
            
            # --- Re-implement Foreshadowing History Retrieval ---
            knowledge_context = "(无相关伏笔历史记录)"
            embedding_adapter = None # Initialize embedding_adapter
            try:
                self.safe_log("开始检索伏笔历史记录...")
                
                foreshadowing_ids = []
                if current_chapter_blueprint:
                    # --- 修复：在伏笔块中查找所有ID，然后去重 ---
                    foreshadowing_ids = []
                    # 1. 定位伏笔条目块
                    foreshadowing_block_match = re.search(r'├─伏笔条目：([\s\S]*?)(?=\n[├└]─[\u4e00-\u9fa5]|\Z)', current_chapter_blueprint)
                    if foreshadowing_block_match:
                        foreshadowing_block = foreshadowing_block_match.group(1)
                        # 2. 在块内查找所有ID
                        all_ids_in_block = re.findall(r'([A-Z]{1,2}F\d+)', foreshadowing_block)
                        # 3. 去重
                        if all_ids_in_block:
                            foreshadowing_ids = sorted(list(set(all_ids_in_block)))

                if not foreshadowing_ids:
                    self.safe_log("本章无需要检索历史的伏笔。")
                else:
                    self.safe_log(f"本章涉及伏笔: {', '.join(foreshadowing_ids)}")
                    
                    from novel_generator.json_utils import load_store
                    foreshadowing_store = load_store(filepath, "foreshadowing_collection")
                    if not foreshadowing_store:
                        self.safe_log("⚠️ 伏笔状态JSON文件未找到或加载失败。")
                    else:
                        self.safe_log("✅ 伏笔状态JSON文件加载成功。")
                        retrieved_entries = []
                        processed_fb_ids = set()
                        for fb_id in foreshadowing_ids:
                            if fb_id in processed_fb_ids:
                                self.safe_log(f"【调试日志】检测到重复的伏笔ID '{fb_id}'，已跳过。")
                                continue
                            processed_fb_ids.add(fb_id)

                            self.safe_log(f"  - 正在查询伏笔ID: {fb_id}")
                            fb_data = foreshadowing_store.get(fb_id)
                            if fb_data:
                                content = fb_data.get("内容", "无内容记录")
                                last_chapter = fb_data.get("伏笔最后章节", "未知")
                                entry_text = f"伏笔编号: {fb_id}\n伏笔内容: {content}\n"
                                if last_chapter != '未知':
                                    entry_text += f"伏笔最后章节：{last_chapter}\n\n"
                                retrieved_entries.append(entry_text)
                                self.safe_log(f"  ✅ 成功检索到伏笔 {fb_id} 的历史记录。")
                            else:
                                self.safe_log(f"  ⚠️ 未能检索到伏笔 {fb_id} 的历史记录。")
                        if retrieved_entries:
                            knowledge_context = "\n".join(retrieved_entries)
            except Exception as e:
                self.safe_log(f"❌ 检索伏笔历史时出错: {str(e)}\n{traceback.format_exc()}")
                knowledge_context = f"(检索伏笔历史时出错: {str(e)})"

            # --- Asynchronous Character Generation ---
            # This part will now be handled in the `get_prompt_in_background` function
            # and the result will be passed to the prompt editor.
            # For now, we just prepare a placeholder.
            setting_characters = "{{setting_characters_placeholder}}"

            # --- Fetch Historical Chapter Content ---
            history_text = "(无历史章节内容)"
            if num_history_chapters > 0:
                self.safe_log(f"正在提取前 {num_history_chapters} 章的历史正文...")
                history_chapters_content = []
                for i in range(num_history_chapters):
                    history_chap_num = chap_num - (i + 1)
                    if history_chap_num > 0:
                        history_chapter_path = get_chapter_filepath(filepath, history_chap_num)
                        if os.path.exists(history_chapter_path):
                            try:
                                # 从文件名中提取章节号和标题
                                filename = os.path.basename(history_chapter_path)
                                match = re.match(r"^第(\d+)章\s+(.*)\.txt$", filename)
                                if match:
                                    chap_num_from_file = match.group(1)
                                    chapter_title_from_file = match.group(2)
                                    header = f"--- 第{chap_num_from_file}章 {chapter_title_from_file} ---\n"
                                else:
                                    # 如果文件名解析失败，则回退到旧方法
                                    header = self._get_formatted_chapter_header(history_chap_num, filepath)
                                
                                content = read_file(history_chapter_path)
                                history_chapters_content.append(f"{header}{content}\n")
                                self.safe_log(f"  ✅ 已加载第 {history_chap_num} 章内容。")
                            except Exception as e:
                                self.safe_log(f"  ❌ 加载第 {history_chap_num} 章内容失败: {e}")
                        else:
                            self.safe_log(f"  ⚠️ 未找到第 {history_chap_num} 章的文件。")
                if history_chapters_content:
                    # Reverse the list to maintain chronological order
                    history_text = "\n".join(reversed(history_chapters_content))

            # --- Final Prompt Assembly ---
            # 使用统一的函数获取章节信息
            chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
            if chapter_info is None:
                chapter_info = {}  # 如果未找到章节信息，则提供一个空字典以避免AttributeError
            chapter_title = chapter_info.get('chapter_title', f"无标题")
            word_number = self.safe_get_int(self.word_number_var, 3000)
            
            # For draft generation, word count limits are typically derived from the main word count setting
            final_word_min = word_count_min if word_count_min is not None else int(word_number * 0.8)
            final_word_max = word_count_max if word_count_max is not None else int(word_number * 1.2)

            prompt = chapter_draft_prompt.format(
                novel_number=chap_num,
                chapter_title=chapter_title,
                word_number=word_number,
                genre=genre,
                topic=topic,
                key_items=self.key_items_var.get(),
                scene_location=self.scene_location_var.get(),
                time_constraint=self.time_constraint_var.get(),
                user_guidance=user_guidance,
                current_chapter_blueprint=current_chapter_blueprint,
                next_chapter_blueprint=next_chapter_blueprint,
                volume_outline=volume_outline,
                setting_characters=setting_characters,
                characters_involved=setting_characters, # Use the same for both for simplicity
                global_summary=global_summary,
                plot_points=plot_points,
                knowledge_context=knowledge_context,
                历史章节正文=history_text, # Add the new variable
                字数下限=final_word_min,
                字数上限=final_word_max
            )

        return prompt
        
    except Exception as e:
        self.handle_exception(f"构建初始提示词时出错: {str(e)}")
        self.safe_log(f"❌ 构建初始提示词失败: {traceback.format_exc()}")
        return ""

def generate_chapter_draft_ui(self):
    """
    章节草稿生成UI - 此功能已被工作流引擎取代，保留为空函数。
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    logging.info("--- generate_chapter_draft_ui function entered ---")
    
    self.disable_button_safe(self.btn_generate_chapter)

    # --- Custom Confirmation Dialog ---
    def show_confirmation_dialog():
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("生成草稿确认")
        dialog.geometry("450x200")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.attributes('-topmost', True)

        chap_num = self.safe_get_int(self.chapter_num_var, 1)
        
        # Get chapter title for display
        chapter_title = ""
        directory_file = os.path.join(filepath, "章节目录.txt")
        if os.path.exists(directory_file):
            directory_content = read_file(directory_file)
            match = re.search(rf"^第\s*{chap_num}\s*章\s*《([^》]+)》", directory_content, re.MULTILINE)
            if match:
                chapter_title = f"《{match.group(1)}》"

        # Main label
        main_label = ctk.CTkLabel(dialog, text=f"当前准备生成 第{chap_num}章 {chapter_title} 草稿", font=("Microsoft YaHei", 16))
        main_label.pack(pady=20)

        # History chapters input frame
        input_frame = ctk.CTkFrame(dialog)
        input_frame.pack(pady=10)
        
        ctk.CTkLabel(input_frame, text="提取历史章节 前", font=("Microsoft YaHei", 14)).pack(side="left", padx=5)
        history_chapters_var = tk.StringVar(value="2") # Default value
        history_entry = ctk.CTkEntry(input_frame, textvariable=history_chapters_var, width=50, font=("Microsoft YaHei", 14))
        history_entry.pack(side="left", padx=5)
        ctk.CTkLabel(input_frame, text="章的章节内容", font=("Microsoft YaHei", 14)).pack(side="left", padx=5)

        # Button frame
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=20)

        def on_confirm():
            try:
                num_str = history_chapters_var.get().strip()
                if not num_str:
                    num_history = 0
                else:
                    num_history = int(num_str)

                if not 0 <= num_history <= 10:
                    messagebox.showwarning("输入错误", "请输入 0 到 10 之间的数字。", parent=dialog)
                    return
                
                dialog.destroy()
                # Pass the number to the background prompt generation
                get_prompt_in_background(num_history)

            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字。", parent=dialog)

        def on_cancel():
            dialog.destroy()
            self.enable_button_safe(self.btn_generate_chapter)
            self.safe_log("❌ 用户取消了草稿生成请求。")

        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        ctk.CTkButton(btn_frame, text="确认", command=on_confirm).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="退出", command=on_cancel).pack(side="left", padx=10)

    # --- End of Custom Dialog ---

    # 创建提示词编辑对话框
    def show_prompt_editor(prompt_text):
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("生成草稿提示词")
        dialog.geometry("800x600")
        dialog.transient(self.master)  # 使弹窗相对于主窗口
        dialog.grab_set()  # 使弹窗成为模态窗口，阻止与主窗口交互
        dialog.attributes('-topmost', True)  # 设置为置顶窗口
        
        # 禁止最小化窗口
        dialog.protocol("WM_ICONIFY_WINDOW", lambda: dialog.deiconify())

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

        word_count_label = ctk.CTkLabel(btn_frame, text="字数: 0", font=("Microsoft YaHei", 14))
        word_count_label.pack(side="right", padx=10)

        def update_word_count(event=None):
            text = textbox.get("1.0", "end-1c")
            words = len(text)
            word_count_label.configure(text=f"字数: {words}")

        textbox.bind("<KeyRelease>", update_word_count)
        update_word_count() # Initial count
    
    def generate_draft(prompt_text):
        def task():
            try:
                from novel_generator.common import execute_with_polling, invoke_stream_with_cleaning
                from utils import clear_file_content, save_string_to_txt

                chap_num = self.safe_get_int(self.chapter_num_var, 1)

                def draft_generation_task(llm_adapter, **kwargs):
                    """Core logic for draft generation, passed to the polling executor."""
                    return "".join(chunk for chunk in invoke_stream_with_cleaning(llm_adapter, prompt_text, log_func=self.safe_log))

                full_draft_text = execute_with_polling(
                    gui_app=self,
                    step_name="生成草稿",
                    target_func=draft_generation_task,
                    log_func=self.safe_log,
                    context_info=f"第 {chap_num} 章",
                    is_manual_call=True
                )

                if full_draft_text:
                    self.safe_log("\n\n章节草稿生成完成")
                    directory_file = os.path.join(filepath, "章节目录.txt")
                    directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""
                    chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
                    plain_title = chapter_info.get('chapter_title', '无标题')
                    chapter_title_full = f"第{chap_num}章 {plain_title}"
                    final_text_with_title = f"{chapter_title_full}\n\n{full_draft_text}"
                    final_text_to_save = self._reformat_text_if_needed(final_text_with_title)
                    
                    chapter_file = get_chapter_filepath(filepath, chap_num)
                    clear_file_content(chapter_file)
                    save_string_to_txt(final_text_to_save, chapter_file)
                    self.safe_log(f"章节草稿已保存到 {os.path.basename(chapter_file)}")
                    
                    self.safe_log(f"✅ 第{chap_num}章草稿生成完成。请在左侧查看或编辑。")
                    self.master.after(0, lambda: self.show_chapter_in_textbox(final_text_to_save))
                else:
                    self.safe_log("⚠️ 本章草稿生成失败或无内容。")
            except Exception as e:
                self.handle_exception(f"生成章节草稿流程时出错: {str(e)}")
            finally:
                self.enable_button_safe(self.btn_generate_chapter)
        
        threading.Thread(target=task, daemon=True).start()
    
    # 将获取初始提示词的过程移到后台线程
    def get_prompt_in_background(num_history_chapters):
        def task():
            try:
                self.safe_log("正在准备提示词，此过程可能需要一些时间...")
                
                # 1. Build the initial prompt template without character info
                prompt_template = get_initial_prompt(self, num_history_chapters=num_history_chapters)
                if not prompt_template:
                    self.safe_log("ℹ️ 未能生成初始提示词模板，请检查设置或错误日志。")
                    self.enable_button_safe(self.btn_generate_chapter)
                    return

                # 2. Synchronously generate character info using execute_with_polling
                self.safe_log("开始同步准备角色信息...")
                from novel_generator.character_generator import generate_characters_for_draft
                
                # Create necessary adapters
                embedding_adapter = None

                # Prepare chapter_info dictionary
                chap_num = self.safe_get_int(self.chapter_num_var, 1)
                directory_content = read_file(os.path.join(filepath, "章节目录.txt")) if os.path.exists(os.path.join(filepath, "章节目录.txt")) else ""
                volume_content = read_file(os.path.join(filepath, "分卷大纲.txt")) if os.path.exists(os.path.join(filepath, "分卷大纲.txt")) else ""
                from novel_generator.volume import find_volume_for_chapter
                
                blueprint_text = get_chapter_blueprint_text(directory_content, chap_num)
                chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)

                chapter_info_for_char_gen = {
                    'novel_number': chap_num,
                    'chapter_title': chapter_info.get('chapter_title', '无标题'),
                    'genre': self.genre_var.get(),
                    'volume_count': self.safe_get_int(self.volume_count_var, 3),
                    'num_chapters': self.safe_get_int(self.num_chapters_var, 30),
                    'volume_number': find_volume_for_chapter(volume_content, chap_num),
                    'word_number': self.safe_get_int(self.word_number_var, 3000),
                    'topic': self.topic_text.get("0.0", "end").strip(),
                    'user_guidance': self.user_guide_text.get("0.0", "end").strip(),
                    'global_summary': read_file(os.path.join(filepath, "前情摘要.txt")) if os.path.exists(os.path.join(filepath, "前情摘要.txt")) else "",
                    'plot_points': get_plot_points(filepath, chap_num),
                    'volume_outline': get_volume_outline(filepath, chap_num),
                    'current_chapter_blueprint': blueprint_text
                }

                def character_generation_task(llm_adapter, **kwargs):
                    # This is the synchronous core logic
                    return generate_characters_for_draft(
                        filepath=filepath,
                        chapter_info=chapter_info_for_char_gen,
                        llm_adapter=llm_adapter,
                        log_func=self.safe_log
                    )

                try:
                    character_data = execute_with_polling(
                        gui_app=self,
                        step_name="生成草稿_生成角色信息",
                        target_func=character_generation_task,
                        log_func=self.safe_log,
                        is_manual_call=True, # This is the key fix
                        context_info=f"第 {chap_num} 章"
                    )

                    if character_data is None:
                        character_data = "(角色信息生成失败或被中断)"

                    self.safe_log("✅ 角色信息准备完成，正在组合最终提示词...")
                    final_prompt = prompt_template.replace("{{setting_characters_placeholder}}", character_data)
                    self.master.after(0, lambda: show_prompt_editor(final_prompt))

                except Exception as e:
                    self.handle_exception(f"执行角色生成任务时出错: {str(e)}")
                    self.enable_button_safe(self.btn_generate_chapter)
                    # Also update the UI to show failure
                    final_prompt = prompt_template.replace("{{setting_characters_placeholder}}", f"(角色信息生成出错: {e})")
                    self.master.after(0, lambda: show_prompt_editor(final_prompt))

            except Exception as e:
                self.handle_exception(f"准备草稿提示词时出错: {str(e)}")
                self.enable_button_safe(self.btn_generate_chapter)
        
        threading.Thread(target=task, daemon=True).start()

    # Start the process by showing the confirmation dialog
    show_confirmation_dialog()
