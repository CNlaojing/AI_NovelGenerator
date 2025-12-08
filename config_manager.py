# config_manager.py
# -*- coding: utf-8 -*-
import json
import os
import threading

CONFIG_FILE = "config.json"

def load_config() -> dict:
    """从默认配置文件加载所有配置。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 确保旧配置文件兼容
                if "llm_selection_mode" not in config:
                    config["llm_selection_mode"] = "llm_config" # 默认为指定配置
                return config
        except (json.JSONDecodeError, IOError):
            # 如果文件存在但为空或格式错误，返回默认结构
            return {
                "default_config_name": None, 
                "configurations": {},
                "llm_selection_mode": "llm_config"
            }
    return {
        "default_config_name": None,
        "configurations": {},
        "polling_configs": [],
        "polling_strategy": "sequential",
        "error_handling_settings": {
            "enable_retry": True,
            "retry_count": 3,
            "enable_logging": True
        },
        "llm_selection_mode": "llm_config"
    }

def save_config(config_data: dict) -> bool:
    """将所有配置保存到默认配置文件中。"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        return True
    except IOError:
        return False

def get_config_names() -> list:
    """获取所有已保存配置的名称列表。"""
    config = load_config()
    return list(config.get("configurations", {}).keys())

def get_config(name: str) -> dict:
    """根据名称获取特定配置。"""
    config = load_config()
    return config.get("configurations", {}).get(name)

def save_named_config(name: str, llm_config: dict, embedding_config: dict) -> bool:
    """保存或更新一个命名配置。"""
    if not name:
        return False
    config = load_config()
    if "configurations" not in config:
        config["configurations"] = {}

    new_conf = {"llm_config": llm_config}

    # 仅当旧版数据功能未被隐藏时，才保存嵌入配置
    if not config.get("hide_old_data_features", False):
        new_conf["embedding_config"] = embedding_config

    config["configurations"][name] = new_conf
    return save_config(config)

def delete_config(name: str) -> bool:
    """根据名称删除一个配置。"""
    config = load_config()
    if "configurations" in config and name in config["configurations"]:
        del config["configurations"][name]
        # 如果删除的是默认配置，则将默认配置清空
        if config.get("default_config_name") == name:
            config["default_config_name"] = None
        return save_config(config)
    return False

def get_default_config_name() -> str:
    """获取默认配置的名称。"""
    config = load_config()
    return config.get("default_config_name")

def set_default_config_name(name: str) -> bool:
    """设置默认配置的名称。"""
    config = load_config()
    if "configurations" in config and name in config["configurations"]:
        config["default_config_name"] = name
        return save_config(config)
    return False

