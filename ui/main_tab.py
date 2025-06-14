# ui/main_tab.py
# -*- coding: utf-8 -*-
import customtkinter as ctk
from tkinter import messagebox
from ui.context_menu import TextWidgetContextMenu
import os
import json
import logging
import tkinter as tk

def build_main_tab(self):
    """
    主Tab包含左侧的"内容编辑框"编辑框和输出日志，以及右侧的主要操作和参数设置区
    """
    self.main_tab = self.tabview.add("主界面")
    self.main_tab.rowconfigure(0, weight=1)
    self.main_tab.columnconfigure(0, weight=1)
    self.main_tab.columnconfigure(1, weight=0)

    self.left_frame = ctk.CTkFrame(self.main_tab)
    self.left_frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

    self.right_frame = ctk.CTkFrame(self.main_tab)
    self.right_frame.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)

    build_left_layout(self)
    build_right_layout(self)

def build_left_layout(self):
    """
    左侧区域：内容编辑框 + Step流程按钮 + 输出日志(只读)
    """
    self.left_frame.grid_rowconfigure(0, weight=0)
    self.left_frame.grid_rowconfigure(1, weight=2)
    self.left_frame.grid_rowconfigure(2, weight=0)
    self.left_frame.grid_rowconfigure(3, weight=0)
    self.left_frame.grid_rowconfigure(4, weight=1)
    self.left_frame.columnconfigure(0, weight=1)

    self.chapter_label = ctk.CTkLabel(self.left_frame, text="内容编辑框  字数：0", font=("Microsoft YaHei", 14))
    self.chapter_label.grid(row=0, column=0, padx=5, pady=(5, 0), sticky="w")

    # 章节文本编辑框
    self.chapter_result = ctk.CTkTextbox(self.left_frame, wrap="word", font=("Microsoft YaHei", 14))
    TextWidgetContextMenu(self.chapter_result)
    self.chapter_result.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))



    def update_word_count(event=None):
        text = self.chapter_result.get("0.0", "end")
        count = len(text) - 1  # 减去最后一个换行符
        self.chapter_label.configure(text=f"内容编辑框  字数：{count}")

    self.chapter_result.bind("<KeyRelease>", update_word_count)
    self.chapter_result.bind("<ButtonRelease>", update_word_count)

    # Step 按钮区域
    self.step_buttons_frame = ctk.CTkFrame(self.left_frame)
    self.step_buttons_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
    self.step_buttons_frame.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)  # 6列均分

    self.btn_generate_architecture = ctk.CTkButton(
        self.step_buttons_frame,
        text="生成架构",
        command=self.generate_novel_architecture_ui,
        font=("Microsoft YaHei", 14)
    )
    self.btn_generate_architecture.grid(row=0, column=0, padx=5, pady=2, sticky="ew")

    self.btn_generate_volume = ctk.CTkButton(
        self.step_buttons_frame,
        text="生成分卷",
        command=self.generate_volume_ui,
        font=("Microsoft YaHei", 14)
    )
    self.btn_generate_volume.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

    self.btn_generate_directory = ctk.CTkButton(
        self.step_buttons_frame,
        text="生成目录", 
        command=self.generate_chapter_blueprint_ui,
        font=("Microsoft YaHei", 14)
    )
    self.btn_generate_directory.grid(row=0, column=2, padx=5, pady=2, sticky="ew")

    self.btn_generate_chapter = ctk.CTkButton(
        self.step_buttons_frame,
        text="生成草稿",  
        command=self.generate_chapter_draft_ui,
        font=("Microsoft YaHei", 14)
    )
    self.btn_generate_chapter.grid(row=0, column=3, padx=5, pady=2, sticky="ew")

    self.btn_rewrite_chapter = ctk.CTkButton(
        self.step_buttons_frame, 
        text="改写章节",
        command=self.rewrite_chapter_ui,
        font=("Microsoft YaHei", 14)
    )
    self.btn_rewrite_chapter.grid(row=0, column=4, padx=5, pady=2, sticky="ew")

    self.btn_finalize_chapter = ctk.CTkButton(
        self.step_buttons_frame,
        text="定稿章节",  
        command=self.finalize_chapter_ui,
        font=("Microsoft YaHei", 14)
    )
    self.btn_finalize_chapter.grid(row=0, column=5, padx=5, pady=2, sticky="ew")

    # 日志文本框
    log_label = ctk.CTkLabel(self.left_frame, text="输出日志 (只读)", font=("Microsoft YaHei", 14))
    log_label.grid(row=3, column=0, padx=5, pady=(5, 0), sticky="w")

    self.log_text = ctk.CTkTextbox(self.left_frame, wrap="word", font=("Microsoft YaHei", 14))
    TextWidgetContextMenu(self.log_text)
    self.log_text.grid(row=4, column=0, sticky="nsew", padx=5, pady=(0, 5))
    self.log_text.configure(state="disabled")

def build_right_layout(self):
    """
    右侧区域：配置区(tabview) + 小说主参数 + 可选功能按钮
    """
    self.right_frame.grid_rowconfigure(0, weight=0)
    self.right_frame.grid_rowconfigure(1, weight=1)
    self.right_frame.grid_rowconfigure(2, weight=0)
    self.right_frame.columnconfigure(0, weight=1)

    # 配置区（AI/Embedding）
    self.config_frame = ctk.CTkFrame(self.right_frame, corner_radius=10, border_width=2, border_color="gray")
    self.config_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    self.config_frame.columnconfigure(0, weight=1)
    # 其余部分将在 config_tab.py 与 novel_params_tab.py 中构建

def init_ui(self):
    try:
        # 读取配置文件中的章节号
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
        current_chapter = 1  # 默认值
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                current_chapter = config.get('novel_params', {}).get('current_chapter', 1)
            except Exception as e:
                logging.error(f"读取配置文件时出错: {str(e)}")
        
        # 初始化章节号输入框
        self.chapter_var = tk.StringVar(value=str(current_chapter))
    except Exception as e:
        logging.error(f"初始化UI时出错: {str(e)}")
