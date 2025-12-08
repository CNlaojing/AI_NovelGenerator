# ui/role_library.py
import os
import tkinter as tk
from tkinter import filedialog
import shutil
import re
import customtkinter as ctk
from tkinter import messagebox, BooleanVar
from customtkinter import CTkScrollableFrame, CTkTextbox, END
from utils import read_file, save_string_to_txt  # 导入 utils 中的函数
from novel_generator.common import invoke_with_cleaning  # 新增导入
from prompt_definitions import Character_Import_Prompt

DEFAULT_FONT = ("Microsoft YaHei", 14)

class RoleLibrary:
    def __init__(self, master, save_path, llm_adapter):  # 新增llm_adapter参数
        self.master = master
        self.save_path = os.path.join(save_path, "角色库")
        self.selected_category = None
        self.current_roles = []
        self.selected_del = []
        self.llm_adapter = llm_adapter  # 保存LLM适配器实例

        # 初始化窗口
        self.window = ctk.CTkToplevel(master)
        self.window.title("角色库管理")
        self.window.geometry("1200x800")
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        # 创建目录结构
        self.create_library_structure()
        # 构建UI
        self.create_ui()
        # 窗口居中
        self.center_window()
        # 窗口模态设置
        self.window.grab_set()
        self.window.attributes('-topmost', 1)
        self.window.after(200, lambda: self.window.attributes('-topmost', 0))

    def create_library_structure(self):
        """创建必要的目录结构"""
        os.makedirs(self.save_path, exist_ok=True)
        all_dir = os.path.join(self.save_path, "全部")
        os.makedirs(all_dir, exist_ok=True)

    def create_ui(self):
        """创建主界面"""
        # 分类按钮区
        self.create_category_bar()

        # 主内容区
        main_frame = ctk.CTkFrame(self.window)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 左侧面板 - 角色列表区
        left_panel = ctk.CTkFrame(main_frame, width=300)
        left_panel.pack(side="left", fill="both", padx=5, pady=5)

        # 角色列表区
        self.role_list_frame = ctk.CTkScrollableFrame(left_panel)
        self.role_list_frame.pack(fill="both", expand=True)

        # 右侧面板（信息编辑区）
        right_panel = ctk.CTkFrame(main_frame)
        right_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)

        # 分类选择行
        category_frame = ctk.CTkFrame(right_panel)
        category_frame.pack(fill="x", padx=5, pady=5)

        # 分类选择标签
        ctk.CTkLabel(category_frame, text="分类选择", font=DEFAULT_FONT).pack(side="left", padx=(0, 5))

        # 分类选择框
        self.category_combobox = ctk.CTkComboBox(
            category_frame,
            values=self._get_all_categories(),
            width=200,
            font=DEFAULT_FONT
        )
        self.category_combobox.pack(side="left", padx=0)

        # 分类保存按钮
        self.save_category_btn = ctk.CTkButton(
            category_frame,
            text="保存分类",
            width=80,
            command=self._move_to_category,
            font=DEFAULT_FONT
        )
        self.save_category_btn.pack(side="left", padx=(0, 5))

        # 打开文件夹按钮
        ctk.CTkButton(
            category_frame,
            text="打开文件夹",
            width=80,
            command=lambda: os.startfile(
                os.path.join(self.save_path, self.category_combobox.get())),
            font=DEFAULT_FONT
        ).pack(side="left", padx=0)

        # 角色名编辑行
        name_frame = ctk.CTkFrame(right_panel)
        name_frame.pack(fill="x", padx=5, pady=5)

        # 角色名称标签
        ctk.CTkLabel(name_frame, text="角色名称", font=DEFAULT_FONT).pack(side="left", padx=(0, 5))

        self.role_name_var = tk.StringVar()
        self.role_name_entry = ctk.CTkEntry(
            name_frame,
            textvariable=self.role_name_var,
            placeholder_text="角色名称",
            width=200,
            font=DEFAULT_FONT
        )
        self.role_name_entry.pack(side="left", padx=0)

        ctk.CTkButton(
            name_frame,
            text="修改",
            width=60,
            command=self._rename_role_file,
            font=DEFAULT_FONT
        ).pack(side="left", padx=(0, 5))

        # 角色权重按钮区
        weight_frame = ctk.CTkFrame(right_panel)
        weight_frame.pack(fill="x", padx=5, pady=5)
        
        # 添加六个角色权重等级按钮
        ctk.CTkLabel(weight_frame, text="角色权重：", font=DEFAULT_FONT).pack(side="left", padx=(0, 5))
        
        # 背景角色按钮 (1-20)
        ctk.CTkButton(
            weight_frame,
            text="背景角色",
            width=80,
            command=lambda: self._create_new_role("背景角色", "背景角色", "1-20"),
            font=DEFAULT_FONT
        ).pack(side="left", padx=(0, 5))
        
        # 单元角色按钮 (21-40)
        ctk.CTkButton(
            weight_frame,
            text="单元角色",
            width=80,
            command=lambda: self._create_new_role("单元角色", "单元角色", "21-40"),
            font=DEFAULT_FONT
        ).pack(side="left", padx=(0, 5))
        
        # 次要配角按钮 (41-60)
        ctk.CTkButton(
            weight_frame,
            text="次要配角",
            width=80,
            command=lambda: self._create_new_role("次要配角", "次要配角", "41-60"),
            font=DEFAULT_FONT
        ).pack(side="left", padx=(0, 5))
        
        # 关键角色按钮 (61-80)
        ctk.CTkButton(
            weight_frame,
            text="关键角色",
            width=80,
            command=lambda: self._create_new_role("关键角色", "关键角色", "61-80"),
            font=DEFAULT_FONT
        ).pack(side="left", padx=(0, 5))
        
        # 核心配角按钮 (81-95)
        ctk.CTkButton(
            weight_frame,
            text="核心配角",
            width=80,
            command=lambda: self._create_new_role("核心配角", "核心配角", "81-95"),
            font=DEFAULT_FONT
        ).pack(side="left", padx=(0, 5))
        
        # 主角级按钮 (96-100)
        ctk.CTkButton(
            weight_frame,
            text="主角级",
            width=80,
            command=lambda: self._create_new_role("主角级", "主角级", "96-100"),
            font=DEFAULT_FONT
        ).pack(side="left", padx=0)
        
        # 角色内容编辑区
        self.role_edit_text = ctk.CTkTextbox(right_panel, wrap="word", font=DEFAULT_FONT)
        self.role_edit_text.pack(fill="both", expand=True, padx=5, pady=5)

        button_frame = ctk.CTkFrame(right_panel)
        button_frame.pack(fill="x", padx=5, pady=5)

        ctk.CTkButton(button_frame, text="导入角色",
                      command=self.import_roles, font=DEFAULT_FONT).pack(side="left", padx=5)
        ctk.CTkButton(button_frame, text="删除",
                      command=self.delete_current_role, font=DEFAULT_FONT).pack(side="left", padx=5)
        ctk.CTkButton(button_frame, text="保存",
                      command=self.save_current_role, font=DEFAULT_FONT).pack(side="left", padx=5)

    def _get_all_categories(self):
        """获取所有有效分类（包括动态更新）"""
        categories = ["全部"]
        for d in os.listdir(self.save_path):
            if os.path.isdir(os.path.join(self.save_path, d)) and d != "全部":
                categories.append(d)
        return categories

    def _move_to_category(self):
        """分类转移功能"""
        if not hasattr(self, 'current_role') or not self.current_role:
            messagebox.showwarning("警告", "请先选择一个角色", parent=self.window)
            return

        new_category = self.category_combobox.get()
        
        # 如果当前在"全部"分类下，需要找到角色实际所在分类
        if self.selected_category == "全部":
            # 遍历所有分类查找实际存储位置（包含全部目录）
            actual_category = None
            for category in os.listdir(self.save_path):
                test_path = os.path.join(
                    self.save_path, category, f"{self.current_role}.txt")
                if os.path.exists(test_path):
                    actual_category = category
                    break

            if not actual_category:
                msg = messagebox.showerror("错误", f"找不到角色 {self.current_role} 的实际存储位置", parent=self.window)
                self.window.attributes('-topmost', 1)
                msg.attributes('-topmost', 1)
                self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])
                return

            old_path = os.path.join(
                self.save_path, actual_category, f"{self.current_role}.txt")
        else:
            old_path = os.path.join(
                self.save_path, self.selected_category, f"{self.current_role}.txt")

        # 如果目标分类是"全部"，则实际移动到"全部"分类
        if new_category == "全部":
            new_path = os.path.join(
                self.save_path, "全部", f"{self.current_role}.txt")
        else:
            new_path = os.path.join(
                self.save_path, new_category, f"{self.current_role}.txt")

        # 检查是否已经在目标分类
        if os.path.exists(new_path):
            msg = messagebox.showinfo("提示", "角色已在目标分类中", parent=self.window)
            self.window.attributes('-topmost', 1)
            msg.attributes('-topmost', 1)
            self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])
            return

        confirm = messagebox.askyesno(
            "确认", f"确定要将角色 {self.current_role} 移动到 {new_category} 分类吗？", parent=self.window)
        if not confirm:
            return

        try:
            # 确保目标目录存在
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            
            try:
                # 执行移动操作
                shutil.move(old_path, new_path)
                
                # 更新显示
                self.selected_category = new_category if new_category != "全部" else "全部"
                self.show_category(self.selected_category)
                self.category_combobox.set(new_category)
                
                # 成功提示
                messagebox.showinfo("成功", "分类已更新", parent=self.window)
                return  # 成功时直接返回
                
            except Exception as e:
                # 失败时恢复原分类显示
                self.category_combobox.set(self.selected_category)
                raise e
        except Exception as e:
            msg = messagebox.showerror("错误", f"分类转移失败：{str(e)}", parent=self.window)
            self.window.attributes('-topmost', 1)
            msg.attributes('-topmost', 1)
            self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])
            self.category_combobox.set(self.selected_category)

    def import_roles(self):
        """导入角色窗口"""
        import_window = ctk.CTkToplevel(self.window)
        import_window.title("角色导入")
        import_window.geometry("800x600")
        import_window.transient(self.window)  # 设置为子窗口
        import_window.grab_set()  # 模态窗口
        import_window.lift()  # 置于父窗口前面

        # 窗口居中计算
        import_window.update_idletasks()
        i_width = import_window.winfo_width()
        i_height = import_window.winfo_height()
        x = self.window.winfo_x() + (self.window.winfo_width() - i_width) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - i_height) // 2
        import_window.geometry(f"+{x}+{y}")

        # 主内容区
        main_frame = ctk.CTkFrame(import_window)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 左右面板容器
        content_frame = ctk.CTkFrame(main_frame)
        content_frame.pack(fill="both", expand=True, pady=(0, 10))
        content_frame.grid_columnconfigure(0, weight=1)  # 左侧面板权重
        content_frame.grid_columnconfigure(1, weight=1)  # 右侧面板权重

        # 左侧面板 - 使用权重让控件占满空间
        left_panel = ctk.CTkFrame(content_frame)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=5)
        left_panel.grid_rowconfigure(0, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_propagate(False)  # 防止子控件改变父容器大小

        # 右侧面板（2份宽度） - 添加初始可编辑文本框
        right_panel = ctk.CTkFrame(content_frame)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=5)
        right_panel.grid_rowconfigure(0, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)
        
        # 创建初始可编辑文本框
        text_box = ctk.CTkTextbox(right_panel, wrap="word", font=DEFAULT_FONT)
        text_box.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        text_box.configure(state="normal")  # 保持可编辑状态

        # 初始化角色列表
        self.import_roles_list = []

        # 底部按钮区
        btn_frame = ctk.CTkFrame(main_frame)
        btn_frame.pack(fill="x", pady=(0, 10))

        # 导入按钮
        ctk.CTkButton(
            btn_frame,
            text="导入临时角色库",
            width=120,
            command=lambda: self.confirm_import(import_window),
            font=DEFAULT_FONT
        ).pack(side="left", padx=10)

        # 分析文件按钮
        ctk.CTkButton(
            btn_frame,
            text="分析文件",
            width=100,
            command=lambda: self.analyze_character_state(right_panel, left_panel),
            font=DEFAULT_FONT
        ).pack(side="left", padx=10)

        # 加载角色状态.txt按钮
        ctk.CTkButton(
            btn_frame,
            text="加载角色状态.txt",
            width=160,
            command=lambda: self.load_default_character_state(right_panel),
            font=DEFAULT_FONT
        ).pack(side="right", padx=10)

        # 从文件导入按钮
        ctk.CTkButton(
            btn_frame,
            text="从文件导入",
            width=100,
            command=lambda: self.import_from_file(right_panel),
            font=DEFAULT_FONT
        ).pack(side="right", padx=10)

        # 设置内容区权重
        content_frame.grid_rowconfigure(0, weight=1)

    def analyze_character_state(self, right_panel, left_panel):
        """分析角色状态文件，使用LLM提取角色信息"""
        content = ""
        for widget in right_panel.winfo_children():
            if isinstance(widget, ctk.CTkTextbox):
                content = widget.get("1.0", "end").strip()
                break
        
        if not content:
            messagebox.showwarning("警告", "未找到可分析的内容", parent=self.window)
            return

        try:
            # 显示处理中提示
            for widget in left_panel.winfo_children():
                widget.destroy()
            processing_label = ctk.CTkLabel(left_panel, text="正在分析角色信息，请稍候...", font=("Microsoft YaHei", 14))
            processing_label.pack(pady=20)
            left_panel.update()

            # 调用LLM进行分析
            prompt = f"{Character_Import_Prompt}\n<<待分析小说文本开始>>\n{content}\n<<待分析小说文本结束>>"
            response = invoke_with_cleaning(
                self.llm_adapter,
                prompt
            )
            
            # 解析LLM响应
            roles = self._parse_llm_response(response)
            
            if not roles:
                messagebox.showwarning("警告", "未解析到有效角色信息，请检查文本内容或修改提示词。\n\n可能的原因：\n1. 文本中没有明确的角色信息\n2. LLM返回的格式不符合解析要求\n3. 角色名称格式不正确\n4. 角色名后面的冒号格式不正确", parent=self.window)
                return

            # 显示分析结果
            self._display_analyzed_roles(left_panel, roles)
            messagebox.showinfo("分析成功", f"成功解析出{len(roles)}个角色信息，请选择需要导入的角色。", parent=self.window)

        except Exception as e:
            messagebox.showerror("分析失败", f"LLM分析出错：{str(e)}", parent=self.window)

    def _display_temp_roles(self, parent, temp_dir):
        """显示临时角色库中的角色"""
        # 清空左侧面板
        for widget in parent.winfo_children():
            widget.destroy()

        # 创建滚动容器
        scroll_frame = ctk.CTkScrollableFrame(parent)
        scroll_frame.pack(fill="both", expand=True)

        # 读取所有临时角色文件
        self.character_checkboxes = {}
        for file_name in os.listdir(temp_dir):
            if file_name.endswith(".txt"):
                role_name = os.path.splitext(file_name)[0]
                file_path = os.path.join(temp_dir, file_name)
                
                # 解析角色属性
                attributes = self._parse_temp_role_file(file_path)
                
                # 创建带勾选框的条目
                frame = ctk.CTkFrame(scroll_frame)
                frame.pack(fill="x", pady=2, padx=5)
                
                # 勾选框
                var = BooleanVar(value=True)
                cb = ctk.CTkCheckBox(frame, text="", variable=var, width=20, font=DEFAULT_FONT)
                cb.pack(side="left", padx=5)
                
                # 角色名称
                lbl = ctk.CTkLabel(frame, text=role_name, 
                                 font=("Microsoft YaHei", 14))
                lbl.pack(side="left", padx=5)
                
                # 属性摘要
                attrs = [f"{k}({len(v)})" for k,v in attributes.items()]
                summary = ctk.CTkLabel(frame, text=" | ".join(attrs), 
                                     font=("Microsoft YaHei", 14),
                                     text_color="gray")
                summary.pack(side="right", padx=10)
                
                self.character_checkboxes[role_name] = {
                    'var': var,
                    'data': {'name': role_name, 'attributes': attributes}
                }

        # 添加操作按钮
        btn_frame = ctk.CTkFrame(scroll_frame)
        btn_frame.pack(fill="x", pady=5)
        ctk.CTkButton(btn_frame, text="全选", 
                     command=lambda: self._toggle_all(True), font=DEFAULT_FONT).pack(side="left")
        ctk.CTkButton(btn_frame, text="取消选择", 
                     command=lambda: self._toggle_all(False), font=DEFAULT_FONT).pack(side="left")

    def _parse_llm_response(self, response):
        """解析LLM返回的角色数据"""
        roles = []
        current_role = None
        current_attr = None
        
        # 角色名模式（例如：周雍：）- 修改为更准确匹配中文字符
        role_name_pattern = re.compile(r'^([\u4e00-\u9fff\w]+)[:：]\s*$')
        # 基础属性模式（例如：- 称谓：xxx）
        basic_attr_pattern = re.compile(r'^-\s+([^:：]+)[:：]\s*(.*)')
        # 主要属性模式（例如：基础信息：、势力特征：等）
        main_attr_pattern = re.compile(r'^([^-:：]+)[:：]\s*$')
        
        # 定义属性标题列表，这些不应该被识别为角色名
        attribute_titles = ["基础信息", "势力特征", "生命状态", "基本简介"]
        
        # 记录解析过程，用于调试
        debug_info = []
        
        lines = response.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            
            # 检测角色名称行（格式为：角色名：）
            role_match = role_name_pattern.match(line)
            
            # 如果找到角色名，且不是属性标题
            if role_match and role_match.group(1).strip() not in attribute_titles:
                current_role = role_match.group(1).strip()
                debug_info.append(f"找到角色: {current_role}")
                roles.append({'name': current_role, 'attributes': {}})
                current_attr = None
            # 如果已有角色，处理属性
            elif current_role is not None:
                # 检查是否是主要属性（如基础信息：、势力特征：等）
                main_attr_match = main_attr_pattern.match(line)
                if main_attr_match:
                    current_attr = main_attr_match.group(1).strip()
                    if current_attr not in roles[-1]['attributes']:
                        roles[-1]['attributes'][current_attr] = []
                        debug_info.append(f"  添加主要属性: {current_attr}")
                # 检查是否是基础属性（如其他称谓、角色权重等）
                elif current_attr and line.startswith('-'):
                    basic_attr_match = basic_attr_pattern.match(line)
                    if basic_attr_match:
                        attr_name = basic_attr_match.group(1).strip()
                        attr_value = basic_attr_match.group(2).strip()
                        roles[-1]['attributes'][current_attr].append(f"{attr_name}：{attr_value}")
                        debug_info.append(f"    添加基础属性: {attr_name}：{attr_value}")
                # 如果是属性下的内容行
                elif current_attr and line.strip() and not line.startswith('#'):
                    # 如果不是以-开头但属于某个属性，作为该属性的内容
                    roles[-1]['attributes'][current_attr].append(line.strip())
                    debug_info.append(f"    添加内容: {line.strip()}")
            
            i += 1
        
        # 过滤掉没有属性的角色
        roles = [role for role in roles if role['attributes']]
        
        # 过滤掉没有属性的角色
        roles = [role for role in roles if role['attributes']]
        
        return roles

    def _display_analyzed_roles(self, parent, roles):
        """显示分析后的角色列表"""
        self.character_checkboxes = {}
        
        # 创建带滚动条的容器
        scroll_frame = ctk.CTkScrollableFrame(parent)
        scroll_frame.pack(fill="both", expand=True, padx=5, pady=5)
        scroll_frame.grid_rowconfigure(0, weight=1)
        scroll_frame.grid_columnconfigure(0, weight=1)

        # 为每个角色创建带勾选框的条目
        for role in roles:
            frame = ctk.CTkFrame(scroll_frame)
            frame.pack(fill="x", pady=2, padx=5)
            
            # 勾选框
            var = BooleanVar(value=True)
            cb = ctk.CTkCheckBox(frame, text="", variable=var, width=20, font=DEFAULT_FONT)
            cb.pack(side="left", padx=5)
            
            # 角色名称标签
            lbl = ctk.CTkLabel(frame, text=role['name'], 
                             font=("Microsoft YaHei", 14))
            lbl.pack(side="left", padx=5)
            
            # 属性摘要
            attrs = [f"{k}({len(v)})" for k,v in role['attributes'].items()]
            summary = ctk.CTkLabel(frame, text=" | ".join(attrs), 
                                 font=("Microsoft YaHei", 14),
                                 text_color="gray")
            summary.pack(side="right", padx=10)
            
            self.character_checkboxes[role['name']] = {
                'var': var,
                'data': role
            }

        # 添加全选/反选按钮
        btn_frame = ctk.CTkFrame(scroll_frame)
        btn_frame.pack(fill="x", pady=5)
        
        ctk.CTkButton(btn_frame, text="全选", 
                     command=lambda: self._toggle_all(True), font=DEFAULT_FONT).pack(side="left")
        ctk.CTkButton(btn_frame, text="反选", 
                     command=lambda: self._toggle_all(False), font=DEFAULT_FONT).pack(side="left")

    def _toggle_all(self, select):
        """全选/反选操作"""
        for role in self.character_checkboxes.values():
            current_state = role['var'].get()
            # 如果是反选操作，则设置相反状态
            if isinstance(select, bool):
                role['var'].set(select)
            else:
                role['var'].set(not current_state)
            
    def _parse_temp_role_file(self, file_path):
        """解析临时角色文件的属性
        根据新的角色状态格式解析临时角色文件，提取角色属性
        """
        attributes = {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 使用与_parse_llm_response相同的解析逻辑
            current_attr = None
            
            # 角色名模式（例如：周雍：）
            role_name_pattern = re.compile(r'^([\u4e00-\u9fff\w]+)[:：]\s*$')
            # 基础属性模式（例如：- 称谓：xxx）
            basic_attr_pattern = re.compile(r'^-\s+([^:：]+)[:：]\s*(.*)')
            # 主要属性模式（例如：基础信息：、势力特征：等）
            main_attr_pattern = re.compile(r'^([^-:：]+)[:：]\s*$')
            
            lines = content.split('\n')
            for line in lines:
                line = line.rstrip()
                
                # 检查是否是主要属性（如基础信息：、势力特征：等）
                main_attr_match = main_attr_pattern.match(line)
                if main_attr_match and not role_name_pattern.match(line):  # 排除角色名行
                    current_attr = main_attr_match.group(1).strip()
                    if current_attr not in attributes:
                        attributes[current_attr] = []
                # 检查是否是基础属性或内容行
                elif current_attr and line.strip() and not line.startswith('#'):
                    attributes.setdefault(current_attr, []).append(line.strip())
            
        except Exception as e:
            print(f"解析临时角色文件出错: {str(e)}")
        
        return attributes

    def confirm_import(self, import_window):
        """确认导入选中的角色到临时角色库
        将用户勾选的角色保存到临时角色库目录
        """
        # 获取临时角色库路径 - 修改为角色库文件夹下
        temp_dir = os.path.join(self.save_path, "临时角色库")
        os.makedirs(temp_dir, exist_ok=True)
        
        # 获取选中的角色
        selected_roles = []
        for role_name, role_data in self.character_checkboxes.items():
            if role_data['var'].get():
                selected_roles.append(role_data['data'])
        
        if not selected_roles:
            messagebox.showwarning("警告", "未选择任何角色", parent=self.window)
            return
        
        # 保存选中的角色到临时角色库
        for role in selected_roles:
            role_name = role['name']
            file_path = os.path.join(temp_dir, f"{role_name}.txt")
            
            # 构建角色内容
            content = f"{role_name}：\n"
            
            # 添加属性内容
            for attr_name, attr_values in role['attributes'].items():
                content += f"{attr_name}：\n"
                for value in attr_values:
                    content += f"{value}\n"
            
            # 保存到文件
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                messagebox.showerror("错误", f"保存角色 {role_name} 失败: {str(e)}", parent=self.window)
        
        messagebox.showinfo("成功", f"已成功导入 {len(selected_roles)} 个角色到临时角色库", parent=self.window)
        
        # 刷新角色库页面的类型栏，确保临时角色库类型显示出来
        self.load_categories()
        
        # 关闭导入窗口
        import_window.destroy()


    def import_from_file(self, right_panel):
        """从文件导入内容到右侧窗口"""
        filetypes = (
            ('文本文件', '*.txt'),
            ('Word文档', '*.docx'),
            ('所有文件', '*.*')
        )
        
        file_path = filedialog.askopenfilename(
            title="选择要导入的文件",
            initialdir=os.path.expanduser("~"),
            filetypes=filetypes
        )
        
        if not file_path:
            return

        try:
            content = ""
            if file_path.endswith('.docx'):
                # 处理Word文档
                from docx import Document
                doc = Document(file_path)
                content = "\n".join([para.text for para in doc.paragraphs])
            else:
                # 处理普通文本文件
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

            # 更新右侧文本框中
            for widget in right_panel.winfo_children():
                if isinstance(widget, ctk.CTkTextbox):
                    widget.delete("1.0", "end")
                    widget.insert("1.0", content)
                    break

        except Exception as e:
            messagebox.showerror("导入失败", f"无法读取文件：{str(e)}", parent=self.window)

    def load_default_character_state(self, right_panel):
        """加载角色状态.txt文件到右侧窗口"""
        # 获取保存路径
        save_path = os.path.dirname(self.save_path)
        file_path = os.path.join(save_path, "角色状态.txt")

        if not os.path.exists(file_path):
            messagebox.showwarning("警告", f"未找到文件: {file_path}", parent=self.window)
            return

        try:
            # 读取文件内容
            content = read_file(file_path)

            # 清空右侧面板中可能存在的旧控件
            for widget in right_panel.winfo_children():
                widget.destroy()

            # 查找或创建文本框
            text_box = None
            for widget in right_panel.winfo_children():
                if isinstance(widget, ctk.CTkTextbox):
                    text_box = widget
                    break
            
            if not text_box:
                text_box = ctk.CTkTextbox(right_panel, wrap="word", font=DEFAULT_FONT)
                text_box.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
            
            text_box.configure(state="normal")
            text_box.delete("1.0", "end")
            text_box.insert("1.0", content)

            # 设置右边面板的布局权重
            right_panel.grid_rowconfigure(0, weight=1)
            right_panel.grid_columnconfigure(0, weight=1)

        except Exception as e:
            messagebox.showerror("错误", f"加载文件失败: {str(e)}", parent=self.window)

    def delete_current_role(self):
        """删除当前角色"""
        if not hasattr(self, 'current_role') or not self.current_role:
            return

        confirm = messagebox.askyesno(
            "确认删除", f"确定要删除角色 {self.current_role} 吗？", parent=self.window)
        if not confirm:
            return

        role_path = os.path.join(
            self.save_path, self.selected_category, f"{self.current_role}.txt")
        try:
            os.remove(role_path)
            # 从"全部"分类也删除
            all_path = os.path.join(
                self.save_path, "全部", f"{self.current_role}.txt")
            if os.path.exists(all_path):
                os.remove(all_path)
            self.show_category(self.selected_category)
            self.role_edit_text.delete("1.0", "end")
            msg = messagebox.showinfo("成功", "角色已删除", parent=self.window)
            self.window.attributes('-topmost', 1)
            msg.attributes('-topmost', 1)
            self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])
        except Exception as e:
            msg = messagebox.showerror("错误", f"删除失败：{str(e)}", parent=self.window)
            self.window.attributes('-topmost', 1)
            msg.attributes('-topmost', 1)
            self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])

    def _check_role_name_conflict(self, new_name):
        """检查角色名是否重复，遍历整个角色文件夹"""
        conflicts = []
        # 遍历所有分类目录
        for category in os.listdir(self.save_path):
            if os.path.isdir(os.path.join(self.save_path, category)):
                # 检查该分类下是否有同名角色
                role_path = os.path.join(
                    self.save_path, category, f"{new_name}.txt")
                if os.path.exists(role_path):
                    # 如果是"全部"分类，需要进一步检查是否是实际文件
                    if category == "全部":
                        # 检查"全部"目录下的文件是否是实际文件
                        all_path = os.path.join(
                            self.save_path, "全部", f"{new_name}.txt")
                        if os.path.isfile(all_path):
                            # 如果是实际文件，则认为是冲突
                            conflicts.append(category)
                    else:
                        # 普通分类直接记录冲突
                        conflicts.append(category)
        return conflicts

    def save_current_role(self):
        """保存当前编辑的角色"""
        if not hasattr(self, 'current_role') or not self.current_role:
            return

        new_name = self.role_name_var.get().strip()
        if not new_name:
            msg = messagebox.showwarning("警告", "角色名称不能为空", parent=self.window)
            self.window.attributes('-topmost', 1)
            msg.attributes('-topmost', 1)
            self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])
            return

        # 检查角色名是否重复
        if new_name != self.current_role:
            conflicts = self._check_role_name_conflict(new_name)
            if conflicts:
                messagebox.showerror("错误",       
                                    f"角色名称 '{new_name}' 已存在于以下分类中：\n" +
                                    "\n".join(conflicts) +
                                    "\n请使用不同的角色名称", parent=self.window)
                return

        # 获取编辑框中的内容
        content = self.role_edit_text.get("1.0", "end-1c")
        
        # 检查第一行是否包含角色名称
        lines = content.split('\n')
        if lines and (':' in lines[0] or '：' in lines[0]):
            # 如果角色名称已更改，更新第一行
            first_line = lines[0]
            old_name = first_line.split(':')[0].split('：')[0].strip()
            if old_name != new_name:
                if ':' in first_line:
                    lines[0] = f"{new_name}:{first_line.split(':', 1)[1]}"
                else:
                    lines[0] = f"{new_name}：{first_line.split('：', 1)[1]}"
                content = '\n'.join(lines)
        else:
            # 如果没有合适的第一行，添加角色名称
            content = f"{new_name}：\n{content}"
        
        save_path = os.path.join(self.save_path, self.selected_category,
                                 f"{new_name}.txt")

        try:
            # 直接保存文本内容
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            # 如果修改了角色名，删除旧文件
            if new_name != self.current_role:
                old_path = os.path.join(self.save_path, self.selected_category,
                                        f"{self.current_role}.txt")
                if os.path.exists(old_path):
                    os.remove(old_path)

            # 更新显示
            self.current_role = new_name
            self.show_category(self.selected_category)
            self.show_role(new_name)  # 刷新角色显示
            messagebox.showinfo("成功", "角色已保存", parent=self.window)
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{str(e)}", parent=self.window)

    def _rename_role_file(self):
        """修改角色名称"""
        old_name = self.current_role
        new_name = self.role_name_var.get().strip()

        if not old_name or not new_name:
            return

        # 处理中英文冒号
        for colon in [":", "："]:
            old_name = old_name.split(colon)[0]
            new_name = new_name.split(colon)[0]

        # 如果角色名没有改变，直接返回
        if new_name == old_name:
            return

        # 检查角色名是否重复
        conflicts = self._check_role_name_conflict(new_name)
        if conflicts:
            messagebox.showerror("错误",
                                f"角色名称 '{new_name}' 已存在于以下分类中：\n" +
                                "\n".join(conflicts) +
                                "\n请使用不同的角色名称", parent=self.window)
            return

        try:
            # 如果是"全部"分类，需要找到实际存储的分类
            if self.selected_category == "全部":
                # 首先检查"全部"目录下是否有该角色文件
                all_path = os.path.join(
                    self.save_path, "全部", f"{old_name}.txt")
                if os.path.exists(all_path):
                    # 如果"全部"目录下有文件，则直接操作
                    actual_category = "全部"
                else:
                    # 遍历所有分类查找实际存储位置
                    actual_category = None
                    for category in os.listdir(self.save_path):
                        if category == "全部":
                            continue
                        test_path = os.path.join(
                            self.save_path, category, f"{old_name}.txt")
                        if os.path.exists(test_path):
                            actual_category = category
                            break

                    if not actual_category:
                        raise FileNotFoundError(
                            f"找不到角色 {old_name} 的实际存储位置")
            else:
                actual_category = self.selected_category

            # 读取旧文件内容并更新角色名
            old_path = os.path.join(
                self.save_path, actual_category, f"{old_name}.txt")
            with open(old_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 获取第一行内容
            first_line = content.split('\n')[0].strip()
            # 提取内容中的角色名
            content_role_name = first_line.split('：')[0].split(':')[0].strip()
            # 如果内容中的角色名与旧文件名不同，更新内容
            if content_role_name != old_name:
                content = content.replace(
                    f"{content_role_name}：", f"{new_name}：", 1)
            else:
                content = content.replace(f"{old_name}：", f"{new_name}：", 1)

            # 写入新文件
            new_path = os.path.join(
                self.save_path, actual_category, f"{new_name}.txt")
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # 删除旧文件
            os.remove(old_path)

            # 处理"全部"目录
            all_old_path = os.path.join(
                self.save_path, "全部", f"{old_name}.txt")
            all_new_path = os.path.join(
                self.save_path, "全部", f"{new_name}.txt")

            # 如果"全部"目录存在旧文件
            if os.path.exists(all_old_path):
                try:
                    # 更新"全部"目录中的文件内容
                    with open(all_old_path, 'r', encoding='utf-8') as f:
                        all_content = f.read()
                    updated_all_content = all_content.replace(
                        f"{old_name}：", f"{new_name}：", 1)

                    # 写入新文件
                    with open(all_new_path, 'w', encoding='utf-8') as f:
                        f.write(updated_all_content)

                    # 删除旧文件
                    os.remove(all_old_path)
                except Exception as e:
                    messagebox.showerror("错误", f"更新全部目录失败: {str(e)}", parent=self.window)
                    # 回滚重命名操作
                    os.rename(new_path, old_path)
                    return

            # 刷新显示
            self.current_role = new_name
            self.show_category(self.selected_category)
            self.role_name_var.set(new_name)
            self.show_role(new_name)  # 刷新角色显示区域

        except Exception as e:
            msg = messagebox.showerror("错误", f"重命名失败：{str(e)}", parent=self.window)
            self.window.attributes('-topmost', 1)
            msg.attributes('-topmost', 1)
            self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])

    def _create_new_role(self, category, weight_name="背景角色", weight_range="1-20"):
        """在指定分类创建新角色
        
        Args:
            category: 角色分类
            weight_name: 权重名称
            weight_range: 权重范围
        """
        # 确保分类目录存在
        role_dir = os.path.join(self.save_path, category)
        os.makedirs(role_dir, exist_ok=True)
        
        base_name_template = "未命名"
        base_name = base_name_template
        counter = 1

        # 生成唯一文件名，确保在整个角色库中唯一
        while self._check_role_name_conflict(base_name):
            base_name = f"{base_name_template}{counter}"
            counter += 1

        # 根据权重等级生成对应的角色状态字段
        content = f"{base_name}：\n"
        
        # 基础信息（所有权重等级都有）
        content += f"- 称谓：{base_name}（正式名）\n"
        content += f"- 角色权重：{weight_range}（定位：{weight_name}）\n"
        
        # 关键事件记录（所有权重等级都有）
        content += "关键事件记录：\n"
        content += "- 第1章：[事件类型] 简要说明（如初次登场、展示技能、埋下伏笔）\n"
        
        # 单元角色及以上权重等级（21-100）
        if weight_name != "背景角色":
            content += "势力特征：\n"
            content += "- 所属组织/势力：\n"
            content += "- 身份：\n"
            content += "- 外貌特征：\n"
            content += "- 性格：\n"
            content += "生命状态：\n"
            content += "- 身体状态：\n"
            content += "- 心理状态：\n"
            content += "- 长期影响：\n"
        
        # 次要配角及以上权重等级（41-100）
        if weight_name in ["次要配角", "关键角色", "核心配角", "主角级"]:
            content += "持有物品：\n"
            content += "- 物品名称：（功能简述）\n"
            content += "技术能力：\n"
            content += "- 技能名称：（功能描述）\n"
        
        # 关键角色及以上权重等级（61-100）
        if weight_name in ["关键角色", "核心配角", "主角级"]:
            content += "位置轨迹：\n"
            content += "- 场景名称（所在章节：第1章）（事件：简要说明）（同行人物：角色A、角色B）（目的：XXX）\n"
            content += "关系网：\n"
            content += "- 角色名: 关系类型, 关系强度[低/中/高], 互动频率[稀少/普通/频繁]\n"
        
        # 核心配角及以上权重等级（81-100）
        if weight_name in ["核心配角", "主角级"]:
            content += "行为模式 / 决策偏好：\n"
            content += "- 行为模式：\n"
            content += "- 决策偏好：\n"
            content += "语言风格 / 对话关键词：\n"
            content += "- 语言风格：\n"
            content += "- 关键词：\n"
            content += "情感线状态：\n"
            content += "- 情感线状态：起点阶段描述（如初识、敌对、无感、暗恋萌芽）\n"
            content += "- 感情进展标记：【好感度：XX%】【羁绊等级：C/B】\n"

        with open(os.path.join(role_dir, f"{base_name}.txt"), "w", encoding="utf-8") as f:
            f.write(content)

        # 刷新分类列表
        categories = self._get_all_categories()
        self.category_combobox.configure(values=categories)
        
        # 刷新分类按钮区域
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        # 添加分类按钮
        for cat in categories:
            if cat != "全部":  # 全部按钮已经固定在左侧
                btn = ctk.CTkButton(
                    self.scroll_frame,
                    text=cat,
                    width=80,
                    font=("Microsoft YaHei", 14),
                    command=lambda c=cat: self.show_category(c)
                )
                btn.pack(side="left", padx=2)
                # 添加右键菜单
                btn.bind("<Button-3>", lambda event, c=cat: self._show_category_menu(event, c))
        
        # 刷新显示
        self.show_category(category)
        self.role_name_var.set(base_name)
        self.current_role = base_name
        
        # 显示角色内容
        self.show_role(base_name)

    def create_category_bar(self):
        """创建分类按钮区"""
        category_frame = ctk.CTkFrame(self.window)
        category_frame.pack(fill="x", padx=10, pady=5)

        # 操作提示
        ctk.CTkLabel(category_frame,
                     text="右键分类名即可重命名",
                     font=DEFAULT_FONT,
                     text_color="gray").pack(side="top", anchor="w", padx=5)

        # 固定按钮
        ctk.CTkButton(category_frame, text="全部", width=50,
                      font=("Microsoft YaHei", 14),
                      command=lambda: self.show_category("全部")).pack(side="left", padx=2)

        # 滚动分类区
        self.scroll_frame = ctk.CTkScrollableFrame(
            category_frame, orientation="horizontal", height=30)
        self.scroll_frame.pack(side="left", fill="x", expand=True, padx=5)

        # 操作按钮
        ctk.CTkButton(category_frame, text="新增", width=50,
                      command=self.add_category, font=DEFAULT_FONT).pack(side="right", padx=2)
        ctk.CTkButton(category_frame, text="删除", width=50,
                      command=self.delete_category, font=DEFAULT_FONT).pack(side="right", padx=2)

        self.load_categories()

    def center_window(self):
        """窗口居中"""
        self.window.update_idletasks()
        parent_x = self.master.winfo_x()
        parent_y = self.master.winfo_y()
        parent_width = self.master.winfo_width()
        parent_height = self.master.winfo_height()
        win_width = 1200
        win_height = 800
        x = parent_x + (parent_width - win_width) // 2
        y = parent_y + (parent_height - win_height) // 2
        self.window.geometry(f"{win_width}x{win_height}+{x}+{y}")

    def load_categories(self):
        """加载分类按钮"""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        categories = [d for d in os.listdir(self.save_path)
                      if os.path.isdir(os.path.join(self.save_path, d)) and d != "全部"]

        for category in categories:
            btn = ctk.CTkButton(self.scroll_frame, text=category, width=80, font=DEFAULT_FONT)
            btn.bind("<Button-1>", lambda e, c=category: self.show_category(c))
            btn.bind("<Button-3>", lambda e, c=category: self.rename_category(c))
            btn.pack(side="left", padx=2)

    def _create_category_directory(self, category_name):
        """创建分类目录"""
        new_dir = os.path.join(self.save_path, category_name)
        if not os.path.exists(new_dir):
            os.makedirs(new_dir)
        return new_dir

    def add_category(self):
        """新增分类"""
        self._create_category_directory("未命名")
        self.load_categories()
        # 刷新分类选择下拉框
        self.category_combobox.configure(values=self._get_all_categories())

    def delete_category(self):
        """删除分类对话框"""
        if not self.window.winfo_exists():
            return

        del_window = ctk.CTkToplevel(self.window)
        del_window.title("删除分类")
        del_window.transient(self.window)
        del_window.grab_set()
        del_window.attributes('-topmost', 1)

        # 居中计算
        parent_x = self.window.winfo_x()
        parent_y = self.window.winfo_y()
        parent_width = self.window.winfo_width()
        parent_height = self.window.winfo_height()
        del_window.geometry(
            f"300x400+{parent_x + (parent_width-300)//2}+{parent_y + (parent_height-400)//2}")

        scroll_frame = ctk.CTkScrollableFrame(del_window)
        scroll_frame.pack(fill="both", expand=True)

        categories = [d for d in os.listdir(self.save_path)
                      if os.path.isdir(os.path.join(self.save_path, d)) and d != "全部"]
        self.selected_del = []

        for cat in categories:
            var = tk.BooleanVar()
            chk = ctk.CTkCheckBox(scroll_frame, text=cat, variable=var, font=DEFAULT_FONT)
            chk.pack(anchor="w")
            self.selected_del.append((cat, var))

        # 操作按钮
        btn_frame = ctk.CTkFrame(del_window)
        btn_frame.pack(fill="x", pady=5)

        ctk.CTkButton(btn_frame, text="删除选中",
                      command=lambda: self.confirm_delete(del_window), font=DEFAULT_FONT).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消",
                      command=del_window.destroy, font=DEFAULT_FONT).pack(side="right", padx=5)

        self.category_combobox.configure(values=self._get_all_categories())
        self.category_combobox.set("全部")

    def confirm_delete(self, original_window):
        """确认删除操作"""
        selected = [item[0] for item in self.selected_del if item[1].get()]
        if not selected:
            msg = messagebox.showwarning("警告", "请至少选择一个分类", parent=self.window)
            self.window.attributes('-topmost', 1)
            self.window.after(200, lambda: self.window.attributes('-topmost', 0))
            return

        # 创建选择窗口时添加前置设置
        choice_window = ctk.CTkToplevel(self.window)
        choice_window.transient(self.window)  # 设置为子窗口
        choice_window.grab_set()  # 模态窗口
        choice_window.lift()  # 置顶
        choice_window.attributes('-topmost', 1)  # 强制置顶

        # 添加居中计算
        choice_window.update_idletasks()
        c_width = choice_window.winfo_width()
        c_height = choice_window.winfo_height()
        x = self.window.winfo_x() + (self.window.winfo_width() - c_width) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - c_height) // 2
        choice_window.geometry(f"+{x}+{y}")

        ctk.CTkLabel(choice_window, text="请选择删除方式：", font=DEFAULT_FONT).pack(pady=10)
        btn_frame = ctk.CTkFrame(choice_window)
        btn_frame.pack(pady=10)

        def perform_delete(mode):
            all_dir = os.path.join(self.save_path, "全部")
            for cat in selected:
                cat_path = os.path.join(self.save_path, cat)
                if mode == "move":
                    for role_file in os.listdir(cat_path):
                        if role_file.endswith(".txt"):
                            src = os.path.join(cat_path, role_file)
                            dst = os.path.join(all_dir, role_file)
                            try:
                                shutil.move(src, dst)
                            except:
                                os.remove(dst)
                                shutil.move(src, dst)
                shutil.rmtree(cat_path)
            self.load_categories()
            # 刷新分类选择下拉框
            self.category_combobox.configure(values=self._get_all_categories())
            original_window.destroy()
            choice_window.destroy()

        ctk.CTkButton(btn_frame, text="全部删除",
                      command=lambda: perform_delete("all"), font=DEFAULT_FONT).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="移动角色",
                      command=lambda: perform_delete("move"), font=DEFAULT_FONT).pack(side="left", padx=5)

    def count_roles(self, categories):
        """统计角色数量"""
        count = 0
        for cat in categories:
            cat_path = os.path.join(self.save_path, cat)
            count += len([f for f in os.listdir(cat_path) if f.endswith(".txt")])
        return count

    def show_category(self, category):
        """显示分类内容"""
        self.selected_category = category
        self.category_combobox.set(category)
        for widget in self.role_list_frame.winfo_children():
            widget.destroy()

        # 如果是"全部"分类，显示所有角色
        if category == "全部":
            # 获取所有分类目录
            categories = [d for d in os.listdir(self.save_path)
                          
                          if os.path.isdir(os.path.join(self.save_path, d))]
            # 用于去重的角色集合
            unique_roles = set()

            for cat in categories:
                role_dir = os.path.join(self.save_path, cat)
                try:
                    for role_file in os.listdir(role_dir):
                        if role_file.endswith(".txt"):
                            role_name = os.path.splitext(role_file)[0]
                            # 去重
                            if role_name not in unique_roles:
                                unique_roles.add(role_name)
                                btn = ctk.CTkButton(
                                    self.role_list_frame,
                                    text=role_name,
                                    command=lambda r=role_name: self.show_role(r),
                                    font=DEFAULT_FONT
                                )
                                btn.pack(fill="x", pady=2)
                except FileNotFoundError:
                    continue
        else:
            # 普通分类显示
            role_dir = os.path.join(self.save_path, category)
            try:
                for role_file in os.listdir(role_dir):
                    if role_file.endswith(".txt"):
                        role_name = os.path.splitext(role_file)[0]
                        btn = ctk.CTkButton(
                            self.role_list_frame,
                            text=role_name,
                            command=lambda r=role_name: self.show_role(r),
                            font=DEFAULT_FONT
                        )
                        btn.pack(fill="x", pady=2)
            except FileNotFoundError:
                messagebox.showerror("错误", "分类目录不存在", parent=self.window)

    def show_role(self, role_name):
        """显示角色详细信息（支持UTF-8/ANSI编码）"""
        try:
            # 清空编辑区
            self.role_edit_text.delete('1.0', tk.END)

            # 更新角色名称显示
            self.current_role = role_name.split(":")[0].split("：")[0]
            self.role_name_var.set(self.current_role)

            # 查找角色实际所在目录
            if self.selected_category == "全部":
                # 首先检查"全部"目录下是否有该角色文件
                all_path = os.path.join(
                    self.save_path, "全部", f"{role_name}.txt")
                if os.path.exists(all_path):
                    file_path = all_path
                    actual_category = "全部"
                else:
                    # 如果"全部"目录下没有，则遍历其他分类查找
                    file_path = None
                    for cat in os.listdir(self.save_path):
                        if cat == "全部":
                            continue
                        test_path = os.path.join(
                            self.save_path, cat, f"{role_name}.txt")
                        if os.path.exists(test_path):
                            file_path = test_path
                            actual_category = cat
                            # 保存实际分类
                            self.actual_category = cat
                            break
                    if file_path is None:
                        raise FileNotFoundError(f"找不到角色文件：{role_name}")

                # 只更新分类选择框的显示值，不改变当前选中的分类
                self.category_combobox.set(actual_category)
            else:
                # 普通分类直接使用当前路径
                file_path = os.path.join(
                    self.save_path, self.selected_category, f"{role_name}.txt")

            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 显示原始文件内容到编辑框
            self.role_edit_text.insert(tk.END, content)

        except FileNotFoundError as e:
            messagebox.showerror("错误", f"文件不存在：{e}", parent=self.window)
        except UnicodeDecodeError:
            # 尝试使用ANSI编码读取
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
                self.role_edit_text.insert(tk.END, content)
            except Exception as e:
                messagebox.showerror("错误", f"读取文件失败：{e}", parent=self.window)
        except Exception as e:
            messagebox.showerror("错误", f"读取文件失败：{e}", parent=self.window)

    def _create_attribute_section(self, attr_name, items):
        """创建单个属性的编辑区域"""

        # 属性块 (attribute_block)
        attribute_block = ctk.CTkFrame(self.attributes_frame)
        attribute_block.pack(fill="x", pady=5)
        attribute_block.attribute_name = attr_name  # 存储属性名称
        attribute_block.grid_columnconfigure(1, weight=1)  # 设置第二列权重
        attribute_block.grid_columnconfigure(1, weight=1)  # 设置第二列权重

        # 属性名称标签
        label = ctk.CTkLabel(attribute_block, text=attr_name, font=DEFAULT_FONT)
        label.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)

        # 第一个条目和“增加”按钮的容器
        first_item_frame = ctk.CTkFrame(attribute_block)
        first_item_frame.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        first_item_frame.grid_columnconfigure(0, weight=1)

        # 第一个条目输入框
        first_entry = ctk.CTkEntry(first_item_frame, font=DEFAULT_FONT)
        first_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5), ipadx=5, ipady=3)
        if items:
            first_entry.insert(0, items[0])  # 填充第一个条目的内容

        # “增加”按钮容器
        add_button_frame = ctk.CTkFrame(first_item_frame, fg_color="transparent")
        add_button_frame.grid(row=0, column=1, sticky="e", padx=(5, 0))

        # “增加”按钮
        add_button = ctk.CTkButton(
            add_button_frame,
            text="+",
            width=30,
            command=lambda: self._add_item(attr_name),
            font=DEFAULT_FONT
        )
        add_button.grid(row=0, column=0)

        # 创建剩余的条目（如果有）
        for i, item_text in enumerate(items[1:]):
            self._add_item(attr_name, item_text)  # 传入初始文本

    def _add_item(self, attr_name, initial_text=""):
        """为指定属性添加一个新条目"""

        # 找到对应的 attribute_block
        attribute_block = None
        for block in self.attributes_frame.winfo_children():
            if isinstance(block, ctk.CTkFrame) and block.attribute_name == attr_name:
                attribute_block = block
                break

        if attribute_block is None:
            return

        # 计算新条目的行号
        row_number = 0
        for child in attribute_block.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                row_number += 1

        # 条目容器
        item_frame = ctk.CTkFrame(attribute_block)
        item_frame.grid(row=row_number, column=1, sticky="ew", padx=5, pady=2)
        item_frame.grid_columnconfigure(0, weight=1)

        # 条目输入框
        new_entry = ctk.CTkEntry(item_frame, font=DEFAULT_FONT)
        new_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5), ipadx=5, ipady=3)
        new_entry.insert(0, initial_text)  # 设置初始文本

        # 删除按钮容器
        del_button_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
        del_button_frame.grid(row=0, column=1, sticky="e", padx=(5, 0))
        # “删除”按钮
        del_button = ctk.CTkButton(
            del_button_frame,
            text="-",
            width=30,
            command=lambda f=item_frame: self._remove_item(f, attr_name),
            font=DEFAULT_FONT
        )
        del_button.grid(row=0, column=0)


    def _remove_item(self, item_frame, attr_name):
        """移除指定的条目，并重新调整布局"""

        # 找到对应的 attribute_block
        attribute_block = None
        for block in self.attributes_frame.winfo_children():
            if isinstance(block, ctk.CTkFrame) and block.attribute_name == attr_name:
                attribute_block = block
                break

        if attribute_block is None:
            return

        # 确认不是删除带"+"号的原始条目
        for child in item_frame.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                for btn in child.winfo_children():
                    if isinstance(btn, ctk.CTkButton) and btn.cget("text") == "+":
                        msg = messagebox.showinfo("提示", "不能删除带'+'号的原始条目", parent=self.window)
                        self.window.attributes('-topmost', 1)
                        msg.attributes('-topmost', 1)
                        self.window.after(200, lambda: [self.window.attributes('-topmost', 0), msg.attributes('-topmost', 0)])
                        return

        # 移除条目
        item_frame.destroy()

        # 重新调整剩余条目的行号
        current_row = 0
        for child in attribute_block.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                if current_row == 0:  # 找到属性标签
                    current_row += 1
                    continue
                ctk.CTkFrame.grid_configure(child, row=current_row)
                current_row += 1

    def _read_file_with_fallback_encoding(self, file_path):
        """带编码回退的文件读取，支持UTF-8、GBK(ANSI)和BOM"""
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'latin1']  # 增加更多编码支持

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                    # 检查内容是否包含乱码
                    if any(ord(char) > 127 and not char.isprintable() for char in content):
                        continue  # 如果包含乱码，尝试下一个编码
                    return content.splitlines(), encoding
            except UnicodeDecodeError:
                continue
            except Exception as e:
                raise

        # 如果所有编码尝试都失败，尝试二进制读取
        try:
            with open(file_path, "rb") as f:
                raw_data = f.read()
                # 尝试UTF-8解码
                try:
                    return raw_data.decode('utf-8').splitlines(), 'utf-8'
                except UnicodeDecodeError:
                    # 尝试GBK解码
                    try:
                        return raw_data.decode('gbk').splitlines(), 'gbk'
                    except UnicodeDecodeError:
                        # 最后尝试latin1解码
                        return raw_data.decode('latin1').splitlines(), 'latin1'
        except Exception as e:
            raise ValueError(f"无法识别的文件编码：{file_path}")

    def rename_category(self, old_name):
        """分类重命名（带居中功能）"""
        new_name = None  # 初始化变量

        # 创建对话框窗口
        dialog = ctk.CTkToplevel(self.window)
        dialog.title("重命名分类")
        dialog.transient(self.window)
        dialog.grab_set()

        # 窗口内容
        content_frame = ctk.CTkFrame(dialog)
        content_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 顶部提示
        ctk.CTkLabel(content_frame, text=f"当前分类：{old_name}", 
                    font=DEFAULT_FONT).pack(pady=(10, 5))

        # 输入框
        input_frame = ctk.CTkFrame(content_frame)
        input_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(input_frame, text="新名称：", 
                    font=DEFAULT_FONT).pack(side="left", padx=5)
        name_var = tk.StringVar()
        name_entry = ctk.CTkEntry(input_frame, textvariable=name_var, width=150, font=DEFAULT_FONT)
        name_entry.pack(side="left", padx=5)

        # 按钮区
        button_frame = ctk.CTkFrame(content_frame)
        button_frame.pack(fill="x", pady=(10, 5))

        def confirm_rename():
            nonlocal new_name  # 引用外部变量
            new_name = name_var.get().strip()
            if not new_name:
                messagebox.showwarning("警告", "分类名称不能为空", parent=self.window)
                return
            if new_name == old_name:
                dialog.destroy()
                return
            if os.path.exists(os.path.join(self.save_path, new_name)):
                messagebox.showerror("错误", "分类名称已存在", parent=self.window)
                return

            try:
                os.rename(os.path.join(self.save_path, old_name),
                          os.path.join(self.save_path, new_name))
                self.load_categories()
                # 更新分类选择框
                self.category_combobox.configure(
                    values=self._get_all_categories())
                self.category_combobox.set(new_name)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"重命名失败：{str(e)}", parent=self.window)

        ctk.CTkButton(button_frame, text="确认",
                      command=confirm_rename, font=DEFAULT_FONT).pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="取消",
                      command=dialog.destroy, font=DEFAULT_FONT).pack(side="right", padx=10)

        # 窗口居中
        dialog.update_idletasks()
        d_width = dialog.winfo_width()
        d_height = dialog.winfo_height()
        x = self.window.winfo_x() + (self.window.winfo_width() - d_width) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - d_height) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.attributes('-topmost', 1)

    def on_close(self):
        """关闭窗口"""
        self.window.destroy()


