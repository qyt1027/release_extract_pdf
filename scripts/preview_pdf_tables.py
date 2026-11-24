"""本地预览 PDF 的复杂表格：python -m scripts.preview_pdf_tables 文件路径。"""
from __future__ import annotations

import argparse
from html import escape
import json
from itertools import groupby
from pathlib import Path

import fitz

from core.models import BlockType, ContentBlock
from core.structured_tables import merge_continued_tables
from parsers.pdf_tables import extract_structured_page


def _render(table: dict) -> str:
    chunks = [f'<article><h2>{escape(table.get("title") or "表格")}</h2>',
              f'<p class="pages">原文第 {table["page_start"] + 1}–{table["page_end"] + 1} 页</p>']
    keys = list(dict.fromkeys(row['group_key'] for row in table['rows']))
    for key in keys:
        rows = [row for row in table['rows'] if row['group_key'] == key]
        chunks.append(f'<h3>{escape(rows[0]["scope"])}</h3><div class="scroll"><table><thead><tr>')
        for label, columns in groupby(table['columns']):
            chunks.append(f'<th colspan="{len(list(columns))}">{escape(label or "内容")}</th>')
        chunks.append('</tr></thead><tbody>')
        for row in rows:
            chunks.append('<tr>' + ''.join(f'<td>{escape(value).replace(chr(10), "<br>")}</td>' for value in row['values']) + '</tr>')
        chunks.append('</tbody></table></div>')
        for note in table['notes']:
            if note['group_key'] == key:
                chunks.append(f'<div class="notes"><h4>{escape(note["scope"])} · 说明</h4><p>{escape(note["text"]).replace(chr(10), "</p><p>")}</p></div>')
    if 'table' not in keys:
        for note in table['notes']:
            if note['group_key'] == 'table':
                chunks.append(f'<div class="notes"><h4>全表说明</h4><p>{escape(note["text"]).replace(chr(10), "</p><p>")}</p></div>')
    chunks.append('<details><summary>查看原表结构与合并单元格</summary><div class="scroll">' + table['html'] + '</div></details></article>')
    return '\n'.join(chunks)


def preview_pdf_tables(pdf_path: str, output_dir: str | Path, start_page: int = 1, end_page: int | None = None) -> tuple[Path, Path]:
    """只读取原文件，输出可校验表格的 HTML 和 JSON，不请求 OCR 或写入数据库。"""
    source = Path(pdf_path).resolve()
    blocks = []
    with fitz.open(source) as document:
        end_page = end_page if end_page is not None else len(document)
        if not 1 <= start_page <= end_page <= len(document):
            raise ValueError('预览页码超出 PDF 范围')
        for index in range(start_page - 1, end_page):
            page = document[index]
            extracted = extract_structured_page(page, 'preview', source.name)
            if extracted is None:
                # 普通页面作为接续边界，不把两张不相邻的表格拼接起来。
                blocks.append(ContentBlock(type=BlockType.TEXT, page_num=page.number, content='[普通页面]'))
            else:
                blocks.extend(extracted)
    tables = [block.raw['structured_table'] for block in merge_continued_tables(blocks)
              if (block.raw or {}).get('structured_table')]
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / 'structured-tables.json'
    html_path = output / 'table-preview.html'
    json_path.write_text(json.dumps({'source_file': str(source), 'tables': tables}, ensure_ascii=False, indent=2), encoding='utf-8')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>复杂表格整理预览</title><style>
body{margin:0;background:#f3f5f7;color:#18242f;font:16px/1.75 "Microsoft YaHei",sans-serif}main{max-width:1180px;margin:auto;padding:36px 24px}h1{font-size:27px}h2{font-size:21px;margin:0}h3{margin:28px 0 10px;color:#164e63}h4{margin:0 0 10px}article{background:white;margin:26px 0;padding:28px;border:1px solid #dbe2e8;border-radius:8px}.pages{color:#667788}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:15px}td,th{border:1px solid #cbd5df;padding:10px 12px;vertical-align:top;text-align:left}th{background:#edf3f7}tr:nth-child(even){background:#f8fafb}.notes{background:#f0f6f8;border-left:4px solid #22748b;margin:18px 0;padding:18px 22px}.notes p{margin:8px 0;white-space:normal}summary{cursor:pointer;color:#375a70;margin-top:20px}details table{min-width:900px}header p{overflow-wrap:anywhere;color:#576777}
</style><main><header><h1>复杂表格整理预览</h1><p>'''
    html += escape(source.name) + f' · 第 {start_page}–{end_page} 页</p><p>评分明细与分组说明分别展示，原始合并单元格可展开核对。此预览仅包含可靠文字层表格。</p></header>'
    html += '\n'.join(_render(table) for table in tables) + '</main></html>'
    html_path.write_text(html, encoding='utf-8')
    return html_path, json_path


def main(argv=None):
    parser = argparse.ArgumentParser(description='本地预览复杂表格，不调用模型、不修改源文件')
    parser.add_argument('pdf_path')
    parser.add_argument('--output', default='outputs/pdf-tables')
    parser.add_argument('--start-page', type=int, default=1)
    parser.add_argument('--end-page', type=int)
    args = parser.parse_args(argv)
    for path in preview_pdf_tables(args.pdf_path, args.output, args.start_page, args.end_page):
        print(path)


if __name__ == '__main__':
    main()
