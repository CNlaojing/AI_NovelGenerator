# ui/main_window.py
# -*- coding: utf-8 -*-
import os
import threading
import logging
import traceback
import sys
import re
import json
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
try:
    from tkcalendar import DateEntry
except ImportError:
    DateEntry = None
from .role_library import RoleLibrary
from llm_adapters import create_llm_adapter, PollingManager
from embedding_adapters import create_embedding_adapter

import config_manager as cm
from utils import read_file, save_string_to_txt, clear_file_content
from tooltips import tooltips

from ui.context_menu import TextWidgetContextMenu
from ui.main_tab import build_main_tab, build_left_layout, build_right_layout
from ui.llm_settings_tab import build_llm_settings_tab, load_llm_embedding_config_logic # 移除其他导入
from ui.novel_params_tab import build_novel_params_area, build_optional_buttons_area, _setup_resizable_textbox
from ui.generation_handlers import (
    _reformat_text_if_needed,
    generate_novel_architecture_ui,
    generate_volume_ui,
    generate_chapter_blueprint_ui,
    generate_chapter_draft_ui,
    finalize_chapter_ui,
    do_consistency_check,
    show_plot_arcs_ui,
    rewrite_chapter_ui,
    show_rewrite_prompt_editor,
    execute_chapter_rewrite,
    show_consistency_check_results_ui,
    import_knowledge_handler,
    clear_vectorstore_handler,
    repair_character_database
)
from ui.setting_tab import build_setting_tab, load_novel_architecture, save_novel_architecture
from ui.directory_tab import build_directory_tab, load_chapter_blueprint, save_chapter_blueprint, load_text_file
from ui.character_tab import build_character_tab, load_character_file, load_character_state, save_character_state
from ui.summary_tab import build_summary_tab, load_global_summary, save_global_summary
from ui.chapters_tab import build_chapters_tab, refresh_chapters_list, on_chapter_selected, load_chapter_content, save_current_chapter, prev_chapter, next_chapter
from ui.volume_tab import build_volume_tab, load_volume, save_volume, show_volume_tab
from ui.vectorstore_tab import build_vectorstore_tab
from novel_generator.common import get_chapter_filepath

