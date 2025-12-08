# ui/vectorstore_tab.py
# -*- coding: utf-8 -*-
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import os
import logging
import threading
import traceback
import re
import json
import config_manager as cm

def build_vectorstore_tab(self):
    """
    构建向量库/JSON存储标签页
    """
    # --- First, add methods to main class to ensure they exist before UI elements are created ---
    self.load_vectorstore_data = load_vectorstore_data.__get__(self)
    self.display_vectorstore_items = display_vectorstore_items.__get__(self)
    self.load_item_content_to_editor = load_item_content_to_editor.__get__(self)
    self.save_vectorstore_item = save_vectorstore_item.__get__(self)
    self.convert_vectorstore_to_markdown = convert_vectorstore_to_markdown.__get__(self) # 重命名转换方法
    self.clear_old_data = clear_old_data.__get__(self) # 新增清除旧数据方法
    self.current_editing_item = None # To store info about the item being edited

    # --- Now, build the UI ---
    self.vectorstore_tab = self.tabview.add("数据查看") # 更改标签页名称
    
    # --- Main Frame ---
    main_frame = ctk.CTkFrame(self.vectorstore_tab)
    main_frame.pack(fill="both", expand=True, padx=5, pady=5)
    main_frame.grid_columnconfigure(0, weight=1)
    main_frame.grid_rowconfigure(1, weight=1) # Display area
    main_frame.grid_rowconfigure(2, weight=2) # Edit area

    # --- Top Button Frame ---
    button_frame = ctk.CTkFrame(main_frame)
    button_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

    self.btn_load_chars = ctk.CTkButton(
        button_frame,
        text="加载角色状态",
        command=lambda: self.load_vectorstore_data('character')
    )
    self.btn_load_chars.pack(side="left", padx=5, pady=5)

    self.btn_load_fs = ctk.CTkButton(
        button_frame,
        text="加载伏笔状态",
        command=lambda: self.load_vectorstore_data('foreshadowing')
    )
    self.btn_load_fs.pack(side="left", padx=5, pady=5)

    self.btn_save_vs_item = ctk.CTkButton(
        button_frame,
        text="保存修改",
        command=self.save_vectorstore_item
    )
    self.btn_save_vs_item.pack(side="left", padx=5, pady=5)

    # 根据配置决定是否创建旧数据迁移相关按钮
    config = cm.load_config()
    if not config.get("hide_old_data_features", False):
        self.btn_convert_vs_to_markdown = ctk.CTkButton(
            button_frame,
            text="转换旧项目为MD格式",
            command=self.convert_vectorstore_to_markdown
        )
        self.btn_convert_vs_to_markdown.pack(side="left", padx=10, pady=5)

        self.btn_clear_old_data = ctk.CTkButton(
            button_frame,
            text="清除旧版数据",
            command=self.clear_old_data
        )
        self.btn_clear_old_data.pack(side="left", padx=5, pady=5)


    # --- Display Area (Scrollable) ---
    self.vs_display_frame = ctk.CTkScrollableFrame(main_frame, label_text="数据内容")
    self.vs_display_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

    # --- Edit Area ---
    self.vs_edit_textbox = ctk.CTkTextbox(main_frame, wrap="word")
    self.vs_edit_textbox.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

def load_vectorstore_data(self, type):
    """
    加载并显示角色/伏笔数据（从Markdown文件）
    """
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择项目路径")
        return

    def task():
        try:
            self.safe_log(f"正在加载 {type} 数据...")
            collection_name = "character_state_collection" if type == 'character' else "foreshadowing_collection"
            
            from novel_generator.json_utils import get_store_path, load_store
            md_path = get_store_path(filepath, collection_name)
            
            items = []
            if os.path.exists(md_path):
                self.safe_log(f"  -> 从 {os.path.basename(md_path)} 加载...")
                data_dict = load_store(filepath, collection_name)
                # 转换为与显示功能兼容的列表格式
                for item_id, data in data_dict.items():
                    items.append({
                        'id': item_id,
                        'document': "N/A", # Document不再是主要数据源
                        'metadata': data
                    })
            else:
                self.safe_log(f"  -> Markdown文件不存在: {os.path.basename(md_path)}")

            if not items:
                self.safe_log(f"未能从任何来源加载 {collection_name} 的内容。")
                self.master.after(0, lambda: self.display_vectorstore_items([], type)) # 清空显示
                return

            self.master.after(0, lambda: self.display_vectorstore_items(items, type))
            self.safe_log(f"✅ 成功加载 {len(items)} 条目。")

        except Exception as e:
            self.handle_exception(f"加载数据时出错: {e}")

    threading.Thread(target=task, daemon=True).start()

