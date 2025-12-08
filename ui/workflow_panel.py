# -*- coding: utf-8 -*-
import re
import customtkinter as ctk
from novel_generator.workflow_engine import WorkflowEngine
import threading
from config_manager import load_config, save_config
import os
import json
from tkinter import messagebox
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from novel_generator.common import get_chapter_filepath
from ui.context_menu import TextWidgetContextMenu

class WorkflowPanel(ctk.CTkToplevel):
    """
    一个全新的UI面板，用于控制和管理小说的全自动生成。
    该面板使用 CustomTkinter 构建，以确保与主应用的兼容性。
    """
    def __init__(self, gui_app, parent=None):
        super().__init__(parent)
        self.gui_app = gui_app
        self.title("自动生成")
        self.geometry("1600x900") # 调整窗口大小以容纳三栏

        # --- 引擎实例 ---
        self.engine = WorkflowEngine(self.gui_app, self.update_status_display, self.append_log, self.on_engine_started, self.on_engine_finished)
        self.current_task_log = [] # 用于存储当前任务的日志
        self.task_log_window = None # 用于持有日志窗口的引用

        # --- 章节选择相关状态 ---
        self.chapters_list = []
        self.chapter_select_var = ctk.StringVar(value="选择章节")
        self.chapter_dropdown_window = None
        
        # --- 文件监控 ---
        self.file_observer = None
        self.current_watched_file = None

        # --- 主布局 ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- 创建三栏布局的主框架 ---
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=0)  # 左侧设置区不扩展
        main_frame.grid_columnconfigure(1, weight=1)  # 中间日志区占据剩余空间
        main_frame.grid_columnconfigure(2, weight=1)  # 右侧信息显示区
        main_frame.grid_rowconfigure(0, weight=1)

        # --- 左侧面板 (设置) ---
        left_panel = ctk.CTkFrame(main_frame, corner_radius=0)
        left_panel.grid(row=0, column=0, padx=0, pady=0, sticky="ns")
        left_panel.grid_columnconfigure(0, weight=1)

        # --- 中间面板 (日志) ---
        center_panel = ctk.CTkFrame(main_frame, corner_radius=0)
        center_panel.grid(row=0, column=1, padx=0, pady=0, sticky="nsew")
        center_panel.grid_rowconfigure(0, weight=1)
        center_panel.grid_columnconfigure(0, weight=1)
        
        self.log_display = ctk.CTkTextbox(center_panel, wrap="word", corner_radius=0, state="disabled")
        self.log_display.grid(row=0, column=0, sticky="nsew")
        TextWidgetContextMenu(self.log_display)

        # --- 右侧面板 (信息显示) ---
        right_panel = ctk.CTkFrame(main_frame, corner_radius=0)
        right_panel.grid(row=0, column=2, padx=0, pady=0, sticky="nsew")
        right_panel.grid_rowconfigure(1, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_columnconfigure(1, weight=0)

        self.info_display_label = ctk.CTkLabel(right_panel, text="信息显示窗口", font=("Microsoft YaHei", 14))
        self.info_display_label.grid(row=0, column=0, padx=5, pady=(5, 0), sticky="w")

        self.word_count_label = ctk.CTkLabel(right_panel, text="字数: 0", font=("Microsoft YaHei", 12))
        self.word_count_label.grid(row=0, column=1, padx=5, pady=(5, 0), sticky="e")

        self.info_display_textbox = ctk.CTkTextbox(right_panel, wrap="word", font=("Microsoft YaHei", 14))
        self.info_display_textbox.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        self.info_display_textbox.configure(state="disabled")
        TextWidgetContextMenu(self.info_display_textbox)

        # --- 1. 状态显示区 (移入左侧) ---
        status_group = ctk.CTkFrame(left_panel)
        status_group.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        status_group.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(status_group, text="当前状态").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.status_display = ctk.CTkLabel(status_group, text="引擎待命中...", wraplength=480)
        self.status_display.grid(row=1, column=0, padx=10, pady=5, sticky="w")

        # --- 2. 生成任务控制区 (移入左侧) ---
        task_group = ctk.CTkFrame(left_panel)
        task_group.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        task_group.grid_columnconfigure(1, weight=1)
        task_group.grid_columnconfigure(3, weight=1)

        self.num_chapters_var = ctk.StringVar(value="1")
        ctk.CTkLabel(task_group, text="生成章节数:").grid(row=0, column=0, padx=(10, 0), pady=5, sticky="w")
        self.num_chapters_entry = ctk.CTkEntry(task_group, textvariable=self.num_chapters_var, width=60)
        self.num_chapters_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        self.start_chapter_var = ctk.StringVar(value="")
        ctk.CTkLabel(task_group, text="从第").grid(row=0, column=2, padx=(20, 0), pady=5, sticky="e")
        self.start_chapter_entry = ctk.CTkEntry(task_group, textvariable=self.start_chapter_var, width=60)
        self.start_chapter_entry.grid(row=0, column=3, padx=(5, 0), pady=5, sticky="w")
        ctk.CTkLabel(task_group, text="章,").grid(row=0, column=4, padx=(5, 0), pady=5, sticky="w")

        # --- 新增：生成草稿时提取历史章节数量 ---
        self.auto_history_chapters_var = ctk.StringVar(value="2")
        ctk.CTkLabel(task_group, text="提取历史章节数:").grid(row=1, column=0, padx=(10, 0), pady=5, sticky="w")
        self.auto_history_chapters_entry = ctk.CTkEntry(task_group, textvariable=self.auto_history_chapters_var, width=60)
        self.auto_history_chapters_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # --- 手动选择步骤的下拉菜单 (移至此处) ---
        self.manual_start_step_var = ctk.StringVar(value="不指定")
        self.step_map = {
            "不指定": None,
            "生成草稿": "generate_draft",
            "一致性审校": "consistency_check",
            "改写章节": "rewrite",
            "定稿章节": "finalize"
        }
        self.manual_start_step_menu = ctk.CTkOptionMenu(
            task_group,
            variable=self.manual_start_step_var,
            values=list(self.step_map.keys()),
            width=120
        )
        self.manual_start_step_menu.grid(row=0, column=5, padx=5, pady=5, sticky="w")
        ctk.CTkLabel(task_group, text="步骤开始").grid(row=0, column=6, padx=(0, 10), pady=5, sticky="w")

        # --- 3. 章节处理流程区 (移入左侧) ---
        process_group = ctk.CTkFrame(left_panel)
        process_group.grid(row=3, column=0, padx=5, pady=5, sticky="ew")
        self.generate_volume_var = ctk.BooleanVar(value=True)
        self.generate_blueprint_var = ctk.BooleanVar(value=True)
        self.consistency_check_var = ctk.BooleanVar(value=True)
        self.rewrite_chapter_var = ctk.BooleanVar(value=True)
        self.finalize_chapter_var = ctk.BooleanVar(value=True)

        volume_frame = ctk.CTkFrame(process_group)
        volume_frame.pack(fill="x", padx=5, pady=2)
        ctk.CTkCheckBox(volume_frame, text="生成分卷", variable=self.generate_volume_var).pack(side="left", padx=5)
        ctk.CTkLabel(volume_frame, text="提取大于").pack(side="left", padx=(10, 0))
        self.volume_char_weight_var = ctk.StringVar(value="91")
        ctk.CTkEntry(volume_frame, textvariable=self.volume_char_weight_var, width=40).pack(side="left", padx=5)
        ctk.CTkLabel(volume_frame, text="权重的角色状态").pack(side="left")

        blueprint_frame = ctk.CTkFrame(process_group)
        blueprint_frame.pack(fill="x", padx=5, pady=2)
        ctk.CTkCheckBox(blueprint_frame, text="生成目录", variable=self.generate_blueprint_var).pack(side="left", padx=5)
        ctk.CTkLabel(blueprint_frame, text="生成数量:").pack(side="left", padx=(10, 0))
        self.blueprint_num_chapters_var = ctk.StringVar(value="20")
        ctk.CTkEntry(blueprint_frame, textvariable=self.blueprint_num_chapters_var, width=40).pack(side="left", padx=5)

        consistency_frame = ctk.CTkFrame(process_group)
        consistency_frame.pack(fill="x", padx=5, pady=2)
        ctk.CTkCheckBox(consistency_frame, text="一致性审校", variable=self.consistency_check_var).pack(side="left", padx=5)
        
        consistency_sub_frame = ctk.CTkFrame(process_group)
        consistency_sub_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.review_pass_finalize_var = ctk.BooleanVar(value=False)
        self.review_pass_finalize_checkbox = ctk.CTkCheckBox(consistency_sub_frame, text="审校通过直接定稿", variable=self.review_pass_finalize_var)
        self.review_pass_finalize_checkbox.pack(side="left", padx=(20, 10))
        ctk.CTkLabel(consistency_sub_frame, text="字数:").pack(side="left", padx=(10, 0))
        self.word_count_min_var = ctk.StringVar(value="2500")
        ctk.CTkEntry(consistency_sub_frame, textvariable=self.word_count_min_var, width=50).pack(side="left", padx=5)
        ctk.CTkLabel(consistency_sub_frame, text="-").pack(side="left")
        self.word_count_max_var = ctk.StringVar(value="3500")
        ctk.CTkEntry(consistency_sub_frame, textvariable=self.word_count_max_var, width=50).pack(side="left", padx=5)

        rewrite_frame = ctk.CTkFrame(process_group)
        rewrite_frame.pack(fill="x", padx=5, pady=2)
        ctk.CTkCheckBox(rewrite_frame, text="改写章节", variable=self.rewrite_chapter_var).pack(side="left", padx=5)

        rewrite_sub_frame = ctk.CTkFrame(process_group)
        rewrite_sub_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.rewrite_then_review_var = ctk.BooleanVar(value=False)
        self.rewrite_then_review_checkbox = ctk.CTkCheckBox(
            rewrite_sub_frame, text="改写完成后重新审校", variable=self.rewrite_then_review_var, command=self._on_rewrite_then_review_toggle
        )
        self.rewrite_then_review_checkbox.pack(side="left", padx=(20, 10))

        self.force_finalize_after_rewrite_var = ctk.BooleanVar(value=False)
        self.force_finalize_count_var = ctk.StringVar(value="3")
        self.force_finalize_checkbox = ctk.CTkCheckBox(rewrite_sub_frame, text="改写", variable=self.force_finalize_after_rewrite_var)
        self.force_finalize_checkbox.pack(side="left", padx=(15, 0))
        self.force_finalize_entry = ctk.CTkEntry(rewrite_sub_frame, textvariable=self.force_finalize_count_var, width=40)
        self.force_finalize_entry.pack(side="left", padx=(5, 0))
        ctk.CTkLabel(rewrite_sub_frame, text="次后强制定稿").pack(side="left", padx=(5, 0))

        ctk.CTkCheckBox(process_group, text="定稿章节", variable=self.finalize_chapter_var).pack(anchor="w", padx=10, pady=2)

        # --- 4. 新增按钮区域 (移入左侧) ---
        info_buttons_frame = ctk.CTkFrame(left_panel)
        info_buttons_frame.grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        info_buttons_frame.columnconfigure((0, 1, 2), weight=1)

        buttons_info = {
            "小说架构": "小说设定.txt",
            "小说分卷": "分卷大纲.txt",
            "小说目录": "章节目录.txt",
            "角色状态": os.path.join("定稿内容", "角色状态.md"),
            "审校结果": "一致性审校.txt",
        }

        row, col = 0, 0
        for btn_text, file_path in buttons_info.items():
            btn = ctk.CTkButton(
                info_buttons_frame,
                text=btn_text,
                font=("Microsoft YaHei", 14),
                command=lambda p=file_path, t=btn_text: self.display_file_content(p, t)
            )
            btn.grid(row=row, column=col, padx=5, pady=2, sticky="ew")
            col += 1
            if col > 2:
                col = 0
                row += 1

        # --- 章节选择下拉菜单 ---
        self.chapter_select_menu = ctk.CTkButton(
            info_buttons_frame,
            textvariable=self.chapter_select_var,
            font=("Microsoft YaHei", 14),
            command=lambda: self.show_chapter_dropdown()
        )
        self.chapter_select_menu.grid(row=row, column=col, padx=5, pady=2, sticky="ew")
        
        # 刷新章节列表以备后用
        self.refresh_chapters_list()

        # --- 5. 提示信息区 (移入左侧) ---
        hint_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        hint_frame.grid(row=5, column=0, padx=5, pady=(5, 5), sticky="ew")
        hint_text = (
            "提示:\n"
            "1. 留空“从第 N 章开始”将自动从最新章节继续。\n"
            "2. 选择“不指定”步骤将从流程的第一步开始。"
        )
        ctk.CTkLabel(hint_frame, text=hint_text, justify="left", text_color="gray").pack(anchor="w")

        # --- 6. 控制按钮 (移入左侧) ---
        button_frame = ctk.CTkFrame(left_panel)
        button_frame.grid(row=6, column=0, padx=5, pady=10, sticky="ew")
        self.start_button = ctk.CTkButton(button_frame, text="启动引擎", command=self.start_engine)
        self.start_button.pack(side="left", padx=5)
        self.stop_button = ctk.CTkButton(button_frame, text="停止引擎", command=self.engine.force_stop, state="disabled")
        self.stop_button.pack(side="left", padx=5)
        self.view_log_button = ctk.CTkButton(button_frame, text="查看日志", command=self.gui_app.show_polling_log_viewer)
        self.view_log_button.pack(side="left", padx=5)
        self.close_button = ctk.CTkButton(button_frame, text="关闭", command=self._on_close)
        self.close_button.pack(side="right", padx=5)

        # 初始化UI联动状态
        self._on_rewrite_then_review_toggle()
        
        # 加载保存的设置
        self._load_settings()
        
        # 绑定窗口关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # 移除继续生成相关逻辑

    # --- 新增的章节选择相关方法 ---
    def refresh_chapters_list(self):
        filepath = self.gui_app.filepath_var.get().strip()
        if not filepath:
            return # Silently fail if no path is set

        chapters_dir = os.path.join(filepath, "章节正文")
        if not os.path.exists(chapters_dir):
            self.chapters_list = []
            return

        all_files = os.listdir(chapters_dir)
        chapters_data = []
        pattern = re.compile(r"^第(\d+)章\s+(.*)\.txt$")
        for f in all_files:
            match = pattern.match(f)
            if match:
                chapter_num = int(match.group(1))
                chapters_data.append((chapter_num, f))

        chapters_data.sort(key=lambda x: x[0], reverse=True)
        self.chapters_list = chapters_data
        
        display_values = [os.path.splitext(f[1])[0] for f in self.chapters_list]
        current_selected_display = self.chapter_select_var.get()
        
        if not display_values:
            self.chapter_select_var.set("无章节")
        elif current_selected_display not in display_values or current_selected_display == "选择章节":
            self.chapter_select_var.set("选择章节")

    def show_chapter_dropdown(self):
        self.refresh_chapters_list() # Refresh list every time dropdown is opened
        if hasattr(self, 'chapter_dropdown_window') and self.chapter_dropdown_window is not None and self.chapter_dropdown_window.winfo_exists():
            self.close_chapter_dropdown()
            return

        if not self.chapters_list:
            messagebox.showinfo("提示", "章节列表为空。")
            return

        x = self.chapter_select_menu.winfo_rootx()
        y = self.chapter_select_menu.winfo_rooty() + self.chapter_select_menu.winfo_height()

        self.chapter_dropdown_window = ctk.CTkToplevel(self)
        self.chapter_dropdown_window.geometry(f"300x400+{x}+{y}")
        self.chapter_dropdown_window.overrideredirect(True)

        scrollable_frame = ctk.CTkScrollableFrame(self.chapter_dropdown_window)
        scrollable_frame.pack(expand=True, fill="both")

        def on_select(display_value, filename):
            self.chapter_select_var.set(display_value)
            self.load_selected_chapter(filename)
            self.close_chapter_dropdown()

        for chapter_num, filename in self.chapters_list:
            display_name = os.path.splitext(filename)[0]
            btn = ctk.CTkButton(scrollable_frame, text=display_name,
                                  command=lambda dn=display_name, fn=filename: on_select(dn, fn))
            btn.pack(fill="x", padx=2, pady=2)

        self.chapter_dropdown_window.bind("<FocusOut>", lambda e: self.close_chapter_dropdown())
        self.chapter_dropdown_window.focus_set()
        self.master.bind("<Configure>", lambda e: self.close_chapter_dropdown(), add="+")

    def close_chapter_dropdown(self):
        if hasattr(self, 'chapter_dropdown_window') and self.chapter_dropdown_window is not None and self.chapter_dropdown_window.winfo_exists():
            self.chapter_dropdown_window.destroy()
            self.chapter_dropdown_window = None
            if self.master:
                try:
                    self.master.unbind("<Configure>")
                except Exception:
                    pass # Ignore error if binding doesn't exist

    def _update_info_word_count(self, *args):
        """更新信息显示窗口的字数统计"""
        content = self.info_display_textbox.get("1.0", "end-1c")
        count = len(content)
        self.word_count_label.configure(text=f"字数: {count}")

    def load_selected_chapter(self, filename):
        """显示指定章节文件的内容到右侧文本框"""
        base_path = self.gui_app.filepath_var.get()
        if not base_path:
            messagebox.showwarning("警告", "请先在主界面设置小说保存路径。")
            return

        full_path = os.path.join(base_path, "章节正文", filename)
        content = ""
        try:
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = f"文件不存在: {full_path}"

        except Exception as e:
            content = f"读取文件时出错: {e}"

        self.info_display_textbox.configure(state="normal")
        self.info_display_textbox.delete("1.0", "end")
        self.info_display_textbox.insert("1.0", content)
        self.info_display_textbox.configure(state="disabled")
        self._update_info_word_count()

        self.info_display_label.configure(text=f"信息显示窗口 - {os.path.splitext(filename)[0]}")
        self.start_watching_file(full_path)

    def display_file_content(self, file_path, button_text):
        """显示指定文件的内容到右侧文本框"""
        base_path = self.gui_app.filepath_var.get()
        if not base_path:
            messagebox.showwarning("警告", "请先在主界面设置小说保存路径。")
            return

        full_path = os.path.join(base_path, file_path)
        content = ""
        try:
            if os.path.exists(full_path):
                # Markdown files will be read as plain text
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            elif not content:
                content = f"文件不存在: {file_path}"

        except Exception as e:
            content = f"读取文件时出错: {e}"

        self.info_display_textbox.configure(state="normal")
        self.info_display_textbox.delete("1.0", "end")
        self.info_display_textbox.insert("1.0", content)
        self.info_display_textbox.configure(state="disabled")
        self._update_info_word_count()

        self.info_display_label.configure(text=f"信息显示窗口 - {button_text}")
        self.start_watching_file(full_path)

    def start_watching_file(self, file_path):
        """开始监控指定文件的变化"""
        if self.file_observer:
            self.file_observer.stop()
            try:
                self.file_observer.join()
            except RuntimeError:
                pass # 忽略线程未启动的错误

        self.current_watched_file = file_path
        if not os.path.exists(file_path):
            return

        event_handler = FileChangeHandler(self, file_path)
        self.file_observer = Observer()
        self.file_observer.schedule(event_handler, os.path.dirname(file_path), recursive=False)
        self.file_observer.start()

    def on_file_changed(self, file_path):
        """文件变化时的回调函数"""
        if file_path == self.current_watched_file:
            self.after(0, self.update_displayed_file)

    def update_displayed_file(self):
        """在主线程中更新显示的文件内容"""
        file_path = self.current_watched_file
        content = ""
        try:
            if os.path.exists(file_path):
                # Markdown files will be read as plain text
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = "文件已被删除。"
        except Exception as e:
            content = f"重新加载文件时出错: {e}"

        self.info_display_textbox.configure(state="normal")
        self.info_display_textbox.delete("1.0", "end")
        self.info_display_textbox.insert("1.0", content)
        self.info_display_textbox.configure(state="disabled")
        self._update_info_word_count()

    def _on_rewrite_then_review_toggle(self):
        """当“改写后重新审校”复选框状态改变时调用，处理所有相关的UI联动"""
        is_review_after_rewrite = self.rewrite_then_review_var.get()

        # 联动1: 审校通过直接定稿
        if is_review_after_rewrite:
            self.review_pass_finalize_var.set(True)
            self.review_pass_finalize_checkbox.configure(state="disabled")
        else:
            self.review_pass_finalize_checkbox.configure(state="normal")

        # 联动2: 改写N次后强制定稿
        if is_review_after_rewrite:
            self.force_finalize_after_rewrite_var.set(True)
            # 强制勾选后，应禁用复选框以防止用户取消
            self.force_finalize_checkbox.configure(state="disabled") 
            self.force_finalize_entry.configure(state="normal")
        else:
            self.force_finalize_after_rewrite_var.set(False)
            self.force_finalize_checkbox.configure(state="disabled")
            self.force_finalize_entry.configure(state="disabled")

    def start_engine(self):
        """收集UI参数并启动引擎"""
        self.current_task_log = [] # 为新任务清空日志
        try:
            # --- 从本窗口收集参数 ---
            num_chapters_to_generate = int(self.num_chapters_var.get())
            volume_char_weight = int(self.volume_char_weight_var.get())
            blueprint_num_chapters = int(self.blueprint_num_chapters_var.get())
            auto_history_chapters = int(self.auto_history_chapters_var.get())
            start_chapter_str = self.start_chapter_var.get().strip()
            start_chapter = int(start_chapter_str) if start_chapter_str else None
            
            # --- 简化后的起始步骤确定逻辑 ---
            selected_step_display = self.manual_start_step_var.get()
            raw_start_step = self.step_map.get(selected_step_display)

            force_regenerate_draft = False
            start_step = raw_start_step
            if raw_start_step == "generate_draft":
                force_regenerate_draft = True
                start_step = None # 强制重新生成后，从第一个真实步骤开始

            # 新增：获取新UI控件的值
            review_pass_finalize = self.review_pass_finalize_var.get()
            rewrite_then_review = self.rewrite_then_review_var.get()
            word_count_min = int(self.word_count_min_var.get())
            word_count_max = int(self.word_count_max_var.get())
            force_finalize_after_rewrite = self.force_finalize_after_rewrite_var.get()
            force_finalize_count = int(self.force_finalize_count_var.get())

            # --- 从主窗口安全地收集所有需要的参数 ---
            # 这是关键修复：在启动线程前，在UI线程中一次性读取所有需要的参数
            main_app_params = {
                "word_number": self.gui_app.safe_get_int(self.gui_app.word_number_var, 3000),
                "num_chapters_total": self.gui_app.safe_get_int(self.gui_app.num_chapters_var, 10),
                "genre": self.gui_app.genre_var.get(),
                "topic": self.gui_app.topic_var.get(),
                "user_guidance": self.gui_app.user_guidance_var.get(),
                "main_character": self.gui_app.main_character_var.get(),
                "volume_count": self.gui_app.safe_get_int(self.gui_app.volume_count_var, 3),
                "project_path": self.gui_app.filepath_var.get(),
                # 尝试获取章节列表，如果失败则传递空列表
                "chapter_list": self.gui_app.chapters_tab_listbox.get(0, "end") if hasattr(self.gui_app, 'chapters_tab_listbox') else []
            }

        except ValueError:
            self.append_log("错误：生成章节数、角色权重、目录生成数量和开始章节必须是有效的整数。")
            return
        except Exception as e:
            self.append_log(f"错误：读取主界面参数时出错: {e}")
            return

        workflow_params = {
            "num_chapters_to_generate": num_chapters_to_generate,
            "volume_char_weight": volume_char_weight,
            "blueprint_num_chapters": blueprint_num_chapters,
            "auto_history_chapters": auto_history_chapters,
            "start_chapter": start_chapter,
            "start_step": start_step,
            "force_regenerate_draft": force_regenerate_draft,
            # 新增参数
            "review_pass_finalize": review_pass_finalize,
            "rewrite_then_review": rewrite_then_review,
            "word_count_min": word_count_min,
            "word_count_max": word_count_max,
            "force_finalize_after_rewrite": force_finalize_after_rewrite,
            "force_finalize_count": force_finalize_count,
            "continue_from_last_run": False, # 永久禁用
        }
        # 将从主应用收集的参数合并进来
        workflow_params.update(main_app_params)

        # --- 动态获取角色信息 ---
        try:
            self.append_log("正在为工作流准备角色信息...")
            # 从UI获取筛选参数
            weight_threshold = int(self.volume_char_weight_var.get()) # 复用分卷的权重设置
            chapter_range = 20 # 使用默认值或从新UI获取
            
            # 调用筛选函数
            from ui.generation_handlers import get_high_weight_characters_from_json
            high_weight_characters_info = get_high_weight_characters_from_json(self.gui_app, main_app_params["project_path"], weight_threshold, chapter_range)
            
            # 合并
            combined_characters = main_app_params["main_character"]
            if high_weight_characters_info:
                combined_characters += "\n\n" + high_weight_characters_info
                self.append_log(f"已成功提取并合并了最近{chapter_range}章内，权重大于{weight_threshold}的角色。")
            
            # 更新workflow_params
            workflow_params["main_character"] = combined_characters
        except Exception as e:
            self.append_log(f"警告：在为工作流准备角色信息时出错: {e}")


        workflow_steps = []
        if self.generate_volume_var.get():
            workflow_steps.append("generate_volume")
        if self.generate_blueprint_var.get():
            workflow_steps.append("generate_blueprint")
        if self.consistency_check_var.get():
            workflow_steps.append("consistency_check")
        if self.rewrite_chapter_var.get():
            workflow_steps.append("rewrite")
        if self.finalize_chapter_var.get():
            workflow_steps.append("finalize")
        
        # 在新线程中启动引擎，以避免UI冻结
        engine_thread = threading.Thread(
            target=self.engine.run_workflow_for_chapters,
            args=(workflow_params, workflow_steps)
        )
        engine_thread.daemon = True
        engine_thread.start()


    def update_status_display(self, status):
        if not self.winfo_exists(): return
        self.status_display.configure(text=status)

    def append_log(self, message, stream=False, replace_last_line=False):
        if not self.winfo_exists(): return

        # 为独立的日志查看器存储日志
        if replace_last_line and self.current_task_log:
            self.current_task_log[-1] = message
        else:
            self.current_task_log.append(message)
        
        # 如果日志窗口已打开，则实时更新
        if self.task_log_window and self.task_log_window.winfo_exists():
            self.update_task_log_window(message, stream, replace_last_line)

        try:
            self.log_display.configure(state="normal")
            scroll_at_bottom = self.log_display.yview()[1] >= 1.0
            
            timer_tag = "timer_line"
            tag_ranges = self.log_display.tag_ranges(timer_tag)

            if replace_last_line:
                if tag_ranges:
                    start, end = tag_ranges
                    self.log_display.delete(start, end)
                    self.log_display.insert(start, message, timer_tag)
                else:
                    if self.log_display.index("end-1c") != "1.0" and self.log_display.get("end-2c", "end-1c") != '\n':
                        self.log_display.insert("end", "\n")
                    self.log_display.insert("end", message, timer_tag)
            else:
                if tag_ranges:
                    start, end = tag_ranges
                    line_start = self.log_display.index(f"{start} linestart")
                    self.log_display.delete(line_start, f"{end}+1c")

                end_char = "" if stream else "\n"
                self.log_display.insert("end", message + end_char)

            if scroll_at_bottom:
                self.log_display.see("end")
        finally:
            self.log_display.configure(state="disabled")

    def on_engine_started(self):
        if not self.winfo_exists(): return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def on_engine_finished(self):
        if not self.winfo_exists(): return
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _on_close(self):
        """处理窗口关闭事件，确保引擎和文件观察器停止，并保存设置。"""
        self.append_log("正在关闭自动生成面板...")
        if self.engine.is_running():
            self.append_log("检测到引擎仍在运行，正在发送停止信号...")
            self.engine.force_stop()
        
        if self.file_observer:
            self.file_observer.stop()
            try:
                self.file_observer.join()
            except RuntimeError:
                pass
        
        self._save_settings()
        self.destroy()

    def _load_settings(self):
        """从配置文件加载设置并应用到UI"""
        config = load_config()
        settings = config.get("workflow_settings", {})
        
        # 使用 .get(key, default_value) 避免因缺少键而崩溃
        self.num_chapters_var.set(settings.get("num_chapters_to_generate", "1"))
        self.auto_history_chapters_var.set(settings.get("auto_history_chapters", "2"))
        # start_chapter_var 默认为空，所以不需要加载
        self.generate_volume_var.set(settings.get("generate_volume", True))
        self.volume_char_weight_var.set(settings.get("volume_char_weight", "91"))
        self.generate_blueprint_var.set(settings.get("generate_blueprint", True))
        self.blueprint_num_chapters_var.set(settings.get("blueprint_num_chapters", "20"))
        self.consistency_check_var.set(settings.get("consistency_check", True))
        self.review_pass_finalize_var.set(settings.get("review_pass_finalize", False))
        self.word_count_min_var.set(settings.get("word_count_min", "2500"))
        self.word_count_max_var.set(settings.get("word_count_max", "3500"))
        self.rewrite_chapter_var.set(settings.get("rewrite_chapter", True))
        self.rewrite_then_review_var.set(settings.get("rewrite_then_review", False))
        self.force_finalize_after_rewrite_var.set(settings.get("force_finalize_after_rewrite", False))
        self.force_finalize_count_var.set(settings.get("force_finalize_count", "3"))
        self.finalize_chapter_var.set(settings.get("finalize_chapter", True))

        # 加载后需要再次调用以更新UI状态
        self._on_rewrite_then_review_toggle()
        self.append_log("ℹ️ 已加载保存的设置。")

    def _save_settings(self):
        """保存当前UI设置到配置文件"""
        config = load_config()
        if "workflow_settings" not in config:
            config["workflow_settings"] = {}
            
        settings = {
            "num_chapters_to_generate": self.num_chapters_var.get(),
            "auto_history_chapters": self.auto_history_chapters_var.get(),
            "generate_volume": self.generate_volume_var.get(),
            "volume_char_weight": self.volume_char_weight_var.get(),
            "generate_blueprint": self.generate_blueprint_var.get(),
            "blueprint_num_chapters": self.blueprint_num_chapters_var.get(),
            "consistency_check": self.consistency_check_var.get(),
            "review_pass_finalize": self.review_pass_finalize_var.get(),
            "word_count_min": self.word_count_min_var.get(),
            "word_count_max": self.word_count_max_var.get(),
            "rewrite_chapter": self.rewrite_chapter_var.get(),
            "rewrite_then_review": self.rewrite_then_review_var.get(),
            "force_finalize_after_rewrite": self.force_finalize_after_rewrite_var.get(),
            "force_finalize_count": self.force_finalize_count_var.get(),
            "finalize_chapter": self.finalize_chapter_var.get(),
        }
        config["workflow_settings"] = settings
        save_config(config)
        self.append_log("ℹ️ 当前设置已保存。")

    def show_task_log_window(self):
        """显示当前任务的日志弹窗"""
        if self.task_log_window and self.task_log_window.winfo_exists():
            self.task_log_window.focus()
            return

        self.task_log_window = ctk.CTkToplevel(self)
        self.task_log_window.title("当前任务日志")
        self.task_log_window.geometry("800x600")

        self.task_log_textbox = ctk.CTkTextbox(self.task_log_window, wrap="word", state="disabled")
        self.task_log_textbox.pack(expand=True, fill="both", padx=5, pady=5)
        TextWidgetContextMenu(self.task_log_textbox)

        # 使用现有日志填充
        self.task_log_textbox.configure(state="normal")
        # 日志消息可能不包含换行符，所以用\n连接
        self.task_log_textbox.insert("end", "\n".join(self.current_task_log))
        self.task_log_textbox.see("end")
        self.task_log_textbox.configure(state="disabled")

        def on_close():
            self.task_log_window.destroy()
            self.task_log_window = None

        self.task_log_window.protocol("WM_DELETE_WINDOW", on_close)

    def update_task_log_window(self, message, stream=False, replace_last_line=False):
        """实时更新日志弹窗内容"""
        if not hasattr(self, 'task_log_textbox') or not self.task_log_textbox:
            return
            
        try:
            self.task_log_textbox.configure(state="normal")
            scroll_at_bottom = self.task_log_textbox.yview()[1] >= 1.0

            if replace_last_line:
                # 获取最后一行的起始位置
                last_line_start = self.task_log_textbox.index("end-1c linestart")
                # 删除从该位置到末尾的所有内容
                self.task_log_textbox.delete(last_line_start, "end")
                # 如果文本框不为空，并且末尾不是换行符，则添加一个
                if self.task_log_textbox.index("end-1c") != "1.0" and self.task_log_textbox.get("end-2c", "end-1c") != '\n':
                    self.task_log_textbox.insert("end", "\n")
                # 插入新消息
                self.task_log_textbox.insert("end", message)
            else:
                end_char = "" if stream else "\n"
                self.task_log_textbox.insert("end", message + end_char)

            if scroll_at_bottom:
                self.task_log_textbox.see("end")
        finally:
            self.task_log_textbox.configure(state="disabled")

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, panel, file_path):
        self.panel = panel
        self.file_path = os.path.basename(file_path)

    def on_modified(self, event):
        if not event.is_directory and os.path.basename(event.src_path) == self.file_path:
            self.panel.on_file_changed(event.src_path)
