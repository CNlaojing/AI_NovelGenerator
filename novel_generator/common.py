#novel_generator/common.py
# -*- coding: utf-8 -*-
"""通用重试、清洗、日志工具"""
import logging
import re
import time
import traceback
import threading
import queue
import sys
import sys
import json
from openai import APIStatusError

class SingleProviderExecutionError(Exception):
    """自定义异常，用于表示在单提供商模式下执行失败。"""
    pass

def call_with_retry(func, max_retries=3, sleep_time=2, fallback_return=None, **kwargs):
    """通用的重试机制封装。
    :param func: 要执行的函数
    :param max_retries: 最大重试次数
    :param sleep_time: 重试前的等待秒数
    :param fallback_return: 如果多次重试仍失败时的返回值
    :param kwargs: 传给func的命名参数
    :return: func的结果，若失败则返回 fallback_return
    """
    for attempt in range(1, max_retries + 1):
        try:
            return func(**kwargs)
        except Exception as e:
            logging.warning(f"[call_with_retry] Attempt {attempt} failed with error: {e}")
            traceback.print_exc()
            if attempt < max_retries:
                time.sleep(sleep_time)
            else:
                logging.error("Max retries reached, returning fallback_return.")
                return fallback_return

def remove_think_tags(text: str) -> str:
    """移除 <think>...</think> 包裹的内容"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

def debug_log(prompt: str, response_content: str):
    logging.info(
        f"\n[#########################################  Prompt  #########################################]\n{prompt}\n"
    )
    logging.info(
        f"\n[######################################### Response #########################################]\n{response_content}\n"
    )

def stream_print(text: str, end: str = "", thinking: bool = False):
    """流式打印文本，直接按照LLM返回的token速度显示
    Args:
        text: 要打印的文本
        end: 结束字符
        thinking: 是否是思维链内容
    """
    if not text:
        return
        
    prefix = "💭 " if thinking else "🤖 "
    
    # 确保text是字符串类型
    text_str = str(text)
    
    # 仅在新段落开始时添加前缀
    if text_str.startswith('\n'):
        sys.__stdout__.write(prefix)
    
    # 直接打印文本，让token自然流出
    sys.__stdout__.write(text_str)
    sys.__stdout__.write(end)
    sys.__stdout__.flush()

def extract_thinking_content(response_chunk):
    """从不同模型的响应中提取思维链内容
    Returns:
        tuple: (思维链内容, 最终回答)
    """
    thinking_content = None
    content = None
    
    # DeepSeek模型
    if hasattr(response_chunk, 'choices') and response_chunk.choices and hasattr(response_chunk.choices[0].delta, 'reasoning_content'):
        thinking_content = response_chunk.choices[0].delta.reasoning_content
        content = response_chunk.choices[0].delta.content
        
    # Gemini模型
    elif hasattr(response_chunk, 'parts') and response_chunk.parts:
        # Gemini的思维链在candidates中
        candidates = getattr(response_chunk, 'candidates', [])
        if candidates:
            thinking_content = str(candidates[0].content)
        content = str(getattr(response_chunk, 'text', ''))
        
    # OpenAI模型
    elif hasattr(response_chunk, 'choices') and response_chunk.choices:
        content = response_chunk.choices[0].delta.content
        if content and '<think>' in content:
            thinking_match = re.search(r'<think>(.*?)</think>', content)
            if thinking_match:
                thinking_content = thinking_match.group(1)
                content = re.sub(r'<think>.*?</think>', '', content)
    
    return thinking_content, content

def invoke_with_cleaning(llm_adapter, prompt: str, max_retries: int = 3, check_interrupted=None, log_func=None, log_stream=True) -> str:
    """使用流式输出调用 LLM 并清理返回结果"""
    result_text = ""
    for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, max_retries, check_interrupted, log_func, log_stream):
        result_text += chunk
    return result_text

def invoke_stream_with_cleaning(llm_adapter, prompt: str, max_retries: int = 3, check_interrupted=None, log_func=None, log_stream=True):
    """
    使用流式输出调用 LLM，并以生成器方式返回清理后的文本块。
    增加了在LLM思考时的读秒计时功能，并能在GUI日志中反映。
    """
    # sys.__stdout__.write("\n" + "="*70 + "\n")
    # sys.__stdout__.write("发送到 LLM 的提示词:\n")
    # sys.__stdout__.write("-"*70 + "\n")
    # sys.__stdout__.write(prompt + "\n")
    # sys.__stdout__.write("="*70 + "\n\n")
    # sys.__stdout__.flush()

    retry_count = 0
    while retry_count < max_retries:
        stop_event = threading.Event()
        timer_thread = None
        
        final_elapsed_time = 0
        def _timer():
            nonlocal final_elapsed_time
            start_time = time.time()

            while not stop_event.is_set():
                elapsed = time.time() - start_time
                final_elapsed_time = elapsed
                
                message = f"LLM 正在思考...  （{elapsed:.1f} 秒）"
                
                # 更新终端计时器
                sys.__stdout__.write(f"\r{message}")
                sys.__stdout__.flush()
                
                # 更新GUI日志
                if log_func:
                    # 对于计时器，总是替换最后一行
                    log_func(message, replace_last_line=True)
                
                time.sleep(0.1)
            
            # 计时结束，在终端和GUI打印最终耗时
            final_message = f"LLM 思考完毕，共耗时 {final_elapsed_time:.2f} 秒"
            sys.__stdout__.write(f"\r{final_message}\n")
            sys.__stdout__.flush()
            if log_func:
                log_func(final_message, replace_last_line=True)

        try:
            # 启动计时器
            timer_thread = threading.Thread(target=_timer)
            timer_thread.daemon = True
            timer_thread.start()

            stream = llm_adapter.invoke_stream(prompt)
            if not stream:
                raise Exception("Failed to get stream response")

            first_chunk = True
            for chunk in stream:
                if first_chunk:
                    # 收到第一个数据块，停止计时器
                    stop_event.set()
                    timer_thread.join()
                    # sys.__stdout__.write("\n" + "="*70 + "\n")
                    # sys.__stdout__.write("LLM返回内容:\n")
                    # sys.__stdout__.write("-"*70 + "\n")
                    # sys.__stdout__.flush()
                    first_chunk = False

                content = chunk
                
                if content:
                    sys.__stdout__.write(content)
                    sys.__stdout__.flush()
                    
                    # 根据log_stream参数决定是否将流式内容输出到GUI日志
                    if log_func and log_stream:
                        log_func(content, stream=True)
                        
                    cleaned_content = content.replace("```", "")
                    yield cleaned_content
            
            # if not first_chunk: # 确保即使流为空也打印结束符
            #     sys.__stdout__.write("\n" + "="*70 + "\n")
            #     sys.__stdout__.flush()
            
            return

        except APIStatusError as e:
            # 停止计时器
            if timer_thread and timer_thread.is_alive():
                stop_event.set()
                timer_thread.join()

            error_code = e.status_code
            # 按照用户要求的格式构建错误信息
            error_message = f"错误: 调用失败 ({retry_count + 1}/{max_retries}): Error code: {error_code}"
            
            # 同时记录到终端和GUI日志
            # 注意：这里不再需要 llm_adapter 的配置名和模型名，因为上层 execute_with_polling 会记录
            sys.__stdout__.write(f"\n{error_message}\n")
            sys.__stdout__.flush()
            if log_func:
                # 将简化后的错误信息传递给上层日志函数
                log_func(error_message)

            retry_count += 1
            if retry_count >= max_retries:
                # 抛出简化的异常信息
                raise Exception(f"LLM调用失败，已达最大重试次数: Error code: {error_code}")
            time.sleep(2)

        except Exception as e:
            # 停止计时器
            if timer_thread and timer_thread.is_alive():
                stop_event.set()
                timer_thread.join()

            error_message = f"调用失败 ({retry_count + 1}/{max_retries}): {str(e)}"
            sys.__stdout__.write(f"\n错误: {error_message}\n")
            sys.__stdout__.flush()
            logging.error(error_message)
            
            retry_count += 1
            if retry_count >= max_retries:
                final_error = f"LLM调用失败，已达最大重试次数: {e}"
                raise Exception(final_error)
            time.sleep(2)
        finally:
            # 确保计时器线程在任何情况下都能停止，即使是被外部异常（如SystemExit）中断
            if timer_thread and timer_thread.is_alive():
                stop_event.set()
                timer_thread.join()
                # 强制停止后，在终端打印一个清晰的换行，避免日志混乱
                sys.__stdout__.write("\n")
                sys.__stdout__.flush()

def invoke_llm(llm_adapter, prompt: str, max_retries: int = 3, log_func=None) -> str:
    """直接调用 LLM 并返回结果，包含重试机制。"""
    # 复用 invoke_with_cleaning 的逻辑
    return invoke_with_cleaning(llm_adapter, prompt, max_retries, log_func=log_func)

# 添加异步版本的LLM调用函数
class AsyncLLMInvoker:
    """异步LLM调用器，使用线程池和回调机制实现非阻塞调用"""
    
    def __init__(self, max_workers=5):
        """初始化异步调用器
        
        Args:
            max_workers: 最大工作线程数
        """
        self.result_queues = {}
        self.max_workers = max_workers
        self.workers = []
        self.task_queue = queue.Queue()
        self._start_workers()
    
    def _start_workers(self):
        """启动工作线程"""
        for _ in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop, daemon=True)
            worker.start()
            self.workers.append(worker)
    
    def _worker_loop(self):
        """工作线程循环，从任务队列获取任务并执行"""
        while True:
            try:
                task_id, llm_adapter, prompt, max_retries, callback = self.task_queue.get()
                try:
                    # 调用同步版本的invoke_llm函数
                    result = invoke_llm(llm_adapter, prompt, max_retries)
                    # 如果提供了回调函数，则调用回调
                    if callback:
                        callback(result)
                except Exception as e:
                    logging.error(f"Error in worker thread: {str(e)}")
                    if callback:
                        callback(None, str(e))
                finally:
                    self.task_queue.task_done()
            except Exception as e:
                logging.error(f"Worker loop error: {str(e)}")
    
    def invoke_async(self, llm_adapter, prompt, callback=None, max_retries=3):
        """异步调用LLM
        
        Args:
            llm_adapter: LLM适配器
            prompt: 提示词
            callback: 回调函数，接收结果和可选的错误信息
            max_retries: 最大重试次数
        """
        task_id = id(prompt)
        self.task_queue.put((task_id, llm_adapter, prompt, max_retries, callback))
        return task_id

# 创建全局异步调用器实例
async_invoker = AsyncLLMInvoker()

def invoke_llm_async(llm_adapter, prompt, callback=None, max_retries=3):
    """异步调用LLM的便捷函数
    
    Args:
        llm_adapter: LLM适配器
        prompt: 提示词
        callback: 回调函数，接收结果和可选的错误信息
        max_retries: 最大重试次数
    """
    return async_invoker.invoke_async(llm_adapter, prompt, callback, max_retries)

def invoke_with_cleaning_async(llm_adapter, prompt, callback=None, max_retries=3):
    """异步调用LLM并清理结果的便捷函数
    
    Args:
        llm_adapter: LLM适配器
        prompt: 提示词
        callback: 回调函数，接收清理后的结果和可选的错误信息
        max_retries: 最大重试次数
    """
    def clean_and_callback(result, error=None):
        if error:
            if callback:
                callback(None, error)
            return
        
        # 清理结果
        cleaned_result = result.replace("```", "").strip() if result else ""
        if callback:
            callback(cleaned_result)
    
    return async_invoker.invoke_async(llm_adapter, prompt, clean_and_callback, max_retries)

# 添加异步版本的update_character_states函数
def update_character_states_async(chapter_text, chapter_title, chap_num, filepath, llm_adapter, chapter_blueprint_content="", callback=None, log_func=None, genre="", volume_count=0, num_chapters=0, volume_number=1):
    """异步版本的角色状态更新函数
    
    Args:
        chapter_text: 章节文本
        chapter_title: 章节标题
        chap_num: 章节编号
        filepath: 文件保存路径
        llm_adapter: LLM适配器
        chapter_blueprint_content: 章节目录内容
        callback: 回调函数，接收更新结果和可选的错误信息
        log_func: 日志记录函数
        genre (str): 小说类型.
        volume_count (int): 总卷数.
        num_chapters (int): 总章数.
        volume_number (int): 当前卷号.
    """
    def task():
        try:
            from novel_generator.character_state_updater import update_character_states
            result = update_character_states(
                chapter_text=chapter_text,
                chapter_title=chapter_title,
                chap_num=chap_num,
                filepath=filepath,
                llm_adapter=llm_adapter,
                chapter_blueprint_content=chapter_blueprint_content,
                log_func=log_func,
                genre=genre,
                volume_count=volume_count,
                num_chapters=num_chapters,
                volume_number=volume_number
            )
            if callback:
                callback(result)
        except Exception as e:
            logging.error(f"Error in update_character_states_async: {str(e)}")
            if callback:
                callback({"status": "error", "message": str(e), "character_state": ""})
    
    thread = threading.Thread(target=task)
    thread.daemon = True
    thread.start()
    return thread

def execute_with_polling(gui_app, step_name: str, target_func, log_func=None, adapter_callback=None, check_interrupted=None, context_info: str = "", is_manual_call: bool = False, *args, **kwargs):
    """
    执行一个目标函数，根据UI设置决定是使用单一模型还是轮询。
    这是实现模型自动切换和用户选择尊重的核心逻辑。
    """
    from llm_adapters import PollingManager, create_llm_adapter
    polling_manager = PollingManager()
    logger = log_func if log_func else gui_app.safe_log
    context_prefix = f"[{context_info}] " if context_info else ""

    # --- 核心逻辑：从UI获取当前的LLM模式 ---
    use_polling_mode = gui_app.enable_polling_var.get()

    if not use_polling_mode:
        # --- 单一模型模式 ---
        logger(f"{context_prefix}ℹ️ 当前为单一模型模式。")
        config_name = gui_app.main_config_selection_var.get()
        if not config_name or config_name == "无可用配置":
            logger(f"{context_prefix}❌ 错误：在单一模型模式下，没有选择有效的LLM配置。")
            return None
        
        logger(f"{context_prefix}  -> 将使用UI上选择的配置: '{config_name}'")
        llm_adapter = polling_manager.get_adapter_by_name(config_name)
        if not llm_adapter:
            logger(f"{context_prefix}⚠️ 警告：无法为步骤 '{step_name}' 获取配置 '{config_name}'。")
            return None

        # --- 日志格式优化 ---
        call_prefix = "[手动] " if is_manual_call else "[自动] "
        final_step_name = f"{call_prefix}{step_name} {context_info}".strip()
        llm_adapter.step_name = final_step_name
        llm_adapter.config_name = f"单一模型-{config_name}" # 更新配置名以包含模式

        ui_model_name = gui_app.main_model_name_var.get()
        if ui_model_name and ui_model_name != llm_adapter.model_name:
            logger(f"{context_prefix}  -> 模型已从 '{llm_adapter.model_name}' 覆盖为UI选择的 '{ui_model_name}'")
            llm_adapter.model_name = ui_model_name

        model_name = llm_adapter.model_name or "未知"
        logger(f"{context_prefix}步骤 '{final_step_name}' 正在尝试使用配置 '{llm_adapter.config_name}' (模型: {model_name})...")

        # --- 新增：在执行前检查停止信号 ---
        if check_interrupted and check_interrupted():
            logger(f"{context_prefix}  -> 检测到停止信号，正在中止步骤 '{step_name}'...")
            raise InterruptedError(f"步骤 '{step_name}' 在开始前被中断。")

        if adapter_callback:
            adapter_callback(llm_adapter)
        try:
            kwargs['llm_adapter'] = llm_adapter
            if 'log_func' not in kwargs:
                kwargs['log_func'] = logger
            if 'check_interrupted' not in kwargs:
                kwargs['check_interrupted'] = check_interrupted
            result = target_func(*args, **kwargs)
            
            # 检查返回内容是否为空
            if not result or (isinstance(result, str) and not result.strip()):
                raise ValueError("LLM返回内容为空或仅包含空白字符。")

            logger(f"{context_prefix}✅ 步骤 '{step_name}' 使用配置 '{config_name}' (模型: {model_name}) 成功。\n")
            return result
        except InterruptedError:
            logger(f"{context_prefix}🟡 任务被用户中断。\n")
            raise
        except Exception as e:
            error_msg = f"{context_prefix}❌ 配置 '{config_name}' (模型: {model_name}) 在步骤 '{step_name}' 中失败: {str(e)}\n"
            logger(error_msg)
            raise SingleProviderExecutionError(error_msg) from e
        finally:
            if adapter_callback:
                adapter_callback(None)

    else:
        # --- 轮询模式 ---
        logger(f"{context_prefix}ℹ️ 当前为轮询模式。")
        
        total_rounds = 2 # 总共轮询两遍
        
        # 检查是否有指定的配置
        step_config = polling_manager.step_configs.get(step_name, {})
        specific_config_name = step_config.get("指定配置")
        is_specific_mode = specific_config_name and specific_config_name != "无"

        if is_specific_mode:
            max_attempts_per_round = 1
            logger(f"{context_prefix}  -> 步骤 '{step_name}' 已指定配置 '{specific_config_name}'，将仅使用此配置。")
        else:
            if not polling_manager.polling_list:
                logger(f"{context_prefix}❌ 错误：步骤 '{step_name}' 的轮询列表为空。")
                return None
            max_attempts_per_round = len(polling_manager.polling_list)

        for round_num in range(total_rounds):
            # 如果是单一指定配置模式，只跑一轮
            if is_specific_mode and round_num > 0:
                break

            logger(f"{context_prefix}  -> 开始第 {round_num + 1}/{total_rounds} 轮尝试...")
            polling_manager.reset_random_polling() # 每轮开始时重置随机序列

            for attempt_in_round in range(max_attempts_per_round):
                # --- 新增：在每次尝试前检查停止信号 ---
                if check_interrupted and check_interrupted():
                    logger(f"{context_prefix}  -> 检测到停止信号，正在中止步骤 '{step_name}'...")
                    raise InterruptedError(f"步骤 '{step_name}' 在轮询中被中断。")
                
                config_name_to_use = polling_manager.get_next_config_name(step_name)
                if not config_name_to_use:
                    logger(f"{context_prefix}⚠️ 警告：在第 {attempt_in_round + 1} 次尝试时无法获取下一个轮询配置。")
                    continue

                llm_adapter = polling_manager.get_adapter_by_name(config_name_to_use)
                if not llm_adapter:
                    logger(f"{context_prefix}⚠️ 警告：无法为步骤 '{step_name}' 获取配置 '{config_name_to_use}'。")
                    continue
                
                # --- 日志格式优化 ---
                call_prefix = "[手动] " if is_manual_call else "[自动] "
                final_step_name = f"{call_prefix}{step_name} {context_info}".strip()
                llm_adapter.step_name = final_step_name
                llm_adapter.config_name = f"轮询-{config_name_to_use}" # 更新配置名以包含模式
                
                model_name = llm_adapter.model_name or "未知"
                
                # 更新日志格式以匹配用户反馈
                log_message_attempt = f"(轮次 {round_num + 1}/{total_rounds}, 尝试 {attempt_in_round + 1}/{max_attempts_per_round})"
                if is_specific_mode:
                    # 在指定配置模式下，简化日志
                    log_message_attempt = f"(尝试 {attempt_in_round + 1}/{max_attempts_per_round})"

                logger(f"{context_prefix}步骤 '{final_step_name}' 正在尝试使用配置 '{llm_adapter.config_name}' (模型: {model_name}) {log_message_attempt}...")

                if adapter_callback:
                    adapter_callback(llm_adapter)
                try:
                    kwargs['llm_adapter'] = llm_adapter
                    if 'log_func' not in kwargs:
                        kwargs['log_func'] = logger
                    if 'check_interrupted' not in kwargs:
                        kwargs['check_interrupted'] = check_interrupted
                    result = target_func(*args, **kwargs)

                    # 检查返回内容是否为空
                    if not result or (isinstance(result, str) and not result.strip()):
                        raise ValueError("LLM返回内容为空或仅包含空白字符。")

                    logger(f"{context_prefix}✅ 步骤 '{step_name}' 使用配置 '{config_name_to_use}' (模型: {model_name}) 成功。\n")
                    return result
                except InterruptedError:
                    logger(f"{context_prefix}🟡 任务被用户中断。\n")
                    raise
                except Exception as e:
                    # 现在，从 invoke_stream_with_cleaning 抛出的异常可能是简化的
                    # 我们需要将配置信息和简化后的错误信息组合起来
                    error_str = str(e)
                    # 移除上层函数添加的前缀，避免信息重复
                    if "LLM调用失败，已达最大重试次数:" in error_str:
                        error_str = error_str.split("LLM调用失败，已达最大重试次数:", 1)[1].strip()

                    error_msg = f"{context_prefix}❌ 配置 '{config_name_to_use}' (模型: {model_name}) 在步骤 '{step_name}' 中失败: {error_str}\n"
                    logger(error_msg)
                finally:
                    if adapter_callback:
                        adapter_callback(None)

        logger(f"{context_prefix}❌ 错误：步骤 '{step_name}' 已完成 {total_rounds} 轮尝试，所有可用配置均失败。\n")
        return None

import os
from utils import read_file

def get_chapter_filepath(filepath: str, chapter_num: int) -> str:
    """
    根据章节号生成标准的文件路径，文件名格式为 "第X章 章节名.txt"。
    章节名从 章节目录.txt 中提取。

    :param filepath: 项目根目录的路径。
    :param chapter_num: 章节号。
    :return: 标准化的章节文件完整路径。
    """
    directory_file = os.path.join(filepath, "章节目录.txt")
    chapter_title = f"无标题章节"  # 默认标题

    if os.path.exists(directory_file):
        directory_content = read_file(directory_file)
        # 增强的正则表达式，可以匹配 "第X章 《章节名》" 或 "第X章 章节名"
        match = re.search(rf"^第\s*{chapter_num}\s*章\s*(?:《([^》]+)》|([^\n]+))", directory_content, re.MULTILINE)
        if match:
            # match.group(1) 对应《章节名》，match.group(2) 对应 "章节名"
            title_candidate = match.group(1) or match.group(2)
            if title_candidate:
                chapter_title = title_candidate.strip()

    # 移除Windows文件名中的非法字符
    safe_title = re.sub(r'[\\/*?:"<>|]', '', chapter_title)
    
    # 新的文件名格式
    filename = f"第{chapter_num}章 {safe_title}.txt"
    
    # 新的文件夹名称
    chapter_folder = os.path.join(filepath, "章节正文")
    
    # 确保文件夹存在
    os.makedirs(chapter_folder, exist_ok=True)
    
    return os.path.join(chapter_folder, filename)

def format_character_info(char_data: dict) -> str:
    """
    将单个角色的JSON数据块格式化为人类可读的、详细的字符串。
    该函数递归地处理所有键和值，确保信息的完整性，并美化输出格式。
    """
    if not isinstance(char_data, dict):
        return ""

    # 定义顶级键的显示顺序，确保输出的逻辑性和可读性
    key_order = [
        "ID", "名称", "基础信息", "势力特征", "生命状态", "技术能力", 
        "持有物品", "关系网", "行为模式/决策偏好", "语言风格/对话关键词",
        "情感线状态", "关键事件记录", "位置轨迹"
    ]

    output_lines = []

    def _format_recursive(data, indent_level=0):
        """递归格式化函数"""
        indent = "  " * indent_level
        lines = []

        if isinstance(data, dict):
            for key, value in data.items():
                if value is not None and value != "" and value != [] and value != {}:
                    # 对于字典和列表，将键单独作为标题行
                    if isinstance(value, (dict, list)):
                        lines.append(f"{indent}- **{key}:**")
                        # 递归调用，增加缩进
                        nested_lines = _format_recursive(value, indent_level + 1)
                        if nested_lines:
                            lines.append(nested_lines)
                    # 对于普通值，键值同行
                    else:
                        lines.append(f"{indent}- **{key}:** {str(value).strip()}")
            return "\n".join(lines)

        elif isinstance(data, list):
            # 检查列表内容，判断是字典列表还是普通值列表
            if all(isinstance(item, dict) for item in data):
                for i, item in enumerate(data):
                    # 为每个字典项添加一个项目编号
                    lines.append(f"{indent}- **项目 {i + 1}:**")
                    nested_lines = _format_recursive(item, indent_level + 1)
                    if nested_lines:
                        lines.append(nested_lines)
            else:
                # 普通列表，每个项前加破折号
                for item in data:
                    lines.append(f"{indent}- {str(item).strip()}")
            return "\n".join(lines)
        
        return str(data).strip()

    # 按照预设顺序处理顶级键
    processed_keys = set()
    for key in key_order:
        if key in char_data and char_data[key]:
            value = char_data[key]
            processed_keys.add(key)

            # ID 和 名称 作为顶级标识
            if key in ["ID", "名称"]:
                output_lines.append(f"- **{key}:** {value}")
            else:
                # 其他顶级键作为主要章节标题
                output_lines.append(f"\n- **{key}:**")
                formatted_value = _format_recursive(value, 1) # 内容缩进一级
                if formatted_value:
                    output_lines.append(formatted_value)

    # 处理任何未在预设顺序中定义的其他顶级键，确保不会遗漏信息
    for key, value in char_data.items():
        if key not in processed_keys and value:
            output_lines.append(f"\n- **{key}:**")
            formatted_value = _format_recursive(value, 1)
            if formatted_value:
                output_lines.append(formatted_value)
    
    return "\n".join(output_lines).strip()
