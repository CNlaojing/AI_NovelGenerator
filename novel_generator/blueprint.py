#novel_generator/blueprint.py
# -*- coding: utf-8 -*-
"""
章节蓝图生成（Chapter_blueprint_generate 及辅助函数）
"""
import os
import re
import logging
from novel_generator.common import invoke_with_cleaning
from llm_adapters import create_llm_adapter
from prompt_definitions import chapter_blueprint_prompt
from utils import read_file, clear_file_content, save_string_to_txt
from novel_generator.chapter_blueprint import get_volume_progress  # 添加这行

def compute_chunk_size(number_of_chapters: int, max_tokens: int) -> int:
    """
    基于“每章约100 tokens”的粗略估算，
    再结合当前max_tokens，计算分块大小：
      chunk_size = (floor(max_tokens/100/10)*10) - 10
    并确保 chunk_size 不会小于1或大于实际章节数。
    """
    tokens_per_chapter = 100.0
    ratio = max_tokens / tokens_per_chapter
    ratio_rounded_to_10 = int(ratio // 10) * 10
    chunk_size = ratio_rounded_to_10 - 10
    if chunk_size < 1:
        chunk_size = 1
    if chunk_size > number_of_chapters:
        chunk_size = number_of_chapters
    return chunk_size

def limit_chapter_blueprint(blueprint_text: str, limit_chapters: int = 100) -> str:
    """
    从已有章节目录中只取最近的 limit_chapters 章，以避免 prompt 超长。
    """
    pattern = r"(第\s*\d+\s*章.*?)(?=第\s*\d+\s*章|$)"
    chapters = re.findall(pattern, blueprint_text, flags=re.DOTALL)
    if not chapters:
        return blueprint_text
    if len(chapters) <= limit_chapters:
        return blueprint_text
    selected = chapters[-limit_chapters:]
    return "\n\n".join(selected).strip()

def Chapter_blueprint_generate(
    llm_config: dict,
    filepath: str,
    number_of_chapters: int,
    user_guidance: str = "",  # 新增参数
    log_func=None
) -> None:
    """
    若 章节目录.txt 已存在且内容非空，则表示可能是之前的部分生成结果；
      解析其中已有的章节数，从下一个章节继续分块生成；
      对于已有章节目录，传入时仅保留最近100章目录，避免prompt过长。
    否则：
      - 若章节数 <= chunk_size，直接一次性生成
      - 若章节数 > chunk_size，进行分块生成
    生成完成后输出至 章节目录.txt。
    """
    arch_file = os.path.join(filepath, "小说设定.txt")
    if not os.path.exists(arch_file):
        logging.warning("小说设定.txt not found. Please generate architecture first.")
        return

    architecture_text = read_file(arch_file).strip()
    if not architecture_text:
        logging.warning("小说设定.txt is empty.")
        return

    llm_adapter = create_llm_adapter(llm_config)

    filename_dir = os.path.join(filepath, "章节目录.txt")
    # 确保文件存在
    if not os.path.exists(filename_dir):
        try:
            open(filename_dir, "w", encoding="utf-8").close()
            logging.info(f"创建新的章节目录文件: {filename_dir}")
        except Exception as e:
            logging.error(f"创建章节目录文件失败: {str(e)}")
            return

    existing_blueprint = read_file(filename_dir).strip()
    chunk_size = compute_chunk_size(number_of_chapters, llm_config.get("max_tokens", 4096))
    logging.info(f"章节数为 {number_of_chapters}, computed chunk_size = {chunk_size}.")

    try:
        # 获取当前进度信息
        current_vol, last_chapter, start_chap, end_chap, is_vol_end, is_complete = get_volume_progress(filepath)
        
        # 使用获取到的信息继续处理...
        if not existing_blueprint:
            logging.info(f"开始生成第{current_vol}卷章节目录（第{start_chap}-{end_chap}章）...")
        
        if existing_blueprint:
            logging.info("检测到现有章节目录内容，将从已有内容继续生成。")
            pattern = r"第\s*(\d+)\s*章"
            existing_chapter_numbers = re.findall(pattern, existing_blueprint)
            existing_chapter_numbers = [int(x) for x in existing_chapter_numbers if x.isdigit()]
            max_existing_chap = max(existing_chapter_numbers) if existing_chapter_numbers else 0
            logging.info(f"已存在章节目录，最大章节号为: {max_existing_chap}")
            final_blueprint = existing_blueprint
            current_start = max_existing_chap + 1
            while current_start <= number_of_chapters:
                current_end = min(current_start + chunk_size - 1, number_of_chapters)
                limited_blueprint = limit_chapter_blueprint(final_blueprint, 100)
                chunk_prompt = chapter_blueprint_prompt.format(
                    novel_architecture=architecture_text,
                    chapter_list=limited_blueprint,
                    start_chapter=current_start,
                    end_chapter=current_end,
                    user_guidance=user_guidance
                )
                logging.info(f"正在将章节 {current_start} 转换为 {current_end}...")
                if log_func:
                    log_func(f"发送到 LLM 的提示词 (章节 {current_start}-{current_end}):\n" + chunk_prompt)
                    log_func("\nLLM 返回内容:")
                chunk_result = ""
                from novel_generator.common import invoke_stream_with_cleaning
                for chunk in invoke_stream_with_cleaning(llm_adapter, chunk_prompt):
                    if chunk:
                        chunk_result += chunk
                        if log_func:
                            log_func(chunk, stream=True)
                if log_func:
                    log_func("\n")
                if chunk_result:
                    final_blueprint = final_blueprint + "\n\n" + chunk_result
                    save_string_to_txt(final_blueprint, filename_dir)
                    logging.info(f"已将章节 {current_start} 保存到 {current_end}.")
                else:
                    logging.error(f"未能将章节 {current_start} 生成为 {current_end}.")
                    break
                current_start = current_end + 1
        else:
            logging.info("没有现有章节目录内容，将从头开始生成。")
            if number_of_chapters <= chunk_size:
                logging.info(f"将一次性生成 {number_of_chapters} 章章节目录...")
                prompt = chapter_blueprint_prompt.format(
                    novel_architecture=architecture_text,
                    chapter_list="",
                    start_chapter=1,
                    end_chapter=number_of_chapters,
                    user_guidance=user_guidance
                )
                if log_func:
                    log_func("发送到 LLM 的提示词 (章节 1-{}):\n".format(number_of_chapters) + prompt)
                    log_func("\nLLM 返回内容:")
                result = ""
                from novel_generator.common import invoke_stream_with_cleaning
                for chunk in invoke_stream_with_cleaning(llm_adapter, prompt):
                    if chunk:
                        result += chunk
                        if log_func:
                            log_func(chunk, stream=True)
                if log_func:
                    log_func("\n")
                if result:
                    save_string_to_txt(result, filename_dir)
                    logging.info(f"章节目录已生成并保存到 {filename_dir}.")
                else:
                    logging.error("Failed to generate chapters.")
            else:
                logging.info(f"将分块生成 {number_of_chapters} 章章节目录，每块大小为 {chunk_size} 章...")
                final_blueprint = ""
                current_start = 1
                while current_start <= number_of_chapters:
                    current_end = min(current_start + chunk_size - 1, number_of_chapters)
                    limited_blueprint = limit_chapter_blueprint(final_blueprint, 100)
                    chunk_prompt = chapter_blueprint_prompt.format(
                        novel_architecture=architecture_text,
                        chapter_list=limited_blueprint,
                        start_chapter=current_start,
                        end_chapter=current_end,
                        user_guidance=user_guidance
                    )
                    logging.info(f"正在将章节 {current_start} 转换为 {current_end}...")
                    chunk_result = invoke_with_cleaning(llm_adapter, chunk_prompt)
                    if chunk_result:
                        if final_blueprint:
                            final_blueprint = final_blueprint + "\n\n" + chunk_result
                        else:
                            final_blueprint = chunk_result
                        save_string_to_txt(final_blueprint, filename_dir)
                        logging.info(f"已将章节 {current_start} 保存到 {current_end}.")
                    else:
                        logging.error(f"未能将章节 {current_start} 生成为 {current_end}.")
                        break
                    current_start = current_end + 1
    except Exception as e:
        logging.error(f"生成章节目录时出错: {str(e)}")
        return None
