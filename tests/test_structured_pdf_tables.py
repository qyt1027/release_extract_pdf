"""复杂网格表须保留单元格、跨页说明及制度条款边界。"""
import io
import base64
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import fitz
import httpx

from core.config import MinerUConfig
from parsers.mineru import MinerUParser
from policy.clause_export import build_batch_clause_structure
from policy.pipeline import build_policy_clauses
from processing.text import _merge_by_policy_heading


def create_merged_tables(path, continued_subtype=False):
    """两个接续表页和一个独立新表；说明跨多行，并在换页处断句。"""
    with fitz.open() as document:
        for number in range(3):
            page = document.new_page(width=600, height=400)
            top = 30 if number else 100
            header_end = top + 30
            middle = (header_end + 360) / 2
            for x in (30, 270, 340, 570):
                page.draw_line((x, top), (x, 360))
            page.draw_line((100, header_end), (100, 360))
            for y in (top, header_end, 360):
                page.draw_line((30, y), (570, y))
            page.draw_line((270 if continued_subtype else 100, middle), (340, middle))
            for x, text in ((35, '项目'), (275, '计分'), (345, '说明')):
                page.insert_text((x, top + 20), text, fontname='china-s', fontsize=10)
            if number != 1:
                page.insert_text((30, 30 if number == 0 else 20), '附件1' if number == 0 else '三、独立新表', fontname='china-s', fontsize=11)
                if number == 0:
                    page.insert_text((30, 55), '二、科研成果计分', fontname='china-s', fontsize=11)
                page.insert_text((35, header_end + 20), '2.1 论文类', fontname='china-s', fontsize=9)
            names = [('期刊论文', '100分'), ('会议论文', '60分')] if number != 1 else [('发明专利', '80分'), ('软件著作', '5分')]
            for index, (y, (name, score)) in enumerate(zip((header_end, middle), names)):
                if not continued_subtype or (number != 1 and index == 0):
                    page.insert_text((105, y + 20), name, fontname='china-s', fontsize=10)
                page.insert_text((275, y + 20), score, fontname='china-s', fontsize=10)
            notes = ['1.申请人需提供证明。', '2.共同作者按实际贡献'] if number == 0 else ['计分。', '3.同一成果不重复计分。']
            for index, note in enumerate(notes):
                page.insert_text((345, header_end + 20 + index * 18), note, fontname='china-s', fontsize=9)
            page.insert_text((290, 390), str(number + 1), fontsize=9)
        document.save(path)


