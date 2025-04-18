# ui/generation_handlers.py
# -*- coding: utf-8 -*-
import os
import logging
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import traceback
from utils import read_file, save_string_to_txt, clear_file_content
from llm_adapters import create_llm_adapter  # 添加这一行
from novel_generator.common import invoke_with_cleaning  # 添加这一行
from novel_generator import (
    Novel_architecture_generate,
    Novel_volume_generate,  # 添加导入
    Chapter_blueprint_generate,
    generate_chapter_draft,
    finalize_chapter,
    import_knowledge_file,
    clear_vector_store,
    enrich_chapter_text
)
from novel_generator.volume import get_current_volume_info  # 添加这一行
from novel_generator.chapter_blueprint import (
    analyze_directory_status,
    analyze_volume_range,
    find_current_volume
)
from consistency_checker import check_consistency
from novel_generator.rewrite import rewrite_chapter  # 添加导入

def generate_novel_architecture_ui(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def task():
        confirm = messagebox.askyesno("确认", "确定要生成小说架构吗？")
        if not confirm:
            self.enable_button_safe(self.btn_generate_architecture)
            return

        self.disable_button_safe(self.btn_generate_architecture)
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)

            topic = self.topic_text.get("0.0", "end").strip()
            genre = self.genre_var.get().strip()
            num_chapters = self.safe_get_int(self.num_chapters_var, 10)
            word_number = self.safe_get_int(self.word_number_var, 3000)
            # 获取内容指导
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            self.safe_log("开始生成小说架构...")
            Novel_architecture_generate(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                llm_model=model_name,
                topic=topic,
                genre=genre,
                number_of_chapters=num_chapters,
                word_number=word_number,
                filepath=filepath,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_val,
                user_guidance=user_guidance  # 添加内容指导参数
            )
            self.safe_log("✅ 小说架构生成完成。请在 'Novel Architecture' 标签页查看或编辑。")
        except Exception:
            self.handle_exception("生成小说架构时出错")
        finally:
            self.enable_button_safe(self.btn_generate_architecture)
    threading.Thread(target=task, daemon=True).start()

