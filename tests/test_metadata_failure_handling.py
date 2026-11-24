"""别名配置空项及元数据失败的可见性与处理状态。"""
import io
import json
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch, mock_open

from core.models import BlockType, ContentBlock


class MetadataFailureTests(unittest.TestCase):
    def test_empty_alias_entries_are_ignored_without_removing_valid_aliases(self):
        from core.unit_aliases import unit_aliases
        unit_aliases.cache_clear()
        self.addCleanup(unit_aliases.cache_clear)
        data={'哲学学院':[''], '文学院':['  '], '新闻与传播学院':['', '新传院']}
        with patch('pathlib.Path.read_text', return_value=json.dumps(data)):
            result=unit_aliases()
        self.assertEqual(result['哲学学院'], '哲学学院')
        self.assertEqual(result['新传院'], '新闻与传播学院')
        self.assertNotIn('', result)

    def test_conflicting_alias_is_still_rejected(self):
        from core.unit_aliases import unit_aliases
        unit_aliases.cache_clear()
        self.addCleanup(unit_aliases.cache_clear)
        data={'计算机学院':['冲突'], '文学院':['冲突']}
        with patch('pathlib.Path.read_text', return_value=json.dumps(data)), self.assertRaises(ValueError):
            unit_aliases()

    def run_failed_stage(self, stage):
        from core.config import app_config
        from processing.pipeline import process_pdf
        output=io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch('builtins.open', mock_open(read_data=b'file')))
            stack.enter_context(patch.object(app_config.minio, 'enabled', False))
            stack.enter_context(patch('processing.pipeline.ensure_file_record', return_value={'file_id':'f1','status':'pending'}))
            failed=stack.enter_context(patch('processing.pipeline.record_file_failed'))
            done=stack.enter_context(patch('processing.pipeline.record_file_done'))
            parser=stack.enter_context(patch('processing.pipeline.PDFParser'))
            parser.return_value.parse.return_value=[ContentBlock(type=BlockType.TEXT, content='第一条 正文')]
            stack.enter_context(patch('processing.pipeline.classify_document', return_value={'doc_type':'policy_regulation','confidence':1}))
            metadata=stack.enter_context(patch('processing.pipeline.extract_document_metadata', return_value={'title':'管理办法'}))
            stack.enter_context(patch('policy.duplicates.confirm_policy_import', return_value=('continue', [])))
            structure=stack.enter_context(patch('policy.pipeline.structure_policy_file'))
            text=stack.enter_context(patch('processing.pipeline.process_text_blocks', return_value=(0, [])))
            stack.enter_context(patch('processing.pipeline.process_image_blocks', return_value=0))
            stack.enter_context(patch('processing.pipeline.process_table_blocks', return_value=(0,0,0)))
            stack.enter_context(patch('processing.pipeline.record_block_storage'))
            if stage == 'metadata':
                metadata.side_effect=ValueError('配置测试错误')
            else:
                structure.side_effect=ValueError('结构测试错误')
            with redirect_stdout(output):
                result=process_pdf('example.docx')
            self.assertEqual(result.status.value, 'failed')
            self.assertIn('失败', output.getvalue())
            self.assertIn('测试错误', output.getvalue())
            text.assert_not_called()
            done.assert_not_called()
            failed.assert_called_once()
            if stage == 'metadata':
                structure.assert_not_called()

    def test_metadata_failure_is_printed_and_stops_file(self):
        self.run_failed_stage('metadata')

    def test_structure_failure_is_printed_and_stops_file(self):
        self.run_failed_stage('structure')
