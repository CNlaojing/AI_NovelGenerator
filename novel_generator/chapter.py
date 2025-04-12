# novel_generator/chapter.py
# -*- coding: utf-8 -*-
"""
章节草稿生成及获取历史章节文本、当前章节摘要等
"""
import os
import json
import logging
import re  # 添加re模块导入
from llm_adapters import create_llm_adapter
from prompt_definitions import (
    first_chapter_draft_prompt, 
    next_chapter_draft_prompt, 
    summarize_recent_chapters_prompt,  # 修改这行
    knowledge_filter_prompt,           # 修改这行
    knowledge_search_prompt           # 修改这行
)
from chapter_directory_parser import get_chapter_info_from_blueprint
from novel_generator.common import invoke_with_cleaning
from utils import read_file, clear_file_content, save_string_to_txt
from novel_generator.vectorstore_utils import (
    get_relevant_context_from_vector_store,
    load_vector_store  # 添加导入
)

def get_last_n_chapters_text(chapters_dir: str, current_chapter_num: int, n: int = 3) -> list:
    """
    从目录 chapters_dir 中获取最近 n 章的文本内容，返回文本列表。
    """
    texts = []
    start_chap = max(1, current_chapter_num - n)
    for c in range(start_chap, current_chapter_num):
        chap_file = os.path.join(chapters_dir, f"chapter_{c}.txt")
        if os.path.exists(chap_file):
            text = read_file(chap_file).strip()
            texts.append(text)
        else:
            texts.append("")
    return texts

