# ui/context_menu.py
# -*- coding: utf-8 -*-
import tkinter as tk
import customtkinter as ctk
import re

class FindReplaceDialog(ctk.CTkToplevel):
    """查找和替换功能的对话框"""
    def __init__(self, parent_widget, mode='find'):
        super().__init__(parent_widget)
        self.widget = parent_widget
        self.matches = []
        self.current_match_index = -1

        self.title("查找和替换")
        self.geometry("450x230")
        self.transient(parent_widget)
        self.grab_set()

        self.find_var = tk.StringVar()
        self.replace_var = tk.StringVar()

        # --- 布局 ---
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 查找
        find_frame = ctk.CTkFrame(main_frame)
        find_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(find_frame, text="查找:", width=60).pack(side="left", padx=5)
        self.find_entry = ctk.CTkEntry(find_frame, textvariable=self.find_var)
        self.find_entry.pack(side="left", fill="x", expand=True)
        self.find_entry.bind("<Return>", self.find_all)

        # 替换
        replace_frame = ctk.CTkFrame(main_frame)
        replace_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(replace_frame, text="替换为:", width=60).pack(side="left", padx=5)
        self.replace_entry = ctk.CTkEntry(replace_frame, textvariable=self.replace_var)
        self.replace_entry.pack(side="left", fill="x", expand=True)

        # 状态标签
        self.status_label = ctk.CTkLabel(main_frame, text="输入内容以开始查找")
        self.status_label.pack(fill="x", pady=2)

        # 按钮
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", pady=10)
        button_frame.columnconfigure((0,1,2,3,4), weight=1)

        self.find_button = ctk.CTkButton(button_frame, text="查找", command=self.find_all)
        self.find_button.grid(row=0, column=0, padx=2)
        self.prev_button = ctk.CTkButton(button_frame, text="上一个", command=self.find_previous, state="disabled")
        self.prev_button.grid(row=0, column=1, padx=2)
        self.next_button = ctk.CTkButton(button_frame, text="下一个", command=self.find_next, state="disabled")
        self.next_button.grid(row=0, column=2, padx=2)
        self.replace_button = ctk.CTkButton(button_frame, text="替换", command=self.replace_current, state="disabled")
        self.replace_button.grid(row=0, column=3, padx=2)
        self.replace_all_button = ctk.CTkButton(button_frame, text="全部替换", command=self.replace_all, state="disabled")
        self.replace_all_button.grid(row=0, column=4, padx=2)

        self.protocol("WM_DELETE_WINDOW", self.close_dialog)
        self.widget.tag_config("search_highlight", background="yellow", foreground="black")
        self.find_entry.focus()

        if mode == 'replace':
            self.replace_entry.focus()

    def find_all(self, event=None):
        self.widget.tag_remove("search_highlight", "1.0", "end")
        self.matches = []
        self.current_match_index = -1
        
        find_term = self.find_var.get()
        if not find_term:
            self.status_label.configure(text="查找内容不能为空")
            self.update_button_states()
            return

        try:
            content = self.widget.get("1.0", "end-1c")
            for match in re.finditer(find_term, content):
                start, end = match.span()
                self.matches.append((self.widget.index(f"1.0 + {start} chars"), self.widget.index(f"1.0 + {end} chars")))
            
            if self.matches:
                self.current_match_index = 0
                self.highlight_current_match()
                self.status_label.configure(text=f"找到 {len(self.matches)} 个匹配项")
            else:
                self.status_label.configure(text="未找到匹配项")
        except re.error as e:
            self.status_label.configure(text=f"正则错误: {e}")
        
        self.update_button_states()

    def highlight_current_match(self):
        self.widget.tag_remove("search_highlight", "1.0", "end")
        if self.current_match_index != -1:
            start, end = self.matches[self.current_match_index]
            self.widget.tag_add("search_highlight", start, end)
            self.widget.see(start)
            self.status_label.configure(text=f"匹配 {self.current_match_index + 1} / {len(self.matches)}")

    def find_next(self):
        if self.matches:
            self.current_match_index = (self.current_match_index + 1) % len(self.matches)
            self.highlight_current_match()

    def find_previous(self):
        if self.matches:
            self.current_match_index = (self.current_match_index - 1 + len(self.matches)) % len(self.matches)
            self.highlight_current_match()

    def replace_current(self):
        if self.current_match_index != -1:
            start, end = self.matches[self.current_match_index]
            replace_term = self.replace_var.get()
            self.widget.delete(start, end)
            self.widget.insert(start, replace_term)
            # Replacing invalidates old matches, so we need to find again
            self.find_all()

    def replace_all(self):
        find_term = self.find_var.get()
        replace_term = self.replace_var.get()
        if not find_term: return

        try:
            content = self.widget.get("1.0", "end-1c")
            new_content, count = re.subn(find_term, replace_term, content)
            if count > 0:
                self.widget.delete("1.0", "end")
                self.widget.insert("1.0", new_content)
                self.status_label.configure(text=f"已完成 {count} 处替换")
                self.matches = []
                self.current_match_index = -1
                self.update_button_states()
            else:
                self.status_label.configure(text="未找到匹配项")
        except re.error as e:
            self.status_label.configure(text=f"正则错误: {e}")

    def update_button_states(self):
        has_matches = bool(self.matches)
        self.prev_button.configure(state="normal" if has_matches else "disabled")
        self.next_button.configure(state="normal" if has_matches else "disabled")
        self.replace_button.configure(state="normal" if has_matches else "disabled")
        self.replace_all_button.configure(state="normal" if has_matches else "disabled")

    def close_dialog(self):
        self.widget.tag_remove("search_highlight", "1.0", "end")
        self.destroy()

