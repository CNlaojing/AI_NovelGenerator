# -*- coding: utf-8 -*-
import threading
import time
import logging
import os
import ctypes
import re
import glob
from utils import read_file, save_string_to_txt
# 移除对 generation_logic 的依赖
# from novel_generator.generation_logic import (
#     generate_chapter_draft_logic, consistency_check_logic,
#     rewrite_chapter_logic, finalize_chapter_logic
# )
from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.volume import Novel_volume_generate
from novel_generator.chapter_blueprint import Chapter_blueprint_generate, analyze_directory_status, analyze_volume_range, find_current_volume

# 导入需要复用的核心功能
from novel_generator.consistency_checker import do_consistency_check as cc_do_consistency_check
from novel_generator.rewrite import rewrite_chapter
# from novel_generator.generation_logic import generate_chapter_draft_logic # 不再需要
from novel_generator.character_generator import generate_characters_for_draft
from novel_generator.json_utils import load_store # Replace vectorstore with json_utils
from novel_generator.volume import extract_volume_outline, find_volume_for_chapter
from prompt_definitions import chapter_draft_prompt, Chapter_Review_prompt
from llm_adapters import BaseLLMAdapter
from .common import execute_with_polling, SingleProviderExecutionError
from config_manager import get_project_continue_state, save_project_continue_state, clear_project_continue_state

