# ui/llm_settings_tab.py
# -*- coding: utf-8 -*-
import os
import json
from tkinter import messagebox, simpledialog
import customtkinter as ctk
import config_manager as cm
from tooltips import tooltips
import customtkinter as ctk
import logging
from llm_adapters import create_llm_adapter
from embedding_adapters import create_embedding_adapter # 新增导入
from .helpers import enable_combobox_wheel_scroll
from .custom_widgets import CustomComboBox

def create_label_with_help(parent, label_text, tooltip_key, row, column,
                           font=None, sticky="e", padx=5, pady=5):
    """
    封装一个带"?"按钮的Label，用于展示提示信息。
    """
    frame = ctk.CTkFrame(parent)
    frame.grid(row=row, column=column, padx=padx, pady=pady, sticky=sticky)
    frame.columnconfigure(0, weight=0)

    label = ctk.CTkLabel(frame, text=label_text, font=font)
    label.pack(side="left")

    btn = ctk.CTkButton(
        frame,
        text="?",
        width=22,
        height=22,
        font=("Microsoft YaHei", 10),
        command=lambda: messagebox.showinfo("参数说明", tooltips.get(tooltip_key, "暂无说明"))
    )
    btn.pack(side="left", padx=3)

    return frame

def build_llm_settings_tab(self_instance, parent_tabview):
    """
    构建大模型设置标签页，包含 LLM Model settings 和 Embedding settings。
    """
    llm_settings_tab = parent_tabview.add("大模型设置")
    llm_settings_tab.grid_columnconfigure(0, weight=1) # 左侧 LLM/Embedding 设置
    llm_settings_tab.grid_columnconfigure(1, weight=1) # 右侧 轮询设置
    llm_settings_tab.grid_rowconfigure(0, weight=1) # 顶部 LLM/Embedding Tabview
    llm_settings_tab.grid_rowconfigure(1, weight=0) # 底部 配置管理

    # 左侧框架，包含 LLM 和 Embedding 设置的 Tabview
    left_frame = ctk.CTkFrame(llm_settings_tab)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    left_frame.grid_columnconfigure(0, weight=1)
    left_frame.grid_rowconfigure(0, weight=1) # tabview

    # LLM 和 Embedding 设置的 Tabview
    llm_embedding_tabview = ctk.CTkTabview(left_frame)
    llm_embedding_tabview.grid(row=0, column=0, sticky="nsew")

    # 创建一个字典来存储对这些标签页框架的引用
    self_instance.llm_settings_tab_frames = {}

    # LLM 设置标签页
    llm_tab = llm_embedding_tabview.add("LLM 模型设置")
    llm_tab.grid_columnconfigure(0, weight=1)
    llm_tab.grid_rowconfigure(0, weight=1)
    llm_frame = ctk.CTkFrame(llm_tab, corner_radius=10, border_width=2, border_color="gray", width=450)
    llm_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    llm_frame.grid_propagate(False)
    llm_frame.grid_columnconfigure(0, weight=1)
    llm_frame.grid_rowconfigure(1, weight=1)
    llm_label = ctk.CTkLabel(llm_frame, text="LLM 模型设置", font=("Microsoft YaHei", 16, "bold"))
    llm_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
    llm_content_frame = ctk.CTkFrame(llm_frame)
    llm_content_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    llm_content_frame.grid_columnconfigure(1, weight=1)
    self_instance.ai_config_tab = llm_content_frame
    build_ai_config_section(self_instance)

    # 根据配置决定是否创建 Embedding 设置标签页
    config = cm.load_config()
    if not config.get("hide_old_data_features", False):
        embeddings_tab = llm_embedding_tabview.add("Embedding 模型设置")
        self_instance.llm_settings_tab_frames["embedding"] = embeddings_tab # 存储引用
        embeddings_tab.grid_columnconfigure(0, weight=1)
        embeddings_tab.grid_rowconfigure(0, weight=1)
        embeddings_frame = ctk.CTkFrame(embeddings_tab, corner_radius=10, border_width=2, border_color="gray")
        embeddings_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        embeddings_frame.grid_columnconfigure(0, weight=1)
        embeddings_frame.grid_rowconfigure(1, weight=1)
        embeddings_label = ctk.CTkLabel(embeddings_frame, text="Embedding 模型设置", font=("Microsoft YaHei", 16, "bold"))
        embeddings_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        embeddings_content_frame = ctk.CTkFrame(embeddings_frame)
        embeddings_content_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        embeddings_content_frame.grid_columnconfigure(1, weight=1)
        self_instance.embeddings_config_tab = embeddings_content_frame
        build_embeddings_config_section(self_instance)

    self_instance.llm_embedding_tabview = llm_embedding_tabview

    # 配置管理区域 (位于左侧 Tabview 下方)
    config_management_frame = ctk.CTkFrame(llm_settings_tab)
    config_management_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
    config_management_frame.grid_columnconfigure([1, 2, 3, 4], weight=1)

    # 设置名称
    ctk.CTkLabel(config_management_frame, text="设置名称:", font=("Microsoft YaHei", 14)).grid(row=0, column=0, padx=5, pady=5, sticky="w")
    self_instance.config_name_var = ctk.StringVar()
    config_name_entry = ctk.CTkEntry(config_management_frame, textvariable=self_instance.config_name_var, font=("Microsoft YaHei", 14))
    config_name_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # 保存按钮
    save_btn = ctk.CTkButton(config_management_frame, text="保存", command=self_instance.save_named_config, font=("Microsoft YaHei", 14))
    save_btn.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

    # 选择配置
    ctk.CTkLabel(config_management_frame, text="选择配置:", font=("Microsoft YaHei", 14)).grid(row=1, column=0, padx=5, pady=5, sticky="w")
    self_instance.config_selection_var = ctk.StringVar()
    self_instance.config_option_menu = ctk.CTkOptionMenu(config_management_frame, variable=self_instance.config_selection_var, command=self_instance.load_named_config, font=("Microsoft YaHei", 14))
    self_instance.config_option_menu.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

    # 删除按钮
    delete_btn = ctk.CTkButton(config_management_frame, text="删除", command=self_instance.delete_named_config, font=("Microsoft YaHei", 14))
    delete_btn.grid(row=1, column=2, padx=5, pady=5, sticky="ew")

    # 设为默认按钮
    set_default_btn = ctk.CTkButton(config_management_frame, text="设为默认", command=self_instance.set_default_named_config, font=("Microsoft YaHei", 14))
    set_default_btn.grid(row=1, column=3, padx=5, pady=5, sticky="ew")

    # 初始化时加载配置
    self_instance.update_config_menu()
    self_instance.load_default_config_on_startup()

    # 右侧轮询设置区域
    polling_settings_frame = ctk.CTkFrame(llm_settings_tab, corner_radius=10, border_width=2, border_color="gray", width=450)
    polling_settings_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=10, pady=10) # 占据右侧所有行
    polling_settings_frame.grid_propagate(False)
    polling_settings_frame.grid_columnconfigure(1, weight=1)
    polling_settings_frame.grid_rowconfigure(9, weight=1) # 让日志文本框所在的行可以扩展

    polling_label = ctk.CTkLabel(polling_settings_frame, text="轮询生成设置", font=("Microsoft YaHei", 16, "bold"))
    polling_label.grid(row=0, column=0, columnspan=3, padx=10, pady=10, sticky="w")

    # 轮询配置列表
    ctk.CTkLabel(polling_settings_frame, text="轮询列表:", font=("Microsoft YaHei", 14)).grid(row=1, column=0, padx=5, pady=5, sticky="nw") # row 从 1 开始
    self_instance.polling_configs_textbox = ctk.CTkTextbox(polling_settings_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), state="disabled") # 默认高度为2行 (20*2=40)
    self_instance.polling_configs_textbox.grid(row=1, column=1, padx=5, pady=5, sticky="nsew") # 修改 sticky 为 "nsew"

    # 导入和策略在同一行
    import_strategy_frame = ctk.CTkFrame(polling_settings_frame)
    import_strategy_frame.grid(row=2, column=0, columnspan=2, padx=0, pady=0, sticky="w")

    ctk.CTkLabel(import_strategy_frame, text="轮询策略:", font=("Microsoft YaHei", 14)).grid(row=0, column=0, padx=(5, 0), pady=5, sticky="w")
    polling_strategy_options = ["顺序轮询", "随机轮询"]
    polling_strategy_optionmenu = ctk.CTkOptionMenu(import_strategy_frame, variable=self_instance.polling_strategy_var, values=polling_strategy_options, font=("Microsoft YaHei", 14))
    polling_strategy_optionmenu.grid(row=0, column=1, padx=5, pady=5, sticky="w")

    import_polling_btn = ctk.CTkButton(import_strategy_frame, text="导入轮询配置", command=self_instance.open_polling_config_selection_dialog, font=("Microsoft YaHei", 14))
    import_polling_btn.grid(row=0, column=2, padx=5, pady=5, sticky="w")

    # 错误处理设置
    error_handling_label = ctk.CTkLabel(polling_settings_frame, text="错误处理设置:", font=("Microsoft YaHei", 14, "bold"))
    error_handling_label.grid(row=5, column=0, padx=5, pady=(10, 5), sticky="w")

    # 是否重试
    retry_checkbox = ctk.CTkCheckBox(polling_settings_frame, text="是否重试", variable=self_instance.enable_retry_var, font=("Microsoft YaHei", 14), command=self_instance.toggle_retry_count_entry)
    retry_checkbox.grid(row=6, column=0, padx=5, pady=5, sticky="w")

    # 重试次数
    self_instance.retry_count_entry = ctk.CTkEntry(polling_settings_frame, textvariable=self_instance.retry_count_var, font=("Microsoft YaHei", 14), width=50)
    self_instance.retry_count_entry.grid(row=6, column=1, padx=5, pady=5, sticky="w")
    ctk.CTkLabel(polling_settings_frame, text="次", font=("Microsoft YaHei", 14)).grid(row=6, column=1, padx=(60, 5), pady=5, sticky="w")
    
    # 是否记录日志
    log_checkbox = ctk.CTkCheckBox(polling_settings_frame, text="是否记录日志", variable=self_instance.enable_logging_var, font=("Microsoft YaHei", 14))
    log_checkbox.grid(row=7, column=0, padx=5, pady=5, sticky="w")

    # 错误处理策略和保存在同一行
    error_handling_frame = ctk.CTkFrame(polling_settings_frame)
    error_handling_frame.grid(row=8, column=0, columnspan=2, padx=0, pady=0, sticky="w")

    ctk.CTkLabel(error_handling_frame, text="错误处理策略:", font=("Microsoft YaHei", 14)).grid(row=0, column=0, padx=(5,0), pady=5, sticky="w")
    error_handling_options = ["log_and_continue", "raise_exception", "return_empty_string"]
    error_handling_optionmenu = ctk.CTkOptionMenu(error_handling_frame, variable=self_instance.error_handling_strategy_var, values=error_handling_options, font=("Microsoft YaHei", 14))
    error_handling_optionmenu.grid(row=0, column=1, padx=5, pady=5, sticky="w")

    save_polling_btn = ctk.CTkButton(error_handling_frame, text="保存轮询设置", command=self_instance.save_polling_settings, font=("Microsoft YaHei", 14))
    save_polling_btn.grid(row=0, column=2, padx=5, pady=5, sticky="w")

    # 步骤配置UI
    steps_frame = ctk.CTkScrollableFrame(polling_settings_frame)
    steps_frame.grid(row=9, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
    polling_settings_frame.grid_rowconfigure(9, weight=1)

    try:
        # 确保 'ui/轮询设定' 目录存在
        polling_settings_dir = os.path.join("ui", "轮询设定")
        os.makedirs(polling_settings_dir, exist_ok=True)
        polling_settings_file = os.path.join(polling_settings_dir, "轮询设定.json")

        # 检查文件是否存在，如果不存在则创建并写入默认内容
        if not os.path.exists(polling_settings_file):
            default_steps = {
                "生成架构_生成核心设定": {"策略": "轮询", "指定配置": None},
                "生成架构_生成主要角色": {"策略": "轮询", "指定配置": None},
                "生成架构_生成世界观": {"策略": "轮询", "指定配置": None},
                "生成架构_生成情节大纲": {"策略": "轮询", "指定配置": None},
                "生成分卷_生成分卷角色": {"策略": "轮询", "指定配置": None},
                "生成分卷_生成分卷大纲": {"策略": "轮询", "指定配置": None},
                "生成目录_生成章节蓝图": {"策略": "轮询", "指定配置": None},
                "生成草稿_生成角色信息": {"策略": "轮询", "指定配置": None},
                "生成草稿_生成章节草稿": {"策略": "轮询", "指定配置": None},
                "一致性审校_一致性检查": {"策略": "轮询", "指定配置": None},
                "改写章节_重写或改写章节": {"策略": "轮询", "指定配置": None},
                "章节定稿_生成章节摘要": {"策略": "轮询", "指定配置": None},
                "章节定稿_从章节中识别角色": {"策略": "轮询", "指定配置": None},
                "章节定稿_更新角色状态": {"策略": "轮询", "指定配置": None},
                "章节定稿_更新历史知识": {"策略": "轮询", "指定配置": None},
                "章节定稿_更新内容知识": {"策略": "轮询", "指定配置": None},
                "章节定稿_整合伏笔": {"策略": "轮询", "指定配置": None},
                "章节定稿_提取剧情要点": {"策略": "轮询", "指定配置": None}
            }
            default_polling_data = {
                "轮询列表": [],
                "设置": {
                    "轮询策略": "sequential",
                    "启用重试": True,
                    "重试次数": 3,
                    "启用日志": True,
                    "429错误暂停分钟": 5
                },
                "调用状态": {
                    "上次调用AI索引": -1,
                    "AI状态": {}
                },
                "步骤": default_steps
            }
            with open(polling_settings_file, "w", encoding="utf-8") as f:
                json.dump(default_polling_data, f, indent=2, ensure_ascii=False)

        with open(polling_settings_file, "r", encoding="utf-8") as f:
            polling_settings = json.load(f)
        steps = polling_settings.get("步骤", {})
        
        all_llm_configs = cm.get_config_names()
        
        # 创建一个字典来存储每个步骤的 StringVar
        self_instance.step_config_vars = {}

        for i, (step_name, step_config) in enumerate(steps.items()):
            step_label = ctk.CTkLabel(steps_frame, text=step_name, font=("Microsoft YaHei", 12))
            step_label.grid(row=i, column=0, padx=5, pady=5, sticky="w")
            
            config_var = ctk.StringVar(value=step_config.get("指定配置", "无"))
            self_instance.step_config_vars[step_name] = config_var # 存储StringVar
            
            config_menu = ctk.CTkOptionMenu(steps_frame, variable=config_var, values=["无"] + all_llm_configs, font=("Microsoft YaHei", 12))
            config_menu.grid(row=i, column=1, padx=5, pady=5, sticky="ew")
            
            # 移除独立的 "应用" 按钮

    except Exception as e:
        error_label = ctk.CTkLabel(steps_frame, text=f"加载步骤配置失败: {e}", font=("Microsoft YaHei", 12))
        error_label.pack(pady=10)

    # 查看日志按钮
    view_log_btn = ctk.CTkButton(polling_settings_frame, text="查看日志", command=self_instance.show_polling_log_viewer, font=("Microsoft YaHei", 14))
    view_log_btn.grid(row=10, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

    # 初始化时更新轮询UI
    self_instance.update_polling_config_ui()

def load_llm_embedding_config_logic(self_instance, config_data):
    """加载指定的配置数据到UI"""
    if not config_data:
        return

    self_instance._is_loading_config = True
    try:
        llm_conf = config_data.get("llm_config", {})
        self_instance.interface_format_var.set(llm_conf.get("interface_format", "OpenAI"))
        self_instance.api_key_var.set(llm_conf.get("api_key", ""))
        self_instance.base_url_var.set(llm_conf.get("base_url", ""))
        self_instance.model_name_var.set(llm_conf.get("model_name", ""))
        self_instance.temperature_var.set(llm_conf.get("temperature", 0.7))
        self_instance.top_p_var.set(llm_conf.get("top_p", 0.9))
        self_instance.max_tokens_var.set(llm_conf.get("max_tokens", 8192))
        self_instance.timeout_var.set(llm_conf.get("timeout", 600))
        self_instance.proxy_var.set(llm_conf.get("proxy", ""))

        emb_conf = config_data.get("embedding_config", {})
        self_instance.embedding_interface_format_var.set(emb_conf.get("interface_format", "OpenAI"))
        self_instance.embedding_api_key_var.set(emb_conf.get("api_key", ""))
        self_instance.embedding_url_var.set(emb_conf.get("base_url", ""))
        self_instance.embedding_model_name_var.set(emb_conf.get("model_name", "text-embedding-ada-002"))
        self_instance.embedding_retrieval_k_var.set(str(emb_conf.get("retrieval_k", 4)))

        # 手动触发一次更新，以确保URL等默认值被正确设置
        # 使用 after 确保在主循环中执行，此时 _is_loading_config 标志仍然为 True
        self_instance.master.after(1, lambda: self_instance.on_llm_interface_change(force_update_url=True, skip_model_refresh=True))
        self_instance.master.after(1, lambda: self_instance.on_embedding_interface_change(from_config_load=True))

    finally:
        # 在UI更新完成后，重置标志位
        self_instance.master.after(100, lambda: setattr(self_instance, '_is_loading_config', False))

def save_llm_embedding_config_logic(self_instance):
    config_name = self_instance.config_name_var.get()
    if not config_name:
        messagebox.showerror("错误", "配置名称不能为空。")
        return

    llm_config = {
        "interface_format": self_instance.interface_format_var.get(),
        "api_key": self_instance.api_key_var.get(),
        "base_url": self_instance.base_url_var.get(),
        "model_name": self_instance.model_name_var.get(),
        "temperature": self_instance.temperature_var.get(),
        "top_p": self_instance.top_p_var.get(),
        "max_tokens": self_instance.max_tokens_var.get(),
        "timeout": self_instance.safe_get_int(self_instance.timeout_var, 600),
        "proxy": self_instance.proxy_var.get().strip()
    }
    embedding_config = {
        "interface_format": self_instance.embedding_interface_format_var.get(),
        "api_key": self_instance.embedding_api_key_var.get(),
        "base_url": self_instance.embedding_url_var.get(),
        "model_name": self_instance.embedding_model_name_var.get(),
        "retrieval_k": self_instance.safe_get_int(self_instance.embedding_retrieval_k_var, 4)
    }

    if cm.save_named_config(config_name, llm_config, embedding_config):
        messagebox.showinfo("成功", f"配置 '{config_name}' 已保存。")
        self_instance.update_config_menu()
        self_instance.log(f"配置 '{config_name}' 已保存。")
    else:
        messagebox.showerror("错误", f"保存配置 '{config_name}' 失败。")

def build_ai_config_section(self_instance):
    """
    构建AI模型配置区域
    """
    ai_config_tab = self_instance.ai_config_tab
    ai_config_tab.columnconfigure(1, weight=1)
    ai_config_tab.rowconfigure(10, weight=1) # 让日志窗口所在的行可以扩展

    # 1) 接口格式
    create_label_with_help(ai_config_tab, "接口格式:", "interface_format", 0, 0, font=("Microsoft YaHei", 14))
    interface_options = ["OpenAI兼容", "OpenAI", "Claude", "Google Gemini", "Ollama", "LMStudio", "DeepSeek", "硅基流动", "OpenRouter", "火山引擎", "Azure OpenAI", "Moonshot Kimi", "阿里云百炼"]
    interface_format_optionmenu = ctk.CTkOptionMenu(ai_config_tab, variable=self_instance.interface_format_var, values=interface_options, font=("Microsoft YaHei", 14))
    interface_format_optionmenu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # 2) API Key
    create_label_with_help(ai_config_tab, "API Key:", "api_key", 1, 0, font=("Microsoft YaHei", 14))
    api_key_entry = ctk.CTkEntry(ai_config_tab, textvariable=self_instance.api_key_var, show="*", font=("Microsoft YaHei", 14))
    api_key_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

    # 3) Base URL
    create_label_with_help(ai_config_tab, "Base URL:", "base_url", 2, 0, font=("Microsoft YaHei", 14))
    base_url_entry = ctk.CTkEntry(ai_config_tab, textvariable=self_instance.base_url_var, font=("Microsoft YaHei", 14))
    base_url_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

    # 4) 模型名称
    create_label_with_help(ai_config_tab, "模型名称:", "model_name", 3, 0, font=("Microsoft YaHei", 14))
    self_instance.model_name_combobox = CustomComboBox(
        ai_config_tab,
        variable=self_instance.model_name_var,
        values=[""],
        font=("Microsoft YaHei", 14),
        dropdown_fg_color=ctk.ThemeManager.theme["CTkFrame"]["fg_color"],
        dropdown_hover_color=ctk.ThemeManager.theme["CTkButton"]["hover_color"],
        dropdown_text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"]
    )
    self_instance.model_name_combobox.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
    
    # 绑定接口格式变化事件，用于更新Base URL，但不自动刷新模型列表
    self_instance._llm_interface_trace_id = self_instance.interface_format_var.trace_add("write", lambda name, index, mode: self_instance.on_llm_interface_change(force_update_url=False, skip_model_refresh=True))

    # 5) Temperature
    create_label_with_help(ai_config_tab, "温度 (Temperature):", "temperature", 4, 0, font=("Microsoft YaHei", 14))
    temperature_slider = ctk.CTkSlider(ai_config_tab, from_=0, to=1, number_of_steps=10, variable=self_instance.temperature_var)
    temperature_slider.grid(row=4, column=1, padx=5, pady=5, sticky="ew")
    self_instance.temperature_label_var = ctk.StringVar()
    def format_temperature(*args):
        self_instance.temperature_label_var.set(f"{self_instance.temperature_var.get():.1f}")
    self_instance.temperature_var.trace_add("write", format_temperature)
    format_temperature() # Initial call
    temperature_label = ctk.CTkLabel(ai_config_tab, textvariable=self_instance.temperature_label_var, font=("Microsoft YaHei", 14))
    temperature_label.grid(row=4, column=2, padx=5, pady=5, sticky="w")

    # 6) Top P
    create_label_with_help(ai_config_tab, "Top P:", "top_p", 5, 0, font=("Microsoft YaHei", 14))
    top_p_slider = ctk.CTkSlider(ai_config_tab, from_=0, to=1, number_of_steps=10, variable=self_instance.top_p_var)
    top_p_slider.grid(row=5, column=1, padx=5, pady=5, sticky="ew")
    self_instance.top_p_label_var = ctk.StringVar()
    def format_top_p(*args):
        self_instance.top_p_label_var.set(f"{self_instance.top_p_var.get():.1f}")
    self_instance.top_p_var.trace_add("write", format_top_p)
    format_top_p() # Initial call
    top_p_label = ctk.CTkLabel(ai_config_tab, textvariable=self_instance.top_p_label_var, font=("Microsoft YaHei", 14))
    top_p_label.grid(row=5, column=2, padx=5, pady=5, sticky="w")

    # 7) Max Tokens
    create_label_with_help(ai_config_tab, "最大令牌 (Max Tokens):", "max_tokens", 6, 0, font=("Microsoft YaHei", 14))
    max_tokens_entry = ctk.CTkEntry(ai_config_tab, textvariable=self_instance.max_tokens_var, font=("Microsoft YaHei", 14))
    max_tokens_entry.grid(row=6, column=1, padx=5, pady=5, sticky="ew")

    # 8) Timeout
    create_label_with_help(ai_config_tab, "超时 (Timeout):", "timeout", 7, 0, font=("Microsoft YaHei", 14))
    timeout_entry = ctk.CTkEntry(ai_config_tab, textvariable=self_instance.timeout_var, font=("Microsoft YaHei", 14))
    timeout_entry.grid(row=7, column=1, padx=5, pady=5, sticky="ew")

    # 9) Proxy
    create_label_with_help(ai_config_tab, "代理 (Proxy):", "proxy", 8, 0, font=("Microsoft YaHei", 14))
    proxy_entry = ctk.CTkEntry(ai_config_tab, textvariable=self_instance.proxy_var, font=("Microsoft YaHei", 14))
    proxy_entry.grid(row=8, column=1, padx=5, pady=5, sticky="ew")

    # 10) 按钮容器
    button_frame = ctk.CTkFrame(ai_config_tab, fg_color="transparent")
    button_frame.grid(row=9, column=0, columnspan=3, padx=5, pady=10, sticky="ew")
    button_frame.grid_columnconfigure(0, weight=1)
    button_frame.grid_columnconfigure(1, weight=1)

    test_llm_btn = ctk.CTkButton(button_frame, text="测试LLM配置", command=lambda: self_instance.test_llm_config(self_instance.llm_status_textbox), font=("Microsoft YaHei", 14))
    test_llm_btn.grid(row=0, column=0, padx=5, pady=0, sticky="ew")

    refresh_models_btn = ctk.CTkButton(button_frame, text="刷新模型", command=self_instance.refresh_models_only, font=("Microsoft YaHei", 14))
    refresh_models_btn.grid(row=0, column=1, padx=5, pady=0, sticky="ew")

    # 11) LLM Status Textbox
    self_instance.llm_status_textbox = ctk.CTkTextbox(ai_config_tab, wrap="word", font=("Microsoft YaHei", 12))
    self_instance.llm_status_textbox.grid(row=10, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")

def build_embeddings_config_section(self_instance):
    """
    构建Embedding模型配置区域
    """
    embeddings_config_tab = self_instance.embeddings_config_tab
    embeddings_config_tab.columnconfigure(1, weight=1)
    embeddings_config_tab.rowconfigure(6, weight=1) # 让日志窗口所在的行可以扩展

    # 1) 接口格式
    create_label_with_help(embeddings_config_tab, "接口格式:", "embedding_interface_format", 0, 0, font=("Microsoft YaHei", 14))
    embedding_interface_options = ["OpenAI", "硅基流动", "阿里云百炼", "火山引擎", "Ollama", "LMStudio", "Google Gemini"]
    embedding_interface_format_optionmenu = ctk.CTkOptionMenu(embeddings_config_tab, variable=self_instance.embedding_interface_format_var, values=embedding_interface_options, font=("Microsoft YaHei", 14))
    embedding_interface_format_optionmenu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # 2) API Key
    create_label_with_help(embeddings_config_tab, "API Key:", "embedding_api_key", 1, 0, font=("Microsoft YaHei", 14))
    embedding_api_key_entry = ctk.CTkEntry(embeddings_config_tab, textvariable=self_instance.embedding_api_key_var, show="*", font=("Microsoft YaHei", 14))
    embedding_api_key_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

    # 3) Base URL
    create_label_with_help(embeddings_config_tab, "Base URL:", "embedding_base_url", 2, 0, font=("Microsoft YaHei", 14))
    embedding_url_entry = ctk.CTkEntry(embeddings_config_tab, textvariable=self_instance.embedding_url_var, font=("Microsoft YaHei", 14))
    embedding_url_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

    # 4) 模型名称
    create_label_with_help(embeddings_config_tab, "模型名称:", "embedding_model_name", 3, 0, font=("Microsoft YaHei", 14))
    embedding_model_name_entry = ctk.CTkEntry(embeddings_config_tab, textvariable=self_instance.embedding_model_name_var, font=("Microsoft YaHei", 14))
    embedding_model_name_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
    
    # 绑定Embedding接口格式变化事件，用于更新Base URL
    self_instance._embedding_interface_trace_id = self_instance.embedding_interface_format_var.trace_add("write", lambda name, index, mode: self_instance.on_embedding_interface_change(from_config_load=False))

    # 5) Retrieval K
    create_label_with_help(embeddings_config_tab, "检索K值:", "retrieval_k", 4, 0, font=("Microsoft YaHei", 14))
    retrieval_k_entry = ctk.CTkEntry(embeddings_config_tab, textvariable=self_instance.embedding_retrieval_k_var, font=("Microsoft YaHei", 14))
    retrieval_k_entry.grid(row=4, column=1, padx=5, pady=5, sticky="ew")

    # 6) Test Embedding Config Button
    test_embedding_btn = ctk.CTkButton(embeddings_config_tab, text="测试Embedding配置", command=lambda: self_instance.test_embedding_config(self_instance.embedding_status_textbox), font=("Microsoft YaHei", 14))
    test_embedding_btn.grid(row=5, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

    # 7) Embedding Status Textbox
    self_instance.embedding_status_textbox = ctk.CTkTextbox(embeddings_config_tab, wrap="word", font=("Microsoft YaHei", 12))
    self_instance.embedding_status_textbox.grid(row=6, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
