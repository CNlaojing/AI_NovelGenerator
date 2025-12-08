# ui/chapters_tab.py
# -*- coding: utf-8 -*-
import os
import re
import customtkinter as ctk
from tkinter import messagebox
from ui.context_menu import TextWidgetContextMenu
from utils import read_file, save_string_to_txt, clear_file_content
from novel_generator.common import get_chapter_filepath

def build_chapters_tab(self):
    self.chapters_view_tab = self.tabview.add("章节正文")
    self.chapters_view_tab.rowconfigure(0, weight=0)  # top_frame
    self.chapters_view_tab.rowconfigure(1, weight=0)  # reformat_frame
    self.chapters_view_tab.rowconfigure(2, weight=1)  # chapter_view_text
    self.chapters_view_tab.columnconfigure(0, weight=1)

    top_frame = ctk.CTkFrame(self.chapters_view_tab)
    top_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    top_frame.columnconfigure(0, weight=0)
    top_frame.columnconfigure(1, weight=0)
    top_frame.columnconfigure(2, weight=0)
    top_frame.columnconfigure(3, weight=0)
    top_frame.columnconfigure(4, weight=0) # Add export button column
    top_frame.columnconfigure(5, weight=1) # Make the space expandable

    prev_btn = ctk.CTkButton(top_frame, text="<< 上一章", command=self.next_chapter, font=("Microsoft YaHei", 14))
    prev_btn.grid(row=0, column=0, padx=5, pady=5, sticky="w")

    next_btn = ctk.CTkButton(top_frame, text="下一章 >>", command=self.prev_chapter, font=("Microsoft YaHei", 14))
    next_btn.grid(row=0, column=1, padx=5, pady=5, sticky="w")

    self.chapter_select_var = ctk.StringVar(value="选择章节")
    self.chapter_select_menu = ctk.CTkButton(top_frame, textvariable=self.chapter_select_var, command=lambda: show_chapter_dropdown(self), font=("Microsoft YaHei", 14))
    self.chapter_select_menu.grid(row=0, column=2, padx=5, pady=5, sticky="w")
    self.chapter_dropdown_window = None # To hold the dropdown window

    save_btn = ctk.CTkButton(top_frame, text="保存修改", command=self.save_current_chapter, font=("Microsoft YaHei", 14))
    save_btn.grid(row=0, column=3, padx=5, pady=5, sticky="w")

    export_btn = ctk.CTkButton(top_frame, text="导出文档", command=self.export_full_novel, font=("Microsoft YaHei", 14))
    export_btn.grid(row=0, column=4, padx=5, pady=5, sticky="w")

    refresh_btn = ctk.CTkButton(top_frame, text="刷新章节列表", command=self.refresh_chapters_list, font=("Microsoft YaHei", 14))
    refresh_btn.grid(row=0, column=6, padx=5, pady=5, sticky="e")

    # 添加捐赠按钮
    donate_btn = ctk.CTkButton(
        top_frame,
        text="捐赠",
        width=40,
        height=25,
        fg_color="transparent",
        border_width=0,
        text_color=("gray60", "gray30"),
        command=self.show_donate_window,
        font=("Microsoft YaHei", 14)
    )
    donate_btn.grid(row=0, column=7, padx=5, pady=5, sticky="e")

    self.chapters_word_count_label = ctk.CTkLabel(top_frame, text="字数：0", font=("Microsoft YaHei", 14))
    self.chapters_word_count_label.grid(row=0, column=5, padx=(0,10), sticky="e")

    # --- 排版选项框架 ---
    reformat_frame = ctk.CTkFrame(self.chapters_view_tab)
    reformat_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=0)

    # 定义排版选项变量并从配置加载
    reformat_settings = self.loaded_config.get('reformat_settings', {})
    self.reformat_indent_var = ctk.BooleanVar(value=reformat_settings.get('indent', True))
    self.reformat_lines_between_paragraphs_var = ctk.StringVar(value=str(reformat_settings.get('lines_between', '0')))
    self.reformat_remove_extra_spaces_var = ctk.BooleanVar(value=reformat_settings.get('remove_spaces', True))
    self.reformat_auto_on_generate_var = ctk.BooleanVar(value=reformat_settings.get('auto_on_generate', True))

    # --- 自动保存排版设置 ---
    def save_reformat_settings(*args):
        try:
            from config_manager import load_config, save_config
            config = load_config(self.config_file)
            if 'reformat_settings' not in config:
                config['reformat_settings'] = {}
            
            config['reformat_settings']['indent'] = self.reformat_indent_var.get()
            config['reformat_settings']['lines_between'] = self.reformat_lines_between_paragraphs_var.get()
            config['reformat_settings']['remove_spaces'] = self.reformat_remove_extra_spaces_var.get()
            config['reformat_settings']['auto_on_generate'] = self.reformat_auto_on_generate_var.get()
            
            save_config(config, self.config_file)
            self.safe_log("ℹ️ 排版设置已自动保存。")
        except Exception as e:
            self.safe_log(f"❌ 自动保存排版设置失败: {e}")

    # 绑定变量到保存函数
    self.reformat_indent_var.trace_add("write", save_reformat_settings)
    self.reformat_lines_between_paragraphs_var.trace_add("write", save_reformat_settings)
    self.reformat_remove_extra_spaces_var.trace_add("write", save_reformat_settings)
    self.reformat_auto_on_generate_var.trace_add("write", save_reformat_settings)

    # 第一行选项
    options_frame_1 = ctk.CTkFrame(reformat_frame)
    options_frame_1.pack(fill="x", padx=5, pady=(2, 2))

    ctk.CTkCheckBox(options_frame_1, text="段首缩进", variable=self.reformat_indent_var, font=("Microsoft YaHei", 12)).pack(side="left", padx=5)
    ctk.CTkCheckBox(options_frame_1, text="去除多余空格", variable=self.reformat_remove_extra_spaces_var, font=("Microsoft YaHei", 12)).pack(side="left", padx=5)
    
    ctk.CTkLabel(options_frame_1, text="段落间空行数:", font=("Microsoft YaHei", 12)).pack(side="left", padx=(10, 0))
    ctk.CTkEntry(options_frame_1, textvariable=self.reformat_lines_between_paragraphs_var, width=40, font=("Microsoft YaHei", 12)).pack(side="left", padx=(0, 5))

    # 第二行按钮和选项
    options_frame_2 = ctk.CTkFrame(reformat_frame)
    options_frame_2.pack(fill="x", padx=5, pady=(2, 2))

    ctk.CTkCheckBox(options_frame_2, text="生成/改写/定稿后自动排版", variable=self.reformat_auto_on_generate_var, font=("Microsoft YaHei", 12)).pack(side="left", padx=10)


    self.chapter_view_text = ctk.CTkTextbox(self.chapters_view_tab, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    
    def update_word_count(event=None):
        text = self.chapter_view_text.get("0.0", "end-1c")
        text_length = len(text)
        self.chapters_word_count_label.configure(text=f"字数：{text_length}")
    
    self.chapter_view_text.bind("<KeyRelease>", update_word_count)
    self.chapter_view_text.bind("<ButtonRelease>", update_word_count)
    TextWidgetContextMenu(self.chapter_view_text)
    self.chapter_view_text.grid(row=2, column=0, sticky="nsew", padx=5, pady=5, columnspan=6)

    self.chapters_list = []
    refresh_chapters_list(self)

def refresh_chapters_list(self):
    filepath = self.filepath_var.get().strip()
    chapters_dir = os.path.join(filepath, "章节正文")
    if not os.path.exists(chapters_dir):
        self.safe_log("尚未找到 '章节正文' 文件夹，请先生成章节或检查保存路径。")
        self.chapters_list = []
        return

    all_files = os.listdir(chapters_dir)
    chapters_data = []
    # 正则表达式匹配 "第X章 章节名.txt"
    pattern = re.compile(r"^第(\d+)章\s+(.*)\.txt$")
    for f in all_files:
        match = pattern.match(f)
        if match:
            chapter_num = int(match.group(1))
            # 存储 (章节号, 完整文件名)
            chapters_data.append((chapter_num, f))

    # 按章节号递减排序
    chapters_data.sort(key=lambda x: x[0], reverse=True)
    
    # self.chapters_list 现在存储元组 (章节号, 文件名)
    self.chapters_list = chapters_data
    
    # 下拉菜单显示的是不带 .txt 后缀的文件名
    display_values = [os.path.splitext(f[1])[0] for f in self.chapters_list]
    
    current_selected_display = self.chapter_select_var.get()
    
    if current_selected_display not in display_values or current_selected_display == "选择章节":
        if display_values:
            # 设置默认选中项为第一项
            self.chapter_select_var.set(display_values[0])
            # 加载内容时，需要传递完整的文件名
            load_chapter_content(self, self.chapters_list[0][1])
        else:
            # 如果列表为空
            self.chapter_select_var.set("选择章节")
            self.chapter_view_text.delete("0.0", "end")

def show_chapter_dropdown(self):
    if hasattr(self, 'chapter_dropdown_window') and self.chapter_dropdown_window is not None and self.chapter_dropdown_window.winfo_exists():
        close_chapter_dropdown(self)
        return

    if not self.chapters_list:
        messagebox.showinfo("提示", "章节列表为空。")
        return

    x = self.chapter_select_menu.winfo_rootx()
    y = self.chapter_select_menu.winfo_rooty() + self.chapter_select_menu.winfo_height()

    self.chapter_dropdown_window = ctk.CTkToplevel(self.master)
    self.chapter_dropdown_window.geometry(f"300x400+{x}+{y}")
    self.chapter_dropdown_window.overrideredirect(True)

    scrollable_frame = ctk.CTkScrollableFrame(self.chapter_dropdown_window)
    scrollable_frame.pack(expand=True, fill="both")

    def on_select(display_value, filename):
        self.chapter_select_var.set(display_value)
        load_chapter_content(self, filename)
        close_chapter_dropdown(self)

    for chapter_num, filename in self.chapters_list:
        display_name = os.path.splitext(filename)[0]
        btn = ctk.CTkButton(scrollable_frame, text=display_name,
                              command=lambda dn=display_name, fn=filename: on_select(dn, fn))
        btn.pack(fill="x", padx=2, pady=2)

    self.chapter_dropdown_window.bind("<FocusOut>", lambda e: close_chapter_dropdown(self))
    self.chapter_dropdown_window.focus_set()
    self.master.bind("<Configure>", lambda e: close_chapter_dropdown(self), add="+")

def close_chapter_dropdown(self):
    if hasattr(self, 'chapter_dropdown_window') and self.chapter_dropdown_window is not None and self.chapter_dropdown_window.winfo_exists():
        self.chapter_dropdown_window.destroy()
        self.chapter_dropdown_window = None
        self.master.unbind("<Configure>")

def on_chapter_selected(self, display_value):
    """当用户从下拉菜单中选择一个项目时调用"""
    # This function is now effectively unused.
    pass

def load_chapter_content(self, filename):
    """根据完整文件名加载章节内容"""
    if not filename:
        return
    filepath = self.filepath_var.get().strip()
    # 文件夹名称已更改
    chapter_file = os.path.join(filepath, "章节正文", filename)
    if not os.path.exists(chapter_file):
        self.safe_log(f"章节文件 {chapter_file} 不存在！")
        return
    content = read_file(chapter_file)
    self.chapter_view_text.delete("0.0", "end")
    self.chapter_view_text.insert("0.0", content)

def save_current_chapter(self):
    selected_display_value = self.chapter_select_var.get()
    if not selected_display_value or selected_display_value == "选择章节":
        messagebox.showwarning("警告", "尚未选择章节，无法保存。")
        return
        
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径")
        return

    # 从显示值找到对应的完整文件名
    filename_to_save = ""
    for num, fname in self.chapters_list:
        if os.path.splitext(fname)[0] == selected_display_value:
            filename_to_save = fname
            break

    if not filename_to_save:
        self.safe_log(f"错误：无法找到要保存的文件，选择项为 '{selected_display_value}'")
        messagebox.showerror("错误", "无法找到要保存的文件。")
        return

    chapter_file = os.path.join(filepath, "章节正文", filename_to_save)
    content = self.chapter_view_text.get("0.0", "end").strip()
    
    save_string_to_txt(content, chapter_file)
    self.safe_log(f"已保存对章节 '{selected_display_value}' 的修改。")

def prev_chapter(self):
    if not self.chapters_list:
        return
    current_display = self.chapter_select_var.get()
    
    # 找到当前显示值在列表中的索引
    current_idx = -1
    display_values = [os.path.splitext(f[1])[0] for f in self.chapters_list]
    if current_display in display_values:
        current_idx = display_values.index(current_display)

    if current_idx > 0:
        new_idx = current_idx - 1
        # 获取新的显示值和完整文件名
        new_display_value = display_values[new_idx]
        new_filename = self.chapters_list[new_idx][1]
        
        self.chapter_select_var.set(new_display_value)
        load_chapter_content(self, new_filename)
    elif current_idx == 0:
        messagebox.showinfo("提示", "已经是最后一章了。")

def next_chapter(self):
    if not self.chapters_list:
        return
    current_display = self.chapter_select_var.get()

    # 找到当前显示值在列表中的索引
    current_idx = -1
    display_values = [os.path.splitext(f[1])[0] for f in self.chapters_list]
    if current_display in display_values:
        current_idx = display_values.index(current_display)

    if current_idx != -1 and current_idx < len(self.chapters_list) - 1:
        new_idx = current_idx + 1
        # 获取新的显示值和完整文件名
        new_display_value = display_values[new_idx]
        new_filename = self.chapters_list[new_idx][1]
        
        self.chapter_select_var.set(new_display_value)
        load_chapter_content(self, new_filename)
    elif current_idx == len(self.chapters_list) - 1:
        messagebox.showinfo("提示", "已经是第一章了。")
