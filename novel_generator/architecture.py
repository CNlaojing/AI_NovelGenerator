#novel_generator/architecture.py
# -*- coding: utf-8 -*-
"""
小说总体架构生成（Novel_architecture_generate 及相关辅助函数）
采用模块化四步法，确保高质量生成。
"""
import os
import json
import logging
from novel_generator.common import execute_with_polling
from prompt_definitions import (
    architecture_step1_mission_prompt,
    architecture_step2_worldview_prompt,
    architecture_step3_plot_prompt,
    architecture_step4_character_prompt,
    architecture_step5_style_prompt
)
from utils import clear_file_content, save_string_to_txt

def load_partial_architecture_data(filepath: str) -> dict:
    """
    从 filepath 下的 partial_architecture.json 读取已有的阶段性数据。
    """
    partial_file = os.path.join(filepath, "partial_architecture.json")
    if not os.path.exists(partial_file):
        return {}
    try:
        with open(partial_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"无法加载 partial_architecture.json: {e}")
        return {}

def save_partial_architecture_data(filepath: str, data: dict):
    """
    将阶段性数据写入 partial_architecture.json。
    """
    partial_file = os.path.join(filepath, "partial_architecture.json")
    try:
        with open(partial_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"无法保存 partial_architecture.json: {e}")

def _generation_task(prompt, log_func, llm_adapter, **kwargs):
    """
    包装LLM调用任务。
    """
    result_text = ""
    from novel_generator.common import invoke_stream_with_cleaning
    if log_func:
        log_func(f"发送到 LLM 的提示词:\n" + prompt)
    for chunk in invoke_stream_with_cleaning(llm_adapter, prompt, log_func=log_func):
        if chunk:
            result_text += chunk
    return result_text