def display_vectorstore_items(self, items, type):
    """
    在UI上分类显示向量库条目
    """
    # Clear previous display
    for widget in self.vs_display_frame.winfo_children():
        widget.destroy()

    if type == 'character':
        # Group by weight
        groups = {
            "主角级 (96-100)": [], "核心配角 (81-95)": [], "关键角色 (61-80)": [],
            "次要配角 (41-60)": [], "单元角色 (21-40)": [], "背景角色 (1-20)": [], "未分类": []
        }
        for item in items:
            meta = item.get('metadata', {})
            # 从JSON加载时，权重在'基础信息' -> '角色权重'
            base_info = meta.get('基础信息', {})
            weight_str = base_info.get('角色权重', '-1')
            
            import re
            weight = -1
            if isinstance(weight_str, str):
                match = re.search(r'\d+', weight_str)
                if match:
                    try:
                        weight = int(match.group(0))
                    except (ValueError, TypeError):
                        weight = -1
            elif isinstance(weight_str, (int, float)):
                weight = int(weight_str)

            if 96 <= weight <= 100: groups["主角级 (96-100)"].append(item)
            elif 81 <= weight <= 95: groups["核心配角 (81-95)"].append(item)
            elif 61 <= weight <= 80: groups["关键角色 (61-80)"].append(item)
            elif 41 <= weight <= 60: groups["次要配角 (41-60)"].append(item)
            elif 21 <= weight <= 40: groups["单元角色 (21-40)"].append(item)
            elif 1 <= weight <= 20: groups["背景角色 (1-20)"].append(item)
            else: groups["未分类"].append(item)
        
        # Sort characters within each group by weight descending
        for group in groups.values():
            group.sort(key=lambda x: int(re.search(r'\d+', x.get('metadata', {}).get('基础信息', {}).get('角色权重', '-1')).group(0) if re.search(r'\d+', x.get('metadata', {}).get('基础信息', {}).get('角色权重', '-1')) else -1), reverse=True)


    elif type == 'foreshadowing':
        # Group by type based on detailed rules
        groups = {
            "主线伏笔 (MF)": [], 
            "暗线伏笔 (AF)": [], 
            "人物伏笔 (CF)": [],
            "支线伏笔 (SF)": [], 
            "一般伏笔 (YF)": [], 
            "其他伏笔": []
        }
        for item in items:
            id = item.get('id', '')
            if id.startswith('MF'): groups["主线伏笔 (MF)"].append(item)
            elif id.startswith('AF'): groups["暗线伏笔 (AF)"].append(item)
            elif id.startswith('CF'): groups["人物伏笔 (CF)"].append(item)
            elif id.startswith('SF'): groups["支线伏笔 (SF)"].append(item)
            elif id.startswith('YF'): groups["一般伏笔 (YF)"].append(item)
            else: groups["其他伏笔"].append(item)
            
        # Sort foreshadowing within each group by ID
        for group in groups.values():
            group.sort(key=lambda x: x.get('id', ''))

    # Display
    for group_name, group_items in groups.items():
        if not group_items:
            continue
        
        group_frame = ctk.CTkFrame(self.vs_display_frame)
        group_frame.pack(fill="x", pady=(2, 3), padx=5)
        
        label = ctk.CTkLabel(group_frame, text=group_name, font=("Microsoft YaHei", 12, "bold"))
        label.pack(anchor="w", padx=5)
        
        items_frame = ctk.CTkFrame(group_frame)
        items_frame.pack(fill="x", expand=True, pady=2)
        
        row = 0
        col = 0
        # 每行最多显示的按钮数，可以根据窗口大小和按钮宽度调整
        max_cols = 9
        for item in group_items:
            meta = item.get('metadata', {})
            id = item.get('id')
            # 从JSON加载时，名称键是'名称'
            display_name = meta.get('名称', meta.get('name', id)) if type == 'character' else id
            
            btn = ctk.CTkButton(
                items_frame,
                text=display_name,
                command=lambda i=item: self.load_item_content_to_editor(i),
                font=("Microsoft YaHei", 11),
                height=20,
                width=80
            )
            btn.grid(row=row, column=col, padx=3, pady=2)
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