class StructuredPdfTableTests(unittest.TestCase):
    def _parse(self, path, pages_per_request=1):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return httpx.Response(200, json={'choices': [{
                'finish_reason': 'stop', 'message': {'content': '整页模型结果'},
            }]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            parser = MinerUParser(MinerUConfig(api_key='test', dpi=72, pages_per_request=pages_per_request), client)
            with redirect_stdout(io.StringIO()):
                return parser.parse(str(path))

    def test_merged_cells_and_continued_notes_are_kept_without_whole_page_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '计分.pdf'
            create_merged_tables(path)
            blocks = self._parse(path)
        tables = [(block.raw or {}).get('structured_table') for block in blocks]
        tables = [table for table in tables if table]
        self.assertEqual(len(tables), 2)
        self.assertEqual(self.requests, [])
        self.assertEqual((tables[0]['page_start'], tables[0]['page_end']), (0, 1))
        self.assertTrue(any(cell['rowspan'] == 2 for cell in tables[0]['parts'][0]['cells']))
        self.assertTrue(any(cell['colspan'] == 2 for cell in tables[0]['parts'][0]['cells']))
        self.assertEqual(len(tables[0]['rows']), 4)
        self.assertTrue(all(len(row['values']) == len(tables[0]['columns']) for row in tables[0]['rows']))
        self.assertIn('2.共同作者按实际贡献计分。', tables[0]['notes'][0]['text'])
        self.assertIn('3.同一成果不重复计分。', tables[0]['notes'][0]['text'])
        self.assertEqual(tables[0]['notes'][0]['scope'], '2.1 论文类')
        self.assertIn('rowspan="2"', tables[0]['html'])
        self.assertIn('colspan="2"', tables[0]['html'])
        self.assertEqual((tables[1]['page_start'], tables[1]['page_end']), (2, 2))

    def test_multi_page_requests_do_not_swallow_structured_table_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '计分.pdf'
            create_merged_tables(path)
            blocks = self._parse(path, pages_per_request=3)
        self.assertEqual(sum(bool((block.raw or {}).get('structured_table')) for block in blocks), 2)
        self.assertEqual(self.requests, [])

    def test_table_notes_do_not_become_separate_policy_items_and_export_keeps_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '计分.pdf'
            create_merged_tables(path)
            blocks = self._parse(path)
        clauses = build_policy_clauses('policy_1', blocks)
        self.assertFalse(any(clause.item_no in {'1.', '2.', '3.'} for clause in clauses))
        payload = build_batch_clause_structure('batch_1', [{'policy_id': 'policy_1'}], {
            'policy_1': [clause.model_dump(mode='json') for clause in clauses],
        })
        tables = [table for clause in payload['documents'][0]['clauses'] for table in clause.get('tables', [])]
        self.assertEqual(len(tables), 2)
        self.assertIn('2.共同作者按实际贡献计分。', tables[0]['notes'][0]['text'])
        self.assertFalse(any(unit['text'].startswith(('1.', '2.', '3.')) for unit in _merge_by_policy_heading(blocks)))

    def test_outside_image_is_ocrd_separately_without_losing_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '带图像标题.pdf'
            create_merged_tables(path)
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
            pixmap.clear_with(255)
            with fitz.open(path) as document:
                document[0].insert_image(fitz.Rect(30, 70, 130, 90), stream=pixmap.tobytes('png'))
                document.saveIncr()
            blocks = self._parse(path)
        self.assertEqual(len(self.requests), 1)
        payload = json.loads(self.requests[0].content)
        encoded = payload['messages'][0]['content'][0]['image_url']['url'].split(',', 1)[1]
        image = fitz.Pixmap(base64.b64decode(encoded))
        self.assertEqual((image.width, image.height), (100, 20))
        self.assertTrue(any(block.content == '整页模型结果' for block in blocks))
        self.assertEqual(sum(bool((block.raw or {}).get('structured_table')) for block in blocks), 2)

    def test_unaccounted_text_falls_back_instead_of_returning_partial_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '边界文字.pdf'
            create_merged_tables(path)
            with fitz.open(path) as document:
                document[0].insert_text((10, 160), 'OUTSIDE-TABLE', fontsize=10)
                document.saveIncr()
            blocks = self._parse(path)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(blocks[0].content, '整页模型结果')

    def test_storage_keeps_tables_as_json_without_flattening_notes(self):
        from policy.storage import replace_policy_clauses

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '计分.pdf'
            create_merged_tables(path)
            blocks = self._parse(path)
        clauses = build_policy_clauses('policy_1', blocks)
        writes = []
        with (
            patch('policy.storage.ensure_policy_tables'),
            patch('policy.storage.storage.relational.execute', side_effect=lambda sql, params=None: writes.append((sql, params))),
            patch('policy.storage.storage.relational.update_rows'),
            patch('policy.retrieval.invalidate_policy_clause_bm25_index'),
        ):
            replace_policy_clauses('policy_1', clauses, 'test')
        tables = [table for sql, params in writes if sql.lstrip().startswith('INSERT') for table in json.loads(params[-1])]
        self.assertEqual(len(tables), 2)
        self.assertIn('2.共同作者按实际贡献计分。', tables[0]['notes'][0]['text'])

    def test_clipped_merged_subtype_keeps_context_on_next_page(self):
        """页底与页首跨度一致的空白合并格接续上页分类，原始单元格仍保留。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '接续子类.pdf'
            create_merged_tables(path, continued_subtype=True)
            blocks = self._parse(path)
        table = next(block.raw['structured_table'] for block in blocks if (block.raw or {}).get('structured_table'))
        self.assertEqual(table['rows'][2]['values'][1], '期刊论文')
        self.assertEqual(table['rows'][3]['values'][1], '期刊论文')
        original = next(cell for cell in table['parts'][1]['cells'] if cell['column'] == 1 and cell['row'] == 1)
        self.assertEqual(original['text'], '')
