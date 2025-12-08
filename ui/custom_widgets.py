# ui/custom_widgets.py
# -*- coding: utf-8 -*-
import customtkinter as ctk

class CustomComboBox(ctk.CTkFrame):
    """
    一个自定义的组合框，旨在解决 CTkComboBox 的定位和大小调整问题。
    它使用一个 CTkToplevel 窗口来显示下拉列表。
    """
    def __init__(self, master, variable=None, values=None, command=None, **kwargs):
        # 从 kwargs 中提取 entry 和 button 的特定配置
        entry_kwargs = {k.replace('entry_', ''): v for k, v in kwargs.items() if k.startswith('entry_')}
        button_kwargs = {k.replace('button_', ''): v for k, v in kwargs.items() if k.startswith('button_')}
        dropdown_kwargs = {k.replace('dropdown_', ''): v for k, v in kwargs.items() if k.startswith('dropdown_')}
        # 移除这些特定配置，以免传递给主 Frame
        for key in list(kwargs.keys()):
            if key.startswith(('entry_', 'button_', 'dropdown_')):
                del kwargs[key]

        self._font = kwargs.pop('font', None)

        super().__init__(master, **kwargs)

        self.variable = variable if variable else ctk.StringVar()
        self._values = values if values is not None else []
        self._command = command
        self._dropdown_toplevel = None
        self._just_opened = False

        # 配置主框架
        self.configure(fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        # 创建输入框和按钮
        self._entry = ctk.CTkEntry(self, textvariable=self.variable, font=self._font, **entry_kwargs)
        self._entry.grid(row=0, column=0, sticky="ew")

        self._button = ctk.CTkButton(self, text="▼", width=28, command=self._toggle_dropdown, **button_kwargs)
        self._button.grid(row=0, column=1, padx=(2, 0))

        # 存储下拉菜单的配置
        self._dropdown_fg_color = dropdown_kwargs.get("fg_color", None)
        self._dropdown_hover_color = dropdown_kwargs.get("hover_color", None)
        self._dropdown_text_color = dropdown_kwargs.get("text_color", None)

    def _toggle_dropdown(self):
        if self._dropdown_toplevel and self._dropdown_toplevel.winfo_exists():
            self._close_dropdown()
        else:
            self.after(10, self._open_dropdown) # 稍微延迟以确保主窗口更新

    def _open_dropdown(self):
        # --- 计算几何信息 ---
        self.update_idletasks() # 确保获取最新的几何信息
        entry_x = self._entry.winfo_rootx()
        entry_y = self._entry.winfo_rooty()
        entry_height = self._entry.winfo_height()
        entry_width = self._entry.winfo_width()
        
        # 整个组合框的宽度（包括按钮）
        total_width = entry_width + self._button.winfo_width() + 2 # 2 is padx

        # --- 计算下拉菜单的高度 ---
        item_height = 30  # 每个项目的高度
        visible_items = len(self._values) if self._values else 1
        
        # 初始高度
        dropdown_height = visible_items * item_height + 10 # 加一点 padding

        # --- 高度限制 ---
        # 1. 最大高度不超过 15 个项目
        max_height_by_items = 15 * item_height + 15
        dropdown_height = min(dropdown_height, max_height_by_items)

        # 2. 最大高度不能超出主窗口
        main_window = self.winfo_toplevel()
        main_window_height = main_window.winfo_height()
        main_window_rooty = main_window.winfo_rooty()
        
        # 下拉菜单底部相对于屏幕的位置
        dropdown_bottom_y = entry_y + entry_height + dropdown_height
        # 主窗口底部相对于屏幕的位置
        main_window_bottom_y = main_window_rooty + main_window_height
        
        # 如果下拉菜单超出了主窗口，则调整其高度
        if dropdown_bottom_y > main_window_bottom_y:
            new_height = main_window_bottom_y - (entry_y + entry_height) - 10 # 10px buffer
            dropdown_height = max(new_height, item_height + 10) # 至少显示一项

        # --- 创建 Toplevel 窗口 ---
        self._dropdown_toplevel = ctk.CTkToplevel(self)
        self._dropdown_toplevel.overrideredirect(True) # 无边框窗口
        self._dropdown_toplevel.geometry(f"{total_width}x{int(dropdown_height)}+{entry_x}+{entry_y + entry_height}")
        
        # --- 创建可滚动框架 ---
        scroll_frame = ctk.CTkScrollableFrame(self._dropdown_toplevel, label_text="", fg_color=self._dropdown_fg_color)
        scroll_frame.pack(expand=True, fill="both")

        # --- 填充项目 ---
        if not self._values or self._values == [""]:
            label = ctk.CTkLabel(scroll_frame, text="无可用模型", text_color=self._dropdown_text_color, font=self._font)
            label.pack(pady=5, padx=10, fill="x")
        else:
            for value in self._values:
                btn = ctk.CTkButton(
                    scroll_frame,
                    text=value,
                    text_color=self._dropdown_text_color,
                    fg_color="transparent",
                    hover_color=self._dropdown_hover_color,
                    anchor="w",
                    command=lambda v=value: self._select_item(v),
                    font=self._font
                )
                btn.pack(fill="x", padx=5)
        
        # --- 绑定事件 ---
        self._dropdown_toplevel.bind("<FocusOut>", self._close_dropdown, add="+")
        self._dropdown_toplevel.bind("<Escape>", self._close_dropdown, add="+")
        self._dropdown_toplevel.focus_set()
        self._just_opened = True
        self.after(100, self._arm_dropdown) # After 100ms, allow closing by FocusOut

    def _arm_dropdown(self):
        self._just_opened = False

    def _select_item(self, value):
        self.variable.set(value)
        if self._command:
            self._command(value)
        self._close_dropdown()

    def _close_dropdown(self, event=None):
        if self._just_opened:
            return # Ignore the first FocusOut event right after opening
        if self._dropdown_toplevel:
            self._dropdown_toplevel.destroy()
            self._dropdown_toplevel = None

    def configure(self, **kwargs):
        if "values" in kwargs:
            self._values = kwargs.pop("values")
            # 如果下拉菜单是打开的，则刷新它
            if self._dropdown_toplevel and self._dropdown_toplevel.winfo_exists():
                self._close_dropdown()
                self.after(10, self._open_dropdown)
        
        if "variable" in kwargs:
            self.variable = kwargs.pop("variable")

        if "state" in kwargs:
            new_state = kwargs.pop("state")
            self._entry.configure(state=new_state)
            self._button.configure(state=new_state)

        super().configure(**kwargs)

    def get(self):
        return self.variable.get()

    def set(self, value):
        self.variable.set(value)