def load_item_content_to_editor(self, item):
    """
    将选中条目的内容格式化为Markdown字符串并加载到编辑框。
    """
    from novel_generator.json_utils import _json_to_markdown_character, _json_to_markdown_foreshadowing
    self.current_editing_item = item
    
    json_content = item.get('metadata', {})
    if not json_content:
        self.vs_edit_textbox.delete("0.0", "end")
        self.vs_edit_textbox.insert("0.0", "错误：未找到元数据。")
        return

    try:
        item_type = 'character' if '名称' in json_content else 'foreshadowing'
        if item_type == 'character':
            markdown_content = _json_to_markdown_character(json_content)
        else:
            markdown_content = _json_to_markdown_foreshadowing(json_content)
            
        self.vs_edit_textbox.delete("0.0", "end")
        self.vs_edit_textbox.insert("0.0", markdown_content)
    except Exception as e:
        self.safe_log(f"❌ 格式化为Markdown时出错: {e}", level="error")
        self.vs_edit_textbox.delete("0.0", "end")
        self.vs_edit_textbox.insert("0.0", f"无法格式化内容: {json_content}")

def save_vectorstore_item(self):
    """
    保存对数据条目的修改，将编辑框中的Markdown文本解析为JSON并保存。
    """
    if not self.current_editing_item:
        messagebox.showwarning("警告", "请先选择一个条目进行编辑")
        return

    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择项目路径")
        return

    modified_markdown = self.vs_edit_textbox.get("0.0", "end-1c").strip()
    item_id = self.current_editing_item.get('id')
    
    meta = self.current_editing_item.get('metadata', {})
    item_type = 'character' if '名称' in meta else 'foreshadowing'
    collection_name = "character_state_collection" if item_type == 'character' else "foreshadowing_collection"

    def task():
        from novel_generator.json_utils import _markdown_to_json, update_item_in_store
        try:
            self.safe_log(f"正在解析并保存对 {item_id} 的修改...")
            
            # 将单个条目的Markdown解析回JSON对象
            # 注意：_markdown_to_json期望的是包含所有条目的完整文本，
            # 我们需要一个能解析单个条目的方法。
            # 暂时，我们用一个变通的方法：用整个集合的解析器来解析单个块
            parsed_data_dict = _markdown_to_json(modified_markdown, collection_name)
            
            if not parsed_data_dict or item_id not in parsed_data_dict:
                 # 如果主要解析失败，尝试一个更简单的行解析
                if item_type == 'character':
                    # 对于角色，解析比较复杂，失败可能性高，提示用户检查格式
                    raise ValueError("Markdown格式无法被正确解析，请检查是否符合角色模板。")
                else: # 伏笔的简单行解析
                    updated_json_data = {}
                    for line in modified_markdown.split('\n'):
                        if ':' in line:
                            key, val = line.split(':', 1)
                            updated_json_data[key.strip()] = val.strip()
            else:
                updated_json_data = parsed_data_dict[item_id]

            if not updated_json_data:
                raise ValueError("Markdown解析结果为空。")

            success = update_item_in_store(filepath, collection_name, item_id, updated_json_data)

            if success:
                self.safe_log(f"✅ 成功更新条目 {item_id}")
                # 重新加载数据以刷新UI
                self.master.after(0, lambda: self.load_vectorstore_data(item_type))
            else:
                self.safe_log(f"❌ 更新条目 {item_id} 失败", level="error")
                messagebox.showerror("保存失败", f"无法将更新保存到文件 {collection_name}.json。")

        except Exception as e:
            self.handle_exception(f"保存条目时出错: {e}")

    threading.Thread(target=task, daemon=True).start()