class WorkflowEngine:
    """
    小说生成引擎核心。
    负责管理整个自动化生成流程，包括状态管理、任务调度和与UI的通信。
    使用回调函数与 CustomTkinter UI 进行交互。
    """
    def __init__(self, gui_app, status_callback, log_callback, start_callback, finish_callback):
        self.gui_app = gui_app
        self.status_callback = status_callback
        self.log_callback = log_callback
        self.start_callback = start_callback
        self.finish_callback = finish_callback
        
        self._is_running = False
        self.thread: threading.Thread | None = None
        self.active_llm_adapter: BaseLLMAdapter | None = None
        self.rewrite_counts = {} # 用于跟踪每个章节的改写次数
        self.step_display_map = {
            "generate_volume": "生成分卷",
            "generate_blueprint": "生成目录",
            "consistency_check": "一致性审校",
            "rewrite": "改写章节",
            "finalize": "定稿章节"
        }

    def set_active_adapter(self, adapter):
        """回调函数，用于设置当前活动的LLM适配器。"""
        self.active_llm_adapter = adapter

    def is_running(self):
        return self._is_running

    def force_stop(self):
        """
        强制终止工作流线程。
        这是一种激进的方法，通过向线程注入一个异常来立即停止它。
        """
        if not self.thread or not self.thread.is_alive():
            self._log("引擎线程未运行，无需停止。")
            return

        thread_id = self.thread.ident
        if thread_id is None:
            self._log("无法获取线程ID，无法停止。")
            return

        self._log("正在发送强制停止信号...")
        try:
            # 向指定线程ID注入SystemExit异常
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_id), ctypes.py_object(SystemExit))
            if res == 0:
                self._log("错误：无效的线程ID。")
            elif res > 1:
                # 如果有多个线程受到影响，撤销操作
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_id), 0)
                self._log("错误：向多个线程发送了异常，操作已撤销。")
            else:
                self._log("✅ 强制停止信号已成功发送。")
        except Exception as e:
            self._log(f"❌ 发送强制停止信号时出错: {e}")
        finally:
            # 尝试关闭活动的适配器连接
            if self.active_llm_adapter:
                self._log("正在尝试关闭活动的LLM连接...")
                try:
                    self.active_llm_adapter.close()
                except Exception as close_e:
                    self._log(f"⚠️ 关闭LLM连接时出错: {close_e}")

    def _log(self, message, stream=False, replace_last_line=False):
        """安全地记录日志到UI"""
        self.gui_app.master.after(0, lambda: self.log_callback(message, stream=stream, replace_last_line=replace_last_line))

    def _update_status(self, status):
        """安全地更新UI状态"""
        self.gui_app.master.after(0, self.status_callback, status)

    def run_workflow_for_chapters(self, workflow_params, workflow_steps):
        """
        为指定范围的章节启动工作流。
        """
        if self._is_running:
            self._log("引擎已经在运行中。")
            return

        self._is_running = True
        
        self.gui_app.master.after(0, self.start_callback)
        self._log("工作流引擎启动...")
        
        self.thread = threading.Thread(
            target=self._main_loop,
            args=(workflow_params, workflow_steps),
            daemon=True
        )
        self.thread.start()


    def _main_loop(self, workflow_params, workflow_steps):
        """引擎的主工作循环"""
        self.rewrite_counts = {} # 每次运行工作流时重置计数器
        
        try:
            # 从 workflow_params 获取所有需要的参数
            num_chapters_to_generate = workflow_params.get("num_chapters_to_generate", 1)
            volume_char_weight = workflow_params.get("volume_char_weight", 91)
            blueprint_num_chapters = workflow_params.get("blueprint_num_chapters", 20)
            start_chapter_override = workflow_params.get("start_chapter")
            
            # 新增参数
            review_pass_finalize = workflow_params.get("review_pass_finalize", False)
            rewrite_then_review = workflow_params.get("rewrite_then_review", False)
            word_count_min = workflow_params.get("word_count_min", 2500)
            word_count_max = workflow_params.get("word_count_max", 3500)
            force_finalize_after_rewrite = workflow_params.get("force_finalize_after_rewrite", False)
            force_finalize_count = workflow_params.get("force_finalize_count", 3)
            continue_from_last_run = workflow_params.get("continue_from_last_run", False)

            project_path = workflow_params.get("project_path")
            if not project_path or not os.path.isdir(project_path):
                self._log("错误：项目路径无效。")
                return

            self._log(f"工作流已启动，目标生成章节数: {num_chapters_to_generate}。")
            self._log(f"执行步骤: {', '.join(workflow_steps) or '无'}")

            total_chapters = workflow_params.get("num_chapters_total", 0)
            
            # --- 重构后的启动逻辑 (需求 3 & 4) ---
            auto_history_chapters = workflow_params.get("auto_history_chapters", 2)
            start_chapter_param = workflow_params.get("start_chapter")
            start_step_param = workflow_params.get("start_step")
            force_regenerate_draft_from_ui = workflow_params.get("force_regenerate_draft", False)
            
            chap_num = 1
            start_step_index = 0
            force_regenerate = False
            generated_count = 0

            # 模式判断
            if start_chapter_param is not None:
                # --- 指定章节模式 ---
                self._log(f"ℹ️ 用户指定从第 {start_chapter_param} 章开始。")
                chap_num = start_chapter_param
                force_regenerate = force_regenerate_draft_from_ui

                # 验证章节有效性 (需求3)
                draft_path, _ = self._get_draft_path(project_path, chap_num)
                if not os.path.exists(draft_path):
                    self._log(f"  -> 指定的第 {chap_num} 章草稿不存在。")
                    if chap_num > 1:
                        prev_draft_path, _ = self._get_draft_path(project_path, chap_num - 1)
                        if not os.path.exists(prev_draft_path):
                            self._log(f"❌ 错误：指定的第 {chap_num} 章及其前一章（第 {chap_num - 1} 章）的草稿均不存在。无法确定生成序列，工作流中止。")
                            return # 中止
                        else:
                             self._log(f"  -> 前一章（第 {chap_num - 1} 章）存在，将继续生成第 {chap_num} 章。")
                    # 如果 chap_num 是 1 且不存在，是正常情况，会继续生成
                
                # 确定起始步骤
                if start_step_param and start_step_param in workflow_steps:
                    start_step_index = workflow_steps.index(start_step_param)
                    display_step_name = self.step_display_map.get(start_step_param, start_step_param)
                    self._log(f"  -> 将从步骤 '{display_step_name}' 开始。")
                
                if force_regenerate:
                    self._log("  -> 已选择“生成草稿”，将强制重新生成本章。")

            else:
                # --- 自动模式 ---
                self._log("ℹ️ 未指定起始章节，进入自动分析模式。")
                chap_num = self._determine_start_chapter(workflow_params)
                start_step_index = 0 # 需求4: 自动模式下，无视手动选择的步骤
                self._log(f"  -> 分析完成，将从第 {chap_num} 章开始。")
                self._update_status(f"分析完成，将从第 {chap_num} 章开始处理。")

            time.sleep(2)

            while True:

                if chap_num > total_chapters:
                    self._log(f"已达到项目设定的总章节数 ({total_chapters})，工作流完成。")
                    break
                
                if generated_count >= num_chapters_to_generate:
                    self._log(f"已完成本次设定的生成任务 ({num_chapters_to_generate}章)。")
                    break

                self._log("\n" + "-"*20 + f" 开始处理第 {chap_num} 章 " + "-"*20)
                self._update_status(f"准备处理第 {chap_num} 章...")

                # --- 新增逻辑：同步UI编辑框内容 ---
                # 仅在工作流从用户指定的章节启动时，才检查UI编辑框
                start_chapter_param = workflow_params.get("start_chapter")
                if start_chapter_param is not None and start_chapter_param == chap_num:
                    self._log(f"  -> 正在检查主界面编辑框内容（目标章节: {chap_num}）...")
                    try:
                        # 从 self.gui_app 访问主编辑框 chapter_result
                        ui_text = self.gui_app.chapter_result.get("1.0", "end-1c").strip()
                        if ui_text:
                            draft_path, title = self._get_draft_path(project_path, chap_num)
                            os.makedirs(os.path.dirname(draft_path), exist_ok=True)
                            
                            # 从UI获取的纯文本不包含标题，需要从文件或蓝图获取标题并组合
                            # _get_draft_path 已经返回了标题
                            full_content = f"第{chap_num}章 {title}\n\n{ui_text}"
                            
                            existing_content = ""
                            if os.path.exists(draft_path):
                                existing_content = read_file(draft_path)
                            
                            # 只有当内容不同时才保存，避免不必要的文件写入
                            if full_content.strip() != existing_content.strip():
                                self._log(f"  -> 检测到编辑框有已修改内容，将覆盖保存文件: {os.path.basename(draft_path)}")
                                save_string_to_txt(full_content, draft_path)
                            else:
                                self._log("  -> 编辑框内容与文件一致，无需保存。")
                        else:
                            self._log("  -> 主界面编辑框为空，将使用文件内容。")
                    except Exception as e:
                        self._log(f"  -> ⚠️ 检查UI编辑框时出错: {e}")
                # --- 同步逻辑结束 ---

                # 2. 检查并生成大纲和目录
                blueprints_ok = True
                if "generate_volume" in workflow_steps or "generate_blueprint" in workflow_steps:
                    try:
                        self._ensure_blueprints_exist(
                            project_path, chap_num,
                            "generate_volume" in workflow_steps, "generate_blueprint" in workflow_steps,
                            volume_char_weight, blueprint_num_chapters, workflow_params
                        )
                        # --- 新增检查：确认蓝图是否真的已生成 ---
                        directory_content_after = read_file(os.path.join(project_path, "章节目录.txt"))
                        chapter_info_after = get_chapter_info_from_blueprint(directory_content_after, chap_num)
                        if not chapter_info_after:
                            self._log(f"❌ 验证失败：第 {chap_num} 章的蓝图未能成功生成。")
                            blueprints_ok = False
                            
                    except Exception as e:
                        self._log(f"❌ 准备大纲或目录时出错: {e}，跳过此章节。")
                        logging.error(f"准备蓝图时出错: {e}", exc_info=True)
                        blueprints_ok = False
                
                if not blueprints_ok:
                    self._log(f"  -> 因蓝图准备失败，中止工作流。")
                    break # 中止整个工作流

                # 3. 检查草稿是否存在，如果不存在则生成
                draft_path, title = self._ensure_draft_exists(project_path, chap_num, workflow_params, auto_history_chapters, force_regenerate=force_regenerate)
                if force_regenerate:
                    force_regenerate = False
                if not draft_path:
                    self._log(f"无法为第 {chap_num} 章生成草稿，中止工作流。")
                    break # 中止整个工作流
                
                # 4. 按顺序执行工作流步骤 (使用动态列表)
                current_steps = list(workflow_steps) # 创建副本以便动态修改
                step_index = start_step_index # 从计算出的起始步骤开始
                start_step_index = 0 # 重置，确保下一章从头开始
                any_step_failed = False

                while step_index < len(current_steps):
                    step = current_steps[step_index]
                    
                    # --- 关键修复：在步骤开始前就保存当前状态 ---
                    display_step_name = self.step_display_map.get(step, step)
                    save_project_continue_state(project_path, chap_num, step)
                    self._log(f"\n--- 步骤: {display_step_name} (状态已保存) ---")
                    
                    success = False
                    result_data = None # 用于从步骤函数接收返回数据

                    try:
                        if step in ["generate_volume", "generate_blueprint"]:
                            success = True
                            display_step_name = self.step_display_map.get(step, step)
                            self._log(f"步骤 '{display_step_name}' 已在蓝图准备阶段完成。")
                        elif step == "consistency_check":
                            success, review_decision = self._run_consistency_check(project_path, chap_num, title, workflow_params, word_count_min, word_count_max)
                            if success and review_pass_finalize:
                                if review_decision == "通过":
                                    self._log("✅ 审校判定为“通过”，且已启用“审校通过直接定稿”，将跳过改写并直接进入定稿。")
                                    # 从当前步骤之后，移除所有 'rewrite' 和 'consistency_check'
                                    remaining_steps = current_steps[step_index + 1:]
                                    new_remaining = [s for s in remaining_steps if s not in ['rewrite', 'consistency_check']]
                                    
                                    # 确保 'finalize' 在流程中
                                    if 'finalize' not in new_remaining:
                                        new_remaining.append('finalize')
                                        
                                    current_steps = current_steps[:step_index + 1] + new_remaining
                                else: # 审校未通过
                                    self._log("ℹ️ 审校未通过，将安排再次改写。")
                                    # 检查后续步骤中是否已有“改写”，如果没有，则插入一个
                                    # 这确保了在“改写后重新审校”的循环中，失败后能再次改写
                                    if "rewrite" not in current_steps[step_index + 1:]:
                                        current_steps.insert(step_index + 1, "rewrite")
                        elif step == "rewrite":
                            success = self._run_rewrite(project_path, chap_num, title, workflow_params, word_count_min, word_count_max)
                            if success:
                                # 成功改写后，更新计数器
                                self.rewrite_counts[chap_num] = self.rewrite_counts.get(chap_num, 0) + 1
                                self._log(f"  -> 第 {chap_num} 章已成功改写 {self.rewrite_counts[chap_num]} 次。")

                                # 检查是否达到强制定稿条件
                                if force_finalize_after_rewrite and self.rewrite_counts[chap_num] >= force_finalize_count:
                                    self._log(f"ℹ️ 已达到 {force_finalize_count} 次改写上限，将跳过后续审校，直接定稿。")
                                    # 从当前步骤之后，移除所有 'rewrite' 和 'consistency_check'
                                    remaining_steps = current_steps[step_index + 1:]
                                    new_remaining = [s for s in remaining_steps if s not in ['rewrite', 'consistency_check']]
                                    current_steps = current_steps[:step_index + 1] + new_remaining
                                elif rewrite_then_review:
                                    self._log("ℹ️ 已启用“改写完成后重新审校”，将在下一步重新执行一致性检查。")
                                    current_steps.insert(step_index + 1, "consistency_check")
                        elif step == "finalize":
                            success = self._run_finalize(project_path, chap_num, title, workflow_params)
                        
                        if not success:
                            display_step_name = self.step_display_map.get(step, step)
                            self._log(f"❌ 第 {chap_num} 章在步骤 '{display_step_name}' 中失败，中止工作流。")
                            # 失败时，状态已在步骤开始前保存，无需额外操作
                            any_step_failed = True
                            break
                        else:
                            display_step_name = self.step_display_map.get(step, step)
                            self._log(f"✅ 步骤 '{display_step_name}' 完成。")
                            # --- 状态保存逻辑已移至步骤开始前 ---

                    except Exception as e:
                        self._log(f"❌ 在执行步骤 '{step}' 时发生意外错误: {e}", level="error")
                        logging.error(f"执行步骤 '{step}' 时出错:", exc_info=True)
                        any_step_failed = True
                        break
                    
                    step_index += 1 # 移动到下一个步骤
                
                if any_step_failed:
                    self._log("  -> 因步骤失败，工作流已中止。")
                    break
                
                # 暂停一下，给UI和其他线程响应时间
                time.sleep(1)
                
                generated_count += 1
                chap_num += 1 # 处理完当前章节后，移至下一章
            
            self._log("所有章节处理完毕。")
            self._update_status("工作流完成。")
            # 正常完成后，清除继续状态
            clear_project_continue_state(project_path)

        except SystemExit:
            # 捕获由 force_stop 注入的异常
            self._log("引擎已被强制停止。")
            self._update_status("引擎已停止。")
        except Exception as e:
            logging.error(f"工作流引擎发生严重错误: {e}", exc_info=True)
            self._log(f"严重错误: {e}")
            self._update_status("引擎因错误而停止。")
        finally:
            self._is_running = False
            # 确保在任何情况下都尝试关闭活动的适配器
            if self.active_llm_adapter:
                self._log("工作流结束，正在关闭活动的LLM连接...")
                try:
                    self.active_llm_adapter.close()
                except Exception as close_e:
                    self._log(f"⚠️ 关闭LLM连接时出错: {close_e}")
                self.active_llm_adapter = None # 清理活动的适配器
            
            self.gui_app.master.after(0, self.finish_callback)
            # 如果不是用户请求停止（例如，发生错误），也保留状态
            self._log("引擎已停止。")

    def _get_draft_path(self, project_path, chap_num):
        """辅助函数，用于获取给定章节号的草稿文件路径和标题。"""
        draft_dir = os.path.join(project_path, "章节正文")
        # 尝试从目录中获取标题
        directory_content = read_file(os.path.join(project_path, "章节目录.txt"))
        chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
        title = chapter_info['chapter_title'] if chapter_info else f'第{chap_num}章'
        
        draft_filename = f"第{chap_num}章 {title}.txt"
        draft_path = os.path.join(draft_dir, draft_filename)
        return draft_path, title

    def _get_history_chapters_content(self, project_path, current_chap_num, num_history_chapters):
        """获取指定数量的历史章节内容。"""
        if num_history_chapters <= 0:
            return "(未提取历史章节)"

        self._log(f"  -> 正在提取 {num_history_chapters} 章历史内容...")
        history_contents = []
        for i in range(num_history_chapters, 0, -1):
            chap_to_find = current_chap_num - i
            if chap_to_find <= 0:
                continue
            
            # 使用 glob 模糊匹配文件名，因为标题可能变化
            draft_dir = os.path.join(project_path, "章节正文")
            files = glob.glob(os.path.join(draft_dir, f"第{chap_to_find}章*.txt"))
            if files:
                try:
                    content = read_file(files[0])
                    history_contents.append(f"--- 历史章节：{os.path.basename(files[0])} ---\n{content}\n")
                    self._log(f"    -> 已加载: {os.path.basename(files[0])}")
                except Exception as e:
                    self._log(f"    -> ❌ 读取历史章节 {chap_to_find} 失败: {e}")
            else:
                self._log(f"    -> ℹ️ 未找到历史章节 {chap_to_find} 的文件。")

        if not history_contents:
            return "(未找到任何历史章节内容)"
        
        return "\n".join(history_contents)

    def _ensure_draft_exists(self, project_path, chap_num, workflow_params, auto_history_chapters, force_regenerate=False):
        """确保章节草稿存在，如果不存在则生成它。"""
        draft_dir = os.path.join(project_path, "章节正文")
        os.makedirs(draft_dir, exist_ok=True)

        draft_path, title = self._get_draft_path(project_path, chap_num)

        if force_regenerate and os.path.exists(draft_path):
            self._log(f"ℹ️ 强制重新生成第 {chap_num} 章，将删除现有草稿。")
            try:
                os.remove(draft_path)
                self._log(f"  -> 已删除文件: {os.path.basename(draft_path)}")
            except Exception as e:
                self._log(f"  -> ❌ 删除现有草稿失败: {e}")
        if force_regenerate and os.path.exists(draft_path):
            self._log(f"ℹ️ 强制重新生成第 {chap_num} 章，将删除现有草稿。")
            try:
                os.remove(draft_path)
                self._log(f"  -> 已删除文件: {os.path.basename(draft_path)}")
            except Exception as e:
                self._log(f"  -> ❌ 删除现有草稿失败: {e}")

        if os.path.exists(draft_path):
            self._log(f"第 {chap_num} 章草稿已存在，跳过生成。")
            return draft_path, title

        self._log(f"第 {chap_num} 章草稿不存在，开始生成...")
        self._update_status(f"正在生成第 {chap_num} 章草稿...")

        try:
            # --- 1. 获取上下文信息 ---
            self._log("正在准备上下文信息...")
            directory_file = os.path.join(project_path, "章节目录.txt")
            directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""
            if not directory_content:
                self._log("❌ 错误: 章节目录.txt 不存在或为空。")
                return None, None

            volume_file = os.path.join(project_path, "分卷大纲.txt")
            volume_content = read_file(volume_file) if os.path.exists(volume_file) else ""
            if not volume_content:
                self._log("❌ 错误: 分卷大纲.txt 不存在或为空。")
                return None, None

            global_summary_file = os.path.join(project_path, "前情摘要.txt")
            global_summary = read_file(global_summary_file) if os.path.exists(global_summary_file) else ""

            current_chapter_blueprint_match = re.search(rf"^第{chap_num}章.*?(?=^第\d+章|\Z)", directory_content, re.MULTILINE | re.DOTALL)
            current_chapter_blueprint = current_chapter_blueprint_match.group(0).strip() if current_chapter_blueprint_match else ""
            next_chapter_blueprint_match = re.search(rf"^第{chap_num + 1}章.*?(?=^第\d+章|\Z)", directory_content, re.MULTILINE | re.DOTALL)
            next_chapter_blueprint = next_chapter_blueprint_match.group(0).strip() if next_chapter_blueprint_match else ""

            actual_volume_number = find_volume_for_chapter(volume_content, chap_num)
            volume_outline = extract_volume_outline(volume_content, actual_volume_number)

            # --- 2. 准备角色信息 ---
            self._log("正在准备角色信息...")
            embedding_adapter = None # 禁用嵌入模型

            chapter_info_for_char_gen = {
                'novel_number': chap_num, 'chapter_title': title,
                'genre': workflow_params.get("genre"),
                'volume_count': workflow_params.get("volume_count"),
                'num_chapters': workflow_params.get("num_chapters_total"),
                'volume_number': actual_volume_number,
                'word_number': workflow_params.get("word_number"),
                'topic': workflow_params.get("topic"),
                'user_guidance': workflow_params.get("user_guidance"),
                'global_summary': global_summary, 'volume_outline': volume_outline,
                'current_chapter_blueprint': current_chapter_blueprint
            }
            
            setting_characters = execute_with_polling(
                gui_app=self.gui_app,
                step_name="生成草稿_生成角色信息",
                target_func=generate_characters_for_draft,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False,
                chapter_info=chapter_info_for_char_gen,
                filepath=project_path
            )

            if setting_characters is None:
                self._log("❌ 生成角色信息失败，已尝试所有可用配置。")
                return None, None

            # --- 3. 检索伏笔历史 ---
            self._log("正在检索伏笔历史...")
            knowledge_context = ""
            foreshadowing_ids = []
            # --- 修复：在伏笔块中查找所有ID，然后去重 ---
            if current_chapter_blueprint:
                # 1. 定位伏笔条目块
                foreshadowing_block_match = re.search(r'├─伏笔条目：([\s\S]*?)(?=\n[├└]─[\u4e00-\u9fa5]|\Z)', current_chapter_blueprint)
                if foreshadowing_block_match:
                    foreshadowing_block = foreshadowing_block_match.group(1)
                    # 2. 在块内查找所有ID
                    all_ids_in_block = re.findall(r'([A-Z]{1,2}F\d+)', foreshadowing_block)
                    # 3. 去重
                    if all_ids_in_block:
                        foreshadowing_ids = sorted(list(set(all_ids_in_block)))
                else:
                    # 保险措施：如果找不到区块，则全局搜索
                    foreshadowing_ids = sorted(list(set(re.findall(r'([A-Z]{1,2}F\d+)', current_chapter_blueprint))))

            if foreshadowing_ids:
                self._log(f"  -> 本章涉及伏笔: {', '.join(foreshadowing_ids)}")
                foreshadowing_store = load_store(project_path, "foreshadowing_collection")
                if foreshadowing_store:
                    retrieved_foreshadows = []
                    for fb_id in foreshadowing_ids:
                        self._log(f"    -> 正在检索伏笔 {fb_id}...")
                        fs_data = foreshadowing_store.get(fb_id)
                        if fs_data and '内容' in fs_data:
                            content = fs_data['内容']
                            retrieved_foreshadows.append(f"伏笔 {fb_id} 的历史内容:\n{content}")
                            self._log(f"      ✅ 成功检索到伏笔 {fb_id}。")
                        else:
                            self._log(f"      ℹ️ 未找到伏笔 {fb_id} 的历史记录。")
                    
                    if retrieved_foreshadows:
                        knowledge_context = "\n\n".join(retrieved_foreshadows)
                    else:
                        knowledge_context = "(未检索到任何相关伏笔历史记录)"
                else:
                    self._log("  -> ⚠️ `伏笔状态.md` 不存在或加载失败，无法检索历史。")
                    knowledge_context = "(伏笔JSON文件不可用)"
            else:
                self._log("  -> 本章蓝图不涉及任何伏笔。")
                knowledge_context = "(无相关伏笔历史记录)"

            # --- 4. 构建提示词 ---
            self._log("正在构建最终提示词...")
            history_chapters_content = self._get_history_chapters_content(project_path, chap_num, auto_history_chapters)
            word_number = workflow_params.get("word_number", 3000)
            word_count_min = workflow_params.get("word_count_min", int(word_number * 0.8))
            word_count_max = workflow_params.get("word_count_max", int(word_number * 1.2))
            prompt = chapter_draft_prompt.format(
                novel_number=chap_num, chapter_title=title,
                word_number=word_number,
                genre=workflow_params.get("genre"),
                topic=workflow_params.get("topic"),
                key_items="", scene_location="", time_constraint="",
                user_guidance=workflow_params.get("user_guidance"),
                current_chapter_blueprint=current_chapter_blueprint,
                next_chapter_blueprint=next_chapter_blueprint,
                volume_outline=volume_outline,
                setting_characters=setting_characters,
                characters_involved=setting_characters,
                global_summary=global_summary,
                plot_points="", knowledge_context=knowledge_context,
                历史章节正文=history_chapters_content,
                字数下限=word_count_min,
                字数上限=word_count_max
            )

            # --- 5. 调用LLM生成草稿 ---
            self._log("正在调用LLM生成章节草稿...")

            def draft_generation_task(llm_adapter, **kwargs):
                """包装流式调用以在execute_with_polling中使用"""
                text = ""
                from novel_generator.common import invoke_stream_with_cleaning
                logger = kwargs.get('log_func', self._log)
                check_interrupted = kwargs.get('check_interrupted')
                for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, log_func=logger, log_stream=False, check_interrupted=check_interrupted):
                    text += chunk
                return text

            draft_text = execute_with_polling(
                gui_app=self.gui_app,
                step_name="生成草稿_生成章节草稿",
                target_func=draft_generation_task,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False
            )
            
            if draft_text is None:
                self._log("❌ 章节草稿生成失败，已尝试所有可用配置。")
                return None, None

            if not draft_text.strip():
                self._log("❌ 章节草稿生成失败：LLM未返回有效内容。")
                return None, None

            # --- 6. 返回结果 ---
            final_text = f"第{chap_num}章 {title}\n\n{draft_text}"
            save_string_to_txt(final_text, draft_path)
            self._log(f"✅ 第 {chap_num} 章草稿已生成并保存。")
            return draft_path, title

        except Exception as e:
            logging.error(f"生成草稿时出错: {e}", exc_info=True)
            self._log(f"❌ 生成第 {chap_num} 章草稿时发生严重错误: {e}")
            return None, None

    def _ensure_blueprints_exist(self, project_path, chap_num, generate_volume, generate_blueprint, volume_char_weight, blueprint_num_chapters, workflow_params):
        """确保分卷大纲和章节目录存在，如果不存在则生成。"""
        directory_file = os.path.join(project_path, "章节目录.txt")
        directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""
        chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)

        if chapter_info:
            self._log(f"第 {chap_num} 章的蓝图已存在。")
            return

        self._log(f"第 {chap_num} 章的蓝图不存在，开始检查/生成...")
        self._update_status(f"正在准备第 {chap_num} 章的蓝图...")

        # 检查分卷大纲
        volume_ranges = analyze_volume_range(project_path)
        target_volume_num, _ = find_current_volume(chap_num, volume_ranges)
        
        target_volume_exists = any(v['volume'] == target_volume_num for v in volume_ranges)

        if not target_volume_exists and generate_volume:
            self._log(f"第 {chap_num} 章所属的第 {target_volume_num} 卷大纲不存在，开始生成...")
            
            novel_params = self._get_novel_params(workflow_params)
            num_chapters_for_volume = novel_params.pop('num_chapters', None)

            # 使用新的执行器
            result = execute_with_polling(
                gui_app=self.gui_app,
                step_name="生成分卷大纲",
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {target_volume_num} 卷",
                is_manual_call=False,
                target_func=lambda llm_adapter, **kwargs: Novel_volume_generate(
                    llm_adapter=llm_adapter,
                    filepath=project_path,
                    number_of_chapters=num_chapters_for_volume,
                    character_weight_threshold=volume_char_weight,
                    start_from_volume=target_volume_num,
                    generate_single=True,
                    log_func=kwargs.get('log_func', self._log),
                    **novel_params
                )
            )

            if result is not None:
                self._log(f"第 {target_volume_num} 卷大纲已生成。")
            else:
                self._log(f"❌ 生成第 {target_volume_num} 卷大纲失败。")

        # 生成章节目录
        if generate_blueprint:
            self._log(f"开始为第 {chap_num} 章生成章节目录...")
            
            novel_params = self._get_novel_params(workflow_params)
            novel_params['character_weight_threshold'] = 80
            novel_params['previous_chapters_to_include'] = 10

            # --- 动态计算章节范围用于日志 ---
            last_chapter_before, _, _ = analyze_directory_status(project_path)
            start_range = last_chapter_before + 1
            end_range = last_chapter_before + blueprint_num_chapters
            context_range = f"{start_range}-{end_range}章"

            result = execute_with_polling(
                gui_app=self.gui_app,
                step_name="生成章节目录",
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=context_range,
                is_manual_call=False,
                target_func=lambda llm_adapter, **kwargs: Chapter_blueprint_generate(
                    llm_adapter=llm_adapter,
                    filepath=project_path,
                    number_of_chapters=blueprint_num_chapters,
                    generate_single=True,
                    log_func=kwargs.get('log_func', self._log),
                    main_character=workflow_params.get("main_character"),
                    user_guidance=novel_params['user_guidance']
                )
            )

            if result is not None:
                self._log(f"章节目录已更新，应包含第 {chap_num} 章。")
            else:
                self._log(f"❌ 生成章节目录失败。")

    def _determine_start_chapter(self, workflow_params) -> int:
        """分析UI和文件，确定工作流应从哪一章开始。"""
        self._log("ℹ️ 开始自动分析起始章节...")
        self._update_status("自动分析起始章节...")
        time.sleep(1)

        last_chapter = 0
        project_path = workflow_params.get("project_path")
        chapter_list = workflow_params.get("chapter_list", [])

        # 优先从UI列表获取
        if chapter_list:
            numbers = [int(m.group(1)) for item in chapter_list if (m := re.search(r'第(\d+)章', item))]
            if numbers:
                last_chapter = max(numbers)
        
        # 如果UI列表为空，扫描文件
        if last_chapter == 0:
            self._log("  -> ℹ️ UI章节列表为空，将回退到文件扫描。")
            draft_dir = os.path.join(project_path, "章节正文")
            if os.path.exists(draft_dir):
                files = glob.glob(os.path.join(draft_dir, "第*章*.txt"))
                numbers = [int(m.group(1)) for f in files if (m := re.search(r'第(\d+)章', os.path.basename(f)))]
                if numbers:
                    last_chapter = max(numbers)

        self._log(f"ℹ️ 分析完成，找到的最后一章是: 第 {last_chapter} 章。")
        self._update_status(f"找到最后一章: 第 {last_chapter} 章。")
        time.sleep(1)

        if last_chapter > 0:
            self._log(f"  -> 正在检查第 {last_chapter} 章的有效性...")
            self._update_status(f"检查第 {last_chapter} 章...")
            time.sleep(1)

            draft_dir = os.path.join(project_path, "章节正文")
            last_chapter_files = glob.glob(os.path.join(draft_dir, f"第{last_chapter}章*.txt"))
            
            if last_chapter_files:
                last_chapter_path = last_chapter_files[0]
                word_count = len(read_file(last_chapter_path))
                target_word_count = workflow_params.get("word_number", 3000)
                required_word_count = target_word_count * 0.5
                
                if word_count >= required_word_count:
                    self._log(f"✅ 第 {last_chapter} 章有效 ({word_count}字 >= {required_word_count:.0f}字)。工作流将从下一章（第 {last_chapter + 1} 章）开始。")
                    return last_chapter + 1
                else:
                    self._log(f"  -> ⚠️ 第 {last_chapter} 章内容不足 ({word_count}字 < {required_word_count:.0f}字)，将重新生成。")
                    try:
                        os.remove(last_chapter_path)
                        self._log(f"    - 已删除文件: {os.path.basename(last_chapter_path)}")
                    except Exception as e:
                        self._log(f"    - ❌ 删除文件失败: {e}")
                    return last_chapter
            else:
                self._log(f"  -> ⚠️ 找不到第 {last_chapter} 章的正文文件，将从该章开始生成。")
                return last_chapter
        
        self._log("ℹ️ 未找到任何有效历史章节，将从第 1 章开始。")
        return 1

    def _run_consistency_check(self, project_path, chap_num, title, workflow_params, word_count_min, word_count_max):
        self._log(f"开始对第 {chap_num} 章进行一致性检查...")
        self._update_status(f"正在检查第 {chap_num} 章...")

        try:
            # --- 1. 准备完整的上下文信息 ---
            self._log("  -> 正在准备审校所需的上下文...")
            
            # 读取草稿
            draft_path = os.path.join(project_path, "章节正文", f"第{chap_num}章 {title}.txt")
            if not os.path.exists(draft_path):
                self._log(f"❌ 找不到第 {chap_num} 章的草稿文件，无法进行一致性检查。")
                return False, None
            review_text = read_file(draft_path)

            # 读取其他上下文文件
            directory_content = read_file(os.path.join(project_path, "章节目录.txt"))
            volume_content = read_file(os.path.join(project_path, "分卷大纲.txt"))
            global_summary = read_file(os.path.join(project_path, "前情摘要.txt"))
            
            # 获取上一章剧情要点
            plot_points_content = read_file(os.path.join(project_path, "剧情要点.txt"))
            previous_plot_points = ""
            if chap_num > 1:
                match = re.search(rf"(##\s*第\s*{chap_num-1}\s*章[\s\S]*?)(?=\n##\s*第|$)", plot_points_content)
                if match:
                    previous_plot_points = match.group(1).strip()

            # 提取蓝图
            current_chapter_blueprint_match = re.search(rf"^第{chap_num}章.*?(?=^第\d+章|\Z)", directory_content, re.MULTILINE | re.DOTALL)
            current_chapter_blueprint = current_chapter_blueprint_match.group(0).strip() if current_chapter_blueprint_match else ""
            next_chapter_blueprint_match = re.search(rf"^第{chap_num + 1}章.*?(?=^第\d+章|\Z)", directory_content, re.MULTILINE | re.DOTALL)
            next_chapter_blueprint = next_chapter_blueprint_match.group(0).strip() if next_chapter_blueprint_match else ""
            
            # 提取分卷大纲
            actual_volume_number = find_volume_for_chapter(volume_content, chap_num)
            volume_outline = extract_volume_outline(volume_content, actual_volume_number)

            # 提取伏笔历史
            knowledge_context = "(无相关伏笔历史记录)"
            foreshadowing_ids = []
            # --- 修复：在伏笔块中查找所有ID，然后去重 ---
            if current_chapter_blueprint:
                # 1. 定位伏笔条目块
                foreshadowing_block_match = re.search(r'├─伏笔条目：([\s\S]*?)(?=\n[├└]─[\u4e00-\u9fa5]|\Z)', current_chapter_blueprint)
                if foreshadowing_block_match:
                    foreshadowing_block = foreshadowing_block_match.group(1)
                    # 2. 在块内查找所有ID
                    all_ids_in_block = re.findall(r'([A-Z]{1,2}F\d+)', foreshadowing_block)
                    # 3. 去重
                    if all_ids_in_block:
                        foreshadowing_ids = sorted(list(set(all_ids_in_block)))
                else:
                    # 保险措施：如果找不到区块，则全局搜索
                    foreshadowing_ids = sorted(list(set(re.findall(r'([A-Z]{1,2}F\d+)', current_chapter_blueprint))))
            
            if foreshadowing_ids:
                foreshadowing_store = load_store(project_path, "foreshadowing_collection")
                if foreshadowing_store:
                    retrieved_foreshadows = [f"伏笔 {fb_id} 的历史内容:\n{foreshadowing_store.get(fb_id, {}).get('内容', '未找到记录')}" for fb_id in foreshadowing_ids]
                    knowledge_context = "\n\n".join(retrieved_foreshadows)

            # --- 2. 构建完整的提示词 ---
            self._log("  -> 正在构建完整的审校提示词...")
            prompt = Chapter_Review_prompt.format(
                novel_number=chap_num,
                word_number=workflow_params.get("word_number", 3000),
                genre=workflow_params.get("genre", "未知"),
                章节字数=len(review_text),
                user_guidance=workflow_params.get("user_guidance", ""),
                current_chapter_blueprint=current_chapter_blueprint,
                next_chapter_blueprint=next_chapter_blueprint,
                volume_outline=volume_outline,
                global_summary=global_summary,
                plot_points=previous_plot_points,
                knowledge_context=knowledge_context,
                Review_text=review_text,
                字数下限=word_count_min,
                字数上限=word_count_max,
                plot_twist_level=workflow_params.get("plot_twist_level", 3) # 假设一个默认值
            )

            def consistency_check_task(llm_adapter, **kwargs):
                text = ""
                logger = kwargs.get('log_func', self._log)
                check_interrupted = kwargs.get('check_interrupted')
                # 直接使用构建好的完整prompt
                for chunk in cc_do_consistency_check(self.gui_app, custom_prompt=prompt, llm_adapter=llm_adapter, log_stream=False, log_func=logger, check_interrupted=check_interrupted):
                    text += chunk
                return text

            report = execute_with_polling(
                gui_app=self.gui_app,
                step_name="一致性审校_一致性检查",
                target_func=consistency_check_task,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False
            )
            
            if report and report.strip():
                report_path = os.path.join(project_path, "一致性审校.txt")
                with open(report_path, 'w', encoding='utf-8') as f:
                    f.write(f"# 第{chap_num}章 一致性审校报告\n\n{report}")
                self._log(f"✅ 第 {chap_num} 章的一致性报告已保存。")

                # --- 新增：解析报告并记录日志 ---
                review_decision = "未通过" # 默认为未通过
                if "审校通过" in report:
                    review_decision = "通过"
                    self._log("  -> 审校判定：通过")
                else:
                    self._log("  -> 审校判定：未通过")
                    # 提取并记录问题
                    problems = re.findall(r"问题\d+：(.*?)\n问题类型：(.*?)\n", report, re.DOTALL)
                    if problems:
                        self._log("  -> 发现以下问题：")
                        for i, (problem_desc, problem_type) in enumerate(problems, 1):
                            self._log(f"    问题{i}: {problem_desc.strip()}")
                            self._log(f"    问题类型: {problem_type.strip()}")
                    else:
                        self._log("  -> 未能从报告中自动提取具体问题列表。")

                return True, review_decision # 返回成功状态和判定结果
            else:
                self._log(f"❌ 第 {chap_num} 章的一致性检查未能生成有效报告或被中止。")
                return False, "失败"
        except Exception as e:
            logging.error(f"执行一致性检查时出错: {e}", exc_info=True)
            self._log(f"❌ 执行一致性检查时出错: {e}")
            return False, "失败"

    def _run_rewrite(self, project_path, chap_num, title, workflow_params, word_count_min, word_count_max):
        self._log(f"开始对第 {chap_num} 章进行改写...")
        self._update_status(f"正在改写第 {chap_num} 章...")

        try:
            # 1. 准备提示词
            from prompt_definitions import chapter_rewrite_prompt
            draft_path = os.path.join(project_path, "章节正文", f"第{chap_num}章 {title}.txt")
            if not os.path.exists(draft_path):
                self._log(f"❌ 找不到第 {chap_num} 章的草稿文件，无法改写。")
                return False
            
            draft_content = read_file(draft_path)
            report_path = os.path.join(project_path, "一致性审校.txt")
            report_content = read_file(report_path) if os.path.exists(report_path) else "无"
            directory_content = read_file(os.path.join(project_path, "章节目录.txt"))
            
            # 使用与定稿流程相同的、更可靠的方法来提取章节蓝图的完整内容
            def get_chapter_blueprint_text(content, number):
                pattern = re.compile(rf"^第{number}章.*?(?=^第\d+章|\Z)", re.MULTILINE | re.DOTALL)
                match = pattern.search(content)
                return match.group(0).strip() if match else ""
            chapter_blueprint_content = get_chapter_blueprint_text(directory_content, chap_num)

            word_number = workflow_params.get("word_number", 3000)

            # --- 动态获取字数范围 ---
            final_word_min = word_count_min
            final_word_max = word_count_max
            if hasattr(self.gui_app, 'last_review_word_range') and self.gui_app.last_review_word_range:
                final_word_min, final_word_max = self.gui_app.last_review_word_range
                self._log(f"ℹ️ 工作流：使用审校时设定的字数范围进行改写: {final_word_min} - {final_word_max} 字。")
            else:
                self._log(f"ℹ️ 工作流：使用全局设定的字数范围进行改写: {final_word_min} - {final_word_max} 字。")
            # --- 动态获取字数范围结束 ---

            prompt = chapter_rewrite_prompt.format(
                novel_number=chap_num,
                chapter_title=title,
                word_number=word_number,
                genre=workflow_params.get("genre"),
                chapter_blueprint_content=chapter_blueprint_content,
                user_guidance=workflow_params.get("user_guidance"),
                volume_outline=extract_volume_outline(read_file(os.path.join(project_path, "分卷大纲.txt")), find_volume_for_chapter(read_file(os.path.join(project_path, "分卷大纲.txt")), chap_num)),
                global_summary=read_file(os.path.join(project_path, "前情摘要.txt")) if os.path.exists(os.path.join(project_path, "前情摘要.txt")) else "",
                一致性审校=report_content,
                raw_draft=draft_content,
                章节字数=len(draft_content),
                字数下限=final_word_min,
                字数上限=final_word_max
            )

            # 2. 执行改写
            def rewrite_task(llm_adapter, **kwargs):
                """包装流式调用以在execute_with_polling中使用"""
                text = ""
                logger = kwargs.get('log_func', self._log)
                check_interrupted = kwargs.get('check_interrupted')
                # rewrite_chapter is also a generator now, ensure it is handled correctly
                for chunk in rewrite_chapter(
                    current_text=prompt,
                    filepath=project_path,
                    novel_number=chap_num,
                    llm_adapter=llm_adapter,
                    log_func=logger,
                    log_stream=False,
                    check_interrupted=check_interrupted
                ):
                    text += chunk
                return text

            rewritten_content = execute_with_polling(
                gui_app=self.gui_app,
                step_name="改写章节_重写或改写章节",
                target_func=rewrite_task,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False
            )

            # 4. 保存结果
            if rewritten_content and rewritten_content.strip() and "❌" not in rewritten_content:
                final_content = rewritten_content
                # 确保保存为UTF-8
                with open(draft_path, 'w', encoding='utf-8') as f:
                    f.write(final_content)
                self._log(f"✅ 第 {chap_num} 章已改写并覆盖原文件。")
                return True
            else:
                self._log(f"❌ 第 {chap_num} 章的改写未能生成有效内容或被中止。")
                return False
        except Exception as e:
            logging.error(f"执行改写时出错: {e}", exc_info=True)
            self._log(f"❌ 执行改写时出错: {e}")
            return False

    def _run_finalize(self, project_path, chap_num, title, workflow_params):
        self._log(f"开始对第 {chap_num} 章进行定稿...")
        self._update_status(f"正在定稿第 {chap_num} 章...")

        # 复用 finalize_chapter_ui 中的逻辑
        try:
            # --- 准备工作 ---
            self._log("  [0/4] 准备输入数据...")
            chapter_file = os.path.join(project_path, "章节正文", f"第{chap_num}章 {title}.txt")
            summary_file = os.path.join(project_path, "前情摘要.txt")
            character_state_file = os.path.join(project_path, "角色状态.txt")
            plot_points_file = os.path.join(project_path, "剧情要点.txt")
            directory_file = os.path.join(project_path, "章节目录.txt")

            chapter_text = read_file(chapter_file) if os.path.exists(chapter_file) else ""
            if not chapter_text.strip():
                self._log(f"❌ 第 {chap_num} 章内容为空，无法定稿。")
                return False

            global_summary = read_file(summary_file) if os.path.exists(summary_file) else ""
            directory_content = read_file(directory_file) if os.path.exists(directory_file) else ""

            def get_chapter_blueprint_text(content, number):
                pattern = re.compile(rf"^第{number}章.*?(?=^第\d+章|\Z)", re.MULTILINE | re.DOTALL)
                match = pattern.search(content)
                return match.group(0).strip() if match else ""
            
            current_chapter_blueprint = get_chapter_blueprint_text(directory_content, chap_num)
            if not current_chapter_blueprint:
                self._log(f"❌ 未能在章节目录中找到第 {chap_num} 章的信息。定稿流程中止。")
                return False

            chapter_info = get_chapter_info_from_blueprint(directory_content, chap_num)
            if not chapter_info:
                self._log(f"❌ 无法从蓝图中获取第 {chap_num} 章的信息。")
                return False
            chapter_title_full = f"第{chap_num}章 {title}"

            from prompt_definitions import summary_prompt, plot_points_extraction_prompt
            from novel_generator.knowledge import process_and_store_foreshadowing

            embedding_adapter = None

            # --- 步骤 1: 更新前情摘要 ---
            self._log("  [1/4] 正在更新前情摘要...")
            summary_update_prompt = summary_prompt.format(chapter_text=chapter_text, global_summary=global_summary)

            def summary_task(llm_adapter, **kwargs):
                text = ""
                from novel_generator.common import invoke_stream_with_cleaning
                logger = kwargs.get('log_func', self._log)
                check_interrupted = kwargs.get('check_interrupted')
                for chunk in invoke_stream_with_cleaning(llm_adapter, summary_update_prompt, log_func=logger, log_stream=False, check_interrupted=check_interrupted):
                    text += chunk
                return text

            new_summary = execute_with_polling(
                gui_app=self.gui_app,
                step_name="章节定稿_生成章节摘要",
                target_func=summary_task,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False
            )

            if new_summary and new_summary.strip() and "❌" not in new_summary:
                save_string_to_txt(new_summary, summary_file)
                self._log("    ✅ 前情摘要已更新。")
            else:
                self._log("    ⚠️ 更新前情摘要失败。")

            # --- 步骤 2: 更新角色状态 ---
            self._log("  [2/4] 正在更新角色状态...")
            from novel_generator.character_state_updater import update_character_states

            def update_character_states_task(llm_adapter, **kwargs):
                # This wrapper ensures llm_adapter is passed correctly
                logger = kwargs.get('log_func', self._log)
                return update_character_states(
                    chapter_text=chapter_text,
                    chapter_title=chapter_title_full,
                    chap_num=chap_num,
                    filepath=project_path,
                    llm_adapter=llm_adapter, # Pass the adapter here
                    embedding_adapter=None,
                    chapter_blueprint_content=current_chapter_blueprint,
                    log_func=logger # Pass the log function here
                )

            result = execute_with_polling(
                gui_app=self.gui_app,
                step_name="章节定稿_更新角色状态",
                target_func=update_character_states_task,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False
            )

            if result and result.get("status") == "success":
                self._log("    ✅ 角色状态更新成功。")
            else:
                self._log(f"    ❌ 角色状态更新失败: {result.get('message', '未知错误') if result else '已尝试所有配置'}")

            # --- 步骤 3: 整合伏笔内容 ---
            self._log("  [3/4] 正在处理和整合伏笔内容...")
            foreshadowing_str = chapter_info.get('foreshadowing', "")
            if foreshadowing_str: # 修复：移除对 embedding_adapter 的错误依赖
                chapter_info_fs = {'novel_number': chap_num, 'chapter_title': chapter_title_full, 'foreshadowing': foreshadowing_str}
                
                def process_foreshadowing_task(llm_adapter, **kwargs):
                    logger = kwargs.get('log_func', self._log)
                    return process_and_store_foreshadowing(
                        chapter_text=chapter_text,
                        chapter_info=chapter_info_fs,
                        filepath=project_path,
                        llm_adapter=llm_adapter, # Pass the adapter here
                        log_func=logger # Pass the log function here
                    )

                result = execute_with_polling(
                    gui_app=self.gui_app,
                    step_name="章节定稿_整合伏笔",
                    target_func=process_foreshadowing_task,
                    log_func=self._log,
                    adapter_callback=self.set_active_adapter,
                    check_interrupted=lambda: False,
                    context_info=f"第 {chap_num} 章",
                    is_manual_call=False
                )

                # 注意：process_and_store_foreshadowing 内部会自行处理日志，这里不再需要复杂的成功/失败判断
                # 简化逻辑，只要执行过即可认为完成
                self._log("    ✅ 伏笔内容处理完成。")

            else:
                self._log("    ℹ️ 本章蓝图无伏笔信息，跳过。")

            # --- 步骤 4: 提取剧情要点 ---
            self._log("  [4/4] 正在提取剧情要点...")
            previous_plot_points = ""
            if chap_num > 1 and os.path.exists(plot_points_file):
                content = read_file(plot_points_file)
                match = re.search(rf"(##\s*第\s*{chap_num-1}\s*章[\s\S]*?)(?=\n##\s*第|$)", content)
                if match: previous_plot_points = match.group(1).strip()
            
            plot_points_prompt = plot_points_extraction_prompt.format(
                novel_number=chap_num, chapter_title=chapter_title_full, chapter_text=chapter_text,
                current_chapter_blueprint=current_chapter_blueprint, global_summary=global_summary,
                plot_points=previous_plot_points
            )

            def plot_points_task(llm_adapter, **kwargs):
                text = ""
                from novel_generator.common import invoke_stream_with_cleaning
                logger = kwargs.get('log_func', self._log)
                check_interrupted = kwargs.get('check_interrupted')
                for chunk in invoke_stream_with_cleaning(llm_adapter, plot_points_prompt, log_func=logger, log_stream=False, check_interrupted=check_interrupted):
                    text += chunk
                return text

            plot_points = execute_with_polling(
                gui_app=self.gui_app,
                step_name="章节定稿_提取剧情要点",
                target_func=plot_points_task,
                log_func=self._log,
                adapter_callback=self.set_active_adapter,
                check_interrupted=lambda: False,
                context_info=f"第 {chap_num} 章",
                is_manual_call=False
            )

            if plot_points and "❌" not in plot_points:
                existing_content = read_file(plot_points_file) if os.path.exists(plot_points_file) else ""
                chapter_header = f"## 第 {chap_num} 章 《{title}》"
                chapter_pattern = re.compile(f"\n\n## 第 {chap_num} 章.*?(?=\n\n## 第|$)", re.DOTALL)
                if chapter_pattern.search(existing_content):
                    existing_content = chapter_pattern.sub("", existing_content)
                new_content = existing_content.rstrip() + f"\n\n{chapter_header}\n{plot_points}"
                save_string_to_txt(new_content, plot_points_file)
                self._log("    ✅ 剧情要点已提取并更新到文件。")
            else:
                self._log("    ⚠️ 提取剧情要点失败。")

            self._log(f"✅ 第 {chap_num} 章定稿流程全部完成！")
            return True

        except SingleProviderExecutionError as e:
            self._log(f"❌ 定稿流程因单配置失败而中止: {e}")
            return False
        except Exception as e:
            logging.error(f"执行定稿时出错: {e}", exc_info=True)
            self._log(f"❌ 执行定稿时出错: {e}")
            return False

    def _get_novel_params(self, workflow_params):
        """从传递的参数字典中提取小说参数。"""
        return {
            "topic": workflow_params.get("topic"),
            "genre": workflow_params.get("genre"),
            "word_number": workflow_params.get("word_number"),
            "volume_count": workflow_params.get("volume_count"),
            "num_chapters": workflow_params.get("num_chapters_total"),
            "user_guidance": workflow_params.get("user_guidance"),
        }
