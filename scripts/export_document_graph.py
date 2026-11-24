"""只读导出文件级制度关系图谱和可离线浏览的页面。"""
import argparse
import json
from pathlib import Path

from policy.document_graph import graph_neighborhood, load_document_graph
from policy.document_graph_view import render_document_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/document-graph"))
    parser.add_argument("--policy-id", help="可选，仅导出指定节点的有界关联")
    parser.add_argument("--depth", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    graph = load_document_graph()
    stats = graph["stats"]
    if args.policy_id:
        graph = graph_neighborhood(graph, args.policy_id, args.depth, limit=200)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (args.output / "index.html").write_text(render_document_graph(graph), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    print((args.output / "index.html").resolve())


if __name__ == "__main__":
    main()
