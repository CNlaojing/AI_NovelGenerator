# llm_adapters.py
# -*- coding: utf-8 -*-
import logging
import os
import json
import random
import time
import traceback
import tiktoken
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, Iterator
import requests
import httpx
import config_manager as cm
import threading

# 创建一个可重用的httpx客户端
# 在大多数情况下，我们应该启用SSL验证。
# 仅在连接本地或自签名证书的服务时，才考虑在特定适配器中禁用它。
http_client = httpx.Client(verify=True)
logging.info("全局httpx客户端已启用SSL验证。")

def check_base_url(url: str) -> str:
    """处理base_url的规则"""
    import re
    url = url.strip()
    if not url:
        return url
    if url.endswith('#'):
        return url.rstrip('#')
    if not re.search(r'/v\d+$', url):
        if '/v1' not in url:
            url = url.rstrip('/') + '/v1'
    return url

class BaseLLMAdapter:
    """
    统一的 LLM 接口基类，增加了日志记录和Token计算功能。
    """
    def __init__(self, llm_config: Dict[str, Any]):
        self.client = None # 用于存储底层的http客户端
        self.llm_config = llm_config
        self.api_key = llm_config.get("api_key", "")
        self.base_url = llm_config.get("base_url", "")
        self.model_name = llm_config.get("model_name", "")
        self.max_tokens = llm_config.get("max_tokens", 30000)
        self.temperature = llm_config.get("temperature", 0.7)
        self.top_p = llm_config.get("top_p", 0.9)
        self.timeout = llm_config.get("timeout", 600)
        self.proxy = llm_config.get("proxy", "")
        self.step_name = llm_config.get("step_name", "未指定步骤")
        self.config_name = llm_config.get("config_name", "Unknown")

        # 初始化日志文件路径
        log_dir = os.path.join("ui", "轮询设定")
        os.makedirs(log_dir, exist_ok=True)
        self.log_file = os.path.join(log_dir, "polling_run.log")
        self.error_log_file = os.path.join(log_dir, "polling_error.log")

        # 初始化tiktoken编码器
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logging.warning(f"无法加载tiktoken编码器: {e}，Token数量将无法计算。")
            self.tokenizer = None

    def _calculate_tokens(self, text: str) -> int:
        """使用tiktoken计算文本的token数量"""
        if not self.tokenizer or not text:
            return 0
        try:
            return len(self.tokenizer.encode(text))
        except Exception as e:
            logging.error(f"计算token时出错: {e}")
            return 0

    def _log_invocation(self, start_time: datetime, prompt: str, response: str, input_tokens: int, output_tokens: int):
        """记录一次完整的LLM调用日志"""
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        log_entry = {
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "step": self.step_name,
            "config": self.config_name,
            "model": self.model_name,
            "duration_seconds": round(duration, 2),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "prompt": prompt,
            "response": response
        }
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logging.error(f"写入LLM调用日志失败: {e}")

    def _log_error(self, prompt: str, error: Exception):
        """记录一次LLM调用错误日志"""
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "step": self.step_name,
            "config": self.config_name,
            "model": self.model_name,
            "prompt": prompt,
            "error": str(error),
            "traceback": traceback.format_exc()
        }
        
        try:
            with open(self.error_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logging.error(f"写入LLM错误日志失败: {e}")

    def get_config(self) -> dict:
        return self.llm_config

    def get_config_name(self) -> str:
        return self.config_name

    def invoke(self, prompt: str) -> str:
        """模板方法：执行非流式调用并记录日志"""
        start_time = datetime.now()
        input_tokens = self._calculate_tokens(prompt)
        response_content = ""
        try:
            response_content = self._invoke(prompt)
        except Exception as e:
            logging.error(f"LLM调用失败 ({self.config_name}/{self.model_name}): {e}")
            self._log_error(prompt, e)
            response_content = f"Error: {e}"
        finally:
            output_tokens = self._calculate_tokens(response_content)
            self._log_invocation(start_time, prompt, response_content, input_tokens, output_tokens)
        return response_content

    def invoke_stream(self, prompt: str) -> Iterator[str]:
        """模板方法：执行流式调用并记录日志"""
        start_time = datetime.now()
        input_tokens = self._calculate_tokens(prompt)
        full_response = ""
        
        try:
            stream = self._invoke_stream(prompt)
            for chunk in stream:
                full_response += chunk
                yield chunk
        except Exception as e:
            logging.error(f"LLM流式调用失败 ({self.config_name}/{self.model_name}): {e}")
            self._log_error(prompt, e)
            # 关键修复：重新抛出异常，而不是yield一个错误字符串
            # 这将允许上层调用者捕获它并触发轮询切换
            raise
        finally:
            output_tokens = self._calculate_tokens(full_response)
            self._log_invocation(start_time, prompt, full_response, input_tokens, output_tokens)

    def _invoke(self, prompt: str) -> str:
        raise NotImplementedError("Subclasses must implement ._invoke(prompt) method.")

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        raise NotImplementedError("Subclasses must implement ._invoke_stream() method.")

    def get_available_models(self) -> list:
        try:
            return self._fetch_models()
        except Exception as e:
            logging.error(f"获取模型列表失败: {e}")
            return []

    def _fetch_models(self) -> list:
        return []

    def close(self):
        """关闭与此适配器关联的网络连接。"""
        # 检查 self.client 是否存在并且有 close 方法
        if hasattr(self, 'client') and self.client and hasattr(self.client, 'close'):
            try:
                self.client.close()
                logging.info(f"适配器 '{self.config_name}' 的 httpx 客户端已关闭。")
            except Exception as e:
                logging.error(f"关闭适配器 '{self.config_name}' 的客户端时出错: {e}")
        
        # 同样检查 _stream_client
        if hasattr(self, '_stream_client') and self._stream_client and hasattr(self._stream_client, '_client') and hasattr(self._stream_client._client, 'close'):
            try:
                # 检查是否与 self.client 是同一个对象，避免重复关闭
                if self._stream_client._client is not self.client:
                    self._stream_client._client.close()
                    logging.info(f"适配器 '{self.config_name}' 的流式客户端已关闭。")
            except Exception as e:
                logging.error(f"关闭适配器 '{self.config_name}' 的流式客户端时出错: {e}")


class DeepSeekAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from langchain_openai import ChatOpenAI
        from openai import OpenAI
        super().__init__(llm_config)
        self.base_url = check_base_url(self.base_url)
        default_headers = {"User-Agent": "Mozilla/5.0"}
        self._client = ChatOpenAI(model=self.model_name, api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, top_p=self.top_p, timeout=self.timeout, default_headers=default_headers)
        self._stream_client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, default_headers=default_headers, http_client=http_client)
        self.client = self._stream_client._client

    def _invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        return response.content if response else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        # 增加超时并处理keep-alive信号
        # DeepSeek文档提到高负载时会有长达30分钟的等待
        timeout_config = httpx.Timeout(600.0, connect=60.0)
        streaming_client_with_timeout = self.llm_config.get("_stream_client") or self._stream_client
        if hasattr(streaming_client_with_timeout, 'timeout'):
            streaming_client_with_timeout.timeout = timeout_config

        response = streaming_client_with_timeout.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens
        )
        for chunk in response:
            # 增加更严格的检查，忽略None, 空字符串, 或仅包含空格的块
            if chunk.choices:
                content = chunk.choices[0].delta.content
                if content is not None and content.strip():
                    yield content

    def _fetch_models(self) -> list:
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = requests.get(f"{self.base_url}/models", headers=headers)
            if response.status_code == 200:
                return [model["id"] for model in response.json().get("data", [])]
        except Exception:
            pass
        return ["deepseek-chat", "deepseek-coder"]

