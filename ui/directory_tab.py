# ui/directory_tab.py
# -*- coding: utf-8 -*-
import os
import customtkinter as ctk
from tkinter import messagebox
from utils import read_file, save_string_to_txt, clear_file_content
from ui.context_menu import TextWidgetContextMenu

def build_directory_tab(self):
    self.directory_tab = self.tabview.add("小说目录")
    self.directory_tab.rowconfigure(0, weight=0)
    self.directory_tab.rowconfigure(1, weight=1)
    self.directory_tab.columnconfigure(0, weight=1)

    # 创建按钮框架
    button_frame = ctk.CTkFrame(self.directory_tab)
    button_frame.grid(row=0, column=0, columnspan=3, sticky="ew", padx=5, pady=5)

    # 加载目录按钮
    load_btn = ctk.CTkButton(
        button_frame,
        text="加载 章节目录.txt",
        command=self.load_chapter_blueprint,
        font=("Microsoft YaHei", 14)
    )
    load_btn.pack(side="left", padx=5, pady=5)

    # 新增加载伏笔状态按钮
    load_foreshadow_btn = ctk.CTkButton(
        button_frame,
        text="加载 伏笔状态.txt",
        command=lambda: self.load_text_file("伏笔状态.txt"),  # 调用 load_text_file
        font=("Microsoft YaHei", 14)
    )
    load_foreshadow_btn.pack(side="left", padx=5, pady=5)

    # 字数统计标签
    self.directory_word_count_label = ctk.CTkLabel(
        button_frame,
        text="字数：0",
        font=("Microsoft YaHei", 14)
    )
    self.directory_word_count_label.pack(side="left", padx=5, pady=5)

    # 保存按钮
    save_btn = ctk.CTkButton(
        button_frame, 
        text="保存修改", 
        command=self.save_chapter_blueprint,
        font=("Microsoft YaHei", 14)
    )
    save_btn.pack(side="right", padx=5, pady=5)

    # 文本框
    self.directory_text = ctk.CTkTextbox(self.directory_tab, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    
    def update_word_count(event=None):
        text = self.directory_text.get("0.0", "end")
        count = len(text) - 1
        self.directory_word_count_label.configure(text=f"字数：{count}")
    
    self.directory_text.bind("<KeyRelease>", update_word_count)
    self.directory_text.bind("<ButtonRelease>", update_word_count)
    TextWidgetContextMenu(self.directory_text)
    self.directory_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5, columnspan=3)

    # 添加当前加载文件类型跟踪
    self.current_file_type = "章节目录.txt"  # 默认加载的是章节目录

def load_chapter_blueprint(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存文件路径")
        return
    filename = os.path.join(filepath, "章节目录.txt")
    content = read_file(filename)
    self.directory_text.delete("0.0", "end")
    self.directory_text.insert("0.0", content)
    self.current_file_type = "章节目录.txt"  # 更新当前文件类型
    self.log("已加载 章节目录.txt 内容到编辑区。")

def save_chapter_blueprint(self):
    """根据当前加载的文件类型保存到对应文件"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存文件路径")
        return
        
    content = self.directory_text.get("0.0", "end").strip()
    filename = os.path.join(filepath, self.current_file_type)  # 使用当前文件类型
    clear_file_content(filename)
    save_string_to_txt(content, filename)
    self.log(f"已保存对 {self.current_file_type} 的修改。")

def load_text_file(self, filename: str):
    """通用文件加载函数"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存文件路径")
        return
        
    file_path = os.path.join(filepath, filename)
    content = read_file(file_path)
    self.directory_text.delete("0.0", "end")
    self.directory_text.insert("0.0", content)
    self.current_file_type = filename  # 更新当前文件类型
    self.log(f"已加载 {filename} 内容到编辑区。")
