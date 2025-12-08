# embedding_adapters.py
# -*- coding: utf-8 -*-
import logging
import traceback
from typing import List
import requests
import tiktoken
from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings
import config_manager as cm

def _get_embedding_config_by_details(interface_format, model_name):
    """
    A helper function to find the embedding config from config.json
    that matches the provided interface_format and model_name.
    """
    all_configs = cm.load_config().get("configurations", {})
    for config_name, config_data in all_configs.items():
        embedding_config = config_data.get("embedding_config", {})
        if (embedding_config.get("interface_format") == interface_format and
            embedding_config.get("model_name") == model_name):
            return embedding_config
    return None

def ensure_openai_base_url_has_v1(url: str) -> str:
    """
    若用户输入的 url 不包含 '/v1'，则在末尾追加 '/v1'。
    """
    import re
    url = url.strip()
    if not url:
        return url
    if not re.search(r'/v\d+$', url):
        if '/v1' not in url:
            url = url.rstrip('/') + '/v1'
    return url

class BaseEmbeddingAdapter:
    """
    Embedding 接口统一基类
    """
    def __init__(self):
        self.model_name = "Unknown" # Default value

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, query: str) -> List[float]:
        raise NotImplementedError

class OpenAIEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 OpenAIEmbeddings（或兼容接口）的适配器
    """
    def __init__(self, api_key: str, base_url: str, model_name: str):
        super().__init__()
        self.model_name = model_name
        self._embedding = OpenAIEmbeddings(
            openai_api_key=api_key,
            openai_api_base=ensure_openai_base_url_has_v1(base_url),
            model=model_name
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        logging.info(f"向 OpenAI 接口 (模型: {self.model_name}) 发送 {len(texts)} 个文档进行向量化...")
        try:
            result = self._embedding.embed_documents(texts)
            failed_count = sum(1 for emb in result if not emb)
            if failed_count > 0:
                logging.warning(f"OpenAI 接口: {failed_count}/{len(texts)} 个文档向量化失败。")
            else:
                logging.info(f"✅ 成功从 OpenAI 接口获取 {len(texts)} 个文档的向量。")
            return result
        except Exception as e:
            logging.error(f"❌ OpenAI 接口向量化失败: {e}")
            logging.error(traceback.format_exc())
            return [[] for _ in texts]

    def embed_query(self, query: str) -> List[float]:
        logging.info(f"向 OpenAI 接口 (模型: {self.model_name}) 发送1个查询进行向量化...")
        try:
            result = self._embedding.embed_query(query)
            logging.info(f"✅ 成功从 OpenAI 接口获取查询的向量。")
            return result
        except Exception as e:
            logging.error(f"❌ OpenAI 接口查询向量化失败: {e}")
            logging.error(traceback.format_exc())
            return []

class AzureOpenAIEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 AzureOpenAIEmbeddings（或兼容接口）的适配器
    """
    def __init__(self, api_key: str, base_url: str, model_name: str):
        super().__init__()
        self.model_name = model_name
        import re
        match = re.match(r'https://(.+?)/openai/deployments/(.+?)/embeddings\?api-version=(.+)', base_url)
        if match:
            self.azure_endpoint = f"https://{match.group(1)}"
            self.azure_deployment = match.group(2)
            self.api_version = match.group(3)
        else:
            raise ValueError("Invalid Azure OpenAI base_url format")
        
        self._embedding = AzureOpenAIEmbeddings(
            azure_endpoint=self.azure_endpoint,
            azure_deployment=self.azure_deployment,
            openai_api_key=api_key,
            api_version=self.api_version,
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        logging.info(f"向 Azure OpenAI 接口 (模型: {self.azure_deployment}) 发送 {len(texts)} 个文档进行向量化...")
        try:
            result = self._embedding.embed_documents(texts)
            failed_count = sum(1 for emb in result if not emb)
            if failed_count > 0:
                logging.warning(f"Azure OpenAI 接口: {failed_count}/{len(texts)} 个文档向量化失败。")
            else:
                logging.info(f"✅ 成功从 Azure OpenAI 接口获取 {len(texts)} 个文档的向量。")
            return result
        except Exception as e:
            logging.error(f"❌ Azure OpenAI 接口向量化失败: {e}")
            logging.error(traceback.format_exc())
            return [[] for _ in texts]

    def embed_query(self, query: str) -> List[float]:
        logging.info(f"向 Azure OpenAI 接口 (模型: {self.azure_deployment}) 发送1个查询进行向量化...")
        try:
            result = self._embedding.embed_query(query)
            logging.info(f"✅ 成功从 Azure OpenAI 接口获取查询的向量。")
            return result
        except Exception as e:
            logging.error(f"❌ Azure OpenAI 接口查询向量化失败: {e}")
            logging.error(traceback.format_exc())
            return []

class OllamaEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    其接口路径为 /api/embeddings
    """
    def __init__(self, model_name: str, base_url: str):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            vec = self._embed_single(text)
            embeddings.append(vec)
        return embeddings

    def embed_query(self, query: str) -> List[float]:
        return self._embed_single(query)

    def _embed_single(self, text: str) -> List[float]:
        """
        调用 Ollama 本地服务 /api/embeddings 接口，获取文本 embedding
        """
        url = self.base_url.rstrip("/")
        if "/api/embeddings" not in url:
            if "/api" in url:
                url = f"{url}/embeddings"
            else:
                if "/v1" in url:
                    url = url[:url.index("/v1")]
                url = f"{url}/api/embeddings"

        data = {
            "model": self.model_name,
            "prompt": text
        }
        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            result = response.json()
            if "embedding" not in result:
                raise ValueError("No 'embedding' field in Ollama response.")
            return result["embedding"]
        except requests.exceptions.RequestException as e:
            logging.error(f"Ollama embeddings request error: {e}\n{traceback.format_exc()}")
            return []

class LMStudioEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 LM Studio 的 embedding 适配器
    """
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.url = ensure_openai_base_url_has_v1(base_url)
        if not self.url.endswith('/embeddings'):
            self.url = f"{self.url}/embeddings"
        
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self.model_name = model_name

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        try:
            payload = {
                "input": texts,
                "model": self.model_name
            }
            response = requests.post(self.url, json=payload, headers=self.headers)
            response.raise_for_status()
            result = response.json()
            if "data" not in result:
                logging.error(f"Invalid response format from LM Studio API: {result}")
                return [[]] * len(texts)
            return [item.get("embedding", []) for item in result["data"]]
        except requests.exceptions.RequestException as e:
            logging.error(f"LM Studio API request failed: {str(e)}")
            return [[]] * len(texts)
        except (KeyError, IndexError, ValueError, TypeError) as e:
            logging.error(f"Error parsing LM Studio API response: {str(e)}")
            return [[]] * len(texts)

    def embed_query(self, query: str) -> List[float]:
        try:
            payload = {
                "input": query,
                "model": self.model_name
            }
            response = requests.post(self.url, json=payload, headers=self.headers)
            response.raise_for_status()
            result = response.json()
            if "data" not in result or not result["data"]:
                logging.error(f"Invalid response format from LM Studio API: {result}")
                return []
            return result["data"][0].get("embedding", [])
        except requests.exceptions.RequestException as e:
            logging.error(f"LM Studio API request failed: {str(e)}")
            return []
        except (KeyError, IndexError, ValueError, TypeError) as e:
            logging.error(f"Error parsing LM Studio API response: {str(e)}")
            return []

class GeminiEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 Google Generative AI (Gemini) 接口的 Embedding 适配器
    使用直接 POST 请求方式，URL 示例：
    https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key=YOUR_API_KEY
    """
    def __init__(self, api_key: str, model_name: str, base_url: str):
        """
        :param api_key: 传入的 Google API Key
        :param model_name: 这里一般是 "text-embedding-004"
        :param base_url: e.g. https://generativelanguage.googleapis.com/v1beta/models
        """
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/") if base_url else "https://generativelanguage.googleapis.com/v1beta/models"

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            vec = self._embed_single(text)
            embeddings.append(vec)
        return embeddings

    def embed_query(self, query: str) -> List[float]:
        return self._embed_single(query)

    def _embed_single(self, text: str) -> List[float]:
        """
        直接调用 Google Generative Language API (Gemini) 接口，获取文本 embedding
        """
        url = f"{self.base_url}/{self.model_name}:embedContent?key={self.api_key}"
        payload = {
            "model": self.model_name,
            "content": {
                "parts": [
                    {"text": text}
                ]
            }
        }

        try:
            response = requests.post(url, json=payload)
            print(response.text)
            response.raise_for_status()
            result = response.json()
            embedding_data = result.get("embedding", {})
            return embedding_data.get("values", [])
        except requests.exceptions.RequestException as e:
            logging.error(f"Gemini embed_content request error: {e}\n{traceback.format_exc()}")
            return []
        except Exception as e:
            logging.error(f"Gemini embed_content parse error: {e}\n{traceback.format_exc()}")
            return []

class AliyunBailianEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 阿里云百炼 的 embedding 适配器
    """
    def __init__(self, api_key: str, base_url: str, model_name: str):
        # 确保 base_url 指向 compatible-mode/v1
        url = base_url.strip().rstrip('/')
        if 'compatible-mode/v1' not in url:
             if 'compatible-mode' in url:
                 url = url.split('compatible-mode')[0] + 'compatible-mode/v1'
             else:
                 url = url + '/compatible-mode/v1'
        else:
            # 如果它包含更多，如 /embeddings，则剥离它
            url = url.split('/embeddings')[0]

        self.url = url + '/embeddings'
        
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self.model_name = model_name

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            payload = {
                "input": texts,
                "model": self.model_name
            }
            response = requests.post(self.url, json=payload, headers=self.headers)
            response.raise_for_status()
            result = response.json()
            
            if "data" not in result or not isinstance(result["data"], list):
                logging.error(f"Invalid response format from Aliyun API: {result}")
                return [[] for _ in texts]
            
            sorted_data = sorted(result["data"], key=lambda x: x.get("index", 0))
            
            return [item.get("embedding", []) for item in sorted_data]
        except requests.exceptions.RequestException as e:
            logging.error(f"Aliyun API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response status: {e.response.status_code}, body: {e.response.text}")
            return [[] for _ in texts]
        except Exception as e:
            logging.error(f"Error processing Aliyun response: {e}\n{traceback.format_exc()}")
            return [[] for _ in texts]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)

    def embed_query(self, query: str) -> List[float]:
        result = self._embed([query])
        return result[0] if result else []

class VolcanoEngineEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 火山引擎 的 embedding 适配器
    """
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.url = base_url.rstrip('/') + '/embeddings'
        
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self.model_name = model_name

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            payload = {
                "input": texts,
                "model": self.model_name
            }
            response = requests.post(self.url, json=payload, headers=self.headers)
            response.raise_for_status()
            result = response.json()
            
            if "data" not in result or not isinstance(result["data"], list):
                logging.error(f"Invalid response format from Volcano Engine API: {result}")
                return [[] for _ in texts]
            
            sorted_data = sorted(result["data"], key=lambda x: x.get("index", 0))
            
            return [item.get("embedding", []) for item in sorted_data]
        except requests.exceptions.RequestException as e:
            logging.error(f"Volcano Engine API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response status: {e.response.status_code}, body: {e.response.text}")
            return [[] for _ in texts]
        except Exception as e:
            logging.error(f"Error processing Volcano Engine response: {e}\n{traceback.format_exc()}")
            return [[] for _ in texts]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)

    def embed_query(self, query: str) -> List[float]:
        result = self._embed([query])
        return result[0] if result else []

class SiliconFlowEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    基于 SiliconFlow 的 embedding 适配器
    """
    def __init__(self, api_key: str, base_url: str, model_name: str, max_tokens: int = 511):
        super().__init__()
        self.model_name = model_name
        self.max_tokens = max_tokens
        # 自动为 base_url 添加 scheme（如果缺失）
        if base_url and not base_url.startswith("http://") and not base_url.startswith("https://"):
            base_url = "https://" + base_url
        self.url = base_url if base_url else "https://api.siliconflow.cn/v1/embeddings"

        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def _embed(self, texts: list[str]) -> list[list[float]]:
        logging.info(f"向 SiliconFlow 接口 (模型: {self.model_name}) 发送 {len(texts)} 个文档进行向量化...")
        
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            logging.warning("tiktoken 不可用，将使用字符数进行粗略估算。")
            encoding = None

        final_embeddings = [[] for _ in texts]
        batch_size = 32  # 设定一个合理的批次大小

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_indices = list(range(i, i + len(batch_texts)))
            
            logging.info(f"  -> 正在处理批次 {i//batch_size + 1} (文档 {i+1}-{i+len(batch_texts)})...")

            texts_to_process = []
            for text_in_batch in batch_texts:
                if encoding:
                    token_count = len(encoding.encode(text_in_batch))
                else:
                    token_count = len(text_in_batch)

                if token_count > self.max_tokens:
                    logging.warning(f"    - 文本 (长度: {token_count} tokens) 超过 {self.max_tokens} token 限制，将进行截断。")
                    if encoding:
                        tokens = encoding.encode(text_in_batch)
                        truncated_text = encoding.decode(tokens[:self.max_tokens])
                    else:
                        truncated_text = text_in_batch[:self.max_tokens]
                    texts_to_process.append(truncated_text)
                else:
                    texts_to_process.append(text_in_batch)

            if not texts_to_process:
                continue

            payload = {
                "model": self.model_name,
                "input": texts_to_process,
                "encoding_format": "float"
            }
            
            try:
                response = requests.post(self.url, json=payload, headers=self.headers)
                response.raise_for_status()
                result = response.json()
                
                if "data" not in result or not isinstance(result["data"], list):
                    logging.error(f"    - 批次 {i//batch_size + 1} 返回格式无效: {result}")
                    continue
                
                sorted_data = sorted(result["data"], key=lambda x: x.get("index", 0))
                
                for j, item in enumerate(sorted_data):
                    original_idx = batch_indices[j]
                    final_embeddings[original_idx] = item.get("embedding", [])

            except requests.exceptions.RequestException as e:
                logging.error(f"❌ SiliconFlow API 批次请求失败: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logging.error(f"  - Response status: {e.response.status_code}")
                    logging.error(f"  - Response body: {e.response.text}")
                # 这个批次失败了，对应的 embedding 仍然是空的 []
            except Exception as e:
                logging.error(f"❌ 处理 SiliconFlow 批次响应时出错: {e}\n{traceback.format_exc()}")

        failed_count = sum(1 for emb in final_embeddings if not emb)
        if failed_count > 0:
            logging.warning(f"SiliconFlow 接口: {failed_count}/{len(texts)} 个文档向量化失败。")
        else:
            logging.info(f"✅ 成功从 SiliconFlow 接口获取 {len(texts)} 个文档的向量。")
        
        return final_embeddings

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)

    def embed_query(self, query: str) -> List[float]:
        result = self._embed([query])
        return result[0] if result else []