class NovelGeneratorGUI:
    """
    小说生成器的主GUI类，包含所有的界面布局、事件处理、与后端逻辑的交互等。
    """
    def __init__(self, master):
        self.root = master
        self.master = master
        self.master.title("Novel Generator GUI V1.7.3")
        try:
            # 使用 stderr 重定向来捕获 libpng 警告 (已注释掉以排查终端乱码问题)
            # import sys
            # import os
            # stderr = sys.stderr
            # null = open(os.devnull, 'w')
            # sys.stderr = null
            if os.path.exists("icon.ico"):
                self.master.iconbitmap("icon.ico")
            # sys.stderr = stderr
            # null.close()
        except Exception:
            pass
        self.master.geometry("1350x840")
        self.workflow_panel = None # 用于持有对WorkflowPanel实例的引用

        # --------------- 控制标志 ---------------
        self._is_loading_project_info = False
        self._is_loading_config = False

        # --------------- 配置文件路径 ---------------
        self.config_file = "config.json"
        self.loaded_config = cm.load_config() # 使用新的加载函数

        # --------------- 默认URL映射 ---------------
        self.default_urls = {
            "OpenAI兼容": {"llm": "", "embedding": ""},
            "OpenAI": {"llm": "https://api.openai.com/v1", "embedding": "https://api.openai.com/v1/embeddings"},
            "Claude": {"llm": "https://api.anthropic.com/v1", "embedding": ""},
            "Google Gemini": {"llm": "", "embedding": ""},
            "Ollama": {"llm": "http://localhost:11434/v1", "embedding": "http://localhost:11434/api/embeddings"},
            "LMStudio": {"llm": "http://localhost:1234/v1", "embedding": "http://localhost:1234/v1/embeddings"},
            "DeepSeek": {"llm": "https://api.deepseek.com/v1", "embedding": ""},
            "硅基流动": {"llm": "https://api.siliconflow.cn/v1", "embedding": "https://api.siliconflow.cn/v1/embeddings"},
            "OpenRouter": {"llm": "https://openrouter.ai/api/v1", "embedding": ""},
            "火山引擎": {"llm": "https://ark.cn-beijing.volces.com/api/v3", "embedding": "https://ark.cn-beijing.volces.com/api/v3"},
            "Azure OpenAI": {"llm": "https://{your-resource-name}.openai.azure.com/openai/deployments/{deployment}/chat/completions", "embedding": ""},
            "Moonshot Kimi": {"llm": "https://api.moonshot.cn/v1", "embedding": ""},
            "阿里云百炼": {"llm": "https://dashscope.aliyuncs.com/compatible-mode/v1", "embedding": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"}
        }

        # --------------- 新增：默认模型映射 ---------------
        self.default_llm_models = {
            "OpenAI兼容": "gemini-2.5-pro",
            "OpenAI": "gpt-4o-2024-08-06",
            "Claude": "claude-3.5-sonnet-20241022",
            "Google Gemini": "gemini-2.5-pro",
            "Ollama": "",
            "LMStudio": "",
            "DeepSeek": "deepseek-chat",
            "硅基流动": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            "OpenRouter": "google/gemini-2.5-pro",
            "火山引擎": "",
            "Azure OpenAI": "gpt-4o",
            "Moonshot Kimi": "kimi-k2-0905-preview",
            "阿里云百炼": "qwen-plus-2025-09-11"
        }
        self.default_embedding_models = {
            "OpenAI": "text-embedding-3-small",
            "硅基流动": "BAAI/bge-large-zh-v1.5",
            "阿里云百炼": "text-embedding-v4",
            "火山引擎": "",
            "Ollama": "nomic-embed-text:latest",
            "LMStudio": "nomic-embed-text",
            "Google Gemini": "gemini-embedding-001"
        }

        # 获取默认配置
        default_config = cm.get_default_config()
        if default_config:
            llm_conf = default_config.get("llm_config", {})
            emb_conf = default_config.get("embedding_config", {})
            last_llm = llm_conf.get("interface_format", "OpenAI")
            last_embedding = emb_conf.get("interface_format", "OpenAI")
        else:
            # 如果没有默认配置，则使用空配置
            llm_conf = {}
            emb_conf = {}
            last_llm = "OpenAI"
            last_embedding = "OpenAI"

        # -- LLM通用参数 --
        self.api_key_var = ctk.StringVar(value=llm_conf.get("api_key", ""))
        self.base_url_var = ctk.StringVar(value=llm_conf.get("base_url", ""))
        self.interface_format_var = ctk.StringVar(value=last_llm)
        self.model_name_var = ctk.StringVar(value=llm_conf.get("model_name", ""))
        self.temperature_var = ctk.DoubleVar(value=llm_conf.get("temperature", 0.7))
        self.top_p_var = ctk.DoubleVar(value=llm_conf.get("top_p", 0.9))
        self.max_tokens_var = ctk.IntVar(value=llm_conf.get("max_tokens", 30000))
        self.timeout_var = ctk.IntVar(value=llm_conf.get("timeout", 600))
        self.proxy_var = ctk.StringVar(value=llm_conf.get("proxy", ""))

        # -- Embedding相关 --
        self.embedding_interface_format_var = ctk.StringVar(value=last_embedding)
        self.embedding_api_key_var = ctk.StringVar(value=emb_conf.get("api_key", ""))
        self.embedding_url_var = ctk.StringVar(value=emb_conf.get("base_url", ""))
        self.embedding_model_name_var = ctk.StringVar(value=emb_conf.get("model_name", ""))
        self.embedding_retrieval_k_var = ctk.StringVar(value=str(emb_conf.get("retrieval_k", 4)))
        self._llm_interface_trace_id = None
        self._embedding_interface_trace_id = None


        # -- 轮询设置相关 --
        self.polling_configs_var = ctk.StringVar(value="") # 用于显示轮询列表
        self.available_llm_configs_var = ctk.StringVar(value="") # 用于选择添加到轮询的配置
        self.polling_strategy_var = ctk.StringVar(value=cm.get_polling_strategy())

        # -- 错误处理设置相关 --
        self.enable_retry_var = ctk.BooleanVar(value=cm.get_error_handling_setting("enable_retry", True))
        self.retry_count_var = ctk.StringVar(value=str(cm.get_error_handling_setting("retry_count", 3)))
        self.enable_logging_var = ctk.BooleanVar(value=cm.get_error_handling_setting("enable_logging", True))
        self.error_handling_strategy_var = ctk.StringVar(value=cm.get_error_handling_setting("error_handling_strategy", "log_and_continue")) # 新增错误处理策略变量

        # -- 主界面LLM配置相关变量 --
        llm_mode = self.loaded_config.get("llm_selection_mode", "llm_config")
        self.enable_polling_var = ctk.BooleanVar(value=(llm_mode == "polling"))
        self.enable_llm_config_var = ctk.BooleanVar(value=(llm_mode == "llm_config"))
        self.main_config_selection_var = ctk.StringVar()
        self.main_model_name_var = ctk.StringVar()
        self.auto_reformat_var = ctk.BooleanVar(value=True)

        # -- 小说参数相关 --
        # 优先从主配置加载上次使用的路径
        last_used_filepath = self.loaded_config.get("last_used_filepath", "")
        if not last_used_filepath or not os.path.isdir(last_used_filepath):
            # 如果路径无效，则在软件根目录下创建并使用 "小说" 文件夹
            default_novel_dir = os.path.join(os.getcwd(), "小说")
            try:
                os.makedirs(default_novel_dir, exist_ok=True)
                last_used_filepath = default_novel_dir
                # 将这个新路径写回主配置，以便下次启动
                config = cm.load_config()
                config["last_used_filepath"] = last_used_filepath
                cm.save_config(config)
            except Exception as e:
                # 如果创建失败，则回退到根目录
                last_used_filepath = os.getcwd()
                self.safe_log(f"❌ 创建默认小说文件夹失败: {e}")
        self.filepath_var = ctk.StringVar(value=last_used_filepath)

        if self.loaded_config and "other_params" in self.loaded_config:
            op = self.loaded_config["other_params"]
            self.topic_default = op.get("topic", "")
            self.genre_var = ctk.StringVar(value=op.get("genre", "玄幻"))
            self.num_chapters_var = ctk.StringVar(value=str(op.get("num_chapters", 10)))
            self.word_number_var = ctk.StringVar(value=str(op.get("word_number", 3000)))
            self.word_number_var.trace_add("write", self._update_word_count_ranges)
            # 文件路径已在上面处理
            self.chapter_num_var = ctk.StringVar(value=str(op.get("chapter_num", "1")))
            self.characters_involved_var = ctk.StringVar(value=op.get("characters_involved", ""))
            self.key_items_var = ctk.StringVar(value=op.get("key_items", ""))
            self.scene_location_var = ctk.StringVar(value=op.get("scene_location", ""))
            self.time_constraint_var = ctk.StringVar(value=op.get("time_constraint", ""))
            self.user_guidance_default = op.get("user_guidance", "")
            self.volume_count_var = ctk.StringVar(value=str(op.get("volume_count", 3)))  # 修改这里
            self.main_character_var = ctk.StringVar(value=op.get("main_character", ""))
            # 初始化所有StringVar，确保它们在_setup_resizable_textbox中使用时已存在
            self.topic_var = ctk.StringVar(value=self.topic_default)
            self.user_guidance_var = ctk.StringVar(value=self.user_guidance_default)
            self.characters_involved_var = ctk.StringVar(value=op.get("characters_involved", ""))
            self.key_items_var = ctk.StringVar(value=op.get("key_items", ""))
            self.scene_location_var = ctk.StringVar(value=op.get("scene_location", ""))
            self.time_constraint_var = ctk.StringVar(value=op.get("time_constraint", ""))

            # 尝试加载角色状态文件
            character_state_content = ""
            filepath = op.get("filepath", "")
            if filepath and os.path.isdir(filepath):
                char_state_file = os.path.join(filepath, "待用角色.txt")
                if os.path.exists(char_state_file):
                    try:
                        character_state_content = read_file(char_state_file)
                    except Exception as e:
                        logging.warning(f"无法读取角色状态文件 {char_state_file}: {e}")
            self.character_state_var = ctk.StringVar(value=character_state_content)

        else:
            self.topic_default = ""
            self.genre_var = ctk.StringVar(value="玄幻")
            self.num_chapters_var = ctk.StringVar(value="10")
            self.word_number_var = ctk.StringVar(value="3000")
            self.word_number_var.trace_add("write", self._update_word_count_ranges)
            # 文件路径已在上面处理
            self.chapter_num_var = ctk.StringVar(value="1")
            self.characters_involved_var = ctk.StringVar(value="")
            self.key_items_var = ctk.StringVar(value="")
            self.scene_location_var = ctk.StringVar(value="")
            self.time_constraint_var = ctk.StringVar(value="")
            self.user_guidance_default = ""
            self.volume_count_var = ctk.StringVar(value="3")  # 添加这里
            # 初始化所有StringVar (else 分支)
            self.topic_var = ctk.StringVar(value=self.topic_default)
            self.user_guidance_var = ctk.StringVar(value=self.user_guidance_default)
            self.characters_involved_var = ctk.StringVar(value="")
            self.key_items_var = ctk.StringVar(value="")
            self.scene_location_var = ctk.StringVar(value="")
            self.time_constraint_var = ctk.StringVar(value="")
            self.main_character_var = ctk.StringVar(value="")

            # 尝试加载角色状态文件 (else 分支)
            character_state_content = ""
            filepath = self.filepath_var.get() # 从StringVar获取路径
            if filepath and os.path.isdir(filepath):
                char_state_file = os.path.join(filepath, "待用角色.txt")
                if os.path.exists(char_state_file):
                    try:
                        character_state_content = read_file(char_state_file)
                    except Exception as e:
                        logging.warning(f"无法读取角色状态文件 {char_state_file}: {e}")
            self.character_state_var = ctk.StringVar(value=character_state_content)

        # --------------- 整体Tab布局 ---------------
        self.tabview = ctk.CTkTabview(self.master)
        self.tabview.pack(fill="both", expand=True)

        # 绑定生成器处理函数 (确保只绑定一次)
        self.generate_novel_architecture_ui = generate_novel_architecture_ui.__get__(self)
        self.generate_volume_ui = generate_volume_ui.__get__(self)
        self.generate_chapter_blueprint_ui = generate_chapter_blueprint_ui.__get__(self)
        self.generate_chapter_draft_ui = generate_chapter_draft_ui.__get__(self)
        self.finalize_chapter_ui = finalize_chapter_ui.__get__(self)
        self.do_consistency_check = do_consistency_check.__get__(self)
        self.import_knowledge_handler = import_knowledge_handler.__get__(self)
        self.clear_vectorstore_handler = clear_vectorstore_handler.__get__(self)
        self.repair_character_database = repair_character_database.__get__(self)
        self.show_plot_arcs_ui = show_plot_arcs_ui.__get__(self)
        self.rewrite_chapter_ui = rewrite_chapter_ui.__get__(self)
        self.show_rewrite_prompt_editor = show_rewrite_prompt_editor.__get__(self)
        self.execute_chapter_rewrite = execute_chapter_rewrite.__get__(self)
        self.show_consistency_check_results_ui = show_consistency_check_results_ui.__get__(self)
        self._reformat_text_if_needed = _reformat_text_if_needed.__get__(self)
        self.load_chapter_blueprint = load_chapter_blueprint.__get__(self)
        self.save_chapter_blueprint = save_chapter_blueprint.__get__(self)
        self.load_text_file = load_text_file.__get__(self)
        self.export_full_novel = self.export_full_novel.__get__(self)
        self.run_workflow_ui = self.run_workflow_ui.__get__(self)

        # 创建各个标签页
        build_main_tab(self)
        build_llm_settings_tab(self, self.tabview) # 替换为新的LLM设置标签页
        
        build_setting_tab(self)
        build_volume_tab(self)
        build_directory_tab(self)
        build_character_tab(self)
        build_summary_tab(self)
        build_chapters_tab(self)
        build_vectorstore_tab(self)
        self.build_about_tab() # 新增关于页面

        # 初始加载一次项目配置，确保在UI控件创建后执行
        self.load_project_basic_info(self.filepath_var.get())

        # -- 绑定新的配置管理方法 --
        self.save_named_config = self.save_named_config
        self.load_named_config = self.load_named_config
        self.delete_named_config = self.delete_named_config
        self.set_default_named_config = self.set_default_named_config
        self.update_config_menu = self.update_config_menu
        self.load_default_config_on_startup = self.load_default_config_on_startup
        
        # 初始化轮询配置UI
        self.update_polling_config_ui()
        
        # 初始化主界面LLM配置
        self.init_main_llm_config()
        
        # 确保UI状态正确同步
        self.master.after(100, self.update_llm_config_ui_state)

        # 在所有UI加载和初始值设定完成后，再绑定自动保存的trace，防止启动时错误覆盖
        self._bind_project_info_traces()

    # ----------------- 通用辅助函数 -----------------
    def show_tooltip(self, key: str):
        info_text = tooltips.get(key, "暂无说明")
        messagebox.showinfo("参数说明", info_text)

    def safe_get_int(self, var, default=1):
        try:
            val_str = str(var.get()).strip()
            return int(val_str)
        except:
            var.set(str(default))
            return default

    def log(self, message: str, stream: bool = False, replace_last_line: bool = False):
        """
        通用日志记录函数，使用Tkinter标签(tag)来精确、稳定地处理临时行的更新。
        增加了条件自动滚动功能。
        """
        # 预处理消息，确保换行符正确
        message = message.replace('\r\n', '\n').replace('\r', '\n')

        # 检查滚动条是否在底部
        scroll_pos = self.log_text.yview()
        scroll_to_end = scroll_pos[1] >= 1.0

        self.log_text.configure(state="normal")
        
        # 定义计时器行的标签名
        timer_tag = "timer_line"
        
        # 获取当前标签的范围
        tag_ranges = self.log_text.tag_ranges(timer_tag)

        if replace_last_line:
            # 如果标签已存在，说明正在更新计时器
            if tag_ranges:
                start, end = tag_ranges
                # 删除旧内容，插入新内容，并重新应用标签
                self.log_text.delete(start, end)
                self.log_text.insert(start, message, timer_tag)
            # 如果标签不存在，说明是第一次显示计时器
            else:
                # 确保计时器前有一个换行符（如果文本框不为空且末尾不是换行）
                if self.log_text.index("end-1c") != "1.0" and self.log_text.get("end-2c", "end-1c") != '\n':
                    self.log_text.insert("end", "\n")
                
                # 插入带标签的新行
                self.log_text.insert("end", message, timer_tag)
        else:
            # 写入常规日志
            # 如果计时器行存在，先删除它
            if tag_ranges:
                start, end = tag_ranges
                # 删除整行，包括可能的前一个换行符
                line_start = self.log_text.index(f"{start} linestart")
                self.log_text.delete(line_start, f"{end}+1c") # 删除到行尾+换行符

            # 插入常规日志消息
            if stream:
                self.log_text.insert("end", message)
            else:
                self.log_text.insert("end", message + "\n")

        # 只有当滚动条在最底部时才自动滚动
        if scroll_to_end:
            self.log_text.see("end")
            
        self.log_text.configure(state="disabled")

    def safe_log(self, message: str, stream: bool = False, replace_last_line: bool = False):
        """
        log 方法的线程安全版本，确保UI更新在主线程中执行。
        """
        self.master.after(0, lambda: self.log(message, stream=stream, replace_last_line=replace_last_line))

    def disable_button_safe(self, btn):
        self.master.after(0, lambda: btn.configure(state="disabled"))

    def enable_button_safe(self, btn):
        self.master.after(0, lambda: btn.configure(state="normal"))

    def handle_exception(self, context: str):
        full_message = f"{context}\n{traceback.format_exc()}"
        logging.error(full_message)
        self.safe_log(full_message)

    def log_and_show_message(self, message: str, msg_type: str = "info"):
        """记录日志并显示一个消息框。"""
        self.log(message)
        if msg_type == "info":
            messagebox.showinfo("提示", message)
        elif msg_type == "warning":
            messagebox.showwarning("警告", message)
        elif msg_type == "error":
            messagebox.showerror("错误", message)

    def show_chapter_in_textbox(self, text: str):
        self.chapter_result.delete("0.0", "end")
        self.chapter_result.insert("0.0", text)
        self.chapter_result.see("end")
    
    def browse_folder(self):
        selected_dir = filedialog.askdirectory()
        if (selected_dir):
            self.filepath_var.set(selected_dir)
            # The trace on filepath_var will automatically call load_project_basic_info
            
            # --- 新增：将新路径保存到主配置文件 ---
            try:
                config = cm.load_config()
                config["last_used_filepath"] = selected_dir
                cm.save_config(config)
                self.safe_log(f"✅ 已将默认保存路径更新为: {selected_dir}")
            except Exception as e:
                self.safe_log(f"❌ 保存默认路径失败: {e}")

    def open_filepath_in_explorer(self):
        filepath = self.filepath_var.get()
        if not filepath:
            messagebox.showwarning("警告", "保存路径为空，无法打开。")
            return
        if not os.path.exists(filepath):
            messagebox.showwarning("警告", f"路径不存在：{filepath}")
            return
        try:
            os.startfile(filepath) # For Windows
        except AttributeError:
            # For macOS and Linux
            import subprocess
            if sys.platform == "darwin": # macOS
                subprocess.Popen(["open", filepath])
            elif sys.platform.startswith("linux"): # Linux
                subprocess.Popen(["xdg-open", filepath])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开路径：{e}")

    def show_character_import_window(self):
        """显示角色导入窗口"""
        import_window = ctk.CTkToplevel(self.master)
        import_window.title("导入角色信息")
        import_window.geometry("600x500")
        import_window.transient(self.master)  # 设置为父窗口的临时窗口
        import_window.grab_set()  # 保持窗口在顶层
        
        # 主容器
        main_frame = ctk.CTkFrame(import_window)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 滚动容器
        scroll_frame = ctk.CTkScrollableFrame(main_frame)
        scroll_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 获取角色库路径
        role_lib_path = os.path.join(self.filepath_var.get().strip(), "角色库")
        self.selected_roles = []  # 存储选中的角色名称
        
        # 动态加载角色分类
        if os.path.exists(role_lib_path):
            # 配置网格布局参数
            scroll_frame.columnconfigure(0, weight=1)
            max_roles_per_row = 4
            current_row = 0
            
            for category in os.listdir(role_lib_path):
                category_path = os.path.join(role_lib_path, category)
                if os.path.isdir(category_path):
                    # 创建分类容器
                    category_frame = ctk.CTkFrame(scroll_frame)
                    category_frame.grid(row=current_row, column=0, sticky="w", pady=(10,5), padx=5)
                    
                    # 添加分类标签
                    category_label = ctk.CTkLabel(category_frame, text=f"【{category}】", 
                                                font=("Microsoft YaHei", 14, "bold"))
                    category_label.grid(row=0, column=0, padx=(0,10), sticky="w")
                    
                    # 初始化角色排列参数
                    role_count = 0
                    row_num = 0
                    col_num = 1  # 从第1列开始（第0列是分类标签）
                    
                    # 添加角色复选框
                    for role_file in os.listdir(category_path):
                        if role_file.endswith(".txt"):
                            role_name = os.path.splitext(role_file)[0]
                            if not any(name == role_name for _, name in self.selected_roles):
                                chk = ctk.CTkCheckBox(category_frame, text=role_name)
                                chk.grid(row=row_num, column=col_num, padx=5, pady=2, sticky="w")
                                self.selected_roles.append((chk, role_name))
                                
                                # 更新行列位置
                                role_count += 1
                                col_num += 1
                                if col_num > max_roles_per_row:
                                    col_num = 1
                                    row_num += 1
                    
                    # 如果没有角色，调整分类标签占满整行
                    if role_count == 0:
                        category_label.grid(columnspan=max_roles_per_row+1, sticky="w")
                    
                    # 更新主布局的行号
                    current_row += 1
                    
                    # 添加分隔线
                    separator = ctk.CTkFrame(scroll_frame, height=1, fg_color="gray")
                    separator.grid(row=current_row, column=0, sticky="ew", pady=5)
                    current_row += 1
        
        # 底部按钮框架
        btn_frame = ctk.CTkFrame(main_frame)
        btn_frame.pack(fill="x", pady=10)
        
        # 选择按钮
        def confirm_selection():
            selected = [name for chk, name in self.selected_roles if chk.get() == 1]
            self.char_inv_text.delete("0.0", "end")
            self.char_inv_text.insert("0.0", ", ".join(selected))
            # 更新characters_involved_var变量
            if hasattr(self, 'characters_involved_var'):
                self.characters_involved_var.set(", ".join(selected))
            import_window.destroy()
            
        btn_confirm = ctk.CTkButton(btn_frame, text="选择", command=confirm_selection)
        btn_confirm.pack(side="left", padx=20)
        
        # 取消按钮
        btn_cancel = ctk.CTkButton(btn_frame, text="取消", command=import_window.destroy)
        btn_cancel.pack(side="right", padx=20)

    def show_role_library(self):
        save_path = self.filepath_var.get().strip()
        if not save_path:
            messagebox.showwarning("警告", "请先设置保存路径")
            return
        
        # 初始化LLM适配器
        llm_adapter = self.create_llm_adapter_with_current_config()
        
        # 传递LLM适配器实例到角色库
        if hasattr(self, '_role_lib'):
            if self._role_lib.window and self._role_lib.window.winfo_exists():
                self._role_lib.window.destroy()
        
        self._role_lib = RoleLibrary(self.master, save_path, llm_adapter)  # 新增参数

    def build_about_tab(self):
        """创建“关于”标签页"""
        about_tab = self.tabview.add("关于")
        
        # 创建主框架
        main_frame = ctk.CTkFrame(about_tab)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 提取版本号
        version = "未知"
        title_match = re.search(r'v[\d\.]+', self.master.title())
        if title_match:
            version = title_match.group(0)

        # 显示版本号
        version_label = ctk.CTkLabel(main_frame, text=f"版本: {version}", font=("Microsoft YaHei", 16, "bold"))
        version_label.pack(pady=(5, 10))

        # 创建一个文本框来显示README内容
        readme_textbox = ctk.CTkTextbox(main_frame, wrap="word", font=("Microsoft YaHei", 14))
        readme_textbox.pack(fill="both", expand=True, padx=5, pady=5)

        # 读取并插入README.md内容
        try:
            # 直接调用导入的 read_file 函数
            readme_content = read_file("README.md")
            readme_textbox.insert("0.0", readme_content)
        except FileNotFoundError:
            readme_textbox.insert("0.0", "错误：未找到 README.md 文件。")
        except Exception as e:
            readme_textbox.insert("0.0", f"读取 README.md 文件时出错: {e}")
        
        # 设置文本框为只读
        readme_textbox.configure(state="disabled")

    # 删除重复的show_plot_arcs_ui函数实现,只保留函数引用
    show_plot_arcs_ui = show_plot_arcs_ui

    def show_donate_window(self):
        """显示捐赠窗口"""
        donate_window = ctk.CTkToplevel(self.master)
        donate_window.title("感谢支持")
        donate_window.geometry("800x900")
        donate_window.resizable(False, False)
        donate_window.attributes('-topmost', True)  # 设置为置顶窗口
        donate_window.protocol("WM_ICONIFY_WINDOW", lambda: donate_window())        
        # 标题文本
        title_text = (
            "AI_NovelGenerator (CNlaojing Fork)\n"
            "基于 YILING0013/AI_NovelGenerator 的自动小说生成工具增强版本\n"
            "本项目是Fork分支，由 CNlaojing 维护。\n"
            "非正常渠道获取的本项目软件，谢绝打赏。"
        )
        title_label = ctk.CTkLabel(
            donate_window, 
            text=title_text,
            wraplength=380,
            justify="left",
            font=("Microsoft YaHei", 14)
        )
        title_label.pack(pady=(20, 10), padx=10)
        
        # 创建图片框架
        image_frame = ctk.CTkFrame(donate_window)
        image_frame.pack(pady=10, padx=10)
        
        try:
            # 修改图片路径，使用os.path.join来构建正确的路径
            img_path = os.path.join(os.path.dirname(__file__), "ds.dat")
            img = tk.PhotoImage(file=img_path)
            img_label = tk.Label(image_frame, image=img)
            img_label.image = img  # 保持引用防止垃圾回收
            img_label.pack()
        except Exception as e:
            error_label = ctk.CTkLabel(
                image_frame,
                text="无法加载二维码图片",
                font=("Microsoft YaHei", 14)
            )
            error_label.pack(pady=20)
            print(f"Error loading image: {e}")
        
        # 底部文本
        bottom_text = "如非正常渠道获取本软件，请勿扫码捐赠，感谢对本软件的支持"
        bottom_label = ctk.CTkLabel(
            donate_window,
            text=bottom_text,
            font=("Microsoft YaHei", 14)
        )
        bottom_label.pack(pady=(10, 20))

    # ----------------- 将导入的各模块函数直接赋给类方法 -----------------
    generate_novel_architecture_ui = generate_novel_architecture_ui
    generate_volume_ui = generate_volume_ui
    generate_chapter_blueprint_ui = generate_chapter_blueprint_ui
    generate_chapter_draft_ui = generate_chapter_draft_ui
    finalize_chapter_ui = finalize_chapter_ui
    do_consistency_check = do_consistency_check
    show_plot_arcs_ui = show_plot_arcs_ui
    load_novel_architecture = load_novel_architecture
    save_novel_architecture = save_novel_architecture
    load_chapter_blueprint = load_chapter_blueprint
    save_chapter_blueprint = save_chapter_blueprint
    load_character_file = load_character_file
    load_character_state = load_character_state
    save_character_state = save_character_state
    load_global_summary = load_global_summary
    save_global_summary = save_global_summary
    refresh_chapters_list = refresh_chapters_list
    on_chapter_selected = on_chapter_selected
    save_current_chapter = save_current_chapter
    prev_chapter = prev_chapter
    next_chapter = next_chapter
    browse_folder = browse_folder
    open_filepath_in_explorer = open_filepath_in_explorer
    show_volume_tab = show_volume_tab
    load_volume = load_volume
    save_volume = save_volume
    rewrite_chapter_ui = rewrite_chapter_ui
    execute_chapter_rewrite = execute_chapter_rewrite

    def export_full_novel(self):
        """导出整本小说"""
        novel_dir = self.filepath_var.get()
        if not novel_dir or not os.path.isdir(novel_dir):
            messagebox.showerror("错误", "请先设置有效的小说保存路径。")
            return

        chapters_dir = os.path.join(novel_dir, "章节正文")
        if not os.path.isdir(chapters_dir):
            messagebox.showerror("错误", f"找不到章节目录：{chapters_dir}")
            return

        try:
            # 获取所有章节文件并进行自然排序
            chapter_files = [f for f in os.listdir(chapters_dir) if f.endswith(".txt")]
            chapter_files.sort(key=lambda f: int(re.search(r'\d+', f).group()))

            if not chapter_files:
                messagebox.showinfo("提示", "章节目录中没有找到任何章节文件。")
                return

            full_content = []
            self.safe_log("开始导出小说...")
            for chapter_file in chapter_files:
                try:
                    content = read_file(os.path.join(chapters_dir, chapter_file))
                    full_content.append(content)
                    full_content.append("\n\n")
                except Exception as e:
                    self.safe_log(f"读取章节 {chapter_file} 失败: {e}")
                    continue
            
            full_novel_text = "".join(full_content)

            # 弹出文件保存对话框
            save_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="保存整本小说",
                initialdir=novel_dir,
                initialfile=f"{os.path.basename(novel_dir)}.txt"
            )

            if save_path:
                save_string_to_txt(full_novel_text, save_path)
                self.safe_log(f"小说已成功导出到：{save_path}")
                messagebox.showinfo("成功", f"小说已成功导出到：\n{save_path}")
            else:
                self.safe_log("导出操作已取消。")

        except Exception as e:
            self.handle_exception(f"导出小说时发生错误: {e}")
            messagebox.showerror("导出失败", f"导出小说时发生错误：\n{e}")

    # ----------------- 新的配置管理方法 -----------------
    def update_config_menu(self):
        """更新配置选择下拉菜单"""
        names = cm.get_config_names()
        self.config_option_menu.configure(values=names if names else ["无可用配置"])
        if not names:
            self.config_selection_var.set("无可用配置")
        else:
            # 保持当前选择，如果它仍然存在
            current_selection = self.config_selection_var.get()
            if current_selection not in names:
                self.config_selection_var.set(names[0])

    def on_llm_interface_change(self, *args, force_update_url=False, skip_model_refresh=False):
        """
        当LLM接口格式改变时，动态更新模型名称下拉菜单的选项。
        如果 force_update_url 为 True，则强制更新 Base URL 为默认值。
        如果 skip_model_refresh 为 True，则跳过模型列表的刷新。
        """
        if self._is_loading_config:
            return
        interface_format = self.interface_format_var.get().strip()
        api_key = self.api_key_var.get().strip()
        current_model_name = self.model_name_var.get().strip() # 当前选中的模型名称
        
        # 根据接口格式更新Base URL
        interface_urls = self.default_urls.get(interface_format, {"llm": "", "embedding": ""})
        default_url = interface_urls.get("llm", "")
        
        # 新增：根据接口格式更新模型名称
        default_model = self.default_llm_models.get(interface_format, "")
        
        current_base_url_val = self.base_url_var.get().strip()

        # 确定最终的 base_url
        if force_update_url:
            # 如果是强制更新（来自加载配置或启动），则不修改URL，直接使用 base_url_var 的当前值
            # 因为 base_url_var 已经在 load_llm_embedding_config_logic 中被设置
            base_url = self.base_url_var.get().strip() # 获取已设置的值
        else:
            # 如果不是强制更新（用户手动切换接口格式），则将URL和模型设置为对应接口的默认值
            if default_url:
                self.master.after(0, lambda: self.base_url_var.set(default_url))
                base_url = default_url
            else:
                # 如果没有默认URL（例如Custom），则清空
                self.master.after(0, lambda: self.base_url_var.set(""))
                base_url = ""
            # 设置默认模型
            self.master.after(0, lambda: self.model_name_var.set(default_model))
        
        # 确保 base_url 变量始终反映 self.base_url_var 的最新值
        base_url = self.base_url_var.get().strip()

        # 如果 skip_model_refresh 为 True，则只更新URL和状态，不刷新模型列表
        if skip_model_refresh:
            self.safe_update_llm_status_textbox(f"ℹ️ 接口格式已切换为 '{interface_format}'，Base URL 和模型已更新。")
            return

        # 刷新模型列表的逻辑
        # 在开始获取模型前，将状态信息输出到日志窗口
        self.safe_update_llm_status_textbox(f"ℹ️ 正在获取 '{interface_format}' 接口的可用模型...")
        # 暂时清空 ComboBox 的 values，但保留当前 model_name_var 的值
        self.master.after(0, lambda: self.model_name_combobox.configure(values=[""]))


        def fetch_and_update_models_thread():
            try:
                llm_config = {
                    "interface_format": interface_format,
                    "api_key": api_key,
                    "base_url": base_url,
                    "model_name": current_model_name,
                    "max_tokens": self.max_tokens_var.get(),
                    "temperature": self.temperature_var.get(),
                    "top_p": self.top_p_var.get(),
                    "timeout": self.timeout_var.get(),
                    "proxy": self.proxy_var.get().strip()
                }
                temp_adapter = create_llm_adapter(llm_config)
                available_models = temp_adapter.get_available_models()
                
                if not available_models:
                    available_models = ["无可用模型"]
                    self.safe_update_llm_status_textbox(f"ℹ️ 接口 '{interface_format}' 未返回可用模型，请检查配置。")
                
                # 在主线程中更新UI：更新 ComboBox 的 values
                self.master.after(0, lambda: self.model_name_combobox.configure(values=available_models))
                self.safe_update_llm_status_textbox(f"✅ 可用模型列表已更新。")

                # 检查当前模型名称是否在可用模型列表中
                # 如果当前模型名称不在列表中，或者当前是“正在获取可用模型...”，则尝试设置一个有效值
                if current_model_name not in available_models or current_model_name == "正在获取可用模型...":
                    if available_models and available_models[0] != "无可用模型":
                        self.master.after(0, lambda: self.model_name_var.set(available_models[0]))
                        self.safe_update_llm_status_textbox(f"ℹ️ 模型名称已自动设置为第一个可用模型: {available_models[0]}")
                    else:
                        self.master.after(0, lambda: self.model_name_var.set("无可用模型"))
                        self.safe_update_llm_status_textbox(f"ℹ️ 未找到可用模型，模型名称已设置为 '无可用模型'。")
                else:
                    # 如果当前模型名称在列表中，则保持不变
                    self.master.after(0, lambda: self.model_name_var.set(current_model_name))
                    self.safe_update_llm_status_textbox(f"ℹ️ 模型名称保持为: {current_model_name}")
                
            except Exception as e:
                self.safe_update_llm_status_textbox(f"❌ 获取模型列表失败: {e}")
                self.master.after(0, lambda: self.model_name_combobox.configure(values=["获取失败"]))
                # 如果获取失败，且当前模型名称是“正在获取可用模型...”，则设置为“获取失败”
                if current_model_name == "正在获取可用模型...":
                    self.master.after(0, lambda: self.model_name_var.set("获取失败"))
            finally:
                pass # ComboBox 不需要额外的启用/禁用操作

        threading.Thread(target=fetch_and_update_models_thread, daemon=True).start()


    def on_embedding_interface_change(self, *args, from_config_load=False):
        """
        当Embedding接口格式改变时，自动更新Embedding的Base URL。
        如果 from_config_load 为 True，则表示是从加载配置时调用，此时不应覆盖已加载的URL。
        否则（用户手动切换），则将URL更新为该接口的默认URL。
        """
        if self._is_loading_config:
            return
        interface_format = self.embedding_interface_format_var.get().strip()
        
        # 根据接口格式获取默认URL
        interface_urls = self.default_urls.get(interface_format, {"embedding": ""})
        default_url = interface_urls.get("embedding", "")

        # 新增：根据接口格式获取默认模型
        default_model = self.default_embedding_models.get(interface_format, "")

        if from_config_load:
            # 从配置加载时，URL已经被设置，我们只记录日志
            loaded_url = self.embedding_url_var.get().strip()
            self.safe_update_embedding_status_textbox(f"ℹ️ Embedding接口格式已加载为 '{interface_format}'，Base URL 为 '{loaded_url}'。")
        else:
            # 用户手动切换接口时，设置默认URL和模型
            self.embedding_url_var.set(default_url)
            self.embedding_model_name_var.set(default_model)
            self.safe_update_embedding_status_textbox(f"ℹ️ Embedding接口格式已切换为 '{interface_format}'，Base URL 和模型已更新。")

    def refresh_models_only(self):
        """
        只刷新模型列表，不修改任何配置参数（如URL）
        """
        interface_format = self.interface_format_var.get().strip()
        api_key = self.api_key_var.get().strip()
        base_url = self.base_url_var.get().strip()  # 使用当前URL，不修改
        current_model_name = self.model_name_var.get().strip()
        
        # 在开始获取模型前，将状态信息输出到日志窗口
        self.safe_update_llm_status_textbox(f"ℹ️ 正在获取 '{interface_format}' 接口的可用模型...")
        # 暂时清空 ComboBox 的 values，但保留当前 model_name_var 的值
        self.master.after(0, lambda: self.model_name_combobox.configure(values=[""]))

        def fetch_and_update_models_thread():
            try:
                llm_config = {
                    "interface_format": interface_format,
                    "api_key": api_key,
                    "base_url": base_url,
                    "model_name": current_model_name,
                    "max_tokens": self.max_tokens_var.get(),
                    "temperature": self.temperature_var.get(),
                    "top_p": self.top_p_var.get(),
                    "timeout": self.timeout_var.get(),
                    "proxy": self.proxy_var.get().strip()
                }
                temp_adapter = create_llm_adapter(llm_config)
                available_models = temp_adapter.get_available_models()

                if not available_models:
                    available_models = ["无可用模型"]
                    self.safe_update_llm_status_textbox(f"ℹ️ 接口 '{interface_format}' 未返回可用模型，请检查配置。")
                else:
                    # 过滤掉占位符后的真实模型数量
                    real_model_count = len([m for m in available_models if m])
                    self.safe_update_llm_status_textbox(f"✅ 成功获取到 {real_model_count} 个可用模型。")
                
                # 在主线程中更新UI：更新 ComboBox 的 values
                self.master.after(0, lambda: self.model_name_combobox.configure(values=available_models))
                
                # 检查当前模型名称是否在可用模型列表中
                if current_model_name not in available_models or current_model_name == "正在获取可用模型...":
                    if available_models and available_models[0] != "无可用模型":
                        self.master.after(0, lambda: self.model_name_var.set(available_models[0]))
                        self.safe_update_llm_status_textbox(f"ℹ️ 模型名称已自动设置为第一个可用模型: {available_models[0]}")
                    else:
                        self.master.after(0, lambda: self.model_name_var.set("无可用模型"))
                        self.safe_update_llm_status_textbox(f"ℹ️ 未找到可用模型，模型名称已设置为 '无可用模型'。")
                else:
                    # 如果当前模型名称在列表中，则保持不变
                    self.master.after(0, lambda: self.model_name_var.set(current_model_name))
                    self.safe_update_llm_status_textbox(f"ℹ️ 模型名称保持为: {current_model_name}")

            except Exception as e:
                self.safe_update_llm_status_textbox(f"❌ 获取模型列表失败: {e}")
                self.master.after(0, lambda: self.model_name_combobox.configure(values=["获取失败"]))
                # 如果获取失败，且当前模型名称是"正在获取可用模型..."，则设置为"获取失败"
                if current_model_name == "正在获取可用模型...":
                    self.master.after(0, lambda: self.model_name_var.set("获取失败"))
            finally:
                pass

        threading.Thread(target=fetch_and_update_models_thread, daemon=True).start()

    def save_named_config(self):
        """保存当前UI上的配置为一个命名配置"""
        config_name = self.config_name_var.get().strip()
        if not config_name:
            messagebox.showerror("错误", "配置名称不能为空。")
            return

        # 检查配置是否已存在
        if config_name in cm.get_config_names():
            if not messagebox.askyesno("确认", f"配置 '{config_name}' 已存在，要覆盖它吗？"):
                return

        llm_config = {
            "interface_format": self.interface_format_var.get(),
            "api_key": self.api_key_var.get(),
            "base_url": self.base_url_var.get(),
            "model_name": self.model_name_var.get(),
            "temperature": self.temperature_var.get(),
            "top_p": self.top_p_var.get(),
            "max_tokens": self.max_tokens_var.get(),
            "timeout": self.safe_get_int(self.timeout_var, 600),
            "proxy": self.proxy_var.get().strip()
        }
        embedding_config = {
            "interface_format": self.embedding_interface_format_var.get(),
            "api_key": self.embedding_api_key_var.get(),
            "base_url": self.embedding_url_var.get(),
            "model_name": self.embedding_model_name_var.get(),
            "retrieval_k": self.safe_get_int(self.embedding_retrieval_k_var, 4)
        }

        if cm.save_named_config(config_name, llm_config, embedding_config):
            self.log(f"配置 '{config_name}' 已保存。")
            messagebox.showinfo("成功", f"配置 '{config_name}' 已保存。")
            self.update_config_menu()
            self.update_main_config_menu() # 新增：同步更新主界面菜单
            self.config_selection_var.set(config_name) # 保存后自动选中
        else:
            messagebox.showerror("错误", "保存配置失败。")

    def add_to_polling_list(self):
        """将选中的LLM配置添加到轮询列表"""
        selected_config = self.available_llm_configs_var.get()
        if not selected_config or selected_config == "无可用配置":
            messagebox.showwarning("警告", "请选择一个要添加到轮询列表的配置。")
            return
        
        current_polling_configs = self.polling_configs_var.get().split(", ") if self.polling_configs_var.get() else []
        if selected_config not in current_polling_configs:
            current_polling_configs.append(selected_config)
            self.polling_configs_var.set(", ".join(current_polling_configs))
            self.safe_log(f"配置 '{selected_config}' 已添加到轮询列表。")
            self.save_polling_settings() # 自动保存

    def remove_selected_from_polling_list(self):
        """从轮询列表中移除选中的LLM配置 (通过下拉菜单选择)"""
        selected_config_to_remove = self.available_llm_configs_var.get() # 从统一的下拉菜单变量获取
        if not selected_config_to_remove or selected_config_to_remove == "无可用配置":
            messagebox.showwarning("警告", "请选择一个要从轮询列表中移除的配置。")
            return
        
        current_polling_configs = self.polling_configs_var.get().split(", ") if self.polling_configs_var.get() else []
        if selected_config_to_remove in current_polling_configs:
            current_polling_configs.remove(selected_config_to_remove)
            self.polling_configs_var.set(", ".join(current_polling_configs))
            self.safe_log(f"配置 '{selected_config_to_remove}' 已从轮询列表移除。")
            self.save_polling_settings() # 自动保存
            self.update_polling_config_ui() # 移除后更新下拉菜单
        else:
            messagebox.showwarning("警告", f"轮询列表中没有找到配置 '{selected_config_to_remove}'。")

    def save_polling_settings(self):
        """保存轮询配置、策略和错误处理设置到JSON文件"""
        self.safe_log("ℹ️ 正在尝试保存轮询设置...")
        polling_config_names = [name.strip() for name in self.polling_configs_var.get().split(", ") if name.strip()]
        self.safe_log(f"  - 从UI获取的轮询列表: {polling_config_names}")
        
        # 将中文策略转换回英文保存
        strategy_map = {"顺序轮询": "sequential", "随机轮询": "random"}
        selected_strategy_chinese = self.polling_strategy_var.get()
        strategy = strategy_map.get(selected_strategy_chinese, "sequential")

        # 获取错误处理设置
        enable_retry = self.enable_retry_var.get()
        retry_count = self.safe_get_int(self.retry_count_var, 3)
        enable_logging = self.enable_logging_var.get()
        error_429_pause_minutes = 5  # 默认值，后续可以从UI获取

        # 1. 准备要保存的数据结构 (使用中文键名)
        #    轮询列表现在只保存名称
        polling_list_details = [{"name": name} for name in polling_config_names]

        data_to_save = {
            "轮询列表": polling_list_details,
            "设置": {
                "轮询策略": strategy,
                "启用重试": enable_retry,
                "重试次数": retry_count,
                "启用日志": enable_logging,
                "429错误暂停分钟": error_429_pause_minutes
            },
            "调用状态": {
                "上次调用AI索引": -1,
                "AI状态": {}
            }
        }

        # 3. 读取现有文件以保留 调用状态 和 步骤配置
        polling_settings_dir = os.path.join("ui", "轮询设定")
        os.makedirs(polling_settings_dir, exist_ok=True) # 确保目录存在
        polling_settings_file = os.path.join(polling_settings_dir, "轮询设定.json")
        try:
            if os.path.exists(polling_settings_file):
                with open(polling_settings_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    if "调用状态" in existing_data:
                        data_to_save["调用状态"] = existing_data["调用状态"]
                    # 保留现有的步骤配置
                    if "步骤" in existing_data:
                        data_to_save["步骤"] = existing_data["步骤"]
            else:
                # 如果文件不存在，初始化默认的步骤配置
                data_to_save["步骤"] = {
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

            # 更新步骤配置
            if hasattr(self, 'step_config_vars') and isinstance(self.step_config_vars, dict):
                if "步骤" not in data_to_save:
                    data_to_save["步骤"] = {}
                for step_name, config_var in self.step_config_vars.items():
                    selected_config = config_var.get()
                    if step_name not in data_to_save["步骤"]:
                        data_to_save["步骤"][step_name] = {"策略": "轮询", "指定配置": None}
                    data_to_save["步骤"][step_name]["指定配置"] = selected_config if selected_config != "无" else None
            
            # 4. 根据新的 轮询列表 更新 AI状态
            current_ai_names = {ai["name"] for ai in polling_list_details}
            existing_ai_states = data_to_save["调用状态"].get("AI状态", {})
            
            new_ai_states = {name: state for name, state in existing_ai_states.items() if name in current_ai_names}
            
            for name in current_ai_names:
                if name not in new_ai_states:
                    new_ai_states[name] = {
                        "状态": "available",
                        "最后错误": None,
                        "暂停至": None
                    }
            
            data_to_save["调用状态"]["AI状态"] = new_ai_states

            # 5. 写入文件
            self.safe_log(f"  - 准备写入文件: {polling_settings_file}")
            self.safe_log(f"  - 写入内容: {json.dumps(data_to_save, indent=2, ensure_ascii=False)}")
            with open(polling_settings_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            
            self.safe_log("✅ 轮询设置已成功写入 ui/轮询设定/轮询设定.json。")
            # messagebox.showinfo("成功", "轮询设置已保存。")

        except Exception as e:
            self.handle_exception(f"保存轮询设置失败: {e}")
            messagebox.showerror("错误", f"保存轮询设置失败: {e}")

    def update_polling_config_ui(self):
        """更新轮询配置UI，加载已保存的轮询配置和策略"""
        # 加载所有已保存的LLM配置名称到“添加到轮询”下拉菜单
        all_llm_configs = cm.get_config_names()
        if all_llm_configs:
            # 确保下拉菜单的当前值是有效的，如果当前值不在列表中，则设置为第一个
            current_selection = self.available_llm_configs_var.get()
            if current_selection not in all_llm_configs:
                self.available_llm_configs_var.set(all_llm_configs[0])
            
            if hasattr(self, 'polling_config_selection_menu'): # 确保UI元素已创建
                self.polling_config_selection_menu.configure(values=all_llm_configs)
        else:
            self.available_llm_configs_var.set("无可用配置")
            if hasattr(self, 'polling_config_selection_menu'):
                self.polling_config_selection_menu.configure(values=["无可用配置"])

        # 加载已保存的轮询列表到显示框
        saved_polling_configs = cm.get_polling_configs()
        polling_configs_text = ", ".join(saved_polling_configs)
        
        if hasattr(self, 'polling_configs_textbox'):
            self.polling_configs_textbox.configure(state="normal")
            self.polling_configs_textbox.delete("0.0", "end")
            self.polling_configs_textbox.insert("0.0", polling_configs_text)
            self.polling_configs_textbox.configure(state="disabled")

            # --- 更精确地根据内容调整高度 ---
            # 延迟执行以确保UI更新完成，获取到正确的宽度
            def adjust_height():
                try:
                    # 获取字体
                    font_obj = ctk.CTkFont(family="Microsoft YaHei", size=14)
                    
                    # 获取文本框的宽度 (减去内边距)
                    # CTkTextbox 默认有左右各10像素的内边距
                    textbox_width = self.polling_configs_textbox.winfo_width() - 20
                    if textbox_width <= 0: # 如果窗口还没完全渲染，给一个默认值
                        textbox_width = 300 

                    total_lines = 0
                    # 按换行符分割文本
                    lines = polling_configs_text.split('\n')
                    
                    for line in lines:
                        if not line.strip():
                            total_lines += 1
                            continue
                        
                        # 计算当前行需要的行数
                        line_width = font_obj.measure(line)
                        lines_needed = (line_width + textbox_width - 1) // textbox_width # 向上取整
                        total_lines += max(1, lines_needed) # 至少占一行

                    # 限制行数在2到6行之间
                    target_height_lines = max(2, min(6, total_lines))
                    
                    # CTkTextbox 的 height 参数是像素
                    # 字体大小 + 行间距 估算为 28 像素每行
                    line_height = 28 
                    self.polling_configs_textbox.configure(height=target_height_lines * line_height)
                except Exception as e:
                    # 如果出现异常（例如窗口关闭时），则忽略
                    pass

            # 使用 after 延迟执行，确保 winfo_width 能获取到正确的值
            self.master.after(100, adjust_height)

        # 确保下拉菜单的当前值是有效的，如果轮询列表为空，则设置为“无可用配置”
        if not saved_polling_configs and self.available_llm_configs_var.get() != "无可用配置":
            self.available_llm_configs_var.set("无可用配置")
        elif saved_polling_configs and self.available_llm_configs_var.get() == "无可用配置":
            # 如果轮询列表不为空，但下拉菜单显示“无可用配置”，则更新为第一个可用配置
            if all_llm_configs:
                self.available_llm_configs_var.set(all_llm_configs[0])

        # 加载已保存的轮询策略 (英文转换为中文显示)
        saved_strategy_english = cm.get_polling_strategy()
        strategy_map_reverse = {"sequential": "顺序轮询", "random": "随机轮询"}
        self.polling_strategy_var.set(strategy_map_reverse.get(saved_strategy_english, "顺序轮询"))

        # 加载错误处理设置
        self.enable_retry_var.set(cm.get_error_handling_setting("enable_retry", True))
        self.retry_count_var.set(str(cm.get_error_handling_setting("retry_count", 3)))
        self.enable_logging_var.set(cm.get_error_handling_setting("enable_logging", True))

        # 根据 enable_retry_var 的值设置 retry_count_entry 的状态
        # 需要确保 retry_count_entry 已经创建，这在 build_llm_settings_tab 中完成
        # 因此，这里需要一个延迟调用或者确保UI元素已存在
        if hasattr(self, 'retry_count_entry'):
            self.toggle_retry_count_entry()

    def load_named_config(self, name):
        """根据名称加载配置到UI"""
        if name == "无可用配置":
            return
        config_data = cm.get_config(name)
        if config_data:
            load_llm_embedding_config_logic(self, config_data)
            self.config_name_var.set(name) # 加载后，将名称填入输入框
            
            # 同步更新主界面的配置选择
            if hasattr(self, 'main_config_selection_var'):
                self.main_config_selection_var.set(name)
            
            # 更新主界面的模型名称
            llm_conf = config_data.get("llm_config", {})
            if hasattr(self, 'main_model_name_var'):
                self.main_model_name_var.set(llm_conf.get("model_name", ""))
            
            self.log(f"已加载配置: {name}")
        else:
            messagebox.showwarning("警告", f"找不到名为 '{name}' 的配置。")

    def delete_named_config(self):
        """删除选中的配置"""
        name = self.config_selection_var.get()
        if not name or name == "无可用配置":
            messagebox.showwarning("警告", "请先选择一个要删除的配置。")
            return

        if messagebox.askyesno("确认删除", f"确定要删除配置 '{name}' 吗？"):
            if cm.delete_config(name):
                self.log(f"配置 '{name}' 已被删除。")
                messagebox.showinfo("成功", f"配置 '{name}' 已被删除。")
                self.update_config_menu()
                self.update_main_config_menu() # 新增：同步更新主界面菜单
                # 如果删除后没有配置了，可以清空UI
                if not cm.get_config_names():
                    self.clear_ui_configs()
            else:
                messagebox.showerror("错误", f"删除配置 '{name}' 失败。")

    def set_default_named_config(self):
        """将选中的配置设为默认"""
        name = self.config_selection_var.get()
        if not name or name == "无可用配置":
            messagebox.showwarning("警告", "请先选择一个要设为默认的配置。")
            return

        if cm.set_default_config_name(name):
            self.log(f"配置 '{name}' 已被设为默认。")
            messagebox.showinfo("成功", f"配置 '{name}' 已被设为默认。")
        else:
            messagebox.showerror("错误", "设置默认配置失败。")

    def load_default_config_on_startup(self):
        """在程序启动时加载默认配置"""
        default_name = cm.get_default_config_name()
        if default_name:
            self.load_named_config(default_name)
            self.config_selection_var.set(default_name)

    def clear_ui_configs(self):
        """清空UI上的配置信息"""
        self.config_name_var.set("")
        self.interface_format_var.set("OpenAI")
        self.api_key_var.set("")
        self.base_url_var.set("")
        self.model_name_var.set("")
        self.temperature_var.set(0.7)
        self.top_p_var.set(0.9)
        self.max_tokens_var.set(8192)
        self.timeout_var.set(600)
        self.proxy_var.set("")
        self.embedding_interface_format_var.set("OpenAI")
        self.embedding_api_key_var.set("")
        self.embedding_url_var.set("https://api.openai.com/v1")
        self.embedding_model_name_var.set("text-embedding-ada-002")
        self.embedding_retrieval_k_var.set("4")
        self.log("UI配置已清空。")

    def test_llm_config(self, status_textbox):
        """
        测试当前的LLM配置是否可用
        """
        llm_config = {
            "interface_format": self.interface_format_var.get().strip(),
            "api_key": self.api_key_var.get().strip(),
            "base_url": self.base_url_var.get().strip(),
            "model_name": self.model_name_var.get().strip(),
            "temperature": self.temperature_var.get(),
            "top_p": self.top_p_var.get(),
            "max_tokens": self.max_tokens_var.get(),
            "timeout": self.timeout_var.get(),
            "proxy": self.proxy_var.get().strip()
        }

        # Clear the status textbox before starting the test
        status_textbox.delete("1.0", "end")

        cm.test_llm_config(
            llm_config=llm_config,
            log_func=lambda msg: self.safe_update_textbox(status_textbox, msg),
            handle_exception_func=lambda ctx: self.safe_update_textbox(status_textbox, f"{ctx}\n{traceback.format_exc()}")
        )

    def test_embedding_config(self, status_textbox):
        """
        测试当前的Embedding配置是否可用
        """
        api_key = self.embedding_api_key_var.get().strip()
        base_url = self.embedding_url_var.get().strip()
        interface_format = self.embedding_interface_format_var.get().strip()
        model_name = self.embedding_model_name_var.get().strip()

        # Clear the status textbox before starting the test
        status_textbox.delete("1.0", "end")

        cm.test_embedding_config(
            api_key=api_key,
            base_url=base_url,
            interface_format=interface_format,
            model_name=model_name,
            log_func=lambda msg: self.safe_update_textbox(status_textbox, msg),
            handle_exception_func=lambda ctx: self.safe_update_textbox(status_textbox, f"{ctx}\n{traceback.format_exc()}")
        )
    
    def safe_update_textbox(self, textbox, message):
        """Thread-safe method to update a CTkTextbox."""
        def update():
            textbox.configure(state="normal")
            textbox.insert("end", message + "\n")
            textbox.see("end")
            textbox.configure(state="disabled")
        self.master.after(0, update)

    def safe_update_llm_status_textbox(self, message: str, stream: bool = False):
        """线程安全地更新LLM设置页面的状态文本框。"""
        if hasattr(self, 'llm_status_textbox') and self.llm_status_textbox.winfo_exists():
            self.safe_update_textbox(self.llm_status_textbox, message)
        else:
            self.safe_log(message, stream) # Fallback to main log if textbox not available

    def safe_update_embedding_status_textbox(self, message: str, stream: bool = False):
        """线程安全地更新Embedding设置页面的状态文本框。"""
        if hasattr(self, 'embedding_status_textbox') and self.embedding_status_textbox.winfo_exists():
            self.safe_update_textbox(self.embedding_status_textbox, message)
        else:
            self.safe_log(message, stream) # Fallback to main log if textbox not available
    
    def save_project_basic_info(self, *args):
        """自动静默保存基本信息到当前项目的 基本信息.json"""
        if hasattr(self, '_is_loading_project_info') and self._is_loading_project_info:
            return # 正在加载配置时，不执行保存操作

        project_path = self.filepath_var.get()
        if not project_path:
            return # 如果没有项目路径，则不保存

        try:
            # 从UI控件收集最新的数据
            project_config = {
                'topic': self.topic_var.get(),
                'genre': self.genre_var.get(),
                'num_chapters': self.num_chapters_var.get(),
                'word_number': self.word_number_var.get(),
                'chapter_num': self.chapter_num_var.get(),
                'characters_involved': self.characters_involved_var.get(),
                'key_items': self.key_items_var.get(),
                'scene_location': self.scene_location_var.get(),
                'time_constraint': self.time_constraint_var.get(),
                'user_guidance': self.user_guidance_var.get(),
                'volume_count': self.volume_count_var.get()
            }
            
            cm.save_project_config(project_path, project_config)
            # 静默保存，不打扰用户
            # self.safe_log(f"✅ 项目 {os.path.basename(project_path)} 的基本信息已自动保存。")
        except Exception as e:
            self.safe_log(f"❌ 自动保存项目基本信息失败: {e}")

    def load_project_basic_info(self, project_path):
        """从指定项目的 基本信息.json 加载基本信息并更新UI"""
        if hasattr(self, '_is_loading_project_info') and self._is_loading_project_info:
            return # 避免重入

        self._is_loading_project_info = True
        try:
            if not project_path:
                return

            op = cm.load_project_config(project_path)
            
            if op: # 如果成功加载到项目配置
                self.safe_log(f"✅ 已加载项目 '{os.path.basename(project_path)}' 的配置。")
            else: # 如果没有项目配置文件，则使用全局配置或默认值
                self.safe_log(f"ℹ️ 项目 '{os.path.basename(project_path)}' 无独立配置，使用全局设置。")
                global_config = cm.load_config()
                op = global_config.get("other_params", {})

            # --- 更新UI ---
            # 使用 .get() 并提供默认值，以增强健壮性
            self.topic_var.set(op.get("topic", ""))
            self.topic_text.delete("0.0", "end")
            self.topic_text.insert("0.0", self.topic_var.get())

            self.genre_var.set(op.get("genre", "玄幻"))
            self.num_chapters_var.set(str(op.get("num_chapters", 10)))
            self.word_number_var.set(str(op.get("word_number", 3000)))
            self.chapter_num_var.set(str(op.get("chapter_num", "1")))
            
            self.characters_involved_var.set(op.get("characters_involved", ""))
            self.char_inv_text.delete("0.0", "end")
            self.char_inv_text.insert("0.0", self.characters_involved_var.get())

            self.key_items_var.set(op.get("key_items", ""))
            self.key_items_text.delete("0.0", "end")
            self.key_items_text.insert("0.0", self.key_items_var.get())

            self.scene_location_var.set(op.get("scene_location", ""))
            self.scene_location_text.delete("0.0", "end")
            self.scene_location_text.insert("0.0", self.scene_location_var.get())

            self.time_constraint_var.set(op.get("time_constraint", ""))
            self.time_constraint_text.delete("0.0", "end")
            self.time_constraint_text.insert("0.0", self.time_constraint_var.get())

            self.user_guidance_var.set(op.get("user_guidance", ""))
            self.user_guide_text.delete("0.0", "end")
            self.user_guide_text.insert("0.0", self.user_guidance_var.get())

            self.volume_count_var.set(str(op.get("volume_count", 3)))
        finally:
            self._is_loading_project_info = False

    def save_basic_info(self):
        """手动保存当前基本信息到项目配置文件"""
        self.save_project_basic_info() # 直接调用自动保存函数
        self.safe_log("✅ 基本信息已手动保存。")
        messagebox.showinfo("保存成功", "基本信息已成功保存到当前项目的配置文件中。")

    def load_basic_info(self):
        """手动从当前项目配置文件加载基本信息"""
        project_path = self.filepath_var.get()
        self.load_project_basic_info(project_path)
        messagebox.showinfo("加载成功", "已从当前项目加载基本信息。")

    def open_polling_config_selection_dialog(self):
        """
        打开一个弹窗，让用户选择要导入到轮询列表的LLM配置。
        """
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("选择轮询配置")
        dialog.geometry("400x500")
        dialog.transient(self.master)
        dialog.grab_set()

        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text="选择要导入的LLM配置:", font=("Microsoft YaHei", 14, "bold")).pack(pady=10)

        scrollable_frame = ctk.CTkScrollableFrame(frame)
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)

        all_llm_configs = cm.get_config_names()
        if not all_llm_configs:
            ctk.CTkLabel(scrollable_frame, text="无可用LLM配置，请先创建。", font=("Microsoft YaHei", 12)).pack(pady=10)
            return

        checkboxes = []
        selected_initial = self.polling_configs_var.get().split(", ") if self.polling_configs_var.get() else []

        for config_name in all_llm_configs:
            var = ctk.BooleanVar(value=(config_name in selected_initial))
            chk = ctk.CTkCheckBox(scrollable_frame, text=config_name, variable=var, font=("Microsoft YaHei", 12))
            chk.pack(anchor="w", pady=2, padx=5)
            checkboxes.append((config_name, var))

        def confirm_selection():
            selected_configs = [name for name, var in checkboxes if var.get()]
            self.polling_configs_var.set(", ".join(selected_configs))
            self.save_polling_settings() # 保存到config.json
            self.update_polling_config_ui() # 更新主界面的轮询列表显示
            dialog.destroy()

        def cancel_selection():
            dialog.destroy()

        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=10)
        ctk.CTkButton(button_frame, text="确定", command=confirm_selection, font=("Microsoft YaHei", 14)).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(button_frame, text="取消", command=cancel_selection, font=("Microsoft YaHei", 14)).pack(side="right", expand=True, padx=5)

    def toggle_retry_count_entry(self):
        """根据是否重试复选框的状态，启用或禁用重试次数输入框。"""
        if self.enable_retry_var.get():
            self.retry_count_entry.configure(state="normal")
        else:
            self.retry_count_entry.configure(state="disabled")

    def show_polling_log_viewer(self):
        """显示一个功能丰富的轮询日志查看器窗口，包含运行和错误日志的标签页"""
        log_popup = ctk.CTkToplevel(self.master)
        log_popup.title("轮询日志查看器")
        log_popup.geometry("1300x800")
        log_popup.transient(self.master)
        log_popup.grab_set()

        main_frame = ctk.CTkFrame(log_popup)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # --- 顶部控制栏 ---
        control_frame = ctk.CTkFrame(main_frame)
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        # --- 日志文件路径 ---
        log_dir = os.path.join("ui", "轮询设定")
        run_log_path = os.path.join(log_dir, "polling_run.log")
        error_log_path = os.path.join(log_dir, "polling_error.log")

        # --- Tabbed Interface ---
        tab_view = ctk.CTkTabview(main_frame)
        tab_view.grid(row=1, column=0, sticky="nsew")
        
        run_log_tab = tab_view.add("运行日志")
        error_log_tab = tab_view.add("错误日志")

        # --- 运行日志 Tab ---
        run_log_tab.grid_columnconfigure(0, weight=1)
        run_log_tab.grid_rowconfigure(0, weight=1) # 上半部分: 表格
        run_log_tab.grid_rowconfigure(1, weight=1) # 下半部分: 详细信息

        # 上半部分: 表格
        run_tree_frame = ctk.CTkFrame(run_log_tab)
        run_tree_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        
        # 下半部分: 详细信息 (Prompt & Response)
        run_details_frame = ctk.CTkFrame(run_log_tab)
        run_details_frame.grid(row=1, column=0, sticky="nsew")
        run_details_frame.grid_columnconfigure(0, weight=1)
        run_details_frame.grid_rowconfigure(1, weight=1)

        # --- 运行日志表格 ---
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0, rowheight=25)
        style.map('Treeview', background=[('selected', '#1f6aa5')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat", font=('Microsoft YaHei', 10, 'bold'))
        style.map("Treeview.Heading", background=[('active', '#3c3f41')])

        run_columns = ("timestamp", "step", "config", "model", "input_tokens", "output_tokens", "duration")
        run_tree = ttk.Treeview(run_tree_frame, columns=run_columns, show="headings")
        
        run_tree.heading("timestamp", text="时间")
        run_tree.heading("step", text="步骤")
        run_tree.heading("config", text="配置")
        run_tree.heading("model", text="模型")
        run_tree.heading("input_tokens", text="输入Tokens")
        run_tree.heading("output_tokens", text="输出Tokens")
        run_tree.heading("duration", text="耗时(s)")

        run_tree.column("timestamp", width=150, anchor="w")
        run_tree.column("step", width=180, anchor="w")
        run_tree.column("config", width=120, anchor="w")
        run_tree.column("model", width=150, anchor="w")
        run_tree.column("input_tokens", width=100, anchor="e")
        run_tree.column("output_tokens", width=100, anchor="e")
        run_tree.column("duration", width=80, anchor="e")

        run_vsb = ttk.Scrollbar(run_tree_frame, orient="vertical", command=run_tree.yview)
        run_hsb = ttk.Scrollbar(run_tree_frame, orient="horizontal", command=run_tree.xview)
        run_tree.configure(yscrollcommand=run_vsb.set, xscrollcommand=run_hsb.set)
        run_tree_frame.grid_columnconfigure(0, weight=1)
        run_tree_frame.grid_rowconfigure(0, weight=1)
        run_tree.grid(row=0, column=0, sticky="nsew")
        run_vsb.grid(row=0, column=1, sticky="ns")
        run_hsb.grid(row=1, column=0, sticky="ew")

        # --- 运行日志详细信息文本框 ---
        run_details_tab_view = ctk.CTkTabview(run_details_frame)
        run_details_tab_view.pack(fill="both", expand=True)
        run_prompt_tab = run_details_tab_view.add("Prompt")
        run_response_tab = run_details_tab_view.add("Response")

        # 为 run_prompt_tab 添加字数统计
        run_prompt_tab.grid_columnconfigure(0, weight=1)
        run_prompt_tab.grid_rowconfigure(1, weight=1)
        run_prompt_wc_label = ctk.CTkLabel(run_prompt_tab, text="字数: 0", font=("Microsoft YaHei", 10))
        run_prompt_wc_label.grid(row=0, column=0, sticky="e", padx=5)
        run_prompt_text = ctk.CTkTextbox(run_prompt_tab, wrap="word", font=("Microsoft YaHei", 12))
        run_prompt_text.grid(row=1, column=0, sticky="nsew")

        # 为 run_response_tab 添加字数统计
        run_response_tab.grid_columnconfigure(0, weight=1)
        run_response_tab.grid_rowconfigure(1, weight=1)
        run_response_wc_label = ctk.CTkLabel(run_response_tab, text="字数: 0", font=("Microsoft YaHei", 10))
        run_response_wc_label.grid(row=0, column=0, sticky="e", padx=5)
        run_response_text = ctk.CTkTextbox(run_response_tab, wrap="word", font=("Microsoft YaHei", 12))
        run_response_text.grid(row=1, column=0, sticky="nsew")

        # --- 错误日志 Tab ---
        error_log_tab.grid_columnconfigure(0, weight=1)
        error_log_tab.grid_rowconfigure(0, weight=1) # 上半部分: 表格
        error_log_tab.grid_rowconfigure(1, weight=1) # 下半部分: 详细信息

        error_tree_frame = ctk.CTkFrame(error_log_tab)
        error_tree_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        
        error_details_frame = ctk.CTkFrame(error_log_tab)
        error_details_frame.grid(row=1, column=0, sticky="nsew")
        error_details_frame.grid_columnconfigure(0, weight=1)
        error_details_frame.grid_rowconfigure(1, weight=1)

        error_columns = ("timestamp", "step", "config", "model", "error")
        error_tree = ttk.Treeview(error_tree_frame, columns=error_columns, show="headings")
        
        error_tree.heading("timestamp", text="时间")
        error_tree.heading("step", text="步骤")
        error_tree.heading("config", text="配置")
        error_tree.heading("model", text="模型")
        error_tree.heading("error", text="错误信息")

        error_tree.column("timestamp", width=150, anchor="w")
        error_tree.column("step", width=180, anchor="w")
        error_tree.column("config", width=120, anchor="w")
        error_tree.column("model", width=150, anchor="w")
        error_tree.column("error", width=500, anchor="w")

        error_vsb = ttk.Scrollbar(error_tree_frame, orient="vertical", command=error_tree.yview)
        error_hsb = ttk.Scrollbar(error_tree_frame, orient="horizontal", command=error_tree.xview)
        error_tree.configure(yscrollcommand=error_vsb.set, xscrollcommand=error_hsb.set)
        error_tree_frame.grid_columnconfigure(0, weight=1)
        error_tree_frame.grid_rowconfigure(0, weight=1)
        error_tree.grid(row=0, column=0, sticky="nsew")
        error_vsb.grid(row=0, column=1, sticky="ns")
        error_hsb.grid(row=1, column=0, sticky="ew")

        # --- 错误日志详细信息文本框 ---
        error_details_tab_view = ctk.CTkTabview(error_details_frame)
        error_details_tab_view.pack(fill="both", expand=True)
        error_prompt_tab = error_details_tab_view.add("Prompt")
        error_traceback_tab = error_details_tab_view.add("Traceback")

        # 为 error_prompt_tab 添加字数统计
        error_prompt_tab.grid_columnconfigure(0, weight=1)
        error_prompt_tab.grid_rowconfigure(1, weight=1)
        error_prompt_wc_label = ctk.CTkLabel(error_prompt_tab, text="字数: 0", font=("Microsoft YaHei", 10))
        error_prompt_wc_label.grid(row=0, column=0, sticky="e", padx=5)
        error_prompt_text = ctk.CTkTextbox(error_prompt_tab, wrap="word", font=("Microsoft YaHei", 12))
        error_prompt_text.grid(row=1, column=0, sticky="nsew")

        # 为 error_traceback_tab 添加字数统计
        error_traceback_tab.grid_columnconfigure(0, weight=1)
        error_traceback_tab.grid_rowconfigure(1, weight=1)
        error_traceback_wc_label = ctk.CTkLabel(error_traceback_tab, text="字数: 0", font=("Microsoft YaHei", 10))
        error_traceback_wc_label.grid(row=0, column=0, sticky="e", padx=5)
        error_traceback_text = ctk.CTkTextbox(error_traceback_tab, wrap="word", font=("Microsoft YaHei", 12))
        error_traceback_text.grid(row=1, column=0, sticky="nsew")

        # --- 数据加载和处理 ---
        run_log_data_store = {}
        error_log_data_store = {}

        def update_word_count(textbox, label):
            content = textbox.get("1.0", "end-1c")
            label.configure(text=f"字数: {len(content)}")

        def on_run_log_select(event):
            selected_items = run_tree.selection()
            if not selected_items: return
            item_id = selected_items[0]
            log_entry = run_log_data_store.get(item_id)
            if log_entry:
                prompt_content = log_entry.get("prompt", "N/A")
                response_content = log_entry.get("response", "N/A")

                run_prompt_text.configure(state="normal")
                run_prompt_text.delete("1.0", "end")
                run_prompt_text.insert("1.0", prompt_content)
                run_prompt_text.configure(state="disabled")
                update_word_count(run_prompt_text, run_prompt_wc_label)

                run_response_text.configure(state="normal")
                run_response_text.delete("1.0", "end")
                run_response_text.insert("1.0", response_content)
                run_response_text.configure(state="disabled")
                update_word_count(run_response_text, run_response_wc_label)

        def on_error_log_select(event):
            selected_items = error_tree.selection()
            if not selected_items: return
            item_id = selected_items[0]
            log_entry = error_log_data_store.get(item_id)
            if log_entry:
                prompt_content = log_entry.get("prompt", "此错误日志没有记录Prompt。")
                traceback_content = log_entry.get("traceback", "N/A")

                error_prompt_text.configure(state="normal")
                error_prompt_text.delete("1.0", "end")
                error_prompt_text.insert("1.0", prompt_content)
                error_prompt_text.configure(state="disabled")
                update_word_count(error_prompt_text, error_prompt_wc_label)

                error_traceback_text.configure(state="normal")
                error_traceback_text.delete("1.0", "end")
                error_traceback_text.insert("1.0", traceback_content)
                error_traceback_text.configure(state="disabled")
                update_word_count(error_traceback_text, error_traceback_wc_label)

        run_tree.bind("<<TreeviewSelect>>", on_run_log_select)
        error_tree.bind("<<TreeviewSelect>>", on_error_log_select)

        def load_logs():
            # 清空现有数据
            for item in run_tree.get_children(): run_tree.delete(item)
            for item in error_tree.get_children(): error_tree.delete(item)
            run_log_data_store.clear()
            error_log_data_store.clear()
            
            for widget in [run_prompt_text, run_response_text, error_prompt_text, error_traceback_text]:
                widget.configure(state="normal"); widget.delete("1.0", "end"); widget.configure(state="disabled")

            # 加载运行日志
            if os.path.exists(run_log_path):
                with open(run_log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines):
                    try:
                        log = json.loads(line)
                        item_id = run_tree.insert("", "end", values=(
                            log.get('timestamp', 'N/A'),
                            log.get('step', log.get('step_name', 'N/A')),
                            log.get('config', log.get('config_name', 'N/A')),
                            log.get('model', log.get('model_name', 'N/A')),
                            log.get('input_tokens', 'N/A'),
                            log.get('output_tokens', 'N/A'),
                            f"{log.get('duration_seconds', 0):.2f}"
                        ))
                        run_log_data_store[item_id] = log
                    except (json.JSONDecodeError, KeyError): pass

            # 加载错误日志
            if os.path.exists(error_log_path):
                with open(error_log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines):
                    try:
                        log = json.loads(line)
                        error_message = str(log.get('error', log.get('error_message', '')))
                        # 增加健壮性检查，防止空错误信息导致崩溃
                        display_error = error_message.splitlines()[0] if error_message.strip() else ""
                        item_id = error_tree.insert("", "end", values=(
                            log.get('timestamp', 'N/A'),
                            log.get('step', log.get('step_name', 'N/A')),
                            log.get('config', log.get('config_name', 'N/A')),
                            log.get('model', log.get('model_name', 'N/A')),
                            display_error
                        ))
                        error_log_data_store[item_id] = log
                    except (json.JSONDecodeError, KeyError): pass

        def clear_logs_by_date():
            if DateEntry is None:
                messagebox.showerror("错误", "缺少 'tkcalendar' 模块。\n请运行: pip install tkcalendar")
                return
            
            date_dialog = ctk.CTkToplevel(log_popup)
            date_dialog.title("选择日期")
            date_dialog.geometry("300x150")
            date_dialog.transient(log_popup)
            date_dialog.grab_set()

            ctk.CTkLabel(date_dialog, text="删除此日期之前的所有日志:").pack(pady=10)
            
            cal = DateEntry(date_dialog, width=12, background='darkblue', foreground='white', borderwidth=2, date_pattern='y-mm-dd')
            cal.pack(pady=10)

            def confirm_delete():
                selected_date_str = cal.get()
                try:
                    selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
                    if messagebox.askyesno("确认", f"确定要删除 {selected_date} 之前的所有日志吗？"):
                        for log_file in [run_log_path, error_log_path]:
                            if not os.path.exists(log_file): continue
                            with open(log_file, "r", encoding="utf-8") as f:
                                lines = f.readlines()
                            
                            lines_to_keep = []
                            for line in lines:
                                try:
                                    log_date = datetime.strptime(json.loads(line)['timestamp'], "%Y-%m-%d %H:%M:%S").date()
                                    if log_date >= selected_date:
                                        lines_to_keep.append(line)
                                except (json.JSONDecodeError, KeyError, ValueError):
                                    lines_to_keep.append(line) # 保留无法解析的行
                            
                            with open(log_file, "w", encoding="utf-8") as f:
                                f.writelines(lines_to_keep)
                        
                        messagebox.showinfo("成功", "指定日期前的日志已删除。")
                        load_logs()
                except ValueError:
                    messagebox.showerror("错误", "日期格式无效。")
                finally:
                    date_dialog.destroy()

            ctk.CTkButton(date_dialog, text="确定", command=confirm_delete).pack(pady=10)

        def clear_all_logs():
            if messagebox.askyesno("确认", "确定要清空所有运行和错误日志吗？此操作不可恢复。"):
                try:
                    if os.path.exists(run_log_path): open(run_log_path, 'w').close()
                    if os.path.exists(error_log_path): open(error_log_path, 'w').close()
                    messagebox.showinfo("成功", "所有日志已清空。")
                    load_logs()
                except Exception as e:
                    messagebox.showerror("错误", f"清空日志失败: {e}")

        # --- 填充控制按钮 ---
        refresh_btn = ctk.CTkButton(control_frame, text="刷新", command=load_logs)
        refresh_btn.pack(side="left", padx=5, pady=5)
        
        delete_by_date_btn = ctk.CTkButton(control_frame, text="按时间删除", command=clear_logs_by_date)
        delete_by_date_btn.pack(side="left", padx=5, pady=5)

        clear_all_btn = ctk.CTkButton(control_frame, text="全部删除", command=clear_all_logs, fg_color="red")
        clear_all_btn.pack(side="left", padx=5, pady=5)

        # 初始加载
        load_logs()

    # =================== 主界面LLM配置功能方法 ===================
    
    def get_effective_llm_config(self):
        """
        获取有效的LLM配置参数，根据当前选择的模式（轮询或单一配置）
        返回: (interface_format, api_key, base_url, model_name, temperature, top_p, max_tokens, timeout, proxy, enable_polling, polling_configs, polling_strategy)
        """
        enable_polling = self.enable_polling_var.get()
        enable_llm_config = self.enable_llm_config_var.get()
        
        # 确保二选一逻辑
        if enable_polling and enable_llm_config:
            # 如果两个都被启用（异常情况），优先使用轮询
            enable_llm_config = False
            self.enable_llm_config_var.set(False)
        elif not enable_polling and not enable_llm_config:
            # 如果两个都没有启用，默认使用当前主界面设置（不启用轮询）
            enable_polling = False
            enable_llm_config = True
            
        if enable_polling:
            # 使用轮询模式，返回当前主界面设置但启用轮询
            return (
                self.interface_format_var.get(),
                self.api_key_var.get(),
                self.base_url_var.get(),
                self.model_name_var.get(),
                self.temperature_var.get(),
                self.top_p_var.get(),
                self.max_tokens_var.get(),
                self.timeout_var.get(),
                self.proxy_var.get().strip(),
                True,  # enable_polling
                cm.get_polling_configs(),
                self.polling_strategy_var.get()
            )
        else:
            # 使用单一配置模式
            # 如果选择了配置，使用主界面的模型名称覆盖原设置
            model_name = self.model_name_var.get()
            if hasattr(self, 'main_model_name_var') and self.main_model_name_var.get().strip():
                model_name = self.main_model_name_var.get().strip()
                
            return (
                self.interface_format_var.get(),
                self.api_key_var.get(),
                self.base_url_var.get(),
                model_name,
                self.temperature_var.get(),
                self.top_p_var.get(),
                self.max_tokens_var.get(),
                self.timeout_var.get(),
                self.proxy_var.get().strip(),
                False,  # enable_polling
                [],     # polling_configs
                "sequential"  # polling_strategy (default)
            )
    
    def save_llm_selection_mode(self):
        """保存LLM选择模式（轮询或指定配置）到配置文件"""
        config = cm.load_config()
        if self.enable_polling_var.get():
            config["llm_selection_mode"] = "polling"
        else:
            config["llm_selection_mode"] = "llm_config"
        cm.save_config(config)
        self.safe_log(f"ℹ️ LLM选择模式已保存为: {config['llm_selection_mode']}")

    def on_polling_mode_change(self):
        """当启用轮询复选框状态改变时的处理"""
        if self.enable_polling_var.get():
            # 启用轮询时，禁用LLM选择配置
            self.enable_llm_config_var.set(False)
        else:
            # 禁用轮询时，启用LLM选择配置
            self.enable_llm_config_var.set(True)
        self.update_llm_config_ui_state()
        self.save_llm_selection_mode()
        
    def on_llm_config_mode_change(self):
        """当LLM选择配置复选框状态改变时的处理"""
        if self.enable_llm_config_var.get():
            # 启用LLM选择配置时，禁用轮询
            self.enable_polling_var.set(False)
        self.update_llm_config_ui_state()
        self.save_llm_selection_mode()
        
    def update_llm_config_ui_state(self):
        """更新LLM配置UI组件的启用/禁用状态"""
        enabled = self.enable_llm_config_var.get()
        
        # 设置所有LLM配置相关组件的状态
        state = "normal" if enabled else "disabled"
        
        # 检查UI组件是否存在，避免初始化阶段的错误
        if hasattr(self, 'main_config_optionmenu'):
            self.main_config_optionmenu.configure(state=state)
        if hasattr(self, 'main_set_default_btn'):
            self.main_set_default_btn.configure(state=state)
        if hasattr(self, 'main_model_combobox'):
            self.main_model_combobox.configure(state=state)
        if hasattr(self, 'main_refresh_btn'):
            self.main_refresh_btn.configure(state=state)
        if hasattr(self, 'main_save_btn'):
            self.main_save_btn.configure(state=state)
            
        # 添加日志，便于调试
        self.safe_log(f"LLM配置UI状态已更新: {'启用' if enabled else '禁用'}")
        
    def update_main_config_menu(self):
        """更新主界面配置选择下拉菜单"""
        names = cm.get_config_names()
        self.main_config_optionmenu.configure(values=names if names else ["无可用配置"])
        if not names:
            self.main_config_selection_var.set("无可用配置")
        else:
            # 保持当前选择，如果它仍然存在
            current_selection = self.main_config_selection_var.get()
            if current_selection not in names:
                self.main_config_selection_var.set(names[0])
                
    def on_main_config_selection(self, config_name):
        """当主界面配置选择改变时的处理"""
        if config_name == "无可用配置":
            return
        
        # 加载选中的配置到当前设置
        config_data = cm.get_config(config_name)
        if config_data:
            # 使用现有的配置加载逻辑
            from ui.llm_settings_tab import load_llm_embedding_config_logic
            load_llm_embedding_config_logic(self, config_data)
            
            # 同步更新大模型设置页面的配置选择
            if hasattr(self, 'config_selection_var'):
                self.config_selection_var.set(config_name)
            
            # 更新主界面的模型名称
            llm_conf = config_data.get("llm_config", {})
            self.main_model_name_var.set(llm_conf.get("model_name", ""))
            
            self.safe_log(f"已加载配置: {config_name}")
        else:
            self.safe_log(f"配置 '{config_name}' 加载失败")
            
    def set_main_default_config(self):
        """将选中的配置设为默认"""
        config_name = self.main_config_selection_var.get()
        if not config_name or config_name == "无可用配置":
            messagebox.showwarning("警告", "请先选择一个要设为默认的配置。")
            return

        if cm.set_default_config_name(config_name):
            self.safe_log(f"配置 '{config_name}' 已被设为默认。")
            messagebox.showinfo("成功", f"配置 '{config_name}' 已被设为默认。")
        else:
            messagebox.showerror("错误", "设置默认配置失败。")
            
    def refresh_main_models(self):
        """刷新主界面的模型列表"""
        config_name = self.main_config_selection_var.get()
        if not config_name or config_name == "无可用配置":
            self.safe_log("请先在主界面选择一个有效的LLM配置。")
            messagebox.showwarning("提示", "请先选择一个有效的LLM配置。")
            return

        config_data = cm.get_config(config_name)
        if not config_data or "llm_config" not in config_data:
            self.safe_log(f"无法加载配置 '{config_name}' 的详细信息。")
            return

        llm_config = config_data["llm_config"]
        interface_format = llm_config.get("interface_format")
        api_key = llm_config.get("api_key")
        base_url = llm_config.get("base_url")
        
        self.safe_log(f"正在为配置 '{config_name}' ({interface_format}) 刷新模型列表...")
        self.main_model_combobox.configure(values=["正在获取..."])

        def fetch_and_update_models_thread():
            try:
                # 创建一个临时的adapter来获取模型
                temp_adapter = create_llm_adapter({
                    "interface_format": interface_format,
                    "api_key": api_key,
                    "base_url": base_url,
                    "proxy": llm_config.get("proxy", "")
                })
                available_models = temp_adapter.get_available_models()
                
                if not available_models:
                    available_models = ["无可用模型"]
                    self.safe_log(f"配置 '{config_name}' 未返回可用模型。")
                else:
                    self.safe_log(f"✅ 成功获取到 {len(available_models)} 个可用模型。")

                # 在主线程中更新UI
                def update_ui():
                    self.main_model_combobox.configure(values=available_models)
                    # 检查当前模型是否在列表中，如果不在，则选择第一个
                    current_model = self.main_model_name_var.get()
                    if current_model not in available_models:
                        if available_models and available_models[0] != "无可用模型":
                            self.main_model_name_var.set(available_models[0])
                        else:
                            self.main_model_name_var.set("")
                
                self.master.after(0, update_ui)

            except Exception as e:
                error_msg = f"❌ 刷新模型列表失败: {e}"
                self.safe_log(error_msg)
                self.master.after(0, lambda: self.main_model_combobox.configure(values=["刷新失败"]))

        threading.Thread(target=fetch_and_update_models_thread, daemon=True).start()
            
    def save_main_model_config(self):
        """保存主界面的模型配置到当前选中的配置"""
        config_name = self.main_config_selection_var.get()
        if not config_name or config_name == "无可用配置":
            messagebox.showwarning("警告", "请先选择一个配置。")
            return
            
        # 获取当前配置
        config_data = cm.get_config(config_name)
        if not config_data:
            messagebox.showerror("错误", f"配置 '{config_name}' 不存在。")
            return
            
        # 更新模型名称
        model_name = self.main_model_name_var.get().strip()
        if not model_name:
            messagebox.showwarning("警告", "模型名称不能为空。")
            return
            
        # 更新配置中的模型名称
        if "llm_config" not in config_data:
            config_data["llm_config"] = {}
        config_data["llm_config"]["model_name"] = model_name
        
        # 保存配置
        llm_config = config_data.get("llm_config", {})
        embedding_config = config_data.get("embedding_config", {})
        
        if cm.save_named_config(config_name, llm_config, embedding_config):
            self.safe_log(f"配置 '{config_name}' 的模型名称已保存为: {model_name}")
            messagebox.showinfo("成功", f"模型名称已保存到配置 '{config_name}'。")
            
            # 同步更新主界面设置的模型名称
            self.model_name_var.set(model_name)
        else:
            messagebox.showerror("错误", "保存模型配置失败。")
            
    def init_main_llm_config(self):
        """初始化主界面LLM配置"""
        # 更新配置下拉菜单
        self.update_main_config_menu()
        
        # 加载默认配置
        default_name = cm.get_default_config_name()
        if default_name:
            self.main_config_selection_var.set(default_name)
            self.on_main_config_selection(default_name)
            
        # 更新UI状态
        self.update_llm_config_ui_state()
        
        # 确保二选一逻辑正确
        if self.enable_polling_var.get():
            self.enable_llm_config_var.set(False)
        else:
            self.enable_llm_config_var.set(True)

    def _bind_project_info_traces(self):
        """在所有初始化完成后绑定自动保存的回调，防止启动时意外覆盖。"""
        self.topic_var.trace_add("write", self.save_project_basic_info)
        self.genre_var.trace_add("write", self.save_project_basic_info)
        self.user_guidance_var.trace_add("write", self.save_project_basic_info)
        self.volume_count_var.trace_add("write", self.save_project_basic_info)
        self.num_chapters_var.trace_add("write", self.save_project_basic_info)
        self.word_number_var.trace_add("write", self.save_project_basic_info)
        self.chapter_num_var.trace_add("write", self.save_project_basic_info)
        self.characters_involved_var.trace_add("write", self.save_project_basic_info)
        self.key_items_var.trace_add("write", self.save_project_basic_info)
        self.scene_location_var.trace_add("write", self.save_project_basic_info)
        self.time_constraint_var.trace_add("write", self.save_project_basic_info)
        # 当文件路径改变时，加载新的项目配置
        self.filepath_var.trace_add("write", lambda *args: self.load_project_basic_info(self.filepath_var.get()))
        self.safe_log("ℹ️ 项目基本信息自动保存功能已激活。")

    def _get_content_for_processing(self, chap_num, operation_name, check_word_count=False):
        """
        一个辅助函数，用于获取要处理的章节内容，并根据需要进行字数校验。
        - 优先使用编辑框内容。
        - 如果编辑框为空，则从文件读取。
        - 如果 check_word_count 为 True，且使用编辑框内容，且字数不足80%，则弹窗确认。
        返回: 章节内容字符串，如果用户取消则返回 None。
        """
        filepath = self.filepath_var.get().strip()
        chapter_file_path = get_chapter_filepath(filepath, chap_num)
        
        # 1. 确定内容来源
        content_source = "编辑框"
        content_text = self.chapter_result.get("0.0", "end").strip() if hasattr(self, "chapter_result") else ""
        
        if not content_text:
            content_source = "文件"
            if os.path.exists(chapter_file_path):
                content_text = read_file(chapter_file_path)
            else:
                self.safe_log(f"❌ 第 {chap_num} 章内容为空（编辑框和文件均无内容），无法{operation_name}。")
                messagebox.showerror("错误", f"第 {chap_num} 章内容为空，无法{operation_name}。")
                return None

        # 2. 如果需要，且内容来自编辑框，则进行字数校验
        if check_word_count and content_source == "编辑框":
            base_word_count = self.safe_get_int(self.word_number_var, 3000)
            threshold = int(base_word_count * 0.8)
            actual_word_count = len(content_text)
            
            if actual_word_count < threshold:
                self.safe_log(f"⚠️ 警告：编辑框中的内容（{actual_word_count}字）少于设定字数（{base_word_count}字）的80%（{threshold}字）。")
                confirm = messagebox.askyesno(
                    "确认操作",
                    f"编辑框中的内容（{actual_word_count}字）远少于设定的每章字数（{base_word_count}字）。\n\n"
                    f"这可能导致{operation_name}效果不佳。\n\n"
                    "您确定要继续吗？",
                    icon='warning'
                )
                if not confirm:
                    self.safe_log(f"❌ 用户取消了{operation_name}操作。")
                    return None # 用户取消

        return content_text

    def run_workflow_ui(self):
        """启动自动生成面板"""
        from ui.workflow_panel import WorkflowPanel
        # 如果已存在实例，先销毁
        if self.workflow_panel and self.workflow_panel.winfo_exists():
            self.workflow_panel.destroy()
            
        self.workflow_panel = WorkflowPanel(self, self.master)
        self._update_word_count_ranges() # 打开时立即同步一次
        self.workflow_panel.grab_set() # 捕获事件，实现模态效果
        self.workflow_panel.wait_window() # 等待窗口关闭

    def _update_word_count_ranges(self, *args):
        """当主界面的每章字数变化时，更新其他地方的字数范围"""
        try:
            base_word_count = int(self.word_number_var.get())
            min_val = int(base_word_count * 0.8)
            max_val = int(base_word_count * 1.5)

            # 如果WorkflowPanel存在且未被销毁，则更新其变量
            if self.workflow_panel and self.workflow_panel.winfo_exists():
                self.workflow_panel.word_count_min_var.set(str(min_val))
                self.workflow_panel.word_count_max_var.set(str(max_val))
        except (ValueError, tk.TclError):
            # 忽略无效输入或变量不存在的错误
            pass

    def _get_formatted_chapter_header(self, chap_num, filepath):
        """获取格式化的章节标题，如 '--- 第 X 章 章节名 ---'"""
        directory_file = os.path.join(filepath, "章节目录.txt")
        chapter_title = "未知标题"
        if os.path.exists(directory_file):
            directory_content = read_file(directory_file)
            # 尝试匹配带书名号的格式
            match = re.search(rf"第\s*{chap_num}\s*章\s*《([^》]+)》", directory_content, re.MULTILINE)
            if match:
                chapter_title = match.group(1).strip()
            else:
                # 尝试匹配不带书名号的格式 (例如: 第 1 章 标题)
                match = re.search(rf"第\s*{chap_num}\s*章\s+(.*)", directory_content, re.MULTILINE)
                if match:
                    chapter_title = match.group(1).strip()
        return f"--- 第{chap_num}章 {chapter_title} ---\n"

    def create_embedding_adapter(self, interface_format=None, api_key=None, base_url=None, model_name=None):
        """
        创建Embedding适配器的便捷方法。
        如果提供了参数，则使用提供的参数；否则，使用当前UI设置。
        """
        config = {
            "interface_format": interface_format if interface_format is not None else self.embedding_interface_format_var.get(),
            "api_key": api_key if api_key is not None else self.embedding_api_key_var.get(),
            "base_url": base_url if base_url is not None else self.embedding_url_var.get(),
            "model_name": model_name if model_name is not None else self.embedding_model_name_var.get(),
        }
        try:
            # 直接将解包后的字典作为关键字参数传递
            return create_embedding_adapter(**config)
        except Exception as e:
            self.safe_log(f"❌ 创建Embedding适配器失败: {e}")
            return None

    def create_llm_adapter_with_current_config(self, step_name: str = "未指定步骤", **kwargs):
        """
        使用当前有效配置创建LLM适配器的便捷方法。
        此方法现在仅用于手动操作，不再处理轮询逻辑。
        轮询逻辑已移至 novel_generator.common.execute_with_polling。
        """
        # 自动工作流现在使用 execute_with_polling，因此此函数总是为非轮询的单一配置模式
        config = self.get_effective_llm_config()
        (interface_format, api_key, base_url, model_name, temperature, top_p, 
         max_tokens, timeout, proxy, _, _, _) = config
        
        config_name = getattr(self, 'main_config_selection_var', ctk.StringVar()).get()
        if not config_name or config_name == "无可用配置":
            config_name = "当前界面设置"
        
        log_message = f"🤖 (手动模式) 使用LLM配置: {config_name}\n   模型: {model_name} ({interface_format})\n   URL: {base_url}"
        self.safe_log(log_message)
        print(log_message)
        
        llm_config = {
            "interface_format": interface_format,
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "proxy": proxy,
            "config_name": config_name,
            "step_name": step_name,
        }
        try:
            return create_llm_adapter(llm_config)
        except Exception as e:
            self.safe_log(f"❌ 创建LLM适配器失败: {e}")
            traceback.print_exc()
            return None


    def get_initial_prompt(self, for_review=False):
        """
        生成一致性审校的初始提示词
        for_review: 是否为审校模式
        """
        try:
            # 获取当前章节号
            chap_num = self.safe_get_int(self.chapter_num_var, 1)
            
            # 构建基本提示词
            prompt_parts = []
            
            if for_review:
                prompt_parts.append("请对以下章节进行一致性审校，检查角色、情节、世界观等方面的连贯性：")
            else:
                prompt_parts.append("请生成以下章节的草稿：")
            
            prompt_parts.append(f"章节号：第 {chap_num} 章")
            
            # 添加主题信息
            topic = self.topic_var.get()
            if topic:
                prompt_parts.append(f"主题：{topic}")
            
            # 添加类型信息
            genre = self.genre_var.get()
            if genre:
                prompt_parts.append(f"类型：{genre}")
            
            # 添加角色信息
            characters = self.characters_involved_var.get()
            if characters:
                prompt_parts.append(f"涉及角色：{characters}")
            
            # 添加关键道具信息
            key_items = self.key_items_var.get()
            if key_items:
                prompt_parts.append(f"关键道具：{key_items}")
            
            # 添加场景位置信息
            scene_location = self.scene_location_var.get()
            if scene_location:
                prompt_parts.append(f"场景位置：{scene_location}")
            
            # 添加时间约束信息
            time_constraint = self.time_constraint_var.get()
            if time_constraint:
                prompt_parts.append(f"时间约束：{time_constraint}")
            
            # 添加用户指导信息
            user_guidance = self.user_guidance_var.get()
            if user_guidance:
                prompt_parts.append(f"用户指导：{user_guidance}")
            
            # 组合所有部分
            prompt_text = "\n".join(prompt_parts)
            return prompt_text
            
        except Exception as e:
            self.handle_exception(f"生成初始提示词时出错: {e}")
            return None

    def get_embedding_config(self):
        """获取当前UI上的Embedding配置"""
        return {
            "interface_format": self.embedding_interface_format_var.get(),
            "api_key": self.embedding_api_key_var.get(),
            "base_url": self.embedding_url_var.get(),
            "model_name": self.embedding_model_name_var.get(),
        }