class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from langchain_openai import ChatOpenAI
        from openai import OpenAI
        super().__init__(llm_config)
        self.base_url = check_base_url(self.base_url)
        # 如果设置了代理，则为这个特定的适配器创建一个新的、带有代理的客户端实例
        # 否则，使用全局的http_client
        default_headers = {"User-Agent": "Mozilla/5.0"}
        # 为所有操作设置统一且延长的超时
        timeout_config = httpx.Timeout(self.timeout, connect=60.0)
        
        http_client_instance = httpx.Client(
            proxies=self.proxy, 
            verify=True, 
            headers=default_headers,
            timeout=timeout_config
        ) if self.proxy else httpx.Client(verify=True, headers=default_headers, timeout=timeout_config)
        
        self._client = ChatOpenAI(
            model=self.model_name, 
            api_key=self.api_key, 
            base_url=self.base_url, 
            max_tokens=self.max_tokens, 
            temperature=self.temperature, 
            top_p=self.top_p, 
            timeout=self.timeout, 
            http_client=http_client_instance, 
            default_headers=default_headers
        )
        self._stream_client = OpenAI(
            api_key=self.api_key, 
            base_url=self.base_url, 
            timeout=timeout_config, 
            http_client=http_client_instance, 
            default_headers=default_headers
        )
        self.client = self._stream_client._client

    def _invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        return response.content if response else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        # streaming_client 已经通过 __init__ 配置了正确的超时，无需再次修改
        streaming_client_with_timeout = self.llm_config.get("_stream_client") or self._stream_client
            
        response = streaming_client_with_timeout.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens
        )
        for chunk in response:
            try:
                # 增加更严格的检查，忽略None, 空字符串, 或仅包含空格的块
                if chunk.choices:
                    content = chunk.choices[0].delta.content
                    if content is not None and content.strip():
                        yield content
            except IndexError:
                logging.debug("OpenAI API 流式响应中遇到一个不含内容的块，已忽略。")
                continue
            except Exception as e:
                logging.warning(f"处理OpenAI流块时发生未知错误: {e}")

    def _fetch_models(self) -> list:
        import urllib3
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            # 移除 verify=False，使用默认的安全SSL验证
            response = requests.get(f"{self.base_url}/models", headers=headers, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    return [model["id"] for model in data["data"]]
        except Exception:
            pass
        return ["gpt-4", "gpt-3.5-turbo"]

class GeminiAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        import google.generativeai as genai
        self.genai = genai
        super().__init__(llm_config)
        self._configure_genai()
        self._model = self.genai.GenerativeModel(self.model_name)

    def _configure_genai(self):
        if self.proxy:
            os.environ['https_proxy'] = self.proxy
            os.environ['http_proxy'] = self.proxy
        
        # 如果 base_url 为空，则使用默认的 Gemini API endpoint
        # 否则，使用用户提供的 base_url
        client_options = None
        if self.base_url:
            # 移除协议和路径，只保留 host:port
            endpoint = self.base_url.split("://")[-1].split("/")[0]
            client_options = {"api_endpoint": endpoint}
            
        self.genai.configure(api_key=self.api_key, client_options=client_options)

    def _invoke(self, prompt: str) -> str:
        response = self._model.generate_content(prompt, generation_config=self.genai.types.GenerationConfig(max_output_tokens=self.max_tokens, temperature=self.temperature))
        # 增加对 response.candidates 是否存在的检查
        if response and response.candidates:
            return response.text
        else:
            # 当没有有效候选内容时，记录警告并返回空字符串
            logging.warning("Gemini API 响应中没有有效的候选内容。")
            return ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        # Gemini API也可能发送空块作为keep-alive信号
        response = self._model.generate_content(
            prompt,
            generation_config=self.genai.types.GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=self.temperature
            ),
            stream=True,
            request_options={"timeout": 1800} # 设置长超时
        )
        for chunk in response:
            try:
                # 使用 try-except 块来优雅地处理可能出现的 IndexError
                # 当 chunk.candidates 为空列表时，访问 chunk.text 会触发此错误
                if chunk.text and chunk.text.strip():
                    yield chunk.text
            except IndexError:
                # 这是一个预期的行为，当API发送一个空的候选列表（例如，因为安全设置）时会发生
                # 增加更详细的日志记录
                feedback_info = ""
                if hasattr(chunk, 'prompt_feedback'):
                    feedback_info = f" Prompt Feedback: {chunk.prompt_feedback}"
                logging.warning(f"Gemini API 流式响应中遇到一个不含候选内容的块，已忽略。{feedback_info}")
                continue # 继续处理下一个块
            except Exception as e:
                # 捕获并记录其他预料之外的错误
                logging.warning(f"处理Gemini流块时发生未知错误: {e}")

    def _fetch_models(self) -> list:
        try:
            self._configure_genai()
            return [m.name for m in self.genai.list_models() if 'generateContent' in m.supported_generation_methods]
        except Exception:
            return ["gemini-pro"]

class AzureOpenAIAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from langchain_openai import AzureChatOpenAI
        super().__init__(llm_config)
        import re
        match = re.match(r'https://(.+?)/openai/deployments/(.+?)/.*', self.base_url)
        if not match: raise ValueError("Invalid Azure OpenAI base_url format")
        self.azure_endpoint = f"https://{match.group(1)}"
        self.azure_deployment = match.group(2)
        self.api_version = self.base_url.split('api-version=')[-1]
        self._client = AzureChatOpenAI(azure_endpoint=self.azure_endpoint, azure_deployment=self.azure_deployment, api_version=self.api_version, api_key=self.api_key, max_tokens=self.max_tokens, temperature=self.temperature, top_p=self.top_p, timeout=self.timeout, http_client=http_client)

    def _invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        return response.content if response else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        """为Azure OpenAI实现流式调用"""
        try:
            for chunk in self._client.stream(prompt):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logging.error(f"Azure OpenAI流式调用失败: {e}")
            yield f"\nError: {e}"

class OllamaAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from langchain_openai import ChatOpenAI
        from openai import OpenAI
        super().__init__(llm_config)
        self.base_url = check_base_url(self.base_url)
        self.api_key = self.api_key or 'ollama'
        http_client_instance = httpx.Client(proxies=self.proxy, verify=True) if self.proxy else http_client
        self._client = ChatOpenAI(model=self.model_name, api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, top_p=self.top_p, timeout=self.timeout, http_client=http_client_instance)
        self._stream_client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, http_client=http_client_instance)
        self.client = self._stream_client._client

    def _invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        return response.content if response else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        response = self._stream_client.chat.completions.create(model=self.model_name, messages=[{"role": "user", "content": prompt}], stream=True, temperature=self.temperature, top_p=self.top_p, max_tokens=self.max_tokens)
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _fetch_models(self) -> list:
        try:
            response = requests.get(f"{self.base_url.replace('/v1', '')}/api/tags")
            if response.status_code == 200:
                return [model["name"] for model in response.json()["models"]]
        except Exception:
            pass
        return ["llama2", "mistral"]

class LMStudioAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from langchain_openai import ChatOpenAI
        from openai import OpenAI
        super().__init__(llm_config)
        self.base_url = check_base_url(self.base_url)
        http_client_instance = httpx.Client(proxies=self.proxy, verify=True) if self.proxy else http_client
        self._client = ChatOpenAI(model=self.model_name, api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, top_p=self.top_p, timeout=self.timeout, http_client=http_client_instance)
        self._stream_client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, http_client=http_client_instance)
        self.client = self._stream_client._client

    def _invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        return response.content if response else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        response = self._stream_client.chat.completions.create(model=self.model_name, messages=[{"role": "user", "content": prompt}], stream=True, temperature=self.temperature, top_p=self.top_p, max_tokens=self.max_tokens)
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

class AzureAIAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from azure.ai.inference import ChatCompletionsClient
        from azure.core.credentials import AzureKeyCredential
        super().__init__(llm_config)
        import re
        match = re.match(r'https://(.+?)\.services\.ai\.azure\.com.*', self.base_url)
        if not match: raise ValueError("Invalid Azure AI base_url format.")
        self.endpoint = f"https://{match.group(1)}.services.ai.azure.com/models"
        self._client = ChatCompletionsClient(endpoint=self.endpoint, credential=AzureKeyCredential(self.api_key), model=self.model_name, temperature=self.temperature, max_tokens=self.max_tokens, timeout=self.timeout)

    def _invoke(self, prompt: str) -> str:
        from azure.ai.inference.models import UserMessage
        response = self._client.complete(messages=[UserMessage(prompt)])
        return response.choices[0].message.content if response and response.choices else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        """为Azure AI Studio实现流式调用"""
        from azure.ai.inference.models import UserMessage
        try:
            response = self._client.complete(messages=[UserMessage(prompt)], stream=True)
            for chunk in response:
                if chunk.choices:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content
        except Exception as e:
            logging.error(f"Azure AI流式调用失败: {e}")
            yield f"\nError: {e}"

