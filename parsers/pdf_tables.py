"""利用 PDF 文字层及网格恢复合并单元格，失败时保留原 OCR 路径。"""
from collections import Counter
import re

import fitz

from core.models import BlockType, ContentBlock
from core.structured_tables import build_structured_table, join_cell_lines, table_text


def _edges(values: list[float]) -> list[float]:
    edges = []
    for value in sorted(values):
        if not edges or value - edges[-1] > 0.5:
            edges.append(value)
    return edges


def _extract_part(page, table) -> dict | None:
    rectangles = [cell for cell in table.cells if cell is not None]
    xs = _edges([value for cell in rectangles for value in (cell[0], cell[2])])
    ys = _edges([value for cell in rectangles for value in (cell[1], cell[3])])
    if len(xs) != table.col_count + 1 or len(ys) != table.row_count + 1:
        return None
    extracted = table.extract()
    cells, occupied = [], set()
    for row, table_row in enumerate(table.rows):
        for column, rect in enumerate(table_row.cells):
            if rect is None:
                continue
            left, right = [min(range(len(xs)), key=lambda i: abs(xs[i] - x)) for x in (rect[0], rect[2])]
            top, bottom = [min(range(len(ys)), key=lambda i: abs(ys[i] - y)) for y in (rect[1], rect[3])]
            if left != column or top != row or bottom <= top or right <= left:
                return None
            slots = {(r, c) for r in range(top, bottom) for c in range(left, right)}
            if slots & occupied:
                return None
            occupied.update(slots)
            cells.append({'row': row, 'column': column, 'rowspan': bottom - top, 'colspan': right - left,
                          'text': join_cell_lines(extracted[row][column] or ''), 'bbox': list(rect)})
    if len(occupied) != table.row_count * table.col_count:
        return None
    first = [cell for cell in cells if cell['row'] == 0]
    header_rows = max(cell['rowspan'] for cell in first)
    if header_rows > 3 or any(re.match(r'^\d', cell['text']) for cell in first):
        header_rows = 0
    columns = []
    for column in range(table.col_count):
        labels = []
        for row in range(header_rows):
            for cell in cells:
                if cell['row'] <= row < cell['row'] + cell['rowspan'] and cell['column'] <= column < cell['column'] + cell['colspan']:
                    value = ''.join(cell['text'].split())
                    if value and value not in labels:
                        labels.append(value)
        columns.append(' / '.join(labels))
    return {'page_num': page.number, 'page_size': [page.rect.width, page.rect.height], 'bbox': list(table.bbox),
            'row_count': table.row_count, 'column_count': table.col_count, 'header_rows': header_rows,
            'columns': columns, 'column_edges': [(x - xs[0]) / (xs[-1] - xs[0]) for x in xs], 'cells': cells}


def extract_structured_page(page: fitz.Page, source_id: str, source_name: str) -> list[ContentBlock] | None:
    """可靠复杂表格返回独立内容块，表外图像标记为待 OCR 区域。"""
    source = page.get_text()
    if not source.strip() or '\ufffd' in source:
        return None
    tables = page.find_tables().tables
    if not tables or not any(cell is None for table in tables for row in table.rows for cell in row.cells):
        return None
    boxes = [fitz.Rect(table.bbox) for table in tables]
    if any(a.intersects(b) for i, a in enumerate(boxes) for b in boxes[i + 1:]):
        return None
    images = list({tuple(rect) for image in page.get_images() for rect in page.get_image_rects(image[0])})
    if any(fitz.Rect(image).intersects(box) for image in images for box in boxes):
        return None
    elements, recovered = [], []
    for table in tables:
        part = _extract_part(page, table)
        if part is None:
            return None
        recovered.extend(cell['text'] for cell in part['cells'])
        elements.append((table.bbox[1], table.bbox[0], 'table', part))
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            rect = fitz.Rect(line['bbox'])
            if any(rect.intersects(box) for box in boxes):
                continue
            text = ''.join(span['text'] for span in line['spans'])
            recovered.append(text)
            if any(rect.intersects(fitz.Rect(image)) for image in images):
                continue
            # 只清理位置和实际页次同时确认的页边数字，不碰表内数据。
            if text.strip() == str(page.number + 1) and (rect.y0 > page.rect.height * 0.88 or rect.y1 < page.rect.height * 0.06):
                continue
            elements.append((rect.y0, rect.x0, 'text', text))
    characters = lambda text: Counter(char for char in text if not char.isspace())
    if characters(source) != characters(''.join(recovered)):
        return None
    elements.extend((rect[1], rect[0], 'image', list(rect)) for rect in images)
    output, lines = [], []
    last_title = ''
    common = {'parser': 'mineru', 'source_file': source_name, 'page_start': page.number,
              'page_end': page.number, 'extraction': 'native_complex_table'}

    def append_text():
        if lines:
            output.append(ContentBlock(block_id=f'table_page_{source_id}_{page.number}_{len(output)}',
                                       type=BlockType.TEXT, page_num=page.number, content='\n'.join(lines), raw=dict(common)))
            lines.clear()

    for _, _, kind, value in sorted(elements, key=lambda item: (item[0], item[1])):
        if kind == 'text':
            lines.append(value)
            if re.match(r'^(?:[一二三四五六七八九十]+、|第.+[章节]|表\s*\d)', value.strip()):
                last_title = value
            continue
        append_text()
        block_id = f'table_page_{source_id}_{page.number}_{len(output)}'
        if kind == 'image':
            output.append(ContentBlock(block_id=block_id, type=BlockType.TEXT, page_num=page.number,
                                       raw={**common, 'ocr_region': value}))
        else:
            table = build_structured_table([value], block_id, last_title)
            output.append(ContentBlock(block_id=block_id, type=BlockType.TEXT, page_num=page.number,
                                       bbox=value['bbox'], content=table_text(table), table_html=table['html'],
                                       raw={**common, 'structured_table': table}))
    append_text()
    return output