def generate_chapter_blueprint_ui(self):
    """处理生成目录的主UI函数"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def show_dialog():
        """显示生成对话框"""
        try:
            # 获取当前进度
            from novel_generator.chapter_blueprint import get_volume_progress, analyze_volume_range
            current_vol, last_chapter, start_chap, end_chap, is_last, is_complete = get_volume_progress(filepath)
            
            volumes = analyze_volume_range(filepath)
            if not volumes:
                messagebox.showwarning("警告", "请先生成分卷大纲")
                return
                
            # 获取卷数和已有章节信息
            volume_count = self.safe_get_int(self.volume_count_var, 3)
            _, existing_chapters, _ = analyze_directory_status(filepath)
                
            # 获取当前卷的总章节数并检查完整性
            current_vol_info = next((v for v in volumes if v['volume'] == current_vol), None)
            if not current_vol_info:
                messagebox.showerror("错误", f"无法获取第{current_vol}卷信息")
                return
                
            total_chapters = current_vol_info['end'] - current_vol_info['start'] + 1
            completed_chapters = len([x for x in range(current_vol_info['start'], last_chapter + 1) 
                                   if x in set(existing_chapters)])
                
            dialog = ctk.CTkToplevel(self.master)
            dialog.title("章节目录生成")
            dialog.geometry("400x200")
            dialog.transient(self.master)
            dialog.grab_set()
            
            # 按钮点击处理
            def handle_button_click(is_single: bool):
                dialog.destroy()
                self.disable_button_safe(self.btn_generate_directory)
                
                def generation_thread():
                    try:
                        next_vol = current_vol + 1 if is_last else current_vol
                        result = do_generate_blueprint(next_vol, is_single)
                        
                        if result:
                            new_vol, new_chap, _, _, new_is_last, _ = get_volume_progress(filepath)
                            if new_vol < volume_count or not new_is_last:
                                self.master.after(1000, show_dialog)
                    finally:
                        self.enable_button_safe(self.btn_generate_directory)
                
                thread = threading.Thread(target=generation_thread, daemon=True)
                thread.start()
            
            # UI组件设置 - 统一处理一次
            if last_chapter == 0:
                info_text = "准备生成第一卷章节目录"
                btn1_text = "生成第一卷章节目录"
                next_vol = 1
            elif not is_complete:
                # 当前卷还未完成，继续生成当前卷
                progress = f"（已生成{completed_chapters}/{total_chapters}章）"
                info_text = f"当前第{current_vol}卷{progress}\n已生成至第{last_chapter}章"
                btn1_text = f"继续生成第{current_vol}卷目录"
                next_vol = current_vol
            elif is_complete and is_last:
                # 当前卷已完成，准备生成下一卷
                info_text = f"第{current_vol}卷已完成，准备生成第{current_vol + 1}卷"
                btn1_text = f"生成第{current_vol + 1}卷章节目录"
                next_vol = current_vol + 1
            else:
                info_text = f"当前进度：第{current_vol}卷 第{last_chapter}章（总计{end_chap}章）"
                btn1_text = f"继续生成第{current_vol}卷目录"
                next_vol = current_vol

            info_label = ctk.CTkLabel(
                dialog,
                text=f"{info_text}\n请选择生成方式：",
                font=("Microsoft YaHei", 12)
            )
            info_label.pack(pady=20)

            btn_frame = ctk.CTkFrame(dialog)
            btn_frame.pack(pady=20)

            # 生成按钮
            ctk.CTkButton(
                btn_frame,
                text=btn1_text,
                command=lambda: handle_button_click(True),
                font=("Microsoft YaHei", 12)
            ).pack(pady=5)

            if not is_last or current_vol < volume_count:
                ctk.CTkButton(
                    btn_frame,
                    text="生成所有后续章节目录",
                    command=lambda: handle_button_click(False),
                    font=("Microsoft YaHei", 12)
                ).pack(pady=5)

            ctk.CTkButton(
                btn_frame,
                text="退出",
                command=dialog.destroy,
                font=("Microsoft YaHei", 12)
            ).pack(pady=5)

        except Exception as e:
            self.safe_log(f"❌ 显示章节目录生成对话框时出错: {str(e)}")
            self.enable_button_safe(self.btn_generate_directory)

    def do_generate_blueprint(start_vol: int, single_mode: bool):
        """实际执行生成的函数"""
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            self.safe_log(f"开始生成{'当前卷' if single_mode else '所有卷'}章节目录...")
            result = Chapter_blueprint_generate(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                llm_model=model_name,
                number_of_chapters=number_of_chapters,
                filepath=filepath,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_val,
                user_guidance=user_guidance,
                start_from_volume=start_vol,
                generate_single=single_mode
            )
            
            # 检查生成结果
            if not result:
                self.safe_log("❌ 章节目录生成失败：未获得有效内容")
                return False
                
            # 验证文件生成
            directory_file = os.path.join(filepath, "Novel_directory.txt")
            if not os.path.exists(directory_file):
                self.safe_log("❌ 章节目录生成失败：未找到目录文件")
                return False
                
            content = read_file(directory_file).strip()
            if not content:
                self.safe_log("❌ 章节目录生成失败：目录文件为空")
                return False
                
            self.safe_log("✅ 章节目录生成完成")
            return True
            
        except Exception as e:
            self.safe_log(f"❌ 生成章节目录时发生错误: {str(e)}")
            return False

    def main_task():
        """主任务函数"""
        try:
            volume_count = self.safe_get_int(self.volume_count_var, 3)
            volumes = analyze_volume_range(filepath)
            
            if not volumes:
                messagebox.showwarning("警告", "请先生成分卷大纲")
                return
                
            # 获取当前状态，但不传递参数给show_dialog
            last_chapter, current_vol, _ = analyze_chapter_status(filepath)
            show_dialog()  # 修改这里，移除参数
            
        except Exception as e:
            self.safe_log(f"❌ 检查章节目录状态时发生错误: {str(e)}")
            self.enable_button_safe(self.btn_generate_directory)

    threading.Thread(target=main_task, daemon=True).start()

def generate_blueprint_chapters(self, start_from_volume: int, generate_single: bool):
    """执行章节目录生成任务"""
    filepath = self.filepath_var.get().strip()
    self.disable_button_safe(self.btn_generate_directory)
    
    def task():
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            self.safe_log(f"开始生成{'当前卷' if generate_single else '所有卷'}章节目录...")
            result = Chapter_blueprint_generate(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                llm_model=model_name,
                number_of_chapters=number_of_chapters,
                filepath=filepath,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_val,
                user_guidance=user_guidance,
                start_from_volume=start_from_volume,
                generate_single=generate_single
            )
            
            if result:
                self.safe_log("✅ 章节目录生成完成")
                # 检查是否需要继续生成
                last_chapter, current_vol, is_volume_end = analyze_chapter_status(filepath)
                volume_count = self.safe_get_int(self.volume_count_var, 3)
                
                if current_vol < volume_count and (is_volume_end or not generate_single):
                    self.master.after(1000, lambda: self.show_blueprint_dialog())
            else:
                self.safe_log("❌ 章节目录生成失败")

        except Exception as e:
            self.safe_log(f"❌ 生成章节目录时发生错误: {str(e)}")
        finally:
            self.enable_button_safe(self.btn_generate_directory)

    threading.Thread(target=task, daemon=True).start()

def generate_chapter_draft_ui(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径。")
        return

    def task():
        # 添加确认对话框
        if not messagebox.askyesno("确认", "确定要生成章节草稿吗？"):
            return

        self.disable_button_safe(self.btn_generate_chapter)
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)

            chap_num = self.safe_get_int(self.chapter_num_var, 1)
            word_number = self.safe_get_int(self.word_number_var, 3000)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            char_inv = self.characters_involved_var.get().strip()
            key_items = self.key_items_var.get().strip()
            scene_loc = self.scene_location_var.get().strip()
            time_constr = self.time_constraint_var.get().strip()

            embedding_api_key = self.embedding_api_key_var.get().strip()
            embedding_url = self.embedding_url_var.get().strip()
            embedding_interface_format = self.embedding_interface_format_var.get().strip()
            embedding_model_name = self.embedding_model_name_var.get().strip()
            embedding_k = self.safe_get_int(self.embedding_retrieval_k_var, 4)

            self.safe_log(f"生成第{chap_num}章草稿：准备生成请求提示词...")

            # 调用新添加的 build_chapter_prompt 函数构造初始提示词
            from novel_generator.chapter import build_chapter_prompt
            prompt_text = build_chapter_prompt(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                filepath=filepath,
                novel_number=chap_num,
                word_number=word_number,
                temperature=temperature,
                user_guidance=user_guidance,
                characters_involved=char_inv,
                key_items=key_items,
                scene_location=scene_loc,
                time_constraint=time_constr,
                embedding_api_key=embedding_api_key,
                embedding_url=embedding_url,
                embedding_interface_format=embedding_interface_format,
                embedding_model_name=embedding_model_name,
                embedding_retrieval_k=embedding_k,
                interface_format=interface_format,
                max_tokens=max_tokens,
                timeout=timeout_val
            )

            # 弹出可编辑提示词对话框，等待用户确认或取消
            result = {"prompt": None}
            event = threading.Event()

            def create_dialog():
                dialog = ctk.CTkToplevel(self.master)
                dialog.title("当前章节请求提示词（可编辑）")
                dialog.geometry("600x400")
                text_box = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 12))
                text_box.pack(fill="both", expand=True, padx=10, pady=10)

                # 字数统计标签
                wordcount_label = ctk.CTkLabel(dialog, text="字数：0", font=("Microsoft YaHei", 12))
                wordcount_label.pack(side="left", padx=(10,0), pady=5)
                
                # 插入角色内容
                final_prompt = prompt_text
                role_names = [name.strip() for name in self.char_inv_text.get("0.0", "end").strip().split(',') if name.strip()]
                role_lib_path = os.path.join(filepath, "角色库")
                role_contents = []
                
                if os.path.exists(role_lib_path):
                    for root, dirs, files in os.walk(role_lib_path):
                        for file in files:
                            if file.endswith(".txt") and os.path.splitext(file)[0] in role_names:
                                file_path = os.path.join(root, file)
                                try:
                                    with open(file_path, 'r', encoding='utf-8') as f:
                                        role_contents.append(f.read().strip())  # 直接使用文件内容，不添加重复名字
                                except Exception as e:
                                    self.safe_log(f"读取角色文件 {file} 失败: {str(e)}")
                
                if role_contents:
                    role_content_str = "\n".join(role_contents)
                    # 更精确的替换逻辑，处理不同情况下的占位符
                    placeholder_variations = [
                        "核心人物(可能未指定)：{characters_involved}",
                        "核心人物：{characters_involved}",
                        "核心人物(可能未指定):{characters_involved}",
                        "核心人物:{characters_involved}"
                    ]
                    
                    for placeholder in placeholder_variations:
                        if placeholder in final_prompt:
                            final_prompt = final_prompt.replace(
                                placeholder,
                                f"核心人物：\n{role_content_str}"
                            )
                            break
                    else:  # 如果没有找到任何已知占位符变体
                        lines = final_prompt.split('\n')
                        for i, line in enumerate(lines):
                            if "核心人物" in line and "：" in line:
                                lines[i] = f"核心人物：\n{role_content_str}"
                                break
                        final_prompt = '\n'.join(lines)

                text_box.insert("0.0", final_prompt)
                # 更新字数函数
                def update_word_count(event=None):
                    text = text_box.get("0.0", "end-1c")
                    text_length = len(text)
                    wordcount_label.configure(text=f"字数：{text_length}")

                text_box.bind("<KeyRelease>", update_word_count)
                text_box.bind("<ButtonRelease>", update_word_count)
                update_word_count()  # 初始化统计

                button_frame = ctk.CTkFrame(dialog)
                button_frame.pack(pady=10)
                def on_confirm():
                    result["prompt"] = text_box.get("1.0", "end").strip()
                    dialog.destroy()
                    event.set()
                def on_cancel():
                    result["prompt"] = None
                    dialog.destroy()
                    event.set()
                btn_confirm = ctk.CTkButton(button_frame, text="确认使用", font=("Microsoft YaHei", 12), command=on_confirm)
                btn_confirm.pack(side="left", padx=10)
                btn_cancel = ctk.CTkButton(button_frame, text="取消请求", font=("Microsoft YaHei", 12), command=on_cancel)
                btn_cancel.pack(side="left", padx=10)
                # 若用户直接关闭弹窗，则调用 on_cancel 处理
                dialog.protocol("WM_DELETE_WINDOW", on_cancel)
                dialog.grab_set()
            self.master.after(0, create_dialog)
            event.wait()  # 等待用户操作完成
            edited_prompt = result["prompt"]
            if edited_prompt is None:
                self.safe_log("❌ 用户取消了草稿生成请求。")
                return

            self.safe_log("开始生成章节草稿...")
            from novel_generator.chapter import generate_chapter_draft
            draft_text = generate_chapter_draft(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                filepath=filepath,
                novel_number=chap_num,
                word_number=word_number,
                temperature=temperature,
                user_guidance=user_guidance,
                characters_involved=char_inv,
                key_items=key_items,
                scene_location=scene_loc,
                time_constraint=time_constr,
                embedding_api_key=embedding_api_key,
                embedding_url=embedding_url,
                embedding_interface_format=embedding_interface_format,
                embedding_model_name=embedding_model_name,
                embedding_retrieval_k=embedding_k,
                interface_format=interface_format,
                max_tokens=max_tokens,
                timeout=timeout_val,
                custom_prompt_text=edited_prompt  # 使用用户编辑后的提示词
            )
            if draft_text:
                self.safe_log(f"✅ 第{chap_num}章草稿生成完成。请在左侧查看或编辑。")
                self.master.after(0, lambda: self.show_chapter_in_textbox(draft_text))
            else:
                self.safe_log("⚠️ 本章草稿生成失败或无内容。")
        except Exception:
            self.handle_exception("生成章节草稿时出错")
        finally:
            self.enable_button_safe(self.btn_generate_chapter)
    threading.Thread(target=task, daemon=True).start()

def finalize_chapter_ui(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径。")
        return

    def task():
        if not messagebox.askyesno("确认", "确定要定稿当前章节吗？"):
            self.enable_button_safe(self.btn_finalize_chapter)
            return

        self.disable_button_safe(self.btn_finalize_chapter)
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)

            embedding_api_key = self.embedding_api_key_var.get().strip()
            embedding_url = self.embedding_url_var.get().strip()
            embedding_interface_format = self.embedding_interface_format_var.get().strip()
            embedding_model_name = self.embedding_model_name_var.get().strip()

            chap_num = self.safe_get_int(self.chapter_num_var, 1)
            word_number = self.safe_get_int(self.word_number_var, 3000)

            self.safe_log(f"开始定稿第{chap_num}章...")

            chapters_dir = os.path.join(filepath, "chapters")
            os.makedirs(chapters_dir, exist_ok=True)
            chapter_file = os.path.join(chapters_dir, f"chapter_{chap_num}.txt")

            edited_text = self.chapter_result.get("0.0", "end").strip()

            # 在写入前获取章节信息
            from chapter_directory_parser import get_chapter_info_from_blueprint
            directory_file = os.path.join(filepath, "Novel_directory.txt")
            blueprint_text = read_file(directory_file)
            chapter_info = get_chapter_info_from_blueprint(blueprint_text, chap_num)
            if not chapter_info:
                chapter_info = {
                    'chapter_purpose': '推进主线',
                    'foreshadowing': '无特殊伏笔',
                    'plot_twist_level': 'Lv.1'
                }

            clear_file_content(chapter_file)
            save_string_to_txt(edited_text, chapter_file)

            finalize_chapter(
                novel_number=chap_num,
                word_number=word_number,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                temperature=temperature,
                filepath=filepath,
                embedding_api_key=embedding_api_key,
                embedding_url=embedding_url,
                embedding_interface_format=embedding_interface_format,
                embedding_model_name=embedding_model_name,
                interface_format=interface_format,
                max_tokens=max_tokens,
                timeout=timeout_val
            )
            self.safe_log(f"✅ 第{chap_num}章定稿完成（已更新前文摘要、角色状态、向量库）。")

            final_text = read_file(chapter_file)
            self.master.after(0, lambda: self.show_chapter_in_textbox(final_text))

            # 如果有重要情节点或冲突，记录到plot_arcs.txt
            plot_arcs_file = os.path.join(filepath, "plot_arcs.txt")
            if not os.path.exists(plot_arcs_file):
                with open(plot_arcs_file, 'w', encoding='utf-8') as f:
                    f.write("=== 剧情要点与未解决冲突记录 ===\n")
            
            with open(plot_arcs_file, 'a', encoding='utf-8') as f:
                f.write(f"\n=== 第{chap_num}章定稿记录 ===\n")
                f.write(f"核心功能：{chapter_info.get('chapter_purpose', '')}\n")
                f.write(f"伏笔设计：{chapter_info.get('foreshadowing', '')}\n")
                f.write(f"颠覆指数：{chapter_info.get('plot_twist_level', '')}\n")

        except Exception:
            self.handle_exception("定稿章节时出错")
        finally:
            self.enable_button_safe(self.btn_finalize_chapter)
    threading.Thread(target=task, daemon=True).start()

def do_consistency_check(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径。")
        return

    def task():
        self.disable_button_safe(self.btn_check_consistency)
        try:
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            interface_format = self.interface_format_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout = self.timeout_var.get()

            chap_num = self.safe_get_int(self.chapter_num_var, 1)
            current_text = self.chapter_result.get("0.0", "end").strip()  # 获取编辑框内容

            self.safe_log("开始一致性审校...")
            result = check_consistency(
                character_state=read_file(os.path.join(filepath, "character_state.txt")),
                global_summary=read_file(os.path.join(filepath, "global_summary.txt")),
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                temperature=temperature,
                interface_format=interface_format,
                max_tokens=max_tokens,
                timeout=timeout,
                filepath=filepath,
                novel_number=chap_num,
                Review_text=current_text  # 传入编辑框内容
            )
            self.safe_log("审校结果：")
            self.safe_log(result)
        except Exception:
            self.handle_exception("审校时出错")
        finally:
            self.enable_button_safe(self.btn_check_consistency)
    threading.Thread(target=task, daemon=True).start()

def import_knowledge_handler(self):
    selected_file = tk.filedialog.askopenfilename(
        title="选择要导入的知识库文件",
        filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
    )
    if selected_file:
        def task():
            self.disable_button_safe(self.btn_import_knowledge)
            try:
                emb_api_key = self.embedding_api_key_var.get().strip()
                emb_url = self.embedding_url_var.get().strip()
                emb_format = self.embedding_interface_format_var.get().strip()
                emb_model = self.embedding_model_name_var.get().strip()

                # 尝试不同编码读取文件
                content = None
                encodings = ['utf-8', 'gbk', 'gb2312', 'ansi']
                for encoding in encodings:
                    try:
                        with open(selected_file, 'r', encoding=encoding) as f:
                            content = f.read()
                            break
                    except UnicodeDecodeError:
                        continue
                    except Exception as e:
                        self.safe_log(f"读取文件时发生错误: {str(e)}")
                        raise

                if content is None:
                    raise Exception("无法以任何已知编码格式读取文件")

                # 创建临时UTF-8文件
                import tempfile
                import os
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as temp:
                    temp.write(content)
                    temp_path = temp.name

                try:
                    self.safe_log(f"开始导入知识库文件: {selected_file}")
                    import_knowledge_file(
                        embedding_api_key=emb_api_key,
                        embedding_url=emb_url,
                        embedding_interface_format=emb_format,
                        embedding_model_name=emb_model,
                        file_path=temp_path,
                        filepath=self.filepath_var.get().strip()
                    )
                    self.safe_log("✅ 知识库文件导入完成。")
                finally:
                    # 清理临时文件
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

            except Exception:
                self.handle_exception("导入知识库时出错")
            finally:
                self.enable_button_safe(self.btn_import_knowledge)

        try:
            thread = threading.Thread(target=task, daemon=True)
            thread.start()
        except Exception as e:
            self.enable_button_safe(self.btn_import_knowledge)
            messagebox.showerror("错误", f"线程启动失败: {str(e)}")

def clear_vectorstore_handler(self):
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径。")
        return

    first_confirm = messagebox.askyesno("警告", "确定要清空本地向量库吗？此操作不可恢复！")
    if first_confirm:
        second_confirm = messagebox.askyesno("二次确认", "你确定真的要删除所有向量数据吗？此操作不可恢复！")
        if second_confirm:
            if clear_vector_store(filepath):
                self.log("已清空向量库。")
            else:
                self.log(f"未能清空向量库，请关闭程序后手动删除 {filepath} 下的 vectorstore 文件夹。")

def show_plot_arcs_ui(self):
    """显示剧情要点窗口"""
    # 检查是否已存在剧情要点窗口
    if hasattr(self, '_plot_window') and self._plot_window is not None:
        try:
            if self._plot_window.winfo_exists():
                self._plot_window.focus_force()
                return
        except:
            pass  # 如果窗口已不存在，继续创建新窗口
    
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径。")
        return
        
    try:
        plot_arcs_file = os.path.join(filepath, "plot_arcs.txt")
        content = read_file(plot_arcs_file) if os.path.exists(plot_arcs_file) else ""
        
        # 先创建窗口但不显示
        plot_window = ctk.CTkToplevel(self.master)
        plot_window.withdraw()  # 先隐藏窗口
        plot_window.title("剧情要点追踪")
        plot_window.geometry("800x600")
        
        # 设置窗口关闭事件
        def on_window_close():
            self._plot_window = None
            plot_window.destroy()
            
        plot_window.protocol("WM_DELETE_WINDOW", on_window_close)
        
        # 创建可编辑的文本框
        text_frame = ctk.CTkFrame(plot_window)
        text_frame.pack(padx=10, pady=10, fill="both", expand=True)
        
        plot_text = ctk.CTkTextbox(text_frame, wrap="word", font=("Microsoft YaHei", 12))
        plot_text.pack(padx=5, pady=5, fill="both", expand=True)
        plot_text.insert("1.0", content)
        
        # 创建底部按钮框
        button_frame = ctk.CTkFrame(plot_window)
        button_frame.pack(padx=10, pady=(0, 10), fill="x")
        
        def refresh_content():
            content = read_file(plot_arcs_file) if os.path.exists(plot_arcs_file) else ""
            plot_text.delete("1.0", "end")
            plot_text.insert("1.0", content)
            
        def save_content():
            try:
                new_content = plot_text.get("1.0", "end-1c")
                clear_file_content(plot_arcs_file)
                save_string_to_txt(new_content, plot_arcs_file)
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {str(e)}")
        
        # 刷新按钮
        refresh_btn = ctk.CTkButton(
            button_frame, 
            text="刷新", 
            command=refresh_content,
            font=("Microsoft YaHei", 12)
        )
        refresh_btn.pack(side="left", padx=5)
        
        # 保存按钮
        save_btn = ctk.CTkButton(
            button_frame, 
            text="保存", 
            command=save_content,
            font=("Microsoft YaHei", 12)
        )
        save_btn.pack(side="left", padx=5)
        
        # 计算主窗口中心位置
        self.master.update_idletasks()
        master_x = self.master.winfo_x()
        master_y = self.master.winfo_y()
        master_width = self.master.winfo_width()
        master_height = self.master.winfo_height()
        
        window_width = 800
        window_height = 600
        
        x = master_x + (master_width - window_width) // 2
        y = master_y + (master_height - window_height) // 4
        
        # 在显示窗口前先保存实例引用
        self._plot_window = plot_window
        
        # 设置窗口位置并显示
        plot_window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        plot_window.transient(self.master)  # 设置为主窗口的子窗口
        plot_window.deiconify()  # 显示窗口
        plot_window.lift()  # 将窗口提升到顶层
        plot_window.focus_set()  # 设置焦点
        
    except Exception as e:
        self._plot_window = None
        self.safe_log(f"显示剧情要点窗口时出错: {str(e)}")
        messagebox.showerror("错误", str(e))

def generate_volume_ui(self):
    """处理生成分卷的UI交互"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先选择保存文件路径")
        return

    def generate_volumes_task(start_from_volume=None, generate_single=False):
        """单独的生成任务线程"""
        try:
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)
            topic = self.topic_text.get("0.0", "end").strip()
            num_chapters = self.safe_get_int(self.num_chapters_var, 10)
            word_number = self.safe_get_int(self.word_number_var, 3000)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()
            characters_involved = self.char_inv_text.get("0.0", "end").strip()
            volume_count = self.safe_get_int(self.volume_count_var, 3)

            self.safe_log(f"开始生成{'下一卷' if generate_single else '后续所有分卷'} ...")
            
            volume_text = Novel_volume_generate(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                llm_model=model_name,
                topic=topic,
                filepath=filepath,
                number_of_chapters=num_chapters,
                word_number=word_number,
                volume_count=volume_count,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_val,
                user_guidance=user_guidance,
                characters_involved=characters_involved,
                start_from_volume=start_from_volume,
                generate_single=generate_single
            )
            
            # 更新界面显示
            self.master.after(0, lambda: self.volume_text.delete("0.0", "end"))
            self.master.after(0, lambda: self.volume_text.insert("0.0", volume_text))
            self.master.after(0, lambda: self.tabview.set("小说分卷"))
            
            if generate_single:
                # 重新获取分卷信息
                new_current, new_total, new_remaining = get_current_volume_info(filepath, volume_count)
                if new_remaining > 0:
                    self.master.after(100, lambda: show_volume_dialog(new_current, new_remaining))
                else:
                    self.safe_log("✅ 所有分卷生成完成")
            else:
                self.safe_log("✅ 后续所有分卷生成完成")
        except Exception as e:
            self.safe_log(f"❌ 生成分卷时发生错误: {str(e)}")
        finally:
            self.enable_button_safe(self.btn_generate_volume)

    def show_volume_dialog(current_vol, remaining_vol):
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("分卷生成")
        dialog.geometry("400x200")
        dialog.transient(self.master)
        dialog.grab_set()

        if (current_vol > 0):  # 已有分卷的情况
            info_text = f"当前已生成 {current_vol} 卷，还需生成 {remaining_vol} 卷"
        else:  # 无分卷的情况
            info_text = f"准备生成分卷，计划总共 {self.safe_get_int(self.volume_count_var, 3)} 卷"

        info_label = ctk.CTkLabel(
            dialog,
            text=f"{info_text}\n请选择生成方式：",
            font=("Microsoft YaHei", 12)
        )
        info_label.pack(pady=20)

        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=20)

        def on_dialog_choice(choice):
            dialog.destroy()
            self.disable_button_safe(self.btn_generate_volume)
            if choice == "all":
                threading.Thread(
                    target=lambda: generate_volumes_task(current_vol + 1 if current_vol > 0 else 0, False),
                    daemon=True
                ).start()
            elif choice == "single":
                threading.Thread(
                    target=lambda: generate_volumes_task(current_vol + 1, True),
                    daemon=True
                ).start()

        if current_vol > 0:  # 已有分卷时显示不同按钮
            ctk.CTkButton(
                btn_frame,
                text="生成后续所有分卷",
                command=lambda: on_dialog_choice("all"),
                font=("Microsoft YaHei", 12)
            ).pack(pady=5)

            ctk.CTkButton(
                btn_frame,
                text="生成下一分卷",
                command=lambda: on_dialog_choice("single"),
                font=("Microsoft YaHei", 12)
            ).pack(pady=5)
        else:  # 无分卷时显示不同按钮
            ctk.CTkButton(
                btn_frame,
                text="生成第一卷大纲",
                command=lambda: on_dialog_choice("single"),
                font=("Microsoft YaHei", 12)
            ).pack(pady=5)

            ctk.CTkButton(
                btn_frame,
                text="生成所有分卷",
                command=lambda: on_dialog_choice("all"),
                font=("Microsoft YaHei", 12)
            ).pack(pady=5)

        ctk.CTkButton(
            btn_frame,
            text="退出",
            command=dialog.destroy,
            font=("Microsoft YaHei", 12)
        ).pack(pady=5)

        # 添加对话框关闭事件处理
        def on_dialog_close():
            dialog.destroy()
            self.enable_button_safe(self.btn_generate_volume)  # 重新启用按钮

        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)

    def task():
        """主任务函数"""
        self.disable_button_safe(self.btn_generate_volume)
        try:
            volume_count = self.safe_get_int(self.volume_count_var, 3)
            from novel_generator.volume import get_current_volume_info
            current_volume, total_volumes, remaining_volumes = get_current_volume_info(filepath, volume_count)
            
            if current_volume >= volume_count:
                messagebox.showinfo("提示", "所有分卷已生成完成")
                self.enable_button_safe(self.btn_generate_volume)
            else:
                show_volume_dialog(current_volume, remaining_volumes)

        except Exception as e:
            self.safe_log(f"❌ 检查分卷状态时发生错误: {str(e)}")
            self.enable_button_safe(self.btn_generate_volume)

    threading.Thread(target=task, daemon=True).start()

