#novel_generator/common.py
# -*- coding: utf-8 -*-
"""通用重试、清洗、日志工具"""
import logging
import re
import time
import traceback
import threading
import queue

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

def invoke_with_cleaning(llm_adapter, prompt: str, max_retries: int = 3) -> str:
    """调用 LLM 并清理返回结果"""
    print("\n" + "="*50)
    print("发送到 LLM 的提示词:")
    print("-"*50)
    print(prompt)
    print("="*50 + "\n")
    
    result = ""
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            result = llm_adapter.invoke(prompt)
            print("\n" + "="*50)
            print("LLM 返回的内容:")
            print("-"*50)
            print(result)
            print("="*50 + "\n")
            
            # 清理结果中的特殊格式标记
            result = result.replace("```", "").strip()
            if result:
                return result
        except Exception as e:
            print(f"调用失败 ({retry_count + 1}/{max_retries}): {str(e)}")
            retry_count += 1
            if retry_count >= max_retries:
                raise e
            time.sleep(2)  # 等待后重试
    
    return ""

def invoke_llm(llm_adapter, prompt: str, max_retries: int = 3) -> str:
    """直接调用 LLM 并返回结果，包含重试机制。"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            result = llm_adapter.invoke(prompt)
            logging.debug(f"LLM Invocation successful. Prompt length: {len(prompt)}, Result length: {len(result)}")
            # 在终端中显示LLM返回的内容（截断显示以避免日志过长）
            max_display_length = 1000  # 最大显示长度
            display_result = result[:max_display_length] + "...（内容过长已截断）" if len(result) > max_display_length else result
            logging.info(f"\n==============================LLM返回内容==============================:\n{display_result}")
            return result
        except Exception as e:
            logging.warning(f"LLM invocation failed (attempt {retry_count + 1}/{max_retries}): {str(e)}")
            retry_count += 1
            if retry_count >= max_retries:
                logging.error(f"LLM invocation failed after {max_retries} attempts.")
                return "" # Return empty string on failure after retries
            time.sleep(2) # Wait before retrying
    return ""

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
def update_character_states_async(chapter_text, chapter_title, chap_num, filepath, llm_adapter, embedding_adapter, callback=None):
    """异步版本的角色状态更新函数
    
    Args:
        chapter_text: 章节文本
        chapter_title: 章节标题
        chap_num: 章节编号
        filepath: 文件保存路径
        llm_adapter: LLM适配器
        embedding_adapter: 嵌入适配器
        callback: 回调函数，接收更新结果和可选的错误信息
    """
    def task():
        try:
            from novel_generator.character_state_updater import update_character_states
            result = update_character_states(chapter_text, chapter_title, chap_num, filepath, llm_adapter, embedding_adapter)
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