def Novel_architecture_generate(
    main_window_instance,
    topic: str,
    genre: str,
    Total_volume_number: int,
    number_of_chapters: int,
    word_number: int,
    filepath: str,
    user_guidance: str = "",
    log_func=None,
    custom_prompts: dict = None
) -> None:
    """
    采用模块化五步法生成小说架构：
      1. 分卷使命宣言 (模块一)
      2. 世界观与冲突发生器 (模块二)
      3. 情节线设计 (模块三)
      4. 核心角色塑造 (模块四)
      5. 叙事风格与体验设计 (模块五)
    支持断点续传，最终将所有模块组合成 小说设定.txt。
    """
    os.makedirs(filepath, exist_ok=True)
    partial_data = load_partial_architecture_data(filepath)

    # --- 创建LLM适配器 ---
    llm_adapter = main_window_instance.create_llm_adapter_with_current_config(step_name="生成架构")
    if not llm_adapter:
        if log_func:
            log_func("❌ 无法创建LLM适配器，中止小说架构生成。")
        return
    if log_func:
        log_func(f"当前模型配置: {llm_adapter.get_config_name()}")
    
    steps = [
        {
            "name": "step1",
            "log_message": "正在生成小说架构：步骤1 - 生成分卷使命宣言...",
            "prompt_template": architecture_step1_mission_prompt,
            "format_keys": ["genre", "Total_volume_number", "number_of_chapters", "word_number", "topic", "user_guidance"],
            "step_name_polling": "生成架构_步骤1_分卷使命"
        },
        {
            "name": "step2",
            "log_message": "正在生成小说架构：步骤2 - 生成世界观与冲突...",
            "prompt_template": architecture_step2_worldview_prompt,
            "format_keys": ["genre", "Total_volume_number", "number_of_chapters", "word_number", "topic", "user_guidance", "step1"],
            "step_name_polling": "生成架构_步骤2_世界观"
        },
        {
            "name": "step3",
            "log_message": "正在生成小说架构：步骤3 - 设计情节线...",
            "prompt_template": architecture_step3_plot_prompt,
            "format_keys": ["genre", "Total_volume_number", "number_of_chapters", "word_number", "topic", "user_guidance", "step1", "step2"],
            "step_name_polling": "生成架构_步骤3_情节线"
        },
        {
            "name": "step4",
            "log_message": "正在生成小说架构：步骤4 - 塑造核心角色...",
            "prompt_template": architecture_step4_character_prompt,
            "format_keys": ["genre", "Total_volume_number", "number_of_chapters", "word_number", "topic", "user_guidance", "step1", "step2", "step3"],
            "step_name_polling": "生成架构_步骤4_角色"
        },
        {
            "name": "step5",
            "log_message": "正在生成小说架构：步骤5 - 设计叙事风格与最终规划...",
            "prompt_template": architecture_step5_style_prompt,
            "format_keys": ["genre", "Total_volume_number", "number_of_chapters", "word_number", "topic", "user_guidance", "step1", "step2", "step3", "step4"],
            "step_name_polling": "生成架构_步骤5_最终规划"
        }
    ]

    # 准备基础数据
    base_params = {
        "topic": topic if topic else "（未提供）",
        "genre": genre,
        "Total_volume_number": Total_volume_number,
        "number_of_chapters": number_of_chapters,
        "word_number": word_number,
        "user_guidance": user_guidance if user_guidance else "（无）"
    }

    for step in steps:
        step_name = step["name"]
        if step_name not in partial_data:
            logging.info(step["log_message"])
            
            # 准备当前步骤的prompt
            prompt_params = base_params.copy()

            # 动态添加先前步骤的结果作为格式化参数
            # 例如，对于 step3，它需要 {step1_result} 和 {step2_result}
            step_number = int(step_name.replace("step", ""))
            if step_number > 1:
                prompt_params["step1_result"] = partial_data.get("step1", "")
            if step_number > 2:
                prompt_params["step2_result"] = partial_data.get("step2", "")
            if step_number > 3:
                prompt_params["step3_result"] = partial_data.get("step3", "")
            if step_number > 4:
                prompt_params["step4_result"] = partial_data.get("step4", "")

            current_prompt_template = custom_prompts.get(step_name, step["prompt_template"]) if custom_prompts else step["prompt_template"]
            
            # 使用准备好的参数格式化提示词
            # .format(**kwargs) 会忽略掉模板中不存在的键，所以这是安全的
            prompt = current_prompt_template.format(**prompt_params)

            # 执行生成
            result = execute_with_polling(
                gui_app=main_window_instance,
                step_name=step["step_name_polling"],
                target_func=_generation_task,
                log_func=log_func,
                context_info="小说架构",
                prompt=prompt,
                llm_adapter=llm_adapter  # 将适配器实例传递下去
            )

            if not result or not result.strip():
                error_msg = f"❌ {step['log_message']}失败：所有尝试均返回空内容或失败。"
                logging.warning(error_msg)
                if log_func:
                    log_func(error_msg)
                save_partial_architecture_data(filepath, partial_data)
                return
            
            partial_data[step_name] = result
            save_partial_architecture_data(filepath, partial_data)
        else:
            logging.info(f"{step['log_message']}... 已完成，跳过。")

    # 组装最终内容
    final_content = (
        f"#=== 小说设定：五模块动态叙事蓝图 ===\n"
        f"主题：{base_params['topic']}, 类型：{base_params['genre']}, 总卷数：{base_params['Total_volume_number']}, 总章数：约{base_params['number_of_chapters']}章（每章{base_params['word_number']}字）\n\n"
        f"---\n"
        f"{partial_data['step1'].strip()}\n\n"
        f"---\n"
        f"{partial_data['step2'].strip()}\n\n"
        f"---\n"
        f"{partial_data['step3'].strip()}\n\n"
        f"---\n"
        f"{partial_data['step4'].strip()}\n\n"
        f"---\n"
        f"{partial_data['step5'].strip()}\n"
    )

    # 保存到文件
    arch_file = os.path.join(filepath, "小说设定.txt")
    clear_file_content(arch_file)
    save_string_to_txt(final_content, arch_file)
    logging.info("小说设定.txt 已成功生成。请在小说架构页面查看。")

    # 清理临时文件
    partial_arch_file = os.path.join(filepath, "partial_architecture.json")
    if os.path.exists(partial_arch_file):
        try:
            os.remove(partial_arch_file)
            logging.info("partial_architecture.json 已删除（所有步骤均已完成）。")
        except Exception as e:
            logging.warning(f"删除 partial_architecture.json 时出错: {e}")
