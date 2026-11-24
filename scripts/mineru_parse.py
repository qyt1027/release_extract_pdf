"""手动验证 MinerU 页面解析：python -m scripts.mineru_parse PDF路径。"""

import argparse
import base64
import os
import time

import fitz
import requests
from dotenv import load_dotenv

from core.paths import ENV_FILE


def pdf_pages_to_b64(pdf_path, dpi=60, max_pages=20):  # dpi从72降到50
    doc = fitz.open(pdf_path)
    imgs = []
    for i in range(min(len(doc), max_pages)):
        pix = doc[i].get_pixmap(dpi=dpi)
        imgs.append(base64.b64encode(pix.tobytes("jpeg")).decode())  # 去掉 quality 参数
    return imgs

def parse_pdf(pdf_path):
    load_dotenv(ENV_FILE)
    api_url = os.getenv("MINERU_API_URL", "https://llm.example.com/v1/chat/completions")
    api_key = os.getenv("MINERU_API_KEY", "").strip()
    if not api_key:
        raise ValueError("请在项目根目录 .env 中设置 MINERU_API_KEY")
    model = os.getenv("MINERU_MODEL", "mineru2.5-1.2b")
    pages = pdf_pages_to_b64(pdf_path)

    # 只测试前两页，交换顺序
    test_order = [1, 0]  # 先发第二页（索引1），再发第一页（索引0）
    for idx in test_order:
        page_b64 = pages[idx]
        page_num = idx + 1
        print(f"Testing page {page_num} ...")

        content = [{"type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{page_b64}"}}]
        content.append({"type": "text",
                        "text": "Parse this document page. Output in MinerU format."})

        r = requests.post(api_url, headers={"Authorization": f"Bearer {api_key}"}, json={
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }, timeout=300)
        print(f"  status: {r.status_code}")
        if r.status_code != 200:
            print(f"  error: {r.text[:200]}")
        else:
            print(f"  success: {r.json()['choices'][0]['message']['content'][:100]}...")
        time.sleep(5)  # 等待5秒


def main(argv=None):
    """只有显式运行命令时才读取文件并请求服务。"""
    parser = argparse.ArgumentParser(description="手动验证 MinerU 前两页解析")
    parser.add_argument("pdf_path", help="待解析的 PDF 文件路径")
    args = parser.parse_args(argv)
    try:
        parse_pdf(args.pdf_path)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