def create_embedding_adapter(
    interface_format: str,
    api_key: str,
    base_url: str,
    model_name: str
) -> BaseEmbeddingAdapter:
    """
    工厂函数：根据 interface_format 返回不同的 embedding 适配器实例
    """
    if interface_format == "OpenAI":
        return OpenAIEmbeddingAdapter(api_key=api_key, base_url=base_url, model_name=model_name)
    elif interface_format == "Azure OpenAI":
        return AzureOpenAIEmbeddingAdapter(api_key=api_key, base_url=base_url, model_name=model_name)
    elif interface_format == "Ollama":
        return OllamaEmbeddingAdapter(model_name=model_name, base_url=base_url)
    elif interface_format == "LMStudio":
        return LMStudioEmbeddingAdapter(api_key=api_key, base_url=base_url, model_name=model_name)
    elif interface_format == "Google Gemini":
        return GeminiEmbeddingAdapter(api_key=api_key, model_name=model_name, base_url=base_url)
    elif interface_format == "阿里云百炼":
        return AliyunBailianEmbeddingAdapter(api_key=api_key, base_url=base_url, model_name=model_name)
    elif interface_format == "火山引擎":
        return VolcanoEngineEmbeddingAdapter(api_key=api_key, base_url=base_url, model_name=model_name)
    elif interface_format == "硅基流动":
        return SiliconFlowEmbeddingAdapter(api_key=api_key, base_url=base_url, model_name=model_name)
    else:
        logging.error(f"未知的 Embedding 接口格式: {interface_format}")
        return None