def analyze_chapter_status(filepath: str) -> tuple:
    """分析当前章节目录的状态
    返回：(最后章节号, 当前卷号, 是否在卷尾)
    """
    try:
        # 1. 获取最新章节号
        last_chapter, _, _ = analyze_directory_status(filepath)
        
        # 2. 分析分卷范围
        volumes = analyze_volume_range(filepath)
        if not volumes:
            return 0, 1, False
            
        # 3. 找到当前章节所在卷
        if last_chapter == 0:
            return 0, 1, False
            
        current_vol, is_volume_end = find_current_volume(last_chapter, volumes)
        return last_chapter, current_vol, is_volume_end
                
    except Exception as e:
        logging.error(f"分析章节状态时出错: {str(e)}")
        return 0, 1, False

def show_blueprint_dialog(self):
    try:
        filepath = self.filepath_var.get().strip()
        
        last_chapter, current_vol, is_volume_end = analyze_chapter_status(filepath)
        
        dialog = ctk.CTkToplevel(self.master)
        dialog.title("章节目录生成")
        dialog.geometry("400x200")
        dialog.transient(self.master)
        dialog.grab_set()
        
        # 根据状态设置显示信息和按钮
        if last_chapter == 0:
            info_text = "准备生成第一卷章节目录"
            btn1_text = "生成第一卷章节目录"
            next_vol = 1
        elif is_volume_end:
            info_text = f"第{current_vol}卷已完成，准备生成第{current_vol + 1}卷"
            btn1_text = f"生成第{current_vol + 1}卷章节目录"
            next_vol = current_vol + 1
        else:
            info_text = f"继续生成第{current_vol}卷章节目录"
            btn1_text = f"继续生成第{current_vol}卷目录"
            next_vol = current_vol

        info_label = ctk.CTkLabel(
            dialog,
            text=f"{info_text}\n请选择生成方式：",
            font=("Microsoft YaHei", 12)
        )
        info_label.pack(pady=20)

        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=20)

        def on_dialog_choice(choice):
            dialog.destroy()
            self.disable_button_safe(self.btn_generate_directory)
            if choice == "all":
                threading.Thread(
                    target=lambda: self.generate_blueprints_task(next_vol, False),
                    daemon=True
                ).start()
            elif choice == "single":
                threading.Thread(
                    target=lambda: self.generate_blueprints_task(next_vol, True),
                    daemon=True
                ).start()

        # 生成按钮
        ctk.CTkButton(
            btn_frame,
            text=btn1_text,
            command=lambda: on_dialog_choice("single"),
            font=("Microsoft YaHei", 12)
        ).pack(pady=5)

        ctk.CTkButton(
            btn_frame,
            text="生成所有后续章节目录",
            command=lambda: on_dialog_choice("all"),
            font=("Microsoft YaHei", 12)
        ).pack(pady=5)

        ctk.CTkButton(
            btn_frame,
            text="退出",
            command=dialog.destroy,
            font=("Microsoft YaHei", 12)
        ).pack(pady=5)
    except Exception as e:
        self.safe_log(f"❌ 显示章节目录生成对话框时出错: {str(e)}")
        self.enable_button_safe(self.btn_generate_directory)

