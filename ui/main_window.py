# ui/main_window.py
# -*- coding: utf-8 -*-
import os
import threading
import logging
import traceback
import sys
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from .role_library import RoleLibrary
from llm_adapters import create_llm_adapter

from config_manager import load_config, save_config, test_llm_config, test_embedding_config
from utils import read_file, save_string_to_txt, clear_file_content
from tooltips import tooltips

from ui.context_menu import TextWidgetContextMenu
from ui.main_tab import build_main_tab, build_left_layout, build_right_layout
from ui.config_tab import build_config_tabview, load_config_btn, save_config_btn
from ui.novel_params_tab import build_novel_params_area, build_optional_buttons_area
from ui.generation_handlers import (
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
)
from ui.setting_tab import build_setting_tab, load_novel_architecture, save_novel_architecture
from ui.directory_tab import build_directory_tab, load_chapter_blueprint, save_chapter_blueprint, load_text_file
from ui.character_tab import build_character_tab, load_character_file, load_character_state, save_character_state
from ui.summary_tab import build_summary_tab, load_global_summary, save_global_summary
from ui.chapters_tab import build_chapters_tab, refresh_chapters_list, on_chapter_selected, load_chapter_content, save_current_chapter, prev_chapter, next_chapter
from ui.volume_tab import build_volume_tab, load_volume, save_volume, show_volume_tab