class VolcanoEngineAIAdapter(BaseLLMAdapter): # Inherits from BaseLLMAdapter
    def __init__(self, llm_config: Dict[str, Any]):
        from langchain_openai import ChatOpenAI
        from openai import OpenAI
        super().__init__(llm_config)
        self.base_url = check_base_url(self.base_url)
        # 火山引擎的API与OpenAI兼容，但可能需要特定的headers或处理
        # 暂时沿用OpenAIAdapter的客户端初始化逻辑，但需要注意其base_url和api_key的正确性
        default_headers = {"User-Agent": "Mozilla/5.0"}
        timeout_config = httpx.Timeout(self.timeout, connect=60.0)
        
        http_client_instance = httpx.Client(
            proxies=self.proxy, 
            verify=True, 
            headers=default_headers,
            timeout=timeout_config
        ) if self.proxy else httpx.Client(verify=True, headers=default_headers, timeout=timeout_config)
        
        self._client = ChatOpenAI(
            model=self.model_name, 
            api_key=self.api_key, 
            base_url=self.base_url, 
            max_tokens=self.max_tokens, 
            temperature=self.temperature, 
            top_p=self.top_p, 
            timeout=self.timeout, 
            http_client=http_client_instance, 
            default_headers=default_headers
        )
        self._stream_client = OpenAI(
            api_key=self.api_key, 
            base_url=self.base_url, 
            timeout=timeout_config, 
            http_client=http_client_instance, 
            default_headers=default_headers
        )
        self.client = self._stream_client._client

    def _invoke(self, prompt: str) -> str:
        # 火山引擎的调用方式与OpenAI兼容
        response = self._client.invoke(prompt)
        return response.content if response else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        # 火山引擎的流式调用方式与OpenAI兼容
        streaming_client_with_timeout = self.llm_config.get("_stream_client") or self._stream_client
            
        response = streaming_client_with_timeout.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens
        )
        for chunk in response:
            try:
                if chunk.choices:
                    content = chunk.choices[0].delta.content
                    if content is not None and content.strip():
                        yield content
            except IndexError:
                logging.debug("VolcanoEngine API 流式响应中遇到一个不含内容的块，已忽略。")
                continue
            except Exception as e:
                logging.warning(f"处理VolcanoEngine流块时发生未知错误: {e}")

    def _fetch_models(self) -> list:
        """
        尝试从火山引擎API获取模型列表。
        如果火山引擎没有提供模型列表API，或者API调用失败，则返回空列表。
        """
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            # 火山引擎的API可能与OpenAI的/models端点不同，需要根据实际文档调整
            # 假设它也支持 /models 端点，如果不支持，这里会失败
            # 如果火山引擎没有公开的模型列表API，这里应该返回空列表
            response = requests.get(f"{self.base_url}/models", headers=headers, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    return [model["id"] for model in data["data"]]
            logging.warning(f"从火山引擎获取模型列表失败，状态码: {response.status_code}, 响应: {response.text}")
        except requests.exceptions.RequestException as e:
            logging.error(f"请求火山引擎模型列表时发生网络错误: {e}")
        except Exception as e:
            logging.error(f"从火山引擎获取模型列表时发生未知错误: {e}")
        return [] # 默认返回空列表，而不是GPT模型

class SiliconFlowAdapter(OpenAIAdapter): # Inherits from OpenAIAdapter
    pass

class ClaudeAdapter(BaseLLMAdapter):
    def __init__(self, llm_config: Dict[str, Any]):
        from anthropic import Anthropic
        super().__init__(llm_config)
        self.base_url = check_base_url(self.base_url)
        self._client = Anthropic(api_key=self.api_key, base_url=self.base_url)

    def _invoke(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text if response.content else ""

    def _invoke_stream(self, prompt: str) -> Iterator[str]:
        with self._client.messages.stream(
            model=self.model_name,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        ) as stream:
            for text in stream.text_stream:
                yield text

class SimpleEmbeddingAdapter:
    def __init__(self, model_name="text-embedding-ada-002"):
        self.model_name = model_name
    def embed_documents(self, texts):
        import numpy as np
        return [np.ones(1536) for _ in texts]
    def embed_query(self, text):
        import numpy as np
        return np.ones(1536)

def create_llm_adapter(llm_config: dict) -> BaseLLMAdapter:
    """工厂函数：根据 llm_config 字典返回不同的适配器实例。"""
    interface_format = llm_config.get("interface_format", "").strip().lower()
    
    adapter_map = {
        # --- UI中的主要接口 ---
        "openai兼容": OpenAIAdapter,
        "openai": OpenAIAdapter,
        "claude": ClaudeAdapter,
        "google gemini": GeminiAdapter,
        "ollama": OllamaAdapter,
        "lmstudio": LMStudioAdapter,
        "deepseek": DeepSeekAdapter,
        "硅基流动": SiliconFlowAdapter,
        "openrouter": OpenAIAdapter,
        "火山引擎": VolcanoEngineAIAdapter,
        "azure openai": AzureOpenAIAdapter,
        "moonshot kimi": OpenAIAdapter,
        "阿里云百炼": OpenAIAdapter,
        
        # --- 用于兼容旧配置或别名的键 ---
        "gemini": GeminiAdapter,
        "azure ai": AzureAIAdapter,
        "lm studio": LMStudioAdapter,
    }
    
    adapter_class = adapter_map.get(interface_format)
    
    if not adapter_class:
        raise ValueError(f"Unknown interface_format: {interface_format}")
        
    adapter = adapter_class(llm_config)
    
    try:
        adapter.embedding_adapter = SimpleEmbeddingAdapter()
    except Exception as e:
        logging.warning(f"创建embedding_adapter失败: {e}")
    
    return adapter

class PollingManager:
    """管理LLM轮询调用的核心类。"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(PollingManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
        with self._lock:
            if hasattr(self, '_initialized') and self._initialized:
                return
            
            self.polling_settings_file = os.path.join("ui", "轮询设定", "轮询设定.json")
            self.settings = self._load_settings()
            self.polling_list = self.settings.get("轮询列表", [])
            self.step_configs = self.settings.get("步骤", {})
            self.state = self.settings.get("调用状态", {"上次调用AI索引": -1, "AI状态": {}})
            self.last_used_index = self.state.get("上次调用AI索引", -1)
            self.shuffled_indices = None
            self._initialized = True

    def get_next_config_name(self, step_name: str) -> Optional[str]:
        """
        根据轮询策略获取下一个配置的名称，并更新内部状态。
        这是新的核心轮询逻辑。
        """
        step_config = self.step_configs.get(step_name, {})
        specific_config_name = step_config.get("指定配置")

        if specific_config_name and specific_config_name != "无":
            return specific_config_name

        if not self.polling_list:
            return None

        strategy = self.settings.get("设置", {}).get("轮询策略", "sequential")
        
        if strategy == "random":
            if self.shuffled_indices is None or not self.shuffled_indices:
                self.shuffled_indices = list(range(len(self.polling_list)))
                random.shuffle(self.shuffled_indices)
            
            next_index = self.shuffled_indices.pop(0)
            config_name = self.polling_list[next_index]["name"]
        else:  # sequential
            self.last_used_index = (self.last_used_index + 1) % len(self.polling_list)
            config_name = self.polling_list[self.last_used_index]["name"]
            self.state["上次调用AI索引"] = self.last_used_index
            self._save_state()
            
        return config_name

    def _get_default_settings(self) -> Dict[str, Any]:
        """返回默认的轮询设置"""
        return {
            "设置": {
                "轮询策略": "sequential",
                "错误处理": {
                    "是否重试": True,
                    "重试次数": 3,
                    "是否记录日志": True,
                    "错误处理策略": "log_and_continue"
                }
            },
            "轮询列表": [],
            "步骤": {},
            "调用状态": {
                "上次调用AI索引": -1,
                "AI状态": {}
            }
        }

    def _save_settings(self, settings: Dict[str, Any]):
        """将设置保存到文件"""
        try:
            with open(self.polling_settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"保存轮询配置文件失败: {e}")

    def _load_settings(self) -> Dict[str, Any]:
        """加载轮询设置，如果文件不存在、为空或无效，则创建/修复"""
        try:
            if os.path.exists(self.polling_settings_file):
                with open(self.polling_settings_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content.strip():
                        raise ValueError("配置文件为空")
                    return json.loads(content)
            else:
                logging.info(f"轮询配置文件不存在，将创建默认文件: {self.polling_settings_file}")
                default_settings = self._get_default_settings()
                self._save_settings(default_settings)
                return default_settings
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"加载或解析轮询配置文件失败: {e}。将创建并使用默认设置。")
            default_settings = self._get_default_settings()
            self._save_settings(default_settings)
            return default_settings

    def reset_random_polling(self):
        """重置随机轮询的状态，以便开始新的轮询周期。"""
        self.shuffled_indices = None

    def _save_state(self):
        """保存当前的调用状态到配置文件"""
        try:
            self.settings["调用状态"] = self.state
            self._save_settings(self.settings)
        except Exception as e:
            logging.error(f"保存轮询状态失败: {e}")

    def get_adapter_by_name(self, config_name: str) -> Optional[BaseLLMAdapter]:
        """
        根据配置名称直接获取一个LLM适配器实例。
        """
        config_data = cm.get_config(config_name)
        if config_data and "llm_config" in config_data:
            llm_config = config_data["llm_config"].copy()
            llm_config["config_name"] = config_name
            return create_llm_adapter(llm_config)
        
        logging.error(f"找不到配置 '{config_name}' 的数据。")
        return None
