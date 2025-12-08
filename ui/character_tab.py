# ui/character_tab.py
# -*- coding: utf-8 -*-
import os
import customtkinter as ctk
from tkinter import messagebox
from utils import read_file, save_string_to_txt, clear_file_content
from ui.context_menu import TextWidgetContextMenu

def build_character_tab(self):
    self.character_tab = self.tabview.add("角色状态")
    self.character_tab.rowconfigure(0, weight=0)
    self.character_tab.rowconfigure(1, weight=1)
    self.character_tab.columnconfigure(0, weight=1)

    # 创建按钮框架来容纳两个加载按钮
    btn_frame = ctk.CTkFrame(self.character_tab)
    btn_frame.grid(row=0, column=0, padx=5, pady=5, sticky="w")

    # 加载角色状态.txt按钮
    load_state_btn = ctk.CTkButton(
        btn_frame, 
        text="加载 角色状态.txt", 
        command=lambda: self.load_character_file("角色状态.txt"), 
        font=("Microsoft YaHei", 14)
    )
    load_state_btn.pack(side="left", padx=(0,5))

    # 加载待用角色.txt按钮
    load_standby_btn = ctk.CTkButton(
        btn_frame, 
        text="加载 待用角色.txt", 
        command=lambda: self.load_character_file("待用角色.txt"), 
        font=("Microsoft YaHei", 14)
    )
    load_standby_btn.pack(side="left", padx=(0,5))
    
    # 加载角色数据库.txt按钮
    load_all_chars_btn = ctk.CTkButton(
        btn_frame, 
        text="加载 角色数据库.txt", 
        command=lambda: self.load_character_file("角色数据库.txt"), 
        font=("Microsoft YaHei", 14)
    )
    load_all_chars_btn.pack(side="left", padx=(0,5))
    
    # 修复角色数据库.txt按钮
    repair_all_chars_btn = ctk.CTkButton(
        btn_frame, 
        text="修复 角色数据库.txt", 
        command=self.repair_character_database, 
        font=("Microsoft YaHei", 14)
    )
    repair_all_chars_btn.pack(side="left", padx=0)

    self.character_wordcount_label = ctk.CTkLabel(self.character_tab, text="字数：0", font=("Microsoft YaHei", 14))
    self.character_wordcount_label.grid(row=0, column=1, padx=5, pady=5, sticky="w")

    save_btn = ctk.CTkButton(self.character_tab, text="保存修改", command=self.save_character_state, font=("Microsoft YaHei", 14))
    save_btn.grid(row=0, column=2, padx=5, pady=5, sticky="e")

    self.character_text = ctk.CTkTextbox(self.character_tab, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    
    def update_word_count(event=None):
        text = self.character_text.get("0.0", "end-1c")
        text_length = len(text)
        self.character_wordcount_label.configure(text=f"字数：{text_length}")
    
    self.character_text.bind("<KeyRelease>", update_word_count)
    self.character_text.bind("<ButtonRelease>", update_word_count)
    TextWidgetContextMenu(self.character_text)
    self.character_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5, columnspan=3)

def load_character_file(self, filename):
    """统一的文件加载函数"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存文件路径")
        return
    file_path = os.path.join(filepath, filename)
    content = read_file(file_path)
    self.character_text.delete("0.0", "end")
    self.character_text.insert("0.0", content)
    self.current_file = filename  # 记录当前加载的文件名
    self.log(f"已加载 {filename} 到编辑区。")

def load_character_state(self):
    """保持向后兼容的函数"""
    self.load_character_file("待用角色.txt")

def save_character_state(self):
    """保存角色状态文件"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存文件路径")
        return
    content = self.character_text.get("0.0", "end").strip()
    
    # 获取当前编辑的是哪个文件
    current_file = getattr(self, 'current_file', '待用角色.txt')
    file_path = os.path.join(filepath, current_file)
    
    # 保存到对应文件
    clear_file_content(file_path)
    save_string_to_txt(content, file_path)
    self.log(f"已保存对 {current_file} 的修改。")