class NovelGeneratorGUI:
    """
    小说生成器的主GUI类，包含所有的界面布局、事件处理、与后端逻辑的交互等。
    """
    def __init__(self, master):
        self.master = master
        self.master.title("Novel Generator GUI")
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

        # --------------- 配置文件路径 ---------------
        self.config_file = "config.json"
        self.loaded_config = load_config(self.config_file)

        if self.loaded_config:
            last_llm = self.loaded_config.get("last_interface_format", "OpenAI")
            last_embedding = self.loaded_config.get("last_embedding_interface_format", "OpenAI")
        else:
            last_llm = "OpenAI"
            last_embedding = "OpenAI"

        if self.loaded_config and "llm_configs" in self.loaded_config and last_llm in self.loaded_config["llm_configs"]:
            llm_conf = self.loaded_config["llm_configs"][last_llm]
        else:
            llm_conf = {
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": 8192,
                "timeout": 600
            }

        if self.loaded_config and "embedding_configs" in self.loaded_config and last_embedding in self.loaded_config["embedding_configs"]:
            emb_conf = self.loaded_config["embedding_configs"][last_embedding]
        else:
            emb_conf = {
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "model_name": "text-embedding-ada-002",
                "retrieval_k": 4
            }

        # -- LLM通用参数 --
        self.api_key_var = ctk.StringVar(value=llm_conf.get("api_key", ""))
        self.base_url_var = ctk.StringVar(value=llm_conf.get("base_url", "https://api.openai.com/v1"))
        self.interface_format_var = ctk.StringVar(value=last_llm)
        self.model_name_var = ctk.StringVar(value=llm_conf.get("model_name", "gpt-4o-mini"))
        self.temperature_var = ctk.DoubleVar(value=llm_conf.get("temperature", 0.7))
        self.max_tokens_var = ctk.IntVar(value=llm_conf.get("max_tokens", 8192))
        self.timeout_var = ctk.IntVar(value=llm_conf.get("timeout", 600))

        # -- Embedding相关 --
        self.embedding_interface_format_var = ctk.StringVar(value=last_embedding)
        self.embedding_api_key_var = ctk.StringVar(value=emb_conf.get("api_key", ""))
        self.embedding_url_var = ctk.StringVar(value=emb_conf.get("base_url", "https://api.openai.com/v1"))
        self.embedding_model_name_var = ctk.StringVar(value=emb_conf.get("model_name", "text-embedding-ada-002"))
        self.embedding_retrieval_k_var = ctk.StringVar(value=str(emb_conf.get("retrieval_k", 4)))

        # -- 小说参数相关 --
        if self.loaded_config and "other_params" in self.loaded_config:
            op = self.loaded_config["other_params"]
            self.topic_default = op.get("topic", "")
            self.genre_var = ctk.StringVar(value=op.get("genre", "玄幻"))
            self.num_chapters_var = ctk.StringVar(value=str(op.get("num_chapters", 10)))
            self.word_number_var = ctk.StringVar(value=str(op.get("word_number", 3000)))
            self.filepath_var = ctk.StringVar(value=op.get("filepath", ""))
            self.chapter_num_var = ctk.StringVar(value=str(op.get("chapter_num", "1")))
            self.characters_involved_var = ctk.StringVar(value=op.get("characters_involved", ""))
            self.key_items_var = ctk.StringVar(value=op.get("key_items", ""))
            self.scene_location_var = ctk.StringVar(value=op.get("scene_location", ""))
            self.time_constraint_var = ctk.StringVar(value=op.get("time_constraint", ""))
            self.user_guidance_default = op.get("user_guidance", "")
            self.volume_count_var = ctk.StringVar(value=str(op.get("volume_count", 3)))  # 修改这里
            # 初始化缺失的 StringVar
            self.topic_var = ctk.StringVar(value=self.topic_default)
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
            self.user_guidance_var = ctk.StringVar(value=self.user_guidance_default)
        else:
            self.topic_default = ""
            self.genre_var = ctk.StringVar(value="玄幻")
            self.num_chapters_var = ctk.StringVar(value="10")
            self.word_number_var = ctk.StringVar(value="3000")
            self.filepath_var = ctk.StringVar(value="")
            self.chapter_num_var = ctk.StringVar(value="1")
            self.characters_involved_var = ctk.StringVar(value="")
            self.key_items_var = ctk.StringVar(value="")
            self.scene_location_var = ctk.StringVar(value="")
            self.time_constraint_var = ctk.StringVar(value="")
            self.user_guidance_default = ""
            self.volume_count_var = ctk.StringVar(value="3")  # 添加这里
            # 初始化缺失的 StringVar (else 分支)
            self.topic_var = ctk.StringVar(value=self.topic_default)
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
            self.user_guidance_var = ctk.StringVar(value=self.user_guidance_default)

        # --------------- 整体Tab布局 ---------------
        self.tabview = ctk.CTkTabview(self.master)
        self.tabview.pack(fill="both", expand=True)

        # 创建各个标签页
        build_main_tab(self)
        build_config_tabview(self)
        build_novel_params_area(self, start_row=1)
        # 绑定生成器处理函数
        self.generate_novel_architecture_ui = generate_novel_architecture_ui.__get__(self)
        self.generate_volume_ui = generate_volume_ui.__get__(self)
        self.generate_chapter_blueprint_ui = generate_chapter_blueprint_ui.__get__(self)
        self.generate_chapter_draft_ui = generate_chapter_draft_ui.__get__(self)
        self.finalize_chapter_ui = finalize_chapter_ui.__get__(self)
        self.do_consistency_check = do_consistency_check.__get__(self)
        self.import_knowledge_handler = import_knowledge_handler.__get__(self)
        self.clear_vectorstore_handler = clear_vectorstore_handler.__get__(self)
        self.show_plot_arcs_ui = show_plot_arcs_ui.__get__(self)
        self.rewrite_chapter_ui = rewrite_chapter_ui.__get__(self)
        self.show_rewrite_prompt_editor = show_rewrite_prompt_editor.__get__(self)
        self.execute_chapter_rewrite = execute_chapter_rewrite.__get__(self)
        self.show_consistency_check_results_ui = show_consistency_check_results_ui.__get__(self)

        build_optional_buttons_area(self, start_row=2)
        build_setting_tab(self)
        build_volume_tab(self)
        build_directory_tab(self)
        build_character_tab(self)
        build_summary_tab(self)
        build_chapters_tab(self)
        self.generate_chapter_draft_ui = generate_chapter_draft_ui.__get__(self)
        self.finalize_chapter_ui = finalize_chapter_ui.__get__(self)
        self.do_consistency_check = do_consistency_check.__get__(self)
        self.show_plot_arcs_ui = show_plot_arcs_ui.__get__(self)
        self.generate_volume_ui = generate_volume_ui.__get__(self)
        self.rewrite_chapter_ui = rewrite_chapter_ui.__get__(self)  # 添加这行
        self.show_rewrite_prompt_editor = show_rewrite_prompt_editor.__get__(self) # 添加这行
        self.execute_chapter_rewrite = execute_chapter_rewrite.__get__(self) # 添加这行
        self.load_chapter_blueprint = load_chapter_blueprint.__get__(self)
        self.save_chapter_blueprint = save_chapter_blueprint.__get__(self)
        self.load_text_file = load_text_file.__get__(self)  # 添加这一行

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

    def log(self, message: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def safe_log(self, message: str):
        self.master.after(0, lambda: self.log(message))

    def disable_button_safe(self, btn):
        self.master.after(0, lambda: btn.configure(state="disabled"))

    def enable_button_safe(self, btn):
        self.master.after(0, lambda: btn.configure(state="normal"))

    def handle_exception(self, context: str):
        full_message = f"{context}\n{traceback.format_exc()}"
        logging.error(full_message)
        self.safe_log(full_message)

    def show_chapter_in_textbox(self, text: str):
        self.chapter_result.delete("0.0", "end")
        self.chapter_result.insert("0.0", text)
        self.chapter_result.see("end")
    
    def test_llm_config(self):
        """
        测试当前的LLM配置是否可用
        """
        interface_format = self.interface_format_var.get().strip()
        api_key = self.api_key_var.get().strip()
        base_url = self.base_url_var.get().strip()
        model_name = self.model_name_var.get().strip()
        temperature = self.temperature_var.get()
        max_tokens = self.max_tokens_var.get()
        timeout = self.timeout_var.get()

        test_llm_config(
            interface_format=interface_format,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            log_func=self.safe_log,
            handle_exception_func=self.handle_exception
        )

    def test_embedding_config(self):
        """
        测试当前的Embedding配置是否可用
        """
        api_key = self.embedding_api_key_var.get().strip()
        base_url = self.embedding_url_var.get().strip()
        interface_format = self.embedding_interface_format_var.get().strip()
        model_name = self.embedding_model_name_var.get().strip()

        test_embedding_config(
            api_key=api_key,
            base_url=base_url,
            interface_format=interface_format,
            model_name=model_name,
            log_func=self.safe_log,
            handle_exception_func=self.handle_exception
        )
    
    def browse_folder(self):
        selected_dir = filedialog.askdirectory()
        if (selected_dir):
            self.filepath_var.set(selected_dir)

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
                                                font=("Microsoft YaHei", 12, "bold"))
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
        llm_adapter = create_llm_adapter(
            interface_format=self.interface_format_var.get(),
            base_url=self.base_url_var.get(),
            model_name=self.model_name_var.get(),
            api_key=self.api_key_var.get(),
            temperature=self.temperature_var.get(),
            max_tokens=self.max_tokens_var.get(),
            timeout=self.timeout_var.get()
        )
        
        # 传递LLM适配器实例到角色库
        if hasattr(self, '_role_lib'):
            if self._role_lib.window and self._role_lib.window.winfo_exists():
                self._role_lib.window.destroy()
        
        self._role_lib = RoleLibrary(self.master, save_path, llm_adapter)  # 新增参数

    # 删除重复的show_plot_arcs_ui函数实现,只保留函数引用
    show_plot_arcs_ui = show_plot_arcs_ui

    def show_donate_window(self):
        """显示捐赠窗口"""
        donate_window = ctk.CTkToplevel(self.master)
        donate_window.title("感谢支持")
        donate_window.geometry("800x900")
        donate_window.resizable(False, False)
        
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
            font=("Microsoft YaHei", 12)
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
                font=("Microsoft YaHei", 12)
            )
            error_label.pack(pady=20)
            print(f"Error loading image: {e}")
        
        # 底部文本
        bottom_text = "如非正常渠道获取本软件，请勿扫码捐赠，感谢对本软件的支持"
        bottom_label = ctk.CTkLabel(
            donate_window,
            text=bottom_text,
            font=("Microsoft YaHei", 12)
        )
        bottom_label.pack(pady=(10, 20))

    # ----------------- 将导入的各模块函数直接赋给类方法 -----------------
    generate_novel_architecture_ui = generate_novel_architecture_ui
    generate_volume_ui = generate_volume_ui  # 添加到类方法列表
    generate_chapter_blueprint_ui = generate_chapter_blueprint_ui
    generate_chapter_draft_ui = generate_chapter_draft_ui
    finalize_chapter_ui = finalize_chapter_ui
    do_consistency_check = do_consistency_check
    show_plot_arcs_ui = show_plot_arcs_ui
    load_config_btn = load_config_btn
    save_config_btn = save_config_btn
    load_novel_architecture = load_novel_architecture
    save_novel_architecture = save_novel_architecture
    load_chapter_blueprint = load_chapter_blueprint
    save_chapter_blueprint = save_chapter_blueprint
    load_character_file = load_character_file  # 新增这行
    load_character_state = load_character_state
    save_character_state = save_character_state
    load_global_summary = load_global_summary
    save_global_summary = save_global_summary
    refresh_chapters_list = refresh_chapters_list
    on_chapter_selected = on_chapter_selected
    save_current_chapter = save_current_chapter
    prev_chapter = prev_chapter
    next_chapter = next_chapter
    test_llm_config = test_llm_config
    test_embedding_config = test_embedding_config
    browse_folder = browse_folder
    open_filepath_in_explorer = open_filepath_in_explorer
    show_volume_tab = show_volume_tab
    load_volume = load_volume
    save_volume = save_volume
    rewrite_chapter_ui = rewrite_chapter_ui
    execute_chapter_rewrite = execute_chapter_rewrite  # 添加这行  # 添加到类方法列表
