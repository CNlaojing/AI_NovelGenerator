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
    interface_format: str,
    api_key: str,
    base_url: str,
    llm_model: str,
    filepath: str,
    number_of_chapters: int,
    user_guidance: str = "",  # 新增参数
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 600
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

    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=llm_model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

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
    chunk_size = compute_chunk_size(number_of_chapters, max_tokens)
    logging.info(f"Number of chapters = {number_of_chapters}, computed chunk_size = {chunk_size}.")

    try:
        # 获取当前进度信息
        current_vol, last_chapter, start_chap, end_chap, is_vol_end, is_complete = get_volume_progress(filepath)
        
        # 使用获取到的信息继续处理...
        if not existing_blueprint:
            logging.info(f"开始生成第{current_vol}卷章节目录（第{start_chap}-{end_chap}章）...")
        
        if existing_blueprint:
            logging.info("Detected existing blueprint content. Will resume chunked generation from that point.")
            pattern = r"第\s*(\d+)\s*章"
            existing_chapter_numbers = re.findall(pattern, existing_blueprint)
            existing_chapter_numbers = [int(x) for x in existing_chapter_numbers if x.isdigit()]
            max_existing_chap = max(existing_chapter_numbers) if existing_chapter_numbers else 0
            logging.info(f"Existing blueprint indicates up to chapter {max_existing_chap} has been generated.")
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
                logging.info(f"Generating chapters {current_start} to {current_end}...")
                chunk_result = invoke_with_cleaning(llm_adapter, chunk_prompt)
                if chunk_result:
                    final_blueprint = final_blueprint + "\n\n" + chunk_result
                    save_string_to_txt(final_blueprint, filename_dir)
                    logging.info(f"Saved chapters {current_start} to {current_end}.")
                else:
                    logging.error(f"Failed to generate chapters {current_start} to {current_end}.")
                    break
                current_start = current_end + 1
        else:
            logging.info("No existing blueprint content. Will generate from scratch.")
            if number_of_chapters <= chunk_size:
                logging.info(f"Generating all {number_of_chapters} chapters at once...")
                prompt = chapter_blueprint_prompt.format(
                    novel_architecture=architecture_text,
                    chapter_list="",
                    start_chapter=1,
                    end_chapter=number_of_chapters,
                    user_guidance=user_guidance
                )
                result = invoke_with_cleaning(llm_adapter, prompt)
                if result:
                    save_string_to_txt(result, filename_dir)
                    logging.info(f"Successfully generated all {number_of_chapters} chapters.")
                else:
                    logging.error("Failed to generate chapters.")
            else:
                logging.info(f"Will generate {number_of_chapters} chapters in chunks of {chunk_size}...")
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
                    logging.info(f"Generating chapters {current_start} to {current_end}...")
                    chunk_result = invoke_with_cleaning(llm_adapter, chunk_prompt)
                    if chunk_result:
                        if final_blueprint:
                            final_blueprint = final_blueprint + "\n\n" + chunk_result
                        else:
                            final_blueprint = chunk_result
                        save_string_to_txt(final_blueprint, filename_dir)
                        logging.info(f"Saved chapters {current_start} to {current_end}.")
                    else:
                        logging.error(f"Failed to generate chapters {current_start} to {current_end}.")
                        break
                    current_start = current_end + 1
    except Exception as e:
        logging.error(f"生成章节目录时出错: {str(e)}")
        return None