class TextWidgetContextMenu:
    """
    为 customtkinter.TextBox 或 tkinter.Text 提供右键菜单和快捷键功能。
    """
    def __init__(self, widget):
        self.widget = widget
        self.menu = tk.Menu(widget, tearoff=0)
        self.menu.add_command(label="复制", command=self.copy, accelerator="Ctrl+C")
        self.menu.add_command(label="粘贴", command=self.paste, accelerator="Ctrl+V")
        self.menu.add_command(label="剪切", command=self.cut, accelerator="Ctrl+X")
        self.menu.add_separator()
        self.menu.add_command(label="全选", command=self.select_all, accelerator="Ctrl+A")
        self.menu.add_separator()
        self.menu.add_command(label="查找", command=self.show_find_dialog, accelerator="Ctrl+F")
        self.menu.add_command(label="替换", command=self.show_replace_dialog, accelerator="Ctrl+H")
        
        # 绑定事件
        self.widget.bind("<Button-3>", self.show_menu)
        self.widget.bind("<Control-f>", self.show_find_dialog_event)
        self.widget.bind("<Control-h>", self.show_replace_dialog_event)

    def show_find_dialog_event(self, event=None):
        self.show_find_dialog()
        return "break"

    def show_replace_dialog_event(self, event=None):
        self.show_replace_dialog()
        return "break"

    def show_find_dialog(self):
        FindReplaceDialog(self.widget, mode='find')

    def show_replace_dialog(self):
        FindReplaceDialog(self.widget, mode='replace')
        
    def show_menu(self, event):
        if isinstance(self.widget, ctk.CTkTextbox):
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()
            
    def copy(self):
        try:
            if self.widget.tag_ranges("sel"):
                text = self.widget.get("sel.first", "sel.last")
                self.widget.clipboard_clear()
                self.widget.clipboard_append(text)
        except tk.TclError:
            pass

    def paste(self):
        try:
            text = self.widget.clipboard_get()
            if self.widget.tag_ranges("sel"):
                start, end = self.widget.tag_ranges("sel")
                self.widget.delete(start, end)
            self.widget.insert("insert", text)
        except tk.TclError:
            pass

    def cut(self):
        try:
            if self.widget.tag_ranges("sel"):
                text = self.widget.get("sel.first", "sel.last")
                self.widget.delete("sel.first", "sel.last")
                self.widget.clipboard_clear()
                self.widget.clipboard_append(text)
        except tk.TclError:
            pass

    def select_all(self, event=None):
        self.widget.tag_add("sel", "1.0", "end")
        return "break"
