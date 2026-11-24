"""共享模型客户端及本地端点识别。"""

from typing import Any
from urllib.parse import urlparse

import httpx
from openai import OpenAI


def is_local_llm_endpoint(api_url: str) -> bool:
    """判断 LLM 地址是否指向本机回环地址。"""
    try:
        hostname = urlparse(str(api_url or "")).hostname
    except ValueError:
        return False
    return str(hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}

def create_llm_client(api_url: str, api_key: str) -> OpenAI:
    """创建 LLM 客户端；本机服务不继承系统代理，远程服务维持默认行为。"""
    options: dict[str, Any] = {"base_url": api_url, "api_key": api_key}
    if is_local_llm_endpoint(api_url):
        # 本机 Ollama 不应经由企业或系统代理转发，否则可能得到 502。
        options["http_client"] = httpx.Client(trust_env=False)
    return OpenAI(**options)