def generate_blueprints_task(self, start_from_volume: int, generate_single: bool):  # 重命名这里
    """执行章节目录生成任务"""
    filepath = self.filepath_var.get().strip()
    try:
        self.disable_button_safe(self.btn_generate_directory)
        # 添加volume_count变量
        volume_count = self.safe_get_int(self.volume_count_var, 3)
        interface_format = self.interface_format_var.get().strip()
        api_key = self.api_key_var.get().strip()
        base_url = self.base_url_var.get().strip()
        model_name = self.model_name_var.get().strip()
        number_of_chapters = self.safe_get_int(self.num_chapters_var, 10)
        temperature = self.temperature_var.get()
        max_tokens = self.max_tokens_var.get()
        timeout_val = self.safe_get_int(self.timeout_var, 600)
        user_guidance = self.user_guide_text.get("0.0", "end").strip()

        def generate_task():
            try:
                self.safe_log(f"开始生成{'当前卷' if generate_single else '所有卷'}章节目录...")
                result = Chapter_blueprint_generate(
                    interface_format=interface_format,
                    api_key=api_key,
                    base_url=base_url,
                    llm_model=model_name,
                    number_of_chapters=number_of_chapters,
                    filepath=filepath,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_val,
                    user_guidance=user_guidance,
                    start_from_volume=start_from_volume,
                    generate_single=generate_single
                )
                self.safe_log(f"❌ 生成章节目录时发生错误: {str(e)}")
            finally:
                self.enable_button_safe(self.btn_generate_directory)

        # 在新线程中执行生成任务
        threading.Thread(target=generate_task, daemon=True).start()

    except Exception as e:
        self.safe_log(f"❌ 启动生成任务时发生错误: {str(e)}")
        self.enable_button_safe(self.btn_generate_directory)

