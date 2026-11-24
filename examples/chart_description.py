"""图片图表分析示例：python -m examples.chart_description 图片路径。"""

import argparse
import base64
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from core.paths import ENV_FILE


def analyze_chart(image_path: str, surrounding_text: str = "") -> dict:
    """用qwen-vl-plus分析单张图表"""

    load_dotenv(ENV_FILE)
    api_key = os.getenv("CHART_API_KEY", "").strip()
    if not api_key:
        raise ValueError("请在项目根目录 .env 中设置 CHART_API_KEY")
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv(
            "CHART_API_URL",
            "https://chart.example.com/v1",
        ),
    )

    # 图片转base64
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = f"""你是一个专业的数据图表分析助手。请对提供的图片进行详细分析，并按以下JSON格式输出：

{{
    "chart_type": "图表类型，如：折线图/柱状图/饼图/表格截图/流程图/示意图/其他",
    "title": "图表标题（如有），无则留空",
    "summary": "用2-3句话概括图表核心结论，面向非专业读者",
    "data_insight": "图表揭示的关键数据趋势、对比关系或异常点",
    "key_data_points": [
        "提取3-5个关键数据点，必须包含具体数值",
        "..."
    ]
}}

要求：
1. summary和data_insight必须包含具体数值
2. 只输出JSON，不要任何解释性文字

图表上下文文本：{surrounding_text}
"""

    response = client.chat.completions.create(
        model=os.getenv("CHART_MODEL", "qwen-vl-plus"),  # 或 qwen-vl-max（效果更好但更贵）
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}},
                {"type": "text", "text": prompt}
            ]
        }],
        temperature=0.1,  # 低温度保证JSON稳定输出
        max_tokens=1024
    )

    result_text = response.choices[0].message.content

    # 解析JSON
    try:
        json_str = result_text[result_text.find("{"):result_text.rfind("}") + 1]
        return json.loads(json_str)
    except Exception as e:
        return {"chart_type": "解析失败", "raw_output": result_text[:500]}


def main(argv=None):
    """从命令行取得图片路径，在运行时创建模型客户端。"""
    parser = argparse.ArgumentParser(description="使用视觉模型分析图片图表")
    parser.add_argument("image_path", help="待分析图片的路径")
    parser.add_argument("--context", default="", help="图表周围的文本")
    args = parser.parse_args(argv)
    try:
        result = analyze_chart(args.image_path, surrounding_text=args.context)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
