import os
import customtkinter as ctk
from tkinter import messagebox
from ui.context_menu import TextWidgetContextMenu
from utils import read_file, save_string_to_txt, clear_file_content

def build_volume_tab(self):
    """构建分卷标签页"""
    self.volume_view_tab = self.tabview.add("小说分卷")
    self.volume_view_tab.rowconfigure(0, weight=0)
    self.volume_view_tab.rowconfigure(1, weight=1)
    self.volume_view_tab.columnconfigure(0, weight=1)

    # 顶部按钮区域
    top_frame = ctk.CTkFrame(self.volume_view_tab)
    top_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    top_frame.columnconfigure(0, weight=0)
    top_frame.columnconfigure(1, weight=0)
    top_frame.columnconfigure(2, weight=0)
    top_frame.columnconfigure(3, weight=0)
    top_frame.columnconfigure(4, weight=1)

    load_btn = ctk.CTkButton(
        top_frame, 
        text="加载 分卷大纲.txt", 
        command=self.load_volume,
        font=("Microsoft YaHei", 14)
    )
    load_btn.grid(row=0, column=0, padx=5, pady=5)

    save_btn = ctk.CTkButton(
        top_frame,
        text="保存修改",
        command=self.save_volume,
        font=("Microsoft YaHei", 14)
    )
    save_btn.grid(row=0, column=1, padx=5, pady=5)

    self.volume_word_count = ctk.CTkLabel(
        top_frame,
        text="字数：0",
        font=("Microsoft YaHei", 14)
    )
    self.volume_word_count.grid(row=0, column=4, padx=(0,10), sticky="e")

    # 文本编辑区域
    self.volume_text = ctk.CTkTextbox(
        self.volume_view_tab,
        wrap="word",
        font=("Microsoft YaHei", 14),
        undo=True
    )
    TextWidgetContextMenu(self.volume_text)
    self.volume_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

    def update_word_count(event=None):
        text = self.volume_text.get("0.0", "end-1c")
        text_length = len(text)
        self.volume_word_count.configure(text=f"字数：{text_length}")

    self.volume_text.bind("<KeyRelease>", update_word_count)
    self.volume_text.bind("<ButtonRelease>", update_word_count)

def load_volume(self):
    """加载分卷内容"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存路径")
        return
    
    volume_file = os.path.join(filepath, "分卷大纲.txt")
    if os.path.exists(volume_file):
        content = read_file(volume_file)
        self.volume_text.delete("0.0", "end")
        self.volume_text.insert("0.0", content)
    else:
        messagebox.showwarning("警告", "分卷大纲.txt 文件不存在")

def save_volume(self):
    """保存分卷内容"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先设置保存路径")
        return

    volume_file = os.path.join(filepath, "分卷大纲.txt")
    content = self.volume_text.get("0.0", "end").strip()
    clear_file_content(volume_file)
    save_string_to_txt(content, volume_file)
    messagebox.showinfo("成功", "分卷内容已保存")

def show_volume_tab(self):
    """显示分卷标签页"""
    self.tabview.set("小说分卷")
