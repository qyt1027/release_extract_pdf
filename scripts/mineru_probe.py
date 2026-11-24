"""手动查看 MinerU 服务接口：python -m scripts.mineru_probe。"""

import argparse
import os
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from core.paths import ENV_FILE


def main(argv=None):
    """显式运行时才发起接口探测，凭据从环境变量读取。"""
    parser = argparse.ArgumentParser(description="查看 MinerU 服务的 OpenAPI 接口")
    parser.parse_args(argv)
    load_dotenv(ENV_FILE)
    api_url = os.getenv("MINERU_API_URL", "https://llm.example.com/v1/chat/completions")
    api_key = os.getenv("MINERU_API_KEY", "").strip()
    if not api_key:
        parser.error("请在项目根目录 .env 中设置 MINERU_API_KEY")
    url = urlsplit(api_url)
    response = requests.get(
        f"{url.scheme}://{url.netloc}/openapi.json",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    print(response.status_code)
    if response.ok:
        for path in response.json().get("paths", {}):
            print(path)
    else:
        print(response.text[:500])


if __name__ == "__main__":
    main()