def rewrite_chapter_ui(self):
    """处理改写章节的UI交互"""
    filepath = self.filepath_var.get().strip()
    if not filepath:
        messagebox.showwarning("警告", "请先配置保存文件路径。")
        return

    def task():
        if not messagebox.askyesno("确认", "确定要改写当前章节吗？"):
            return

        self.disable_button_safe(self.btn_rewrite_chapter)
        try:
            current_text = self.chapter_result.get("0.0", "end").strip()
            if not current_text:
                self.safe_log("⚠️ 当前没有可修改的内容。")
                return

            # 获取基本参数
            interface_format = self.interface_format_var.get().strip()
            api_key = self.api_key_var.get().strip()
            base_url = self.base_url_var.get().strip()
            model_name = self.model_name_var.get().strip()
            temperature = self.temperature_var.get()
            max_tokens = self.max_tokens_var.get()
            timeout_val = self.safe_get_int(self.timeout_var, 600)
            chap_num = self.safe_get_int(self.chapter_num_var, 1)
            word_number = self.safe_get_int(self.word_number_var, 3000)
            user_guidance = self.user_guide_text.get("0.0", "end").strip()

            # 弹出改写对话框
            result = {"prompt": None}
            event = threading.Event()

            def create_dialog():
                # 构造改写提示词
                try:
                    rewritten = rewrite_chapter(
                        api_key=api_key,
                        base_url=base_url,
                        model_name=model_name,
                        filepath=filepath,
                        novel_number=chap_num,
                        word_number=word_number,
                        temperature=temperature,
                        interface_format=interface_format,
                        max_tokens=max_tokens,
                        timeout=timeout_val,
                        current_text=current_text,
                        user_guidance=user_guidance
                    )
                    if not rewritten:
                        self.safe_log("⚠️ 无法生成改写提示词")
                        event.set()
                        return

                    dialog = ctk.CTkToplevel(self.master)
                    dialog.title("改写章节提示词（可编辑）")
                    dialog.geometry("600x400")
                    dialog.transient(self.master)
                    dialog.grab_set()

                    text_box = ctk.CTkTextbox(dialog, wrap="word", font=("Microsoft YaHei", 12))
                    text_box.pack(fill="both", expand=True, padx=10, pady=10)
                    text_box.insert("0.0", rewritten)

                    # 字数统计标签
                    wordcount_label = ctk.CTkLabel(dialog, text=f"字数：{len(rewritten)}", font=("Microsoft YaHei", 12))
                    wordcount_label.pack(side="left", padx=(10,0), pady=5)

                    def update_word_count(event=None):
                        text = text_box.get("0.0", "end-1c")
                        text_length = len(text)
                        wordcount_label.configure(text=f"字数：{text_length}")

                    text_box.bind("<KeyRelease>", update_word_count)
                    text_box.bind("<ButtonRelease>", update_word_count)

                    button_frame = ctk.CTkFrame(dialog)
                    button_frame.pack(pady=10)

                    def on_confirm():
                        result["prompt"] = text_box.get("1.0", "end").strip()
                        dialog.destroy()
                        event.set()

                    def on_cancel():
                        result["prompt"] = None
                        dialog.destroy()
                        event.set()

                    btn_confirm = ctk.CTkButton(button_frame, text="确认使用", font=("Microsoft YaHei", 12), command=on_confirm)
                    btn_confirm.pack(side="left", padx=10)
                    btn_cancel = ctk.CTkButton(button_frame, text="取消请求", font=("Microsoft YaHei", 12), command=on_cancel)
                    btn_cancel.pack(side="left", padx=10)
                    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

                except Exception as e:
                    self.safe_log(f"创建对话框失败: {str(e)}")
                    event.set()

            self.master.after(0, create_dialog)
            event.wait()  
            edited_prompt = result["prompt"]
            
            if edited_prompt:
                # 使用编辑后的提示词调用LLM生成改写内容
                llm_adapter = create_llm_adapter(
                    interface_format=interface_format,
                    base_url=base_url,
                    model_name=model_name,
                    api_key=api_key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_val
                )
                rewritten_text = invoke_with_cleaning(llm_adapter, edited_prompt)
                if rewritten_text:
                    self.master.after(0, lambda: self.chapter_result.delete("0.0", "end"))
                    self.master.after(0, lambda: self.chapter_result.insert("0.0", rewritten_text))
                    self.safe_log("✅ 章节内容已更新")
                else:
                    self.safe_log("⚠️ 改写请求未返回有效内容")
            else:
                self.safe_log("❌ 用户取消了改写")

        except Exception as e:
            self.handle_exception(f"改写章节时出错: {str(e)}")
        finally:
            self.enable_button_safe(self.btn_rewrite_chapter)

    threading.Thread(target=task, daemon=True).start()