def summarize_recent_chapters(
    interface_format: str,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    chapters_text_list: list,
    novel_number: int,            # 新增参数
    chapter_info: dict,           # 新增参数
    next_chapter_info: dict,      # 新增参数
    filepath: str,                # 新增参数
    timeout: int = 600
) -> str:  # 修改返回值类型为 str，不再是 tuple
    """
    根据前三章内容生成当前章节的精准摘要。
    如果解析失败，则返回空字符串。
    """
    try:
        combined_text = "\n".join(chapters_text_list).strip()
        if not combined_text:
            return ""
        
        # 限制组合文本长度
        max_combined_length = 4000
        if len(combined_text) > max_combined_length:
            combined_text = combined_text[-max_combined_length:]
        
        llm_adapter = create_llm_adapter(
            interface_format=interface_format,
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        # 确保所有参数都有默认值
        chapter_info = chapter_info or {}
        next_chapter_info = next_chapter_info or {}
        
        # 获取当前章节所在分卷的大纲
        volume_outline = get_volume_outline_by_chapter(filepath, novel_number)
        if not volume_outline:
            logging.warning(f"未找到第{novel_number}章对应的分卷大纲")
            volume_outline = "（未找到分卷大纲）"
        
        prompt = summarize_recent_chapters_prompt.format(
            combined_text=combined_text,
            novel_number=novel_number,  # 添加这个参数
            chapter_title=chapter_info.get("chapter_title", "未命名"),
            chapter_role=chapter_info.get("chapter_role", "常规章节"),
            chapter_purpose=chapter_info.get("chapter_purpose", "内容推进"),
            emotion_evolution=chapter_info.get("emotion_evolution", "焦虑→震惊→坚定"),
            plot_twist_level=chapter_info.get("plot_twist_level", "Lv.X"),
            volume_outline=volume_outline,
            characters_involved=chapter_info.get("characters_involved", ""),
            next_chapter_foreshadowing=next_chapter_info.get("foreshadowing", "无特殊伏笔"),
            next_chapter_title=next_chapter_info.get("chapter_title", "（未命名）")
        )
        
        response_text = invoke_with_cleaning(llm_adapter, prompt)
        summary = extract_summary_from_response(response_text)
        
        if not summary:
            logging.warning("Failed to extract summary, using full response")
            return response_text[:2000]  # 限制长度
        
        return summary[:2000]  # 限制摘要长度
        
    except Exception as e:
        logging.error(f"Error in summarize_recent_chapters: {str(e)}")
        return ""

def extract_summary_from_response(response_text: str) -> str:
    """从响应文本中提取摘要部分"""
    if not response_text:
        return ""
        
    # 查找摘要标记
    summary_markers = [
        "当前章节摘要:", 
        "章节摘要:",
        "摘要:",
        "本章摘要:"
    ]
    
    for marker in summary_markers:
        if (marker in response_text):
            parts = response_text.split(marker, 1)
            if len(parts) > 1:
                return parts[1].strip()
    
    return response_text.strip()

def format_chapter_info(chapter_info: dict) -> str:
    """将章节信息字典格式化为文本"""
    # 修改格式化模板以匹配新的目录格式
    template = """
第{number}章 [{title}]
├─本章定位：{role}
├─核心作用：{purpose}
├─悬念类型：{suspense_type}
├─情绪演变：{emotion_evolution}
├─伏笔操作：{foreshadow}
├─颠覆指数：{plot_twist_level}
└─本章简述：{summary}
"""
    return template.format(
        number=chapter_info.get('chapter_number', '未知'),
        title=chapter_info.get('chapter_title', '未知'),
        role=chapter_info.get('chapter_role', '常规章节'),
        purpose=chapter_info.get('chapter_purpose', '推进主线'),
        suspense_type=chapter_info.get('suspense_type', '信息差型'),
        emotion_evolution=chapter_info.get('emotion_evolution', '焦虑→震惊→坚定'),
        foreshadow=chapter_info.get('foreshadowing', '1.新埋设.无'),
        plot_twist_level=chapter_info.get('plot_twist_level', 'Lv.1'),
        summary=chapter_info.get('chapter_summary', '')[:75]  # 确保不超过75字
    )

def parse_search_keywords(response_text: str) -> list:
    """解析新版关键词格式（示例输入：'科技公司·数据泄露\n地下实验室·基因编辑'）"""
    return [
        line.strip().replace('·', ' ')
        for line in response_text.strip().split('\n')
        if '·' in line
    ][:5]  # 最多取5组

def apply_content_rules(texts: list, novel_number: int) -> list:
    """应用内容处理规则"""
    processed = []
    for text in texts:
        if re.search(r'第[\d]+章', text) or re.search(r'chapter_[\d]+', text):
            chap_nums = list(map(int, re.findall(r'\d+', text)))
            recent_chap = max(chap_nums) if chap_nums else 0
            time_distance = novel_number - recent_chap
            
            if time_distance <= 2:
                processed.append(f"[SKIP] 跳过近章内容：{text[:120]}...")
            elif 3 <= time_distance <= 5:
                processed.append(f"[MOD40%] {text}（需修改≥40%）")
            else:
                processed.append(f"[OK] {text}（可引用核心）")
        else:
            processed.append(f"[PRIOR] {text}（优先使用）")
    return processed

def apply_knowledge_rules(contexts: list, chapter_num: int) -> list:
    """应用知识库使用规则"""
    processed = []
    for text in contexts:
        # 检测历史章节内容
        if "第" in text and "章" in text:
            # 提取章节号判断时间远近
            chap_nums = [int(s) for s in text.split() if s.isdigit()]
            recent_chap = max(chap_nums) if chap_nums else 0
            time_distance = chapter_num - recent_chap
            
            # 相似度处理规则
            if time_distance <= 3:  # 近三章内容
                processed.append(f"[历史章节限制] 跳过近期内容: {text[:50]}...")
                continue
                
            # 允许引用但需要转换
            processed.append(f"[历史参考] {text} (需进行30%以上改写)")
        else:
            # 第三方知识优先处理
            processed.append(f"[外部知识] {text}")
    return processed

def get_filtered_knowledge_context(
    api_key: str,
    base_url: str,
    model_name: str,
    interface_format: str,
    embedding_adapter,
    filepath: str,
    chapter_info: dict,
    retrieved_texts: list,
    max_tokens: int = 2048,
    timeout: int = 600
) -> str:
    """优化后的知识过滤处理"""
    if not retrieved_texts:
        return "（无相关知识库内容）"

    try:
        processed_texts = apply_knowledge_rules(retrieved_texts, chapter_info.get('chapter_number', 0))
        llm_adapter = create_llm_adapter(
            interface_format=interface_format,
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            temperature=0.3,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        # 限制检索文本长度并格式化
        formatted_texts = []
        max_text_length = 600
        for i, text in enumerate(processed_texts, 1):
            if len(text) > max_text_length:
                text = text[:max_text_length] + "..."
            formatted_texts.append(f"[预处理结果{i}]\n{text}")

        # 获取章节信息和当前卷大纲
        chapter_num = chapter_info.get('chapter_number', 0)
        volume_outline = get_volume_outline_by_chapter(filepath, chapter_num)

        # 构建提示词
        prompt = knowledge_filter_prompt.format(
            novel_number=chapter_num,
            chapter_title=chapter_info.get('chapter_title', ''),
            global_summary=chapter_info.get('global_summary', ''),
            chapter_role=chapter_info.get('chapter_role', '常规章节'),
            chapter_purpose=chapter_info.get('chapter_purpose', '推进主线'),
            emotion_evolution=chapter_info.get('emotion_evolution', '焦虑→震惊→坚定'),
            scene_location=chapter_info.get('scene_location', ''),
            character_state=chapter_info.get('character_state', ''),
            key_items=chapter_info.get('key_items', ''),
            characters_involved=chapter_info.get('characters_involved', ''),
            volume_outline=volume_outline or '（未找到分卷大纲）',
            retrieved_texts="\n\n".join(formatted_texts) if formatted_texts else "（无检索结果）"
        )
        
        filtered_content = invoke_with_cleaning(llm_adapter, prompt)
        return filtered_content if filtered_content else "（知识内容过滤失败）"
        
    except Exception as e:
        logging.error(f"Error in knowledge filtering: {str(e)}")
        return "（内容过滤过程出错）"

def get_volume_outline_by_chapter(filepath: str, chapter_number: int) -> str:
    """根据章节号获取对应分卷的大纲内容"""
    try:
        volume_file = os.path.join(filepath, "Novel_Volume.txt")
        if not os.path.exists(volume_file):
            return ""
            
        content = read_file(volume_file)
        if not content:
            return ""
            
        # 匹配分卷信息的模式
        volume_pattern = r"#=== 第(\d+)卷.*?第(\d+)章.*?第(\d+)章"
        matches = re.finditer(volume_pattern, content, re.DOTALL)
        
        current_volume_text = ""
        for match in matches:
            start_chap = int(match.group(2))
            end_chap = int(match.group(3))
            
            if start_chap <= chapter_number <= end_chap:
                # 提取当前匹配到的卷内容直到下一个卷标记或文件末尾
                start_pos = match.start()
                next_match = re.search(r"#=== 第\d+卷", content[match.end():])
                end_pos = len(content) if not next_match else match.end() + next_match.start()
                current_volume_text = content[start_pos:end_pos].strip()
                break
                
        return current_volume_text
    except Exception as e:
        logging.error(f"获取分卷大纲时出错: {str(e)}")
        return ""

def build_chapter_prompt(
    api_key: str,
    base_url: str,
    model_name: str,
    filepath: str,
    novel_number: int,
    word_number: int,
    temperature: float,
    user_guidance: str,
    characters_involved: str,
    key_items: str,
    scene_location: str,
    time_constraint: str,
    embedding_api_key: str,
    embedding_url: str,
    embedding_interface_format: str,
    embedding_model_name: str,
    embedding_retrieval_k: int = 2,
    interface_format: str = "openai",
    max_tokens: int = 2048,
    timeout: int = 600
) -> str:
    """
    构造当前章节的请求提示词（完整实现版）
    修改重点：
    1. 优化知识库检索流程
    2. 新增内容重复检测机制
    3. 集成提示词应用规则
    """
    # 读取基础文件
    arch_file = os.path.join(filepath, "Novel_architecture.txt")
    novel_architecture_text = read_file(arch_file)
    directory_file = os.path.join(filepath, "Novel_directory.txt")
    blueprint_text = read_file(directory_file)
    global_summary_file = os.path.join(filepath, "global_summary.txt")
    global_summary_text = read_file(global_summary_file)
    character_state_file = os.path.join(filepath, "character_state.txt")
    character_state_text = read_file(character_state_file)
    
    try:
        # 获取章节信息前先清理和规范化目录文本
        blueprint_text = re.sub(r'\r\n', '\n', blueprint_text)
        blueprint_text = re.sub(r'\n\s*\n+', '\n\n', blueprint_text.strip())
        
        # 获取章节信息
        chapter_info = get_chapter_info_from_blueprint(blueprint_text, novel_number)
        if not chapter_info:
            raise ValueError(f"无法从目录中找到第{novel_number}章的信息")
            
        # 提取并验证章节信息
        chapter_title = chapter_info.get("chapter_title", f"第{novel_number}章")
        chapter_role = chapter_info.get("chapter_role", "常规章节")
        chapter_purpose = chapter_info.get("chapter_purpose", "推进主线")
        suspense_type = chapter_info.get("suspense_type", "信息差型")
        emotion_evolution = chapter_info.get("emotion_evolution", "焦虑→震惊→坚定")
        foreshadowing = chapter_info.get("foreshadowing", "1.新埋设.无")
        plot_twist_level = chapter_info.get("plot_twist_level", "Lv.1")
        chapter_summary = chapter_info.get("chapter_summary", "")[:75]
        
        # 记录日志以便调试
        logging.debug(f"找到第{novel_number}章信息：{chapter_info}")
        
        # 获取下一章节信息
        next_chapter_number = novel_number + 1
        next_chapter_info = get_chapter_info_from_blueprint(blueprint_text, next_chapter_number)
        next_chapter_title = next_chapter_info.get("chapter_title", "（未命名）")
        next_chapter_role = next_chapter_info.get("chapter_role", "过渡章节")
        next_chapter_purpose = next_chapter_info.get("chapter_purpose", "承上启下")
        next_chapter_suspense = next_chapter_info.get("suspense_type", "中等")
        next_chapter_foreshadow = next_chapter_info.get("foreshadowing", "无特殊伏笔")
        next_chapter_twist = next_chapter_info.get("plot_twist_level", "Lv.X ")
        next_chapter_summary = next_chapter_info.get("chapter_summary", "衔接过渡内容")

        # 创建章节目录
        chapters_dir = os.path.join(filepath, "chapters")
        os.makedirs(chapters_dir, exist_ok=True)

        # 获取当前章节所在分卷的大纲
        volume_outline = get_volume_outline_by_chapter(filepath, novel_number)
        if not volume_outline:
            logging.warning(f"未找到第{novel_number}章对应的分卷大纲")
            volume_outline = "（未找到分卷大纲）"

        # 第一章特殊处理
        if (novel_number == 1):
            return first_chapter_draft_prompt.format(
                novel_number=novel_number,
                word_number=word_number,
                chapter_title=chapter_title,
                chapter_role=chapter_role or "常规章节",
                chapter_purpose=chapter_purpose or "推进主线",
                suspense_type=suspense_type or "信息差型",
                emotion_evolution=emotion_evolution or "焦虑→震惊→坚定",
                foreshadowing=foreshadowing or "1.新埋设.无",
                plot_twist_level=plot_twist_level or "Lv.1",
                chapter_summary=chapter_summary[:75] if chapter_summary else "",
                characters_involved=characters_involved,
                key_items=key_items,
                scene_location=scene_location,
                time_constraint=time_constraint,
                user_guidance=user_guidance,
                novel_setting=novel_architecture_text,
                volume_outline=volume_outline  # 添加分卷大纲参数
            )

        # 获取前文内容和摘要
        recent_texts = get_last_n_chapters_text(chapters_dir, novel_number, n=3)

        # 修复缩进问题的部分
        try:
            logging.info("Attempting to generate summary")
            short_summary = summarize_recent_chapters(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                chapters_text_list=recent_texts,
                novel_number=novel_number,
                chapter_info=chapter_info,
                next_chapter_info=next_chapter_info,
                filepath=filepath,  # 添加 filepath 参数
                timeout=timeout
            )
            logging.info("Summary generated successfully")
        except Exception as e:
            logging.error(f"Error in summarize_recent_chapters: {str(e)}")
            short_summary = "（摘要生成失败）"

        # 获取前一章结尾
        previous_excerpt = ""
        for text in reversed(recent_texts):
            if (text.strip()):
                previous_excerpt = text[-800:] if len(text) > 800 else text
                break

        # 知识库检索和处理
        try:
            # 生成检索关键词
            llm_adapter = create_llm_adapter(
                interface_format=interface_format,
                base_url=base_url,
                model_name=model_name,
                api_key=api_key,
                temperature=0.3,
                max_tokens=max_tokens,
                timeout=timeout
            )
            
            search_prompt = knowledge_search_prompt.format(
                novel_number=novel_number,              # 修改这行，使用正确的变量名
                chapter_title=chapter_title,
                chapter_role=chapter_role,
                chapter_purpose=chapter_purpose,
                foreshadowing=foreshadowing,
                scene_location=scene_location,
                character_state=character_state_text,
                global_summary=global_summary_text,
                user_guidance=user_guidance,
                characters_involved=characters_involved,
                key_items=key_items
            )
            
            search_response = invoke_with_cleaning(llm_adapter, search_prompt)
            keyword_groups = parse_search_keywords(search_response)

            # 执行向量检索
            all_contexts = []
            from embedding_adapters import create_embedding_adapter
            embedding_adapter = create_embedding_adapter(
                embedding_interface_format,
                embedding_api_key,
                embedding_url,
                embedding_model_name
            )
            
            store = load_vector_store(embedding_adapter, filepath)
            if store:
                collection_size = store._collection.count()
                actual_k = min(embedding_retrieval_k, max(1, collection_size))
                
                for group in keyword_groups:
                    context = get_relevant_context_from_vector_store(
                        embedding_adapter=embedding_adapter,
                        query=group,
                        filepath=filepath,
                        k=actual_k
                    )
                    if context:
                        if any(kw in group.lower() for kw in ["技法", "手法", "模板"]):
                            all_contexts.append(f"[TECHNIQUE] {context}")
                        elif any(kw in group.lower() for kw in ["设定", "技术", "世界观"]):
                            all_contexts.append(f"[SETTING] {context}")
                        else:
                            all_contexts.append(f"[GENERAL] {context}")

            # 应用内容规则
            processed_contexts = apply_content_rules(all_contexts, novel_number)
            
            # 执行知识过滤
            chapter_info_for_filter = {
                "chapter_number": novel_number,
                "chapter_title": chapter_title,
                "chapter_role": chapter_role,
                "chapter_purpose": chapter_purpose,
                "characters_involved": characters_involved,
                "key_items": key_items,
                "scene_location": scene_location,
                "foreshadowing": foreshadowing,  # 修复拼写错误
                "suspense_type": suspense_type,
                "plot_twist_level": plot_twist_level,
                "chapter_summary": chapter_summary,
                "time_constraint": time_constraint
            }
            
            filtered_context = get_filtered_knowledge_context(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                interface_format=interface_format,
                embedding_adapter=embedding_adapter,
                filepath=filepath,
                chapter_info=chapter_info_for_filter,
                retrieved_texts=processed_contexts,
                max_tokens=max_tokens,
                timeout=timeout
            )
            
        except Exception as e:
            logging.error(f"知识处理流程异常：{str(e)}")
            filtered_context = "（知识库处理失败）"

        # 返回最终提示词
        return next_chapter_draft_prompt.format(
            user_guidance=user_guidance if user_guidance else "无特殊指导",
            global_summary=global_summary_text,
            previous_chapter_excerpt=previous_excerpt,
            character_state=character_state_text,
            short_summary=short_summary,
            novel_number=novel_number,
            chapter_title=chapter_title,
            chapter_role=chapter_role or "常规章节",
            chapter_purpose=chapter_purpose or "推进主线",
            suspense_type=suspense_type or "信息差型",
            emotion_evolution=emotion_evolution or "焦虑→震惊→坚定",
            foreshadowing=foreshadowing or "1.新埋设.无",
            plot_twist_level=plot_twist_level or "Lv.1",
            chapter_summary=chapter_summary[:75] if chapter_summary else "",
            word_number=word_number,
            characters_involved=characters_involved,
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            next_chapter_number=next_chapter_number,
            next_chapter_title=next_chapter_title,
            next_chapter_role=next_chapter_role or "常规章节",
            next_chapter_purpose=next_chapter_purpose or "推进主线",
            next_chapter_suspense_type=next_chapter_suspense or "信息差型",
            next_emotion_evolution=next_chapter_info.get("emotion_evolution", "焦虑→震惊→坚定"),
            next_chapter_foreshadowing=next_chapter_foreshadow or "1.新埋设.无",
            next_chapter_plot_twist_level=next_chapter_twist or "Lv.1",
            next_chapter_summary=next_chapter_summary[:75] if next_chapter_summary else "",
            filtered_context=filtered_context,
            volume_outline=volume_outline  # 添加分卷大纲参数
        )
    except Exception as e:
        logging.error(f"构造章节提示词时出错: {str(e)}")
        raise

def generate_chapter_draft(
    api_key: str,
    base_url: str,
    model_name: str, 
    filepath: str,
    novel_number: int,
    word_number: int,
    temperature: float,
    user_guidance: str,
    characters_involved: str,
    key_items: str,
    scene_location: str,
    time_constraint: str,
    embedding_api_key: str,
    embedding_url: str,
    embedding_interface_format: str,
    embedding_model_name: str,
    embedding_retrieval_k: int = 2,
    interface_format: str = "openai",
    max_tokens: int = 2048,
    timeout: int = 600,
    custom_prompt_text: str = None
) -> str:
    """
    生成章节草稿，支持自定义提示词
    """
    if custom_prompt_text is None:
        prompt_text = build_chapter_prompt(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            filepath=filepath,
            novel_number=novel_number,
            word_number=word_number,
            temperature=temperature,
            user_guidance=user_guidance,
            characters_involved=characters_involved,
            key_items=key_items,
            scene_location=scene_location,
            time_constraint=time_constraint,
            embedding_api_key=embedding_api_key,
            embedding_url=embedding_url,
            embedding_interface_format=embedding_interface_format,
            embedding_model_name=embedding_model_name,
            embedding_retrieval_k=embedding_retrieval_k,
            interface_format=interface_format,
            max_tokens=max_tokens,
            timeout=timeout
        )
    else:
        prompt_text = custom_prompt_text

    chapters_dir = os.path.join(filepath, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)

    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

    chapter_content = invoke_with_cleaning(llm_adapter, prompt_text)
    if not chapter_content.strip():
        logging.warning("Generated chapter draft is empty.")
    chapter_file = os.path.join(chapters_dir, f"chapter_{novel_number}.txt")
    clear_file_content(chapter_file)
    save_string_to_txt(chapter_content, chapter_file)
    logging.info(f"[Draft] Chapter {novel_number} generated as a draft.")
    return chapter_content
