"""旧版 DOC 应在本地直接读取，不依赖 Word、格式转换或在线服务。"""
import hashlib
import io
import struct
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core.models import ProcessingResult, ProcessingStatus, ProcessingVersion
from parsers.dispatcher import PDFParser
from policy.pipeline import build_policy_clauses


def make_legacy_doc(text, *, encrypted=False):
    """构造含中文文字片段表的最小 OLE DOC；仅用于独立回归样本。"""
    free, end, fat_sector = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
    header = bytearray(512)
    header[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH', header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into('<I', header, 0x2C, 1)
    struct.pack_into('<I', header, 0x30, 0)
    struct.pack_into('<I', header, 0x38, 4096)
    struct.pack_into('<I', header, 0x3C, end)
    struct.pack_into('<I', header, 0x44, end)
    struct.pack_into('<109I', header, 0x4C, 1, *([free] * 108))
    directory = bytearray(512)
    for index, (name, kind, start, size) in enumerate([
        ('Root Entry', 5, end, 0), ('WordDocument', 2, 2, 4096), ('1Table', 2, 10, 4096),
    ]):
        offset = index * 128
        encoded = (name + '\0').encode('utf-16le')
        directory[offset:offset + len(encoded)] = encoded
        struct.pack_into('<HBBIII', directory, offset + 64, len(encoded), kind, 1, free, free, free)
        struct.pack_into('<IQ', directory, offset + 116, start, size)
    fat = [free] * 128
    fat[0], fat[1] = end, fat_sector
    for first in (2, 10):
        for sector in range(first, first + 7):
            fat[sector] = sector + 1
        fat[first + 7] = end
    raw_text = text.encode('utf-16le')
    word = bytearray(4096)
    struct.pack_into('<HH', word, 0, 0xA5EC, 0xC1)
    struct.pack_into('<H', word, 0xA, 0x200 | (0x100 if encrypted else 0))
    struct.pack_into('<II', word, 0x18, 1024, 1024 + len(raw_text))
    word[1024:1024 + len(raw_text)] = raw_text
    table = bytearray(4096)
    piece_table = struct.pack('<IIHIH', 0, len(raw_text) // 2, 0, 1024, 0)
    table[:5 + len(piece_table)] = b'\x02' + struct.pack('<I', len(piece_table)) + piece_table
    return bytes(header + directory + struct.pack('<128I', *fat) + word + table)


class LegacyDocParserTests(unittest.TestCase):
    text = '测试学院导师管理制度\r第一章 总则\r第一条 导师应当履行指导职责。\r第二条 考核结果纳入年度考核。\r'

    def test_binary_doc_is_read_locally_for_all_backend_settings(self):
        """正文顺序和条款编号保留，且不创建转换文件、不修改原始字节。"""
        for backend in ('mineru', 'pymupdf', 'cloudmineru'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                path = Path(directory) / '导师制度.doc'
                original = make_legacy_doc(self.text)
                path.write_bytes(original)
                with (
                    patch('httpx.Client.post', side_effect=AssertionError('DOC 不应请求在线服务')),
                    patch('subprocess.run', side_effect=AssertionError('DOC 不应调用外部转换程序')),
                    redirect_stdout(io.StringIO()),
                ):
                    try:
                        blocks = PDFParser(backend=backend).parse(str(path))
                    except Exception as error:
                        self.fail(f'本地直接读取旧版 DOC 失败：{error}')
                self.assertEqual([block.content for block in blocks], [
                    '测试学院导师管理制度', '第一章 总则',
                    '第一条 导师应当履行指导职责。', '第二条 考核结果纳入年度考核。',
                ])
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(set(Path(directory).iterdir()), {path})
                self.assertEqual(blocks[0].raw['parser'], 'legacy-doc')
                clauses = build_policy_clauses('policy_1', blocks)
                self.assertEqual([clause.level for clause in clauses], ['preamble', 'chapter', 'article', 'article'])

    def test_corrupt_or_encrypted_doc_fails_without_cloud_fallback(self):
        for data in (b'invalid doc', make_legacy_doc(self.text, encrypted=True)):
            with self.subTest(data=data[:8]), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                path = Path(directory) / '损坏或加密.doc'
                path.write_bytes(data)
                with (
                    patch('httpx.Client.post', side_effect=AssertionError('不能转发失败文件')),
                    self.assertRaisesRegex(ValueError, 'DOC'),
                ):
                    PDFParser(backend='mineru').parse(str(path))

    def test_batch_no_longer_rejects_binary_doc_before_processing(self):
        from core.config import app_config
        from processing.batch import _process_item

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '导师制度.doc'
            data = make_legacy_doc(self.text)
            path.write_bytes(data)
            item = {'item_id': 'item_doc', 'file_name': path.name, 'file_path': str(path),
                    'file_hash': hashlib.sha256(data).hexdigest(), 'status': 'pending'}
            received = []

            def process(file_path, page_count, **kwargs):
                received.extend(PDFParser(backend='mineru').parse(file_path))
                return ProcessingResult(file_id='doc_1', status=ProcessingStatus.DONE)

            with (
                patch.object(app_config.parser, 'parser_backend', 'mineru'),
                patch('processing.batch.ensure_file_record', return_value={'file_id': 'doc_1', 'status': 'pending'}),
                patch('processing.batch.update_batch_item', side_effect=lambda _, values: item.update(values)),
                patch('processing.batch.record_file_attempt'),
                patch('processing.batch.process_pdf', side_effect=process),
                redirect_stdout(io.StringIO()),
            ):
                _process_item(item, ProcessingVersion(parser_version='local-doc', embedding_model='test', llm_model='test'), 3)
            self.assertEqual(item['status'], 'succeeded')
            self.assertEqual(received[-1].content, '第二条 考核结果纳入年度考核。')

    def test_resume_can_retry_old_unsupported_doc_failures_only(self):
        from processing.batch import _eligible

        item = {'status': 'failed', 'error_kind': 'permanent', 'attempt_count': 0,
                'file_path': '导师制度.doc', 'last_error': '真正的 DOC 仅支持 cloudmineru 解析后端'}
        self.assertTrue(_eligible(item, resume=True))
        self.assertFalse(_eligible(item, resume=False))
        self.assertFalse(_eligible({**item, 'last_error': '文件已损坏'}, resume=True))
        self.assertFalse(_eligible({**item, 'status': 'succeeded'}, resume=True))

    def test_process_command_reads_doc_and_passes_it_to_policy_pipeline(self):
        """保留真实命令行、读取和分类，只隔离数据库、模型及存储边界。"""
        from commands.entry import main
        from core.config import app_config

        received = []

        def store_text(blocks, file_id, doc_type):
            self.assertEqual(doc_type, 'policy_regulation')
            received.extend(blocks)
            return len(blocks), []

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / '（行政）导师管理资料.doc'
            path.write_bytes(make_legacy_doc(self.text))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(app_config.parser, 'parser_backend', 'mineru'))
            stack.enter_context(patch.object(app_config.minio, 'enabled', False))
            stack.enter_context(patch('httpx.Client.post', side_effect=AssertionError('不能请求在线解析')))
            stack.enter_context(patch('processing.pipeline.ensure_file_record', return_value={
                'file_id': 'doc_local', 'status': 'pending',
            }))
            stack.enter_context(patch('processing.pipeline.extract_document_metadata', return_value={
                'title': '测试学院导师管理制度',
            }))
            stack.enter_context(patch('processing.pipeline.update_file_name'))
            stack.enter_context(patch('policy.duplicates.confirm_policy_import', return_value=('continue', [])))
            stack.enter_context(patch('policy.document_parts.confirm_folder_applicable_units'))
            stack.enter_context(patch('policy.pipeline.structure_policy_file', return_value={
                'clause_count': 2, 'parse_quality': 1.0, 'documents': [],
            }))
            stack.enter_context(patch('processing.pipeline.process_text_blocks', side_effect=store_text))
            stack.enter_context(patch('processing.pipeline.process_image_blocks', return_value=(0, [])))
            stack.enter_context(patch('processing.pipeline.process_table_blocks', return_value=(0, 0, 0)))
            stack.enter_context(patch('processing.pipeline.record_block_storage'))
            stack.enter_context(patch('processing.pipeline.record_file_done'))
            stack.enter_context(patch('processing.pipeline.record_file_failed', side_effect=AssertionError('处理失败')))
            stack.enter_context(patch('policy.clause_export.export_file_clause_structure'))
            main(['--process', str(path), '--backend', 'mineru'])
        self.assertIn('done', output.getvalue())
        self.assertEqual([block.content for block in received], [
            '测试学院导师管理制度', '第一章 总则',
            '第一条 导师应当履行指导职责。', '第二条 考核结果纳入年度考核。',
        ])
        self.assertEqual({block.file_id for block in received}, {'doc_local'})
