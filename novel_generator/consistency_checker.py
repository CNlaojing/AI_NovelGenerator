# consistency_checker.py
# -*- coding: utf-8 -*-
import os
import re
import datetime
import traceback
import threading
from tkinter import messagebox
from llm_adapters import create_llm_adapter, BaseLLMAdapter
from novel_generator.common import invoke_with_cleaning
from prompt_definitions import Chapter_Review_prompt
from novel_generator.chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.volume import extract_volume_outline
from utils import read_file, save_string_to_txt, clear_file_content
from embedding_adapters import create_embedding_adapter
# from novel_generator.vectorstore_utils import load_vector_store # [REMOVED]

def do_consistency_check(self, log_func=None, custom_prompt=None, llm_config=None, llm_adapter: BaseLLMAdapter = None, log_stream=True, *args, **kwargs):
    """
    Wrapper function for consistency checking.
    It can either use a custom prompt from the UI or build one itself.
    It prioritizes a passed llm_adapter instance over llm_config.
    """
    # Get common parameters
    filepath = self.filepath_var.get().strip()
    output_file_path = os.path.join(filepath, "一致性审校.txt")

    # If a custom prompt is provided by the UI, use it directly
    if custom_prompt:
        try:
            clear_file_content(output_file_path)
            if log_func:
                log_func("正在使用UI提供的自定义提示词进行一致性审校...")
                # log_func("发送到 LLM 的提示词 (一致性审校):\n" + custom_prompt)

            # Ensure we have an adapter
            if not llm_adapter and llm_config:
                llm_adapter = create_llm_adapter(llm_config)
            elif not llm_adapter:
                raise ValueError("一致性审校需要 llm_adapter 或 llm_config。")

            # This function is now a generator. It will yield chunks.
            # The caller is responsible for aggregating the result.
            yield from check_consistency_stream(
                llm_adapter=llm_adapter, custom_prompt=custom_prompt, log_func=log_func, log_stream=log_stream
            )
        except Exception as e:
            error_message = f"❌ 使用自定义提示词进行审校时出错: {str(e)}\n{traceback.format_exc()}"
            if log_func:
                log_func(error_message)
            # Re-raise the exception to allow the polling mechanism to catch it
            raise
        return # End of generator

    # --- Fallback to original logic if no custom_prompt is provided ---
    if log_func:
        log_func("未提供自定义提示词，将执行原有一致性审校逻辑...")
    
    # The rest of the original logic for building the prompt from scratch
    # (This part is now effectively legacy code but kept for compatibility)
    novel_number = self.safe_get_int(self.chapter_num_var, 1)
    Review_text = self.chapter_result.get("0.0", "end").strip()
    
    global_summary = read_file(os.path.join(filepath, "前情摘要.txt"))
    character_state = read_file(os.path.join(filepath, "待用角色.txt"))
    word_number = self.safe_get_int(self.word_number_var, 3000)
    genre = self.genre_var.get().strip()
    
    clear_file_content(output_file_path)
    
    directory_content = read_file(os.path.join(filepath, "章节目录.txt"))
    chapter_info = get_chapter_info_from_blueprint(directory_content, novel_number) or {}
    chapter_title = chapter_info.get('chapter_title', f"第{novel_number}章")

    volume_content = read_file(os.path.join(filepath, "分卷大纲.txt"))
    volume_outline = ""
    if volume_content:
        from .volume import find_actual_volume_number
        actual_volume_number = find_actual_volume_number(volume_content, novel_number)
        volume_outline = extract_volume_outline(volume_content, actual_volume_number)

    # This function is no longer needed as its logic is in the UI layer
    # plot_arcs = extract_recent_plot_arcs(filepath, 2000, novel_number)
    plot_arcs = "" # Placeholder

    knowledge_context = "(此部分逻辑已移至UI层，此处为兼容性保留)"

    prompt = Chapter_Review_prompt.format(
        novel_number=novel_number,
        chapter_title=chapter_title,
        word_number=word_number,
        genre=genre,
        chapter_blueprint_content=read_file(os.path.join(filepath, f"第{novel_number}章-章节目录.txt")) if os.path.exists(os.path.join(filepath, f"第{novel_number}章-章节目录.txt")) else "",
        global_summary=global_summary,
        character_state=character_state,
        volume_outline=volume_outline,
        Review_text=Review_text,
        plot_points=plot_arcs,
        knowledge_context=knowledge_context,
        user_guidance=self.user_guide_text.get("0.0", "end").strip()
    )
    
    # The original dialog and processing logic is now part of the UI layer.
    # This part of the function will now just directly call the stream.
    try:
        # if log_func:
        #     log_func("发送到 LLM 的提示词 (一致性审校 - 后备逻辑):\n" + prompt)

        full_result = ""
        # Ensure we have an adapter
        if not llm_adapter and llm_config:
            llm_adapter = create_llm_adapter(llm_config)
        elif not llm_adapter:
            raise ValueError("一致性审校需要 llm_adapter 或 llm_config。")
            
        for chunk in check_consistency_stream(
            llm_adapter=llm_adapter, custom_prompt=prompt, log_func=log_func, log_stream=log_stream
        ):
            if chunk:
                full_result += chunk

        save_string_to_txt(full_result, output_file_path)
        if log_func:
            log_func("\n✅ 一致性审校完成 (后备逻辑)，结果已保存。")

    except Exception as e:
        error_message = f"❌ 后备审校逻辑出错: {str(e)}\n{traceback.format_exc()}"
        if log_func:
            log_func(error_message)

def check_consistency_stream(
    llm_adapter: BaseLLMAdapter,
    custom_prompt: str,
    log_func=None,
    log_stream=True
):
    """
    使用流式输出进行一致性审校。
    这是一个生成器函数，会 yield LLM 返回的每个块。
    """
    from novel_generator.common import invoke_stream_with_cleaning
    
    if log_func:
        log_func("=== 开始流式一致性审校 ===")
    
    try:
        if not llm_adapter:
            raise ValueError("check_consistency_stream 需要一个有效的 llm_adapter 实例。")

        if not custom_prompt or not custom_prompt.strip():
            yield "错误：审校提示词为空。"
            return

        if log_func:
            log_func("发送审校请求到LLM...")
        
        # 使用流式调用，现在中断由适配器内部处理
        full_response = ""
        for chunk in invoke_stream_with_cleaning(llm_adapter, custom_prompt, log_func=log_func, log_stream=log_stream):
            if chunk:
                full_response += chunk
                yield chunk
        
        if log_func:
            log_func("=== 完成流式一致性审校 ===")
        
        # 流式结束后，可以在这里添加对 full_response 的后处理逻辑，
        # 但对于流式显示，主要任务已经完成。
        
    except Exception as e:
        error_msg = f"审校过程出错: {str(e)}"
        if log_func:
            log_func(error_msg)
        # 重新抛出异常，以便上层的 execute_with_polling 能够捕获并处理
        raise