def get_polling_configs() -> list:
    """获取轮询配置的名称列表。"""
    polling_settings_file = os.path.join("ui", "轮询设定", "轮询设定.json")
    if os.path.exists(polling_settings_file):
        try:
            with open(polling_settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # 从轮询列表的每个字典中提取 "name"
                return [item.get("name") for item in settings.get("轮询列表", []) if "name" in item]
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_polling_configs(polling_config_names: list) -> bool:
    """保存轮询配置的名称列表。"""
    polling_settings_file = os.path.join("ui", "轮询设定", "轮询设定.json")
    try:
        with open(polling_settings_file, 'r+', encoding='utf-8') as f:
            settings = json.load(f)
            # 创建新的轮询列表，只包含名称
            settings["轮询列表"] = [{"name": name} for name in polling_config_names]
            f.seek(0)
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.truncate()
        return True
    except (IOError, json.JSONDecodeError):
        return False

def get_polling_strategy() -> str:
    """获取轮询策略。"""
    config = load_config()
    return config.get("polling_strategy", "sequential")

def set_polling_strategy(strategy: str) -> bool:
    """设置轮询策略。"""
    config = load_config()
    config["polling_strategy"] = strategy
    return save_config(config)

def get_error_handling_setting(key: str, default_value):
    """获取特定的错误处理设置。"""
    config = load_config()
    return config.get("error_handling_settings", {}).get(key, default_value)

def set_error_handling_setting(key: str, value) -> bool:
    """设置特定的错误处理设置。"""
    config = load_config()
    if "error_handling_settings" not in config:
        config["error_handling_settings"] = {}
    config["error_handling_settings"][key] = value
    return save_config(config)

def get_default_config() -> dict:
    """获取默认配置。"""
    default_name = get_default_config_name()
    if default_name:
        return get_config(default_name)
    return None

# --- Project-specific config functions ---

PROJECT_SETTINGS_FILE = "基本信息.json"

def load_project_config(project_path: str) -> dict:
    """从指定的项目路径加载项目配置。"""
    if not project_path or not os.path.isdir(project_path):
        return None
    
    config_path = os.path.join(project_path, PROJECT_SETTINGS_FILE)
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None # 如果文件损坏或为空，则返回None
    return None

def save_project_config(project_path: str, config_data: dict) -> bool:
    """将项目配置保存到指定的项目路径。"""
    if not project_path or not os.path.isdir(project_path):
        return False
        
    config_path = os.path.join(project_path, PROJECT_SETTINGS_FILE)
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        return True
    except IOError:
        return False

def get_project_continue_state(project_path: str) -> dict | None:
    """从项目配置中获取工作流的继续状态。"""
    config = load_project_config(project_path)
    return config.get("workflow_continue_state") if config else None

def save_project_continue_state(project_path: str, chapter: int, step: str):
    """保存工作流的继续状态到项目配置中。"""
    config = load_project_config(project_path)
    if not config:
        # 如果连基本信息文件都没有，就无法保存
        print(f"无法加载项目配置: {project_path}，无法保存继续状态。")
        return
    
    config["workflow_continue_state"] = {
        "chapter": chapter,
        "step": step,
        "timestamp": threading.TIMEOUT_MAX # 使用标准库中的时间戳更佳，此处暂用示意
    }
    save_project_config(project_path, config)

def clear_project_continue_state(project_path: str):
    """从项目配置中清除工作流的继续状态。"""
    config = load_project_config(project_path)
    if config and "workflow_continue_state" in config:
        del config["workflow_continue_state"]
        save_project_config(project_path, config)

def test_llm_config(llm_config, log_func, handle_exception_func):
    """测试当前的LLM配置是否可用"""
    from llm_adapters import create_llm_adapter
    def task():
        try:
            log_func("开始测试LLM配置...")
            llm_adapter = create_llm_adapter(llm_config)

            test_prompt = "Please reply 'OK'"
            response = llm_adapter.invoke(test_prompt)
            if response:
                log_func("✅ LLM配置测试成功！")
                log_func(f"测试回复: {response}")
            else:
                log_func("❌ LLM配置测试失败：未获取到响应")
        except Exception as e:
            log_func(f"❌ LLM配置测试出错: {str(e)}")
            handle_exception_func("测试LLM配置时出错")

    threading.Thread(target=task, daemon=True).start()

def test_embedding_config(api_key, base_url, interface_format, model_name, log_func, handle_exception_func):
    """测试当前的Embedding配置是否可用"""
    from embedding_adapters import create_embedding_adapter
    def task():
        try:
            log_func("开始测试Embedding配置...")
            embedding_adapter = create_embedding_adapter(
                interface_format=interface_format,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name
            )

            test_text = "测试文本"
            embeddings = embedding_adapter.embed_query(test_text)
            if embeddings and len(embeddings) > 0:
                log_func("✅ Embedding配置测试成功！")
                log_func(f"生成的向量维度: {len(embeddings)}")
            else:
                log_func("❌ Embedding配置测试失败：未获取到向量")
        except Exception as e:
            log_func(f"❌ Embedding配置测试出错: {str(e)}")
            handle_exception_func("测试Embedding配置时出错")

    threading.Thread(target=task, daemon=True).start()
