# ui/helpers.py
# -*- coding: utf-8 -*-
import logging
import traceback
import customtkinter as ctk
import platform
import tkinter as tk # 导入 tkinter

def log_error(message: str):
    logging.error(f"{message}\n{traceback.format_exc()}")

class CustomDropdownMenu(ctk.CTkToplevel):
    def __init__(self, master, combobox_instance, values, command, font, fg_color, hover_color, text_color):
        super().__init__(master)
        self.overrideredirect(True) # 移除窗口边框
        self.attributes("-topmost", True) # 保持在最上层
        self.withdraw() # 初始隐藏

        self.combobox_instance = combobox_instance
        self.values = values
        self.command = command
        self.font = font
        self.fg_color = fg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.scroll_speed_multiplier = 25 # 滚轮速度乘数，增加到25

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.scrollable_frame = ctk.CTkScrollableFrame(self, fg_color=self.fg_color)
        self.scrollable_frame.grid(row=0, column=0, sticky="nsew")
        self.scrollable_frame.grid_columnconfigure(0, weight=1)

        self.buttons = []
        for i, value in enumerate(self.values):
            button = ctk.CTkButton(
                self.scrollable_frame,
                text=value,
                command=lambda v=value: self._on_select(v),
                font=self.font,
                fg_color="transparent",
                hover_color=self.hover_color,
                text_color=self.text_color,
                anchor="w"
            )
            button.grid(row=i, column=0, sticky="ew", padx=2, pady=2)
            self.buttons.append(button)
        
        # 绑定鼠标滚轮事件到整个下拉菜单
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        for button in self.buttons:
            button.bind("<MouseWheel>", self._on_mouse_wheel)

        if platform.system() != "Windows" and platform.system() != "Darwin":
            self.bind("<Button-4>", self._on_mouse_wheel)
            self.bind("<Button-5>", self._on_mouse_wheel)
            self.scrollable_frame.bind("<Button-4>", self._on_mouse_wheel)
            self.scrollable_frame.bind("<Button-5>", self._on_mouse_wheel)
            for button in self.buttons:
                button.bind("<Button-4>", self._on_mouse_wheel)
                button.bind("<Button-5>", self._on_mouse_wheel)

        # 绑定点击外部关闭菜单
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Escape>", lambda event: self.hide())
        # 在初始化时绑定一次，并在 _on_master_click 中处理可见性
        self.combobox_instance.master.bind("<Button-1>", self._on_master_click, add="+")


    def _on_select(self, value):
        self.combobox_instance.set(value)
        if self.command:
            self.command(value)
        self.hide()

    def _on_mouse_wheel(self, event):
        if not self.buttons: # 如果没有按钮，则不滚动
            return

        canvas = self.scrollable_frame._parent_canvas
        
        if platform.system() == "Windows":
            scroll_amount = int(-1 * (event.delta / 120)) * self.scroll_speed_multiplier
        elif platform.system() == "Darwin": # macOS
            scroll_amount = event.delta * self.scroll_speed_multiplier
        else: # Linux
            if event.num == 4:
                scroll_amount = -1 * self.scroll_speed_multiplier
            elif event.num == 5:
                scroll_amount = 1 * self.scroll_speed_multiplier
            else:
                scroll_amount = 0
        
        canvas.yview_scroll(scroll_amount, "units") # 直接使用 "units" 滚动
        
        return "break" # 阻止事件传播到父窗口

    def _on_focus_out(self, event):
        # 检查焦点是否还在下拉菜单或其子组件上
        if not self.winfo_exists():
            return
        focused_widget = self.focus_get()
        # 如果没有焦点，或者焦点不在下拉菜单或其子组件上，也不在 combobox 自身上，则隐藏菜单
        if focused_widget is None or \
           (focused_widget != self.combobox_instance and \
            not self.winfo_containing(focused_widget.winfo_x(), focused_widget.winfo_y()) == self):
            self.hide()

    def _on_master_click(self, event):
        # 只有当菜单可见时才处理点击事件
        if self.winfo_exists() and self.winfo_ismapped():
            # 获取下拉菜单的边界
            x1, y1, x2, y2 = self.winfo_x(), self.winfo_y(), self.winfo_x() + self.winfo_width(), self.winfo_y() + self.winfo_height()
            # 获取 combobox 的边界
            cb_x1, cb_y1, cb_x2, cb_y2 = self.combobox_instance.winfo_rootx(), self.combobox_instance.winfo_rooty(), \
                                         self.combobox_instance.winfo_rootx() + self.combobox_instance.winfo_width(), \
                                         self.combobox_instance.winfo_rooty() + self.combobox_instance.winfo_height()

            # 如果点击不在下拉菜单内部，也不在 combobox 内部，则隐藏菜单
            if not (x1 <= event.x_root <= x2 and y1 <= event.y_root <= y2) and \
               not (cb_x1 <= event.x_root <= cb_x2 and cb_y1 <= event.y_root <= cb_y2):
                self.hide()

    def show(self, x, y, width):
        self.update_idletasks() # 确保所有组件都已渲染，以便获取正确尺寸

        # 计算每个按钮的近似高度
        if self.buttons:
            button_height = self.buttons[0].winfo_height()
        else:
            button_height = self.font.cget("size") + 4 # 估算高度

        # 限制最大显示条目数为 15
        max_display_items = 15
        # 计算显示 max_display_items 个条目所需的总高度
        limited_content_height = min(len(self.values), max_display_items) * button_height + \
                                 (self.scrollable_frame.winfo_reqheight() - self.scrollable_frame._parent_canvas.winfo_reqheight()) # 加上边框和内边距

        # 获取屏幕高度
        screen_height = self.winfo_screenheight()
        
        # 计算下拉菜单的理想底部位置
        ideal_bottom_y = y + limited_content_height

        final_y = y
        final_height = limited_content_height

        # 如果下拉菜单超出屏幕底部
        if ideal_bottom_y > screen_height:
            # 计算 combobox 到屏幕顶部的可用空间
            space_above_combobox = self.combobox_instance.winfo_rooty()
            # 计算 combobox 到屏幕底部的可用空间
            space_below_combobox = screen_height - (self.combobox_instance.winfo_rooty() + self.combobox_instance.winfo_height())

            if space_above_combobox >= limited_content_height: # 如果上方空间足够显示整个菜单
                final_y = self.combobox_instance.winfo_rooty() - limited_content_height # 向上移动到combobox上方
            elif space_below_combobox >= limited_content_height: # 如果下方空间足够显示整个菜单
                final_y = y # 保持在combobox下方
            else: # 上下空间都不足，则限制高度，优先显示在下方
                final_y = y
                final_height = space_below_combobox
                if final_height < button_height * 2: # 至少显示两行
                    final_height = button_height * 2
                
                # 如果下方空间不足，且上方空间更大，则尝试显示在上方
                if space_below_combobox < limited_content_height and space_above_combobox > space_below_combobox:
                    final_y = self.combobox_instance.winfo_rooty() - min(limited_content_height, space_above_combobox)
                    final_height = min(limited_content_height, space_above_combobox)

        # 确保下拉菜单的顶部不会超出屏幕顶部
        if final_y < 0:
            final_y = 0
            final_height = min(final_height, screen_height) # 限制高度不超过屏幕高度

        self.geometry(f"{width}x{final_height}+{x}+{final_y}")
        self.deiconify() # 显示窗口
        self.focus_set() # 设置焦点

    def hide(self):
        self.withdraw() # 隐藏窗口


