"""生成无需外部依赖的文件图谱浏览页面。"""
import json
from pathlib import Path


def render_document_graph(graph):
    """脚本数据转义后嵌入，界面原文均通过 textContent 显示。"""
    payload = json.dumps(graph, ensure_ascii=False, default=str).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = Path(__file__).with_name("web_ui").joinpath("document_graph.html").read_text(encoding="utf-8")
    script = Path(__file__).with_name("web_ui").joinpath("document_graph.js").read_text(encoding="utf-8")
    return template.replace("__DOCUMENT_GRAPH_SCRIPT__", script).replace("__DOCUMENT_GRAPH_DATA__", payload)
