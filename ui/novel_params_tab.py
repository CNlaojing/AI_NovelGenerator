# ui/novel_params_tab.py
# -*- coding: utf-8 -*-
import customtkinter as ctk
from tkinter import filedialog, messagebox
from ui.context_menu import TextWidgetContextMenu
from tooltips import tooltips
import re # 导入re模块

def _handle_textbox_scroll(event, textbox):
    """
    处理 CTkTextbox 内的鼠标滚轮事件。
    如果文本框可以滚动，则滚动其内容并阻止事件传播到父组件。
    如果文本框已到达滚动边界，则允许事件传播。
    """
    # CTkTextbox 内部包装了一个 tkinter.Text 组件，我们需要访问它来进行滚动操作
    text_widget = textbox._textbox

    # 获取当前的垂直滚动位置 (顶部和底部的比例)
    top, bottom = text_widget.yview()

    # 如果向上滚动且已经到达顶部，则不处理，让父组件滚动
    if event.delta > 0 and top == 0.0:
        return

    # 如果向下滚动且已经到达底部，则不处理，让父组件滚动
    # 使用 >= 1.0 是为了处理浮点数精度问题
    if event.delta < 0 and bottom >= 1.0:
        return

    # 在其他情况下，滚动文本框并返回 "break" 来阻止事件传播
    # 在 Windows 上，event.delta 是 120 的倍数，yview_scroll 需要单位，所以我们进行除法
    text_widget.yview_scroll(-1 * (event.delta // 120), "units")
    return "break"

def _setup_resizable_textbox(self, textbox: ctk.CTkTextbox, text_var: ctk.StringVar, min_lines: int):
    """
    设置一个可根据内容自动调整高度的CTkTextbox, 高度上限为300像素。
    """
    from tkinter import font as tkfont

    # 获取准确的行高
    try:
        actual_font = tkfont.Font(font=textbox.cget("font"))
        line_height = actual_font.metrics("linespace")
        # 添加一点额外的填充以防止截断
        line_height += 2
    except:
        # 回退到估算值
        font_name = textbox.cget("font")
        try:
            font_size_match = re.search(r'\d+', str(font_name))
            font_size = int(font_size_match.group(0)) if font_size_match else 14
        except:
            font_size = 14
        line_height = font_size + 8

    min_height = min_lines * line_height
    max_height = 300 # 高度上限为300像素

    def _on_text_change(event=None):
        # 更新StringVar
        text_var.set(textbox.get("0.0", "end-1c"))

        # 强制更新UI以获取正确的尺寸信息
        textbox.update_idletasks()

        # 使用 'displaylines' 获取实际显示的行数
        # CTkTextbox 包装了标准的 tk.Text, 我们需要访问内部的 _textbox
        # count 方法返回一个元组, 例如 (5,)
        actual_lines = textbox._textbox.count("1.0", "end", "displaylines")[0]
        
        # 如果文本框为空, count 返回 0. 我们应该使用 min_lines.
        # 否则，确保行数不小于 min_lines
        if not textbox.get("1.0", "end-1c"):
             display_lines = min_lines
        else:
             display_lines = max(min_lines, actual_lines)

        # 计算所需高度
        required_height = display_lines * line_height

        # 将高度限制在最小和最大值之间
        new_height = max(min_height, min(required_height, max_height))

        # 应用新高度
        textbox.configure(height=new_height)

    # 初始设置高度
    # 使用 'after' 来确保组件已完全绘制
    textbox.master.after(100, _on_text_change)

    # 绑定事件
    textbox.bind("<KeyRelease>", _on_text_change)
    textbox.bind("<FocusOut>", _on_text_change)
    textbox.bind("<Configure>", _on_text_change)
    
    # 初始加载内容
    textbox.insert("0.0", text_var.get())
    # 插入后再次调用以确保高度正确
    textbox.master.after(150, _on_text_change)


def build_novel_params_area(self, start_row=2):
    # 小说基础设置的滚动区域，占据剩余空间
    self.params_frame = ctk.CTkScrollableFrame(self.right_frame, orientation="vertical")
    self.params_frame.grid(row=start_row, column=0, sticky="nsew", padx=5, pady=5)
    self.params_frame.columnconfigure(1, weight=1)

    # 新增保存/加载基本信息按钮框架
    basic_info_btn_frame = ctk.CTkFrame(self.params_frame)
    basic_info_btn_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
    basic_info_btn_frame.columnconfigure((0, 1), weight=1)

    save_btn = ctk.CTkButton(basic_info_btn_frame, text="保存基本信息", command=self.save_basic_info, font=("Microsoft YaHei", 14))
    save_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

    load_btn = ctk.CTkButton(basic_info_btn_frame, text="加载基本信息", command=self.load_basic_info, font=("Microsoft YaHei", 14))
    load_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # 1) 主题(Topic)
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="主题(Topic):", tooltip_key="topic", row=1, column=0, font=("Microsoft YaHei", 14), sticky="ne")
    self.topic_text = ctk.CTkTextbox(self.params_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    self.topic_text.bind("<MouseWheel>", lambda e, tb=self.topic_text: _handle_textbox_scroll(e, tb))
    TextWidgetContextMenu(self.topic_text)
    self.topic_text.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
    if hasattr(self, 'topic_default') and self.topic_default:
        self.topic_var.set(self.topic_default) # 确保StringVar同步
        self.topic_text.insert("0.0", self.topic_default)
    _setup_resizable_textbox(self, self.topic_text, self.topic_var, min_lines=2)

    # 2) 类型(Genre)
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="类型(Genre):", tooltip_key="genre", row=2, column=0, font=("Microsoft YaHei", 14))
    genre_entry = ctk.CTkEntry(self.params_frame, textvariable=self.genre_var, font=("Microsoft YaHei", 14))
    genre_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

    # 3) 分卷 & 章节
    row_for_chapter_and_word = 3
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="分卷 & 章节:", tooltip_key="num_chapters", row=row_for_chapter_and_word, column=0, font=("Microsoft YaHei", 14))
    chapter_word_frame = ctk.CTkFrame(self.params_frame)
    chapter_word_frame.grid(row=row_for_chapter_and_word, column=1, padx=5, pady=5, sticky="ew")
    chapter_word_frame.columnconfigure((0, 1, 2, 3, 4, 5), weight=0)
    
    # 分卷数输入
    volume_count_label = ctk.CTkLabel(chapter_word_frame, text="分卷数:", font=("Microsoft YaHei", 14))
    volume_count_label.grid(row=0, column=0, padx=5, pady=5, sticky="e")
    # 不直接设置默认值，而是使用变量中的值
    volume_count_entry = ctk.CTkEntry(chapter_word_frame, textvariable=self.volume_count_var, width=40, font=("Microsoft YaHei", 14))
    volume_count_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    
    # 章节数输入
    num_chapters_label = ctk.CTkLabel(chapter_word_frame, text="章节数:", font=("Microsoft YaHei", 14))
    num_chapters_label.grid(row=0, column=2, padx=(15, 5), pady=5, sticky="e")
    num_chapters_entry = ctk.CTkEntry(chapter_word_frame, textvariable=self.num_chapters_var, width=60, font=("Microsoft YaHei", 14))
    num_chapters_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")
    
    # 每章字数输入
    word_number_label = ctk.CTkLabel(chapter_word_frame, text="每章字数:", font=("Microsoft YaHei", 14))
    word_number_label.grid(row=0, column=4, padx=(15, 5), pady=5, sticky="e")
    word_number_entry = ctk.CTkEntry(chapter_word_frame, textvariable=self.word_number_var, width=60, font=("Microsoft YaHei", 14))
    word_number_entry.grid(row=0, column=5, padx=5, pady=5, sticky="w")

    # 4) 保存路径
    row_fp = 4
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="保存路径:", tooltip_key="filepath", row=row_fp, column=0, font=("Microsoft YaHei", 14))
    self.filepath_frame = ctk.CTkFrame(self.params_frame)
    self.filepath_frame.grid(row=row_fp, column=1, padx=5, pady=5, sticky="nsew")
    self.filepath_frame.columnconfigure(0, weight=1)
    filepath_entry = ctk.CTkEntry(self.filepath_frame, textvariable=self.filepath_var, font=("Microsoft YaHei", 14))
    filepath_entry.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
    # print(f"Debug: filepath_var value in build_novel_params_area: {self.filepath_var.get()}") # Debugging line
    browse_btn = ctk.CTkButton(self.filepath_frame, text="浏览...", command=self.browse_folder, width=60, font=("Microsoft YaHei", 14))
    browse_btn.grid(row=0, column=1, padx=5, pady=5, sticky="e")
    open_btn = ctk.CTkButton(self.filepath_frame, text="打开", command=self.open_filepath_in_explorer, width=60, font=("Microsoft YaHei", 14))
    open_btn.grid(row=0, column=2, padx=5, pady=5, sticky="e")

    # 5) 章节号
    row_chap_num = 5
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="章节号:", tooltip_key="chapter_num", row=row_chap_num, column=0, font=("Microsoft YaHei", 14))
    chapter_num_entry = ctk.CTkEntry(self.params_frame, textvariable=self.chapter_num_var, width=80, font=("Microsoft YaHei", 14))
    chapter_num_entry.grid(row=row_chap_num, column=1, padx=5, pady=5, sticky="w")

    # 6) 内容指导
    row_user_guide = 6
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="内容指导:", tooltip_key="user_guidance", row=row_user_guide, column=0, font=("Microsoft YaHei", 14), sticky="ne")
    self.user_guide_text = ctk.CTkTextbox(self.params_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    self.user_guide_text.bind("<MouseWheel>", lambda e, tb=self.user_guide_text: _handle_textbox_scroll(e, tb))
    TextWidgetContextMenu(self.user_guide_text)
    self.user_guide_text.grid(row=row_user_guide, column=1, padx=5, pady=5, sticky="nsew")
    if hasattr(self, 'user_guidance_default') and self.user_guidance_default:
        self.user_guidance_var.set(self.user_guidance_default) # 确保StringVar同步
        self.user_guide_text.insert("0.0", self.user_guidance_default)
    _setup_resizable_textbox(self, self.user_guide_text, self.user_guidance_var, min_lines=2)

    # 7) 可选元素：核心人物/关键道具/空间坐标/时间压力
    row_idx = 7
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="核心人物:", tooltip_key="characters_involved", row=row_idx, column=0, font=("Microsoft YaHei", 14), sticky="ne")
    
    # 核心人物输入框+按钮容器
    char_inv_frame = ctk.CTkFrame(self.params_frame)
    char_inv_frame.grid(row=row_idx, column=1, padx=5, pady=5, sticky="nsew")
    char_inv_frame.columnconfigure(0, weight=1)
    char_inv_frame.rowconfigure(0, weight=1)
    
    # 文本输入框
    self.char_inv_text = ctk.CTkTextbox(char_inv_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    self.char_inv_text.bind("<MouseWheel>", lambda e, tb=self.char_inv_text: _handle_textbox_scroll(e, tb))
    self.char_inv_text.grid(row=0, column=0, padx=(0,5), pady=5, sticky="nsew")
    if hasattr(self, 'characters_involved_var'):
        self.characters_involved_var.set(self.characters_involved_var.get()) # 确保StringVar同步
        self.char_inv_text.insert("0.0", self.characters_involved_var.get())
    _setup_resizable_textbox(self, self.char_inv_text, self.characters_involved_var, min_lines=2)
    
    # 导入按钮
    import_btn = ctk.CTkButton(char_inv_frame, text="导入", width=60, 
                             command=self.show_character_import_window,
                             font=("Microsoft YaHei", 14))
    import_btn.grid(row=0, column=1, padx=(0,5), pady=5, sticky="e")
    row_idx += 1
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="关键道具:", tooltip_key="key_items", row=row_idx, column=0, font=("Microsoft YaHei", 14), sticky="ne")
    self.key_items_text = ctk.CTkTextbox(self.params_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    self.key_items_text.bind("<MouseWheel>", lambda e, tb=self.key_items_text: _handle_textbox_scroll(e, tb))
    TextWidgetContextMenu(self.key_items_text)
    self.key_items_text.grid(row=row_idx, column=1, padx=5, pady=5, sticky="nsew")
    if hasattr(self, 'key_items_var'):
        self.key_items_var.set(self.key_items_var.get()) # 确保StringVar同步
        self.key_items_text.insert("0.0", self.key_items_var.get())
    _setup_resizable_textbox(self, self.key_items_text, self.key_items_var, min_lines=2)

    row_idx += 1
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="时空坐标:", tooltip_key="scene_location", row=row_idx, column=0, font=("Microsoft YaHei", 14), sticky="ne")
    self.scene_location_text = ctk.CTkTextbox(self.params_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    self.scene_location_text.bind("<MouseWheel>", lambda e, tb=self.scene_location_text: _handle_textbox_scroll(e, tb))
    TextWidgetContextMenu(self.scene_location_text)
    self.scene_location_text.grid(row=row_idx, column=1, padx=5, pady=5, sticky="nsew")
    if hasattr(self, 'scene_location_var'):
        self.scene_location_var.set(self.scene_location_var.get()) # 确保StringVar同步
        self.scene_location_text.insert("0.0", self.scene_location_var.get())
    _setup_resizable_textbox(self, self.scene_location_text, self.scene_location_var, min_lines=2)

    row_idx += 1
    create_label_with_help_for_novel_params(self, parent=self.params_frame, label_text="时间压力:", tooltip_key="time_constraint", row=row_idx, column=0, font=("Microsoft YaHei", 14), sticky="ne")
    self.time_constraint_text = ctk.CTkTextbox(self.params_frame, height=40, wrap="word", font=("Microsoft YaHei", 14), undo=True)
    self.time_constraint_text.bind("<MouseWheel>", lambda e, tb=self.time_constraint_text: _handle_textbox_scroll(e, tb))
    TextWidgetContextMenu(self.time_constraint_text)
    self.time_constraint_text.grid(row=row_idx, column=1, padx=5, pady=5, sticky="nsew")
    if hasattr(self, 'time_constraint_var'):
        self.time_constraint_var.set(self.time_constraint_var.get()) # 确保StringVar同步
        self.time_constraint_text.insert("0.0", self.time_constraint_var.get())
    _setup_resizable_textbox(self, self.time_constraint_text, self.time_constraint_var, min_lines=2)

def build_optional_buttons_area(self, start_row=3):
    # 可选功能按钮区域，放在最下方
    self.optional_btn_frame = ctk.CTkFrame(self.right_frame)
    self.optional_btn_frame.grid(row=start_row, column=0, sticky="ew", padx=5, pady=5)
    self.optional_btn_frame.columnconfigure((0, 1, 2), weight=1)
    self.optional_btn_frame.columnconfigure((3, 4), weight=0)

    self.btn_check_consistency = ctk.CTkButton(
        self.optional_btn_frame, text="一致性审校", command=self.do_consistency_check, 
        font=("Microsoft YaHei", 14), width=120  # 固定宽度
    )
    self.btn_check_consistency.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

    self.btn_show_consistency_results = ctk.CTkButton(
        self.optional_btn_frame, text="查看审校结果", command=self.show_consistency_check_results_ui, 
        font=("Microsoft YaHei", 14), width=120
    )
    self.btn_show_consistency_results.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    self.plot_arcs_btn = ctk.CTkButton(
        self.optional_btn_frame, text="查看剧情要点", command=self.show_plot_arcs_ui,
        font=("Microsoft YaHei", 14), width=120
    )
    self.plot_arcs_btn.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

    # 新增角色库按钮
    self.role_library_btn = ctk.CTkButton(
        self.optional_btn_frame, text="角色库", command=self.show_role_library,
        font=("Microsoft YaHei", 14), width=120
    )
    self.role_library_btn.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

    # 新增查看日志按钮
    view_log_btn = ctk.CTkButton(
        self.optional_btn_frame,
        text="查看日志",
        command=self.show_polling_log_viewer, # 链接到新的日志查看器
        font=("Microsoft YaHei", 14),
        width=120
    )
    view_log_btn.grid(row=0, column=4, padx=5, pady=5, sticky="ew")


def create_label_with_help_for_novel_params(self, parent, label_text, tooltip_key, row, column, font=None, sticky="e", padx=5, pady=5):
    frame = ctk.CTkFrame(parent)
    frame.grid(row=row, column=column, padx=padx, pady=pady, sticky=sticky)
    frame.columnconfigure(0, weight=0)
    label = ctk.CTkLabel(frame, text=label_text, font=font)
    label.pack(side="left")
    btn = ctk.CTkButton(frame, text="?", width=22, height=22, font=("Microsoft YaHei", 10),
                        command=lambda: messagebox.showinfo("参数说明", tooltips.get(tooltip_key, "暂无说明")))
    btn.pack(side="left", padx=3)
    return frame