def enable_combobox_wheel_scroll(combobox: ctk.CTkComboBox):
    """
    Enables mouse wheel scrolling for the dropdown menu of a CTkComboBox by replacing
    its default dropdown with a custom scrollable one.
    """
    
    # 创建自定义下拉菜单实例
    combobox._custom_dropdown_menu = CustomDropdownMenu(
        master=combobox.master,
        combobox_instance=combobox,
        values=combobox._values,
        command=combobox._dropdown_callback,
        font=combobox._font,
        fg_color=combobox._dropdown_menu.cget("fg_color"), # 使用原下拉菜单的颜色
        hover_color=combobox._dropdown_menu.cget("hover_color"),
        text_color=combobox._dropdown_menu.cget("text_color")
    )

    # 替换原始的 _open_dropdown_menu 方法
    def new_open_dropdown_menu():
        # 获取 combobox 的绝对坐标和宽度
        x = combobox.winfo_rootx()
        y = combobox.winfo_rooty() + combobox.winfo_height() # 下拉菜单紧贴 combobox 下方
        width = combobox.winfo_width()
        combobox._custom_dropdown_menu.show(x, y, width)

    # 存储原始方法，以防需要
    if not hasattr(combobox, '_open_dropdown_menu_original'):
        combobox._open_dropdown_menu_original = combobox._open_dropdown_menu
    
    # 替换方法
    combobox._open_dropdown_menu = new_open_dropdown_menu

    # 确保当 combobox 的值更新时，自定义下拉菜单也能更新
    def update_custom_dropdown_values(*args):
        if hasattr(combobox, '_custom_dropdown_menu'):
            combobox._custom_dropdown_menu.values = combobox._values
            combobox._custom_dropdown_menu.update_idletasks() # 强制更新布局
            # 重新创建按钮以反映新值
            for button in combobox._custom_dropdown_menu.buttons:
                button.destroy()
            combobox._custom_dropdown_menu.buttons = []
            for i, value in enumerate(combobox._custom_dropdown_menu.values):
                button = ctk.CTkButton(
                    combobox._custom_dropdown_menu.scrollable_frame,
                    text=value,
                    command=lambda v=value: combobox._custom_dropdown_menu._on_select(v),
                    font=combobox._custom_dropdown_menu.font,
                    fg_color="transparent",
                    hover_color=combobox._custom_dropdown_menu.hover_color,
                    text_color=combobox._custom_dropdown_menu.text_color,
                    anchor="w"
                )
                button.grid(row=i, column=0, sticky="ew", padx=2, pady=2)
                combobox._custom_dropdown_menu.buttons.append(button)
            
            # 重新绑定鼠标滚轮事件到新创建的按钮
            for button in combobox._custom_dropdown_menu.buttons:
                button.bind("<MouseWheel>", combobox._custom_dropdown_menu._on_mouse_wheel)
                if platform.system() != "Windows" and platform.system() != "Darwin":
                    button.bind("<Button-4>", combobox._custom_dropdown_menu._on_mouse_wheel)
                    button.bind("<Button-5>", combobox._custom_dropdown_menu._on_mouse_wheel)
            
            # 如果菜单当前是显示的，则重新显示以更新位置和内容
            if combobox._custom_dropdown_menu.winfo_exists() and combobox._custom_dropdown_menu.winfo_ismapped():
                x = combobox.winfo_rootx()
                y = combobox.winfo_rooty() + combobox.winfo_height()
                width = combobox.winfo_width()
                combobox._custom_dropdown_menu.show(x, y, width)
            else:
                # 否则确保它是隐藏的
                combobox._custom_dropdown_menu.hide()


    # 劫持 configure 方法以更新自定义下拉菜单的 values
    original_configure = combobox.configure
    def hijacked_configure(require_redraw=False, **kwargs):
        if "values" in kwargs:
            combobox._values = kwargs["values"] # 更新内部 _values
            update_custom_dropdown_values() # 更新自定义下拉菜单
        original_configure(require_redraw=require_redraw, **kwargs)
    combobox.configure = hijacked_configure
