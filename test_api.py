import os
import base64
import requests
import fitz  # PyMuPDF

API = os.getenv("MINERU_API_URL", "https://llm.example.com/v1/chat/completions")
KEY = os.getenv("MINERU_API_KEY", "")
MODEL = "mineru2.5-1.2b"


def parse_pdf(pdf_path, dpi=64):
    if not KEY:
        raise ValueError("请通过环境变量设置 MINERU_API_KEY")
    results = []

    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            print(f"正在解析第 {i + 1}/{len(doc)} 页")

            # 每次只渲染、发送当前页
            pix = page.get_pixmap(dpi=dpi)
            image_b64 = base64.b64encode(
                pix.tobytes("png")
            ).decode("ascii")

            r = requests.post(
                API,
                headers={"Authorization": f"Bearer {KEY}"},
                json={
                    "model": MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Parse this document page. "
                                    "Output in MinerU format."
                                ),
                            },
                        ],
                    }],
                },
                timeout=300,
            )
            if not r.ok:
                print(f"第 {i + 1} 页请求失败，HTTP 状态码：{r.status_code}")
                print("服务端错误正文：", r.text[:3000])

            r.raise_for_status()

            choice = r.json()["choices"][0]

            # 防止将被截断的正文当作完整结果
            if choice.get("finish_reason") == "length":
                raise RuntimeError(f"第 {i + 1} 页输出被截断，需要进一步切分该页")

            results.append(choice["message"]["content"])

    # 按原始页序合并
    return "\n\n".join(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="手动验证 PDF 解析接口")
    parser.add_argument("pdf_path", help="待解析的 PDF 文件路径")
    args = parser.parse_args()
    print(parse_pdf(args.pdf_path))
