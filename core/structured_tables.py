"""结构化表格的可读文本、HTML 与保守的跨页接续。"""
from __future__ import annotations

from copy import deepcopy
from html import escape
import re


_NOTE_HEADER = re.compile(r'^(?:说明|备注|注释|附注|计分说明|备注说明)$')
_ITEM_NUMBER = re.compile(r'^\d+(?:[.．]\d+)+')
_NOTE_NUMBER = re.compile(r'^(?:\d+[.．、](?!\d)|[一二三四五六七八九十]+、)')


def join_cell_lines(text: str) -> str:
    """消除排版折行，保留独立编号说明和完整句子之间的换行。"""
    result = ''
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if result:
            if _NOTE_NUMBER.match(line) or result[-1] in '。；！？':
                result += '\n'
            elif result[-1].isascii() and result[-1].isalnum() and line[0].isascii() and line[0].isalnum():
                result += ' '
        result += line
    return result


def _grid(part: dict) -> list[list[dict | None]]:
    grid = [[None] * part['column_count'] for _ in range(part['row_count'])]
    for cell in part['cells']:
        for row in range(cell['row'], cell['row'] + cell['rowspan']):
            for column in range(cell['column'], cell['column'] + cell['colspan']):
                grid[row][column] = cell
    return grid


def _part_html(part: dict) -> str:
    rows = []
    for row in range(part['row_count']):
        cells = []
        for cell in sorted((c for c in part['cells'] if c['row'] == row), key=lambda c: c['column']):
            tag = 'th' if row < part['header_rows'] else 'td'
            text = escape(cell['text']).replace('\n', '<br>')
            cells.append(f'<{tag} rowspan="{cell["rowspan"]}" colspan="{cell["colspan"]}">{text}</{tag}>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return f'<section data-page="{part["page_num"] + 1}"><p>第 {part["page_num"] + 1} 页</p><table>' + ''.join(rows) + '</table></section>'


def build_structured_table(parts: list[dict], table_id: str, title: str = '') -> dict:
    """保留原始单元格，同时按合并说明的覆盖行建立分组，不按视觉行错配说明。"""
    rows, notes = [], {}
    scopes = {'table': title or '本表'}
    active_scope = ''
    previous_tail = {}
    for part in parts:
        grid = _grid(part)
        note_columns = {
            column for column, header in enumerate(part['columns'])
            if _NOTE_HEADER.fullmatch(''.join(header.split()))
        }
        inherited = {}
        if part['header_rows'] < part['row_count']:
            for column, head in enumerate(grid[part['header_rows']]):
                tail = previous_tail.get(column)
                if (column not in note_columns and head and tail and not head['text']
                        and head['column'] == column and head['row'] == part['header_rows']
                        and head['rowspan'] > 1 and tail['cell']['rowspan'] > 1
                        and head['colspan'] == tail['cell']['colspan'] and tail['ends_at_bottom']):
                    inherited[column] = {'text': tail['text'], 'page_num': tail['page_num']}
        row_scopes = {}
        for row in range(part['header_rows'], part['row_count']):
            first = grid[row][0]
            if first and first['text'] and first['row'] == row:
                label = first['text'].replace('\n', '')
                number = _ITEM_NUMBER.match(label)
                if row == part['header_rows'] and active_scope and not number:
                    # 同一表格在页边界切开的左侧合并单元格，接续其标签文字。
                    scopes[active_scope] += label
                else:
                    active_scope = number.group().replace('．', '.') if number else label
                    scopes[active_scope] = label
            row_scopes[row] = active_scope or 'table'
            values, context_sources = [], {}
            for column, cell in enumerate(grid[row]):
                if column in note_columns:
                    continue
                # 同一横向合并单元格只输出一次；纵向合并值保留为本行上下文。
                if cell is not None and cell['column'] != column:
                    values.append('')
                    continue
                value = cell['text'] if cell else ''
                if not value and cell and column in inherited and cell['row'] == part['header_rows']:
                    value = inherited[column]['text']
                    context_sources[str(column)] = inherited[column]['page_num']
                if column == 0 and not value and active_scope:
                    value = scopes[active_scope]
                values.append(value)
            if any(values):
                rows.append({'page_num': part['page_num'], 'row': row,
                             'group_key': row_scopes[row], 'values': values,
                             'context_sources': context_sources})
        previous_tail = {
            column: {'cell': cell,
                     'text': cell['text'] or inherited.get(column, {}).get('text', ''),
                     'page_num': inherited.get(column, {}).get('page_num', part['page_num']),
                     'ends_at_bottom': cell['row'] + cell['rowspan'] == part['row_count']}
            for column, cell in enumerate(grid[-1]) if cell and cell['column'] == column
        }
        for cell in part['cells']:
            if cell['row'] < part['header_rows'] or cell['column'] not in note_columns or not cell['text']:
                continue
            covered = {row_scopes[row] for row in range(cell['row'], cell['row'] + cell['rowspan']) if row in row_scopes}
            key = next(iter(covered)) if len(covered) == 1 else 'table'
            note = notes.setdefault(key, {'group_key': key, 'text': '', 'pages': [], 'cell_refs': []})
            if note['text']:
                # 完整句子或新编号另起段；未结束的跨页句子直接接续。
                separator = '\n' if note['text'][-1] in '。；！？' or _NOTE_NUMBER.match(cell['text']) else ''
                if not separator and note['text'][-1].isascii() and note['text'][-1].isalnum() and cell['text'][0].isascii() and cell['text'][0].isalnum():
                    separator = ' '
                note['text'] += separator
            note['text'] += cell['text']
            if part['page_num'] not in note['pages']:
                note['pages'].append(part['page_num'])
            note['cell_refs'].append({'page_num': part['page_num'], 'row': cell['row'], 'column': cell['column']})
    for row in rows:
        row['scope'] = scopes[row['group_key']]
    for note in notes.values():
        note['scope'] = scopes[note['group_key']]
    return {'table_id': table_id, 'title': title, 'page_start': parts[0]['page_num'],
            'page_end': parts[-1]['page_num'], 'parts': parts, 'rows': rows,
            'columns': [header for header in parts[0]['columns'] if not _NOTE_HEADER.fullmatch(''.join(header.split()))],
            'notes': list(notes.values()), 'html': '\n'.join(_part_html(part) for part in parts)}


def table_text(table: dict) -> str:
    """评分行与对应说明相邻输出，说明不重复塞进每条评分行。"""
    output = [f'[表格：{table["title"]}]' if table.get('title') else '[表格]']
    keys = list(dict.fromkeys(row['group_key'] for row in table['rows']))
    for key in keys:
        rows = [row for row in table['rows'] if row['group_key'] == key]
        if rows:
            output.append(f'[分组：{rows[0]["scope"]}]')
            output.extend(' | '.join(row['values']) for row in rows)
        for note in table['notes']:
            if note['group_key'] == key:
                output.extend([f'[分组说明：{note["scope"]}]', note['text']])
    if 'table' not in keys:
        for note in table['notes']:
            if note['group_key'] == 'table':
                output.extend([f'[全表说明：{note["scope"]}]', note['text']])
    return '\n'.join(output)


def _continues(previous: dict, following: dict) -> bool:
    left, right = previous['parts'][-1], following['parts'][0]
    if right['page_num'] != left['page_num'] + 1 or left['column_count'] != right['column_count']:
        return False
    if not left['header_rows'] or not right['header_rows']:
        return False
    if [''.join(s.split()) for s in left['columns']] != [''.join(s.split()) for s in right['columns']]:
        return False
    if any(abs(a - b) > 0.015 for a, b in zip(left['column_edges'], right['column_edges'])):
        return False
    if abs(left['bbox'][0] / left['page_size'][0] - right['bbox'][0] / right['page_size'][0]) > 0.02:
        return False
    if abs((left['bbox'][2] - left['bbox'][0]) / left['page_size'][0]
           - (right['bbox'][2] - right['bbox'][0]) / right['page_size'][0]) > 0.03:
        return False
    return left['bbox'][3] / left['page_size'][1] >= 0.83 and right['bbox'][1] / right['page_size'][1] <= 0.18


def merge_continued_tables(blocks: list) -> list:
    """仅连接相邻内容块中的表页；中间有新标题或正文就中断接续。"""
    output = []
    for block in blocks:
        table = (block.raw or {}).get('structured_table')
        previous = (output[-1].raw or {}).get('structured_table') if output else None
        if table and previous and _continues(previous, table):
            joined = build_structured_table(deepcopy(previous['parts'] + table['parts']), previous['table_id'], previous.get('title', ''))
            raw = {**output[-1].raw, 'structured_table': joined, 'page_end': joined['page_end']}
            output[-1] = output[-1].model_copy(update={'content': table_text(joined), 'table_html': joined['html'], 'raw': raw})
        else:
            output.append(block)
    return output