def convert_vectorstore_to_markdown(self):
    """
    加载旧项目的角色和伏笔状态向量库，并将其转换为Markdown文件保存在当前项目中。
    """
    from tkinter import filedialog
    from novel_generator.json_utils import save_store
    from embedding_adapters import create_embedding_adapter
    import chromadb
    from chromadb.config import Settings
    from typing import List, Dict, Any

    old_project_path = filedialog.askdirectory(title="请选择旧版项目的根目录")
    if not old_project_path:
        self.safe_log("❌ 用户取消了选择。")
        return

    def task():
        try:
            self.safe_log(f"🚀 开始从旧项目转换数据: {old_project_path}")

            # --- Helper functions to load legacy vectorstore ---
            def get_vectorstore_dir(filepath: str, collection_name: str = None) -> str:
                base_dir = os.path.join(filepath, "vectorstore")
                if collection_name: return os.path.join(base_dir, collection_name)
                return base_dir

            def load_vector_store(embedding_adapter, filepath: str, collection_name: str):
                try:
                    store_dir = get_vectorstore_dir(filepath, collection_name)
                    if not os.path.exists(store_dir):
                        logging.info(f"向量库目录不存在: {store_dir}"); return None
                    class EmbeddingFunctionWrapper:
                        def __init__(self, embedding_adapter): self.embedding_adapter = embedding_adapter
                        def __call__(self, input: List[str]) -> List[List[float]]: return self.embedding_adapter.embed_documents(input)
                        def name(self) -> str: return "custom_legacy_embedding_function" # Add name method to satisfy chromadb
                    client = chromadb.PersistentClient(path=store_dir, settings=Settings(anonymized_telemetry=False))
                    return client.get_collection(name=collection_name, embedding_function=EmbeddingFunctionWrapper(embedding_adapter))
                except Exception as e:
                    logging.error(f"加载向量库失败: {str(e)}"); traceback.print_exc(); return None

            def get_all_items_from_vectorstore_legacy(store) -> List[Dict[str, Any]]:
                try:
                    all_ids = store.get(include=[])['ids']
                    if not all_ids: return []
                    items = []
                    for i in range(0, len(all_ids), 100):
                        batch_ids = all_ids[i:i + 100]
                        batch_results = store.get(ids=batch_ids, include=["metadatas", "documents"])
                        if not batch_results or not batch_results.get('ids'): continue
                        for j, id in enumerate(batch_results['ids']):
                            items.append({'id': id, 'document': batch_results['documents'][j], 'metadata': batch_results['metadatas'][j]})
                    return items
                except Exception as e:
                    logging.error(f"从向量库获取所有条目时出错: {e}"); traceback.print_exc(); return []

            embedding_adapter = self.create_embedding_adapter()
            if not embedding_adapter:
                self.safe_log("❌ 无法创建 Embedding 适配器，转换中止。")
                messagebox.showerror("错误", "无法创建 Embedding 适配器，请检查配置。")
                return

            current_project_path = self.filepath_var.get().strip()
            if not current_project_path:
                messagebox.showerror("错误", "当前项目路径未设置，无法保存文件。")
                return

            # --- 步骤 1/2: 转换角色状态 ---
            self.safe_log("\n--- 步骤 1/2: 转换角色状态 ---")
            def final_perfect_parser(character_block: str) -> dict:
                lines = character_block.strip().split('\n')
                if not lines: return None
                top_level_match = re.match(r'(ID\d+)：([^\n]+)', lines[0])
                if not top_level_match: return None
                char_id, char_name = top_level_match.group(1), top_level_match.group(2).strip()
                parsed_data = {"ID": char_id, "名称": char_name}
                title_pattern = re.compile(r'^([^\n\s：]+)：', re.MULTILINE)
                matches = list(title_pattern.finditer(character_block))
                for i, match in enumerate(matches):
                    section_title = match.group(1)
                    start_pos = match.end()
                    end_pos = matches[i+1].start() if i + 1 < len(matches) else len(character_block)
                    content_str = character_block[start_pos:end_pos].strip()
                    content_lines = content_str.split('\n')
                    if section_title in ["位置轨迹", "关键事件记录"]:
                        item_list = []
                        for line in content_lines:
                            line = line.strip().lstrip('-').strip()
                            if not line: continue
                            item_dict = {k.strip(): v.strip() for k, v in re.findall(r'（([^：]+)：([^）]+)）', line)}
                            main_content = re.sub(r'（[^）]+）', '', line).strip()
                            event_match = re.match(r'第(\d+)章：\[([^\]]+)\]\s*(.+)', main_content)
                            if event_match:
                                item_dict.update({"章节": event_match.group(1).strip(), "类型": event_match.group(2).strip(), "摘要": event_match.group(3).strip()})
                            elif main_content:
                                item_dict["场景名称"] = main_content
                            if item_dict: item_list.append(item_dict)
                        if item_list: parsed_data[section_title] = item_list
                    elif section_title == "关系网":
                        relations = []
                        for line in content_lines:
                            line = line.strip().lstrip('-').strip();
                            if not line: continue
                            parts = re.match(r'([^:]+):\s*([^,]+),关系强度\[([^\]]+)\],互动频率\[([^\]]+)\]', line)
                            if parts: relations.append({"对象": parts.group(1).strip(), "关系": parts.group(2).strip(), "关系强度": parts.group(3).strip(), "互动频率": parts.group(4).strip()})
                        if relations: parsed_data[section_title] = relations
                    else:
                        kv_data = {}
                        if section_title == "势力特征":
                            faction_match = re.search(r'势力归属：\n((?:\s+.*\n?)*)', content_str, re.MULTILINE)
                            if faction_match:
                                nested_content = faction_match.group(1).strip()
                                # Handle full-width spaces for indentation
                                nested_lines = [line.strip().lstrip(' ').lstrip('-').strip() for line in nested_content.split('\n')]
                                nested_data = {parts[0].strip(): parts[1].strip() for line in nested_lines if '：' in line for parts in [line.split('：', 1)]}
                                kv_data["势力归属"] = nested_data
                                content_str = content_str.replace(faction_match.group(0), '')
                        for line in content_str.split('\n'):
                            line = line.strip()
                            if '：' in line:
                                parts = line.split('：', 1)
                                # Robustly strip leading hyphens and spaces from the key
                                key = re.sub(r'^[-\s]+', '', parts[0]).strip()
                                value = parts[1].strip()
                                if key and value:
                                    kv_data[key] = value
                        if kv_data: parsed_data[section_title] = kv_data
                return parsed_data

            char_collection_name = "character_state_collection"
            self.safe_log(f"🔍 正在从旧项目 '{char_collection_name}' 加载向量库...")
            char_store = load_vector_store(embedding_adapter, old_project_path, char_collection_name)
            character_states_json = {}
            char_success = False
            if not char_store: self.safe_log(f"⚠️ 未能从旧项目加载角色向量库。")
            else:
                char_items = get_all_items_from_vectorstore_legacy(char_store)
                if not char_items: self.safe_log(f"⚠️ 未能从旧项目加载任何角色状态。")
                else:
                    self.safe_log(f"✅ 成功从旧项目加载 {len(char_items)} 条角色状态。")
                    for item in char_items:
                        parsed_char = final_perfect_parser(item.get('document', ''))
                        if parsed_char: character_states_json[parsed_char["ID"]] = parsed_char
                    if not character_states_json: self.safe_log("❌ 加载的角色数据中无法解析出任何有效条目。")
                    else:
                        if save_store(current_project_path, char_collection_name, character_states_json):
                            self.safe_log(f"🎉 成功转换 {len(character_states_json)} 条角色状态到Markdown。")
                            char_success = True
                        else: self.safe_log("❌ 保存角色状态Markdown文件失败", level="error")

            # --- 步骤 2/2: 转换伏笔状态 ---
            self.safe_log("\n--- 步骤 2/2: 转换伏笔状态 ---")
            # This function is now designed to parse the entire item dictionary from the vectorstore,
            # not just the document text.
            def parse_foreshadowing_document(item: dict) -> dict:
                """
                The definitive parser based on direct analysis of the complete vectorstore item,
                including both document and metadata.
                """
                if not isinstance(item, dict):
                    return None

                doc_text = item.get('document', '').strip()
                metadata = item.get('metadata', {})
                item_id = item.get('id', '').strip()

                # 清除ID末尾可能存在的 "_数字" 后缀
                item_id = re.sub(r'_\d+$', '', item_id)

                # The ID from the top level is the most reliable.
                if not item_id:
                    return None
                
                # The content is the entire document text.
                if not doc_text:
                    return None
                    
                parsed_data = {
                    "ID": item_id,
                    "内容": doc_text
                }

                # The last chapter is in the metadata.
                last_chapter = metadata.get('伏笔最后章节')
                if last_chapter:
                    parsed_data['伏笔最后章节'] = last_chapter.strip()
                
                return parsed_data

            fs_collection_name = "foreshadowing_collection"
            self.safe_log(f"🔍 正在从旧项目 '{fs_collection_name}' 加载向量库...")
            fs_store = load_vector_store(embedding_adapter, old_project_path, fs_collection_name)
            foreshadowing_json = {}
            fs_success = False
            if not fs_store: self.safe_log(f"⚠️ 未能从旧项目加载伏笔向量库。")
            else:
                fs_items = get_all_items_from_vectorstore_legacy(fs_store)
                if not fs_items: self.safe_log(f"⚠️ 未能从旧项目加载任何伏笔状态。")
                else:
                    self.safe_log(f"✅ 成功从旧项目加载 {len(fs_items)} 条伏笔状态。")
                    for item in fs_items:
                        # Pass the entire item dictionary to the new parser
                        parsed_fs = parse_foreshadowing_document(item)
                        if parsed_fs: foreshadowing_json[parsed_fs["ID"]] = parsed_fs
                    if not foreshadowing_json: self.safe_log("❌ 加载的伏笔数据中无法解析出任何有效条目。")
                    else:
                        if save_store(current_project_path, fs_collection_name, foreshadowing_json):
                            self.safe_log(f"🎉 成功转换 {len(foreshadowing_json)} 条伏笔状态到Markdown。")
                            fs_success = True
                        else: self.safe_log("❌ 保存伏笔状态Markdown文件失败", level="error")

            # --- Final Summary ---
            if char_success or fs_success:
                msg = "数据转换完成！\n\n"
                if char_success: msg += f"角色状态: 成功转换 {len(character_states_json)} 条\n"
                else: msg += "角色状态: 转换失败或无数据\n"
                if fs_success: msg += f"伏笔状态: 成功转换 {len(foreshadowing_json)} 条"
                else: msg += "伏笔状态: 转换失败或无数据"
                messagebox.showinfo("转换成功", msg)
            else:
                messagebox.showwarning("转换完成", "未找到任何可转换的旧版数据。")

        except Exception as e:
            self.handle_exception(f"转换旧项目数据时出错: {e}")
            messagebox.showerror("转换失败", f"处理过程中发生错误:\n{e}")

    threading.Thread(target=task, daemon=True).start()

