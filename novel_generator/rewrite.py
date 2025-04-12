import os
import logging
import traceback  # 添加这一行
from llm_adapters import create_llm_adapter
from utils import read_file
from novel_generator.common import invoke_with_cleaning
from chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.chapter import (
    get_volume_outline_by_chapter, 
    get_last_n_chapters_text
)

def rewrite_chapter(
    api_key: str,
    base_url: str,
    model_name: str,
    filepath: str,
    novel_number: int,
    word_number: int,
    temperature: float,
    interface_format: str,
    max_tokens: int,
    timeout: int,
    current_text: str,
    user_guidance: str = ""  # 添加默认参数
) -> str:
    """
    改写当前章节内容
    """
    try:
        # 读取必要的文件内容
        novel_arch_file = os.path.join(filepath, "Novel_architecture.txt")
        novel_architecture = read_file(novel_arch_file)
        
        directory_file = os.path.join(filepath, "Novel_directory.txt")
        blueprint_text = read_file(directory_file)
        chapter_info = get_chapter_info_from_blueprint(blueprint_text, novel_number)
        
        # 获取当前章节对应的分卷大纲
        volume_outline = get_volume_outline_by_chapter(filepath, novel_number)
        if not volume_outline:
            logging.warning(f"未找到第{novel_number}章对应的分卷大纲")
            volume_outline = "（未找到分卷大纲）"
            
        # 获取下一章信息
        next_chapter_info = get_chapter_info_from_blueprint(blueprint_text, novel_number + 1) or {}
        
        # 准备替换变量
        chapter_title = chapter_info.get('chapter_title', f'第{novel_number}章')
        raw_draft = current_text
        global_summary = read_file(os.path.join(filepath, "global_summary.txt"))
        character_state = read_file(os.path.join(filepath, "character_state.txt"))
        character_trait = ""  # 添加默认值
        
        # 构造提示词
        from prompt_definitions import chapter_rewrite_prompt
        prompt = chapter_rewrite_prompt.format(
            novel_number=novel_number,
            chapter_title=chapter_title,
            raw_draft=raw_draft,
            global_summary=global_summary,
            volume_outline=volume_outline,
            character_state=character_state,
            chapter_role=chapter_info.get('chapter_role', '常规章节'),
            chapter_purpose=chapter_info.get('chapter_purpose', '推进主线'),
            emotion_evolution=chapter_info.get('emotion_evolution', '焦虑→震惊→坚定'),
            plot_twist_level=chapter_info.get('plot_twist_level', 'Lv.1'),
            scene_location=chapter_info.get('scene_location', ''),
            characters_involved=chapter_info.get('characters_involved', ''),
            key_items=chapter_info.get('key_items', ''),
            word_number=word_number,
            core_seed=novel_architecture,
            character_dynamics=character_state,
            world_building=novel_architecture,
            character_trait=character_state,
            novel_setting=novel_architecture,
            user_guidance=user_guidance,
            term_density=5,  # 每1000字允许的专业术语数量
            branch_clues=2,  # 分支线索数量
            knowledge_filter_prompt="（知识库过滤系统）",  # 添加这一行
            number_of_chapters=novel_number,
            next_chapter_foreshadowing=next_chapter_info.get('foreshadowing', '无特殊伏笔'),
            foreshadowing=chapter_info.get('foreshadowing', '无特殊伏笔')
        )

        # 直接返回格式化后的提示词
        return prompt

    except Exception as e:
        logging.error(f"构造改写提示词时出错: {str(e)}")
        traceback.print_exc()  # 添加这行以打印完整错误栈
        return current_text
