"""验证横向填报表预处理及截断恢复不会漏页、丢失空单元格。"""
import base64
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import fitz
import httpx

from tests import test_mineru


class MinerURecoveryTests(unittest.TestCase):
    @staticmethod
    def _create_table_document(path, *, rows=35, columns=12, merged_header=False):
        """构造与问题页相同规模的横向表格，表外标题晚于表格写入。"""
        with fitz.open() as document:
            document.new_page().insert_text((60, 60), 'First page')
            page = document.new_page(width=842, height=595)
            for row in range(rows + 1):
                y = 100 + row * 12
                page.draw_line((40, y), (40 + columns * 60, y))
            for column in range(columns + 1):
                x = 40 + column * 60
                top = 112 if merged_header and column == 1 else 100
                page.draw_line((x, top), (x, 100 + rows * 12))
            for column in range(columns):
                page.insert_text((44 + column * 60, 109), f'H{column + 1}', fontsize=7)
            for row in range(1, rows):
                page.insert_text((44, 109 + row * 12), str(row), fontsize=7)
                page.insert_text((104, 109 + row * 12), f'Unit{row}', fontsize=7)
                page.insert_text((164, 109 + row * 12), str(1101000 + row), fontsize=7)
            page.insert_text((40, 55), 'Annual performance form')
            page.insert_text((40, 80), 'Department:')
            document.new_page().insert_text((60, 60), 'Last page')
            document.save(path)

    @staticmethod
    def _response(text, reason='stop'):
        return httpx.Response(200, json={
            'choices': [{'finish_reason': reason, 'message': {'content': text}}],
            'usage': {'prompt_tokens': 1854, 'completion_tokens': 6338, 'total_tokens': 8192},
        })

    def test_verified_native_table_avoids_model_request_and_preserves_following_page(self):
        """可靠网格表应在请求前直接恢复，不能依赖模型是否正常停止。"""
        replies = iter(['第一页正文', '末页正文'])
        def handler(request):
            payload = json.loads(request.content)
            url = payload['messages'][0]['content'][0]['image_url']['url']
            pixmap = fitz.Pixmap(base64.b64decode(url.split(',', 1)[1]))
            return self._response('模型错误填报' if pixmap.width > pixmap.height else next(replies))

        parser = test_mineru.MinerUParserTests._create_parser(handler)
        self.addCleanup(parser.client.close)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / 'table.pdf'
            self._create_table_document(path)
            blocks = parser.parse(str(path))
        self.assertEqual([block.page_num for block in blocks], [0, 1, 2])
        self.assertEqual([blocks[0].content, blocks[2].content], ['第一页正文', '末页正文'])
        self.assertTrue(blocks[1].content.startswith('Annual performance form\n\nDepartment:'))
        table = [line for line in blocks[1].content.splitlines() if line.startswith('|')]
        self.assertEqual(len(table), 36)
        self.assertTrue(all(len(line.split('|')[1:-1]) == 12 for line in table))
        self.assertEqual(table[-1], '| 34 | Unit34 | 1101034 |  |  |  |  |  |  |  |  |  |')
        self.assertEqual(blocks[1].raw['page_start'], 1)
        self.assertEqual(blocks[1].raw['page_end'], 1)

    def test_merged_table_keeps_spans_instead_of_flattening_cells(self):
        """可校验的合并单元格直接保存跨度，不能伪造成普通网格。"""
        replies = iter(['第一页正文', '末页正文'])
        parser = test_mineru.MinerUParserTests._create_parser(lambda _: self._response(next(replies)))
        self.addCleanup(parser.client.close)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / 'merged.pdf'
            self._create_table_document(path, merged_header=True)
            blocks = parser.parse(str(path))
        self.assertEqual([blocks[0].content, blocks[-1].content], ['第一页正文', '末页正文'])
        table = next(block.raw['structured_table'] for block in blocks if (block.raw or {}).get('structured_table'))
        self.assertTrue(any(cell['colspan'] == 2 for cell in table['parts'][0]['cells']))

    def test_truncated_batch_recovers_native_table_and_keeps_page_mapping(self):
        """多页批次截断后，成功单页与文字层表格均应保留且继续处理尾页。"""
        replies = iter([
            ('不完整批次', 'length'), ('第一页正文', 'stop'),
            ('不完整表格', 'length'), ('末页正文', 'stop'),
        ])
        parser = test_mineru.MinerUParserTests._create_parser(lambda _: self._response(*next(replies)))
        parser.config.pages_per_request = 2
        self.addCleanup(parser.client.close)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / 'table.pdf'
            self._create_table_document(path)
            blocks = parser.parse(str(path))
        self.assertEqual([block.page_num for block in blocks], [0, 1, 2])
        self.assertEqual(blocks[0].content, '第一页正文')
        self.assertIn('| 34 | Unit34 | 1101034 |', blocks[1].content)
        self.assertEqual(blocks[1].raw['recovery'], 'native_table')
        self.assertEqual(blocks[2].content, '末页正文')
        self.assertTrue(all('不完整' not in block.content for block in blocks))

    def test_truncated_image_is_split_and_following_page_is_processed(self):
        """扫描页没有可靠文字层时，应按上、下区域恢复，不采用截断正文。"""
        requests = []
        replies = iter([
            ('第一页正文', 'stop'), ('不完整正文', 'length'),
            ('上半页', 'stop'), ('下半页', 'stop'), ('末页正文', 'stop'),
        ])

        def handler(request):
            payload = json.loads(request.content)
            url = payload['messages'][0]['content'][0]['image_url']['url']
            pixmap = fitz.Pixmap(base64.b64decode(url.split(',', 1)[1]))
            requests.append((pixmap.width, pixmap.height))
            return self._response(*next(replies))

        parser = test_mineru.MinerUParserTests._create_parser(handler)
        self.addCleanup(parser.client.close)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / 'scan.pdf'
            test_mineru.MinerUParserTests._create_pdf(path, page_count=3)
            blocks = parser.parse(str(path))
        self.assertEqual([block.content for block in blocks], ['第一页正文', '上半页\n\n下半页', '末页正文'])
        self.assertEqual(blocks[1].raw['recovery'], 'split_regions')
        self.assertEqual(requests[2:4], [(595, 421), (595, 421)])

    def test_native_detection_failure_falls_back_to_model(self):
        """文字层表格检测异常不能使本来可识别的页面失败。"""
        parser = test_mineru.MinerUParserTests._create_parser(lambda _: self._response('正常正文'))
        self.addCleanup(parser.client.close)
        with (
            tempfile.TemporaryDirectory() as directory,
            redirect_stdout(io.StringIO()),
            patch('parsers.mineru._extract_text_table_page', side_effect=ValueError('无效网格')),
        ):
            path = Path(directory) / 'policy.pdf'
            test_mineru.MinerUParserTests._create_pdf(path, page_count=1)
            blocks = parser.parse(str(path))
        self.assertEqual(blocks[0].content, '正常正文')

    def test_process_command_passes_complete_table_to_text_pipeline(self):
        """保留真实命令行、调度器及解析器，验证正常处理时就已还原表格。"""
        from commands.entry import main
        from core.config import app_config

        received = []
        replies = iter(['第一页正文', '末页正文'])
        parser = test_mineru.MinerUParserTests._create_parser(lambda _: self._response(next(replies)))
        self.addCleanup(parser.client.close)

        def store_text(blocks, file_id, doc_type):
            received.extend(blocks)
            return len(blocks), []

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / 'policy.pdf'
            self._create_table_document(path)
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(app_config.parser, 'parser_backend', 'mineru'))
            stack.enter_context(patch.object(app_config, 'mineru', parser.config))
            stack.enter_context(patch.object(app_config.minio, 'enabled', False))
            stack.enter_context(patch('parsers.mineru.httpx.Client', return_value=parser.client))
            stack.enter_context(patch('processing.pipeline.ensure_file_record', return_value={
                'file_id': 'pdf_recovered', 'status': 'pending',
            }))
            stack.enter_context(patch('processing.pipeline.classify_document', return_value={
                'doc_type': 'other', 'confidence': 1,
            }))
            stack.enter_context(patch('processing.pipeline.extract_document_metadata', return_value={}))
            stack.enter_context(patch('processing.pipeline.process_text_blocks', side_effect=store_text))
            stack.enter_context(patch('processing.pipeline.process_image_blocks', return_value=(0, [])))
            stack.enter_context(patch('processing.pipeline.process_table_blocks', return_value=(0, 0, 0)))
            stack.enter_context(patch('processing.pipeline.record_block_storage'))
            stack.enter_context(patch('processing.pipeline.record_file_done'))
            stack.enter_context(patch('processing.pipeline.record_file_failed', side_effect=AssertionError('流程失败')))
            stack.enter_context(patch('policy.clause_export.export_file_clause_structure'))
            main(['--process', str(path), '--backend', 'mineru'])
        self.assertIn('done', output.getvalue())
        self.assertEqual([block.page_num for block in received], [0, 1, 2])
        self.assertEqual({block.file_id for block in received}, {'pdf_recovered'})
        self.assertIn('| 34 | Unit34 | 1101034 |', received[1].content)
        self.assertEqual(received[2].content, '末页正文')