def clear_old_data(self):
    """
    永久性地清除与旧版向量库相关的数据和UI元素，并保存设置。
    """
    if messagebox.askyesno("确认操作", "此操作将永久移除旧版数据相关功能，重启后生效，且不可逆，确定要继续吗？"):
        try:
            self.safe_log("正在清除旧版数据相关功能...")

            # 1. 更新并保存配置
            config = cm.load_config()
            config["hide_old_data_features"] = True

            # 遍历所有现有配置，删除其中的 embedding_config
            if "configurations" in config:
                for conf_name, conf_data in config["configurations"].items():
                    if "embedding_config" in conf_data:
                        del conf_data["embedding_config"]
                        self.safe_log(f"  -> 已从配置 '{conf_name}' 中移除嵌入模型设置。")

            cm.save_config(config)
            self.safe_log("  -> 已更新并清理配置文件，将在下次启动时隐藏旧功能。")

            # 2. 在当前会话中移除UI元素
            if hasattr(self, 'btn_convert_vs_to_markdown'):
                self.btn_convert_vs_to_markdown.pack_forget()
                self.safe_log("  -> 已隐藏 '转换旧项目为MD格式' 按钮。")

            if hasattr(self, 'btn_clear_old_data'):
                self.btn_clear_old_data.pack_forget()
                self.safe_log("  -> 已隐藏 '清除旧版数据' 按钮。")

            # 3. 正确地移除 Embedding 模型设置标签页
            if hasattr(self, 'llm_embedding_tabview'):
                try:
                    # 使用CTabView的delete方法来移除标签页
                    self.llm_embedding_tabview.delete("Embedding 模型设置")
                    self.safe_log("  -> 已移除 'Embedding 模型设置' 标签页。")
                except Exception as tab_error:
                    self.safe_log(f"  -> 移除 'Embedding 模型设置' 标签页时发生错误: {tab_error}", level="warning")
            else:
                self.safe_log("  -> 未找到 'llm_embedding_tabview' 控件，无法移除标签页。", level="warning")

            self.safe_log("✅ 清除操作完成。")
            messagebox.showinfo("完成", "旧版数据相关功能已标记为移除。请重启软件以使所有更改完全生效。")

        except Exception as e:
            self.handle_exception(f"清除旧版数据时出错: {e}")
            messagebox.showerror("错误", f"清除操作失败:\n{e}")
