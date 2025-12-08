# ui/main_tab.py
# -*- coding: utf-8 -*-
import customtkinter as ctk
from tkinter import messagebox
from ui.context_menu import TextWidgetContextMenu
from ui.workflow_panel import WorkflowPanel
from .helpers import enable_combobox_wheel_scroll
from .custom_widgets import CustomComboBox
import os
import json
import logging
import tkinter as tk
from ui.novel_params_tab import build_novel_params_area, build_optional_buttons_area

def build_main_tab(self):
    """
    主Tab包含左侧的"内容编辑框"编辑框和输出日志，以及右侧的主要操作和参数设置区
    """
    self.main_tab = self.tabview.add("主界面")
    self.main_tab.grid_rowconfigure(0, weight=1)
    self.main_tab.grid_columnconfigure(0, weight=1)
    self.main_tab.grid_columnconfigure(1, weight=1)

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

    # --- 内容编辑框 顶部栏 ---
    self.chapter_header_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
    self.chapter_header_frame.grid(row=0, column=0, padx=5, pady=(5, 0), sticky="ew")
    self.chapter_header_frame.columnconfigure(0, weight=1) # 让标签占据左侧空间

    self.chapter_label = ctk.CTkLabel(self.chapter_header_frame, text="内容编辑框  字数：0", font=("Microsoft YaHei", 14))
    self.chapter_label.grid(row=0, column=0, sticky="w")

    self.auto_reformat_checkbox = ctk.CTkCheckBox(
        self.chapter_header_frame,
        text="自动排版",
        variable=self.auto_reformat_var,
        font=("Microsoft YaHei", 14)
    )
    self.auto_reformat_checkbox.grid(row=0, column=1, padx=(10, 0), sticky="e")


    # 章节文本编辑框
    self.chapter_result = ctk.CTkTextbox(self.left_frame, wrap="word", font=("Microsoft YaHei", 14), undo=True)
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
    self.step_buttons_frame.rowconfigure(1, weight=0)

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

    # 自动生成按钮
    self.btn_run_workflow = ctk.CTkButton(
        self.step_buttons_frame,
        text="自动生成",
        command=self.run_workflow_ui,
        font=("Microsoft YaHei", 14, "bold")
    )
    self.btn_run_workflow.grid(row=1, column=0, columnspan=6, padx=5, pady=(5, 10), sticky="ew")

    # 日志文本框
    log_label = ctk.CTkLabel(self.left_frame, text="输出日志 (只读)", font=("Microsoft YaHei", 14))
    log_label.grid(row=3, column=0, padx=5, pady=(5, 0), sticky="w")

    self.log_text = ctk.CTkTextbox(self.left_frame, wrap="word", font=("Microsoft YaHei", 14))
    TextWidgetContextMenu(self.log_text)
    self.log_text.grid(row=4, column=0, sticky="nsew", padx=5, pady=(0, 5))
    self.log_text.configure(state="disabled")

def build_right_layout(self):
    """
    右侧区域：启用轮询生成 + LLM配置选择 + 小说基础设置 + 可选功能按钮
    """
    self.right_frame.grid_rowconfigure(0, weight=0) # For polling checkbox
    self.right_frame.grid_rowconfigure(1, weight=0) # For LLM config section
    self.right_frame.grid_rowconfigure(2, weight=1) # For config_frame (小说基础设置)
    self.right_frame.grid_rowconfigure(3, weight=0) # For optional buttons
    self.right_frame.columnconfigure(0, weight=1)

    # 启用轮询生成复选框
    self.enable_polling_checkbox = ctk.CTkCheckBox(
        self.right_frame,
        text="启用轮询生成",
        variable=self.enable_polling_var,
        font=("Microsoft YaHei", 14),
        command=self.on_polling_mode_change
    )
    self.enable_polling_checkbox.grid(row=0, column=0, padx=5, pady=(5, 0), sticky="w")

    # LLM选择配置区域 (与启用轮询形成二选一)
    self.llm_config_frame = ctk.CTkFrame(self.right_frame)
    self.llm_config_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(5, 0))
    self.llm_config_frame.columnconfigure(1, weight=1)

    # LLM选择配置复选框（不重新初始化变量，使用已有的）
    self.enable_llm_config_checkbox = ctk.CTkCheckBox(
        self.llm_config_frame,
        text="选择配置",
        variable=self.enable_llm_config_var,
        font=("Microsoft YaHei", 14),
        command=self.on_llm_config_mode_change
    )
    self.enable_llm_config_checkbox.grid(row=0, column=0, padx=5, pady=5, sticky="w")

    # 配置选择下拉框
    # self.main_config_selection_var = ctk.StringVar() # 已经在 main_window.py 中初始化
    self.main_config_optionmenu = ctk.CTkOptionMenu(
        self.llm_config_frame,
        variable=self.main_config_selection_var,
        command=self.on_main_config_selection,
        font=("Microsoft YaHei", 14),
        values=["无可用配置"]
    )
    self.main_config_optionmenu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # 设为默认按钮
    self.main_set_default_btn = ctk.CTkButton(
        self.llm_config_frame,
        text="设为默认",
        command=self.set_main_default_config,
        font=("Microsoft YaHei", 14),
        width=80
    )
    self.main_set_default_btn.grid(row=0, column=2, padx=5, pady=5)

    # 模型名称设置区域
    self.model_config_frame = ctk.CTkFrame(self.llm_config_frame)
    self.model_config_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
    self.model_config_frame.columnconfigure(1, weight=1)

    # 模型名称标签
    ctk.CTkLabel(self.model_config_frame, text="模型名称:", font=("Microsoft YaHei", 14)).grid(row=0, column=0, padx=5, pady=5, sticky="w")

    # 模型名称可编辑下拉框
    # self.main_model_name_var = ctk.StringVar() # 已经在 main_window.py 中初始化
    self.main_model_combobox = CustomComboBox(
        self.model_config_frame,
        variable=self.main_model_name_var,
        values=[""],
        font=("Microsoft YaHei", 14),
        dropdown_text_color="#000000"  # 设置下拉菜单字体颜色为黑色
    )
    self.main_model_combobox.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # 刷新按钮
    self.main_refresh_btn = ctk.CTkButton(
        self.model_config_frame,
        text="刷新",
        command=self.refresh_main_models,
        font=("Microsoft YaHei", 14),
        width=60
    )
    self.main_refresh_btn.grid(row=0, column=2, padx=5, pady=5)

    # 保存按钮
    self.main_save_btn = ctk.CTkButton(
        self.model_config_frame,
        text="保存",
        command=self.save_main_model_config,
        font=("Microsoft YaHei", 14),
        width=60
    )
    self.main_save_btn.grid(row=0, column=3, padx=5, pady=5)

    # 配置区（小说基础设置）- 这部分将在novel_params_tab.py中构建
    # 占据剩余空间，权重为1
    self.config_frame = ctk.CTkFrame(self.right_frame, corner_radius=10, border_width=2, border_color="gray")
    self.config_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
    self.config_frame.columnconfigure(0, weight=1)

    # 构建小说基础设置区域和可选功能按钮区域
    build_novel_params_area(self)
    build_optional_buttons_area(self)

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
