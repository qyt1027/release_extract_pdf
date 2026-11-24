"""只重建文本向量的迁移恢复，不重置制度和审核记录。"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.config import app_config
from core.models import BlockType, ContentBlock


class TextRebuildTests(unittest.TestCase):
    def source(self):
        directory=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        path=Path(directory.name)/'管理规定.docx'
        path.write_bytes(b'source-document')
        return path

    def database(self, path, file_hash=None):
        db=MagicMock()
        record={'file_id':'f1', 'file_name':path.name, 'status':'done',
                'file_hash':file_hash or hashlib.sha256(path.read_bytes()).hexdigest(),
                'embedding_model':app_config.embedding.model_name, 'page_count':0}
        def query(table, *args, **kwargs):
            if table=='pdf_files': return [record]
            if table=='pdf_batch_items': return [{'file_path':str(path)}]
            if table=='policy_documents': return [{'policy_id':'p1'}]
            return []
        db.relational.query.side_effect=query
        return db, record

    def test_rebuild_reuses_source_and_only_processes_text(self):
        from processing.text_rebuild import rebuild_file_text
        path=self.source()
        db, record=self.database(path)
        blocks=[ContentBlock(type=BlockType.TEXT, content='第一条 正文')]
        with patch('processing.text_rebuild.storage', db), \
             patch('processing.text_rebuild.PDFParser') as parser, \
             patch('processing.text_rebuild.process_text_blocks', return_value=(1, [object()])) as process:
            parser.return_value.parse.return_value=blocks
            report=rebuild_file_text('f1')
        self.assertEqual(report['text_chunks_stored'], 1)
        self.assertEqual(blocks[0].file_id, 'f1')
        process.assert_called_once_with(blocks, 'f1', 'policy_regulation', update_provenance=True, expected_file=record)
        db.relational.execute.assert_not_called()
        db.relational.update_rows.assert_not_called()
        db.relational.drop_table.assert_not_called()

    def test_wrong_source_hash_is_rejected_before_parsing_or_writing(self):
        from processing.text_rebuild import rebuild_file_text
        path=self.source()
        db, _=self.database(path, 'wrong-hash')
        with patch('processing.text_rebuild.storage', db), \
             patch('processing.text_rebuild.PDFParser') as parser, \
             patch('processing.text_rebuild.process_text_blocks') as process, self.assertRaises(ValueError):
            rebuild_file_text('f1', str(path))
        parser.assert_not_called()
        process.assert_not_called()

    def test_busy_file_is_rejected(self):
        from processing.text_rebuild import rebuild_file_text
        path=self.source()
        db, record=self.database(path)
        record['status']='processing'
        with patch('processing.text_rebuild.storage', db), self.assertRaises(ValueError):
            rebuild_file_text('f1')

    def test_source_changed_during_parse_is_rejected_before_embedding(self):
        from processing.text_rebuild import rebuild_file_text
        path=self.source()
        db, _=self.database(path)
        def parse(*_):
            path.write_bytes(b'changed')
            return [ContentBlock(type=BlockType.TEXT, content='第一条 正文')]
        with patch('processing.text_rebuild.storage', db), \
             patch('processing.text_rebuild.PDFParser') as parser, \
             patch('processing.text_rebuild.process_text_blocks') as process, self.assertRaises(ValueError):
            parser.return_value.parse.side_effect=parse
            rebuild_file_text('f1')
        process.assert_not_called()

    def test_different_model_is_rejected(self):
        from processing.text_rebuild import rebuild_file_text
        path=self.source()
        db, record=self.database(path)
        record['embedding_model']='different-model'
        with patch('processing.text_rebuild.storage', db), \
             patch('processing.text_rebuild.PDFParser') as parser, self.assertRaises(ValueError):
            rebuild_file_text('f1')
        parser.assert_not_called()

    def test_cli_dispatches_explicit_source(self):
        from commands.entry import main
        with patch('commands.entry.run_rebuild_file_text') as run:
            main(['--rebuild-file-text', 'f1', '--text-source', 'source.docx'])
        run.assert_called_once_with('f1', source_path='source.docx')

    def test_reset_during_embedding_is_rejected_before_shared_table_write(self):
        from storage.text_chunks import TextChunkStore
        from core.models import TextChunk
        db=MagicMock()
        cur=db.conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=('hash','pending',app_config.embedding.model_name,None)
        expected={'file_hash':'hash','status':'done','embedding_model':app_config.embedding.model_name,'updated_at':None}
        with patch.object(TextChunkStore,'ensure') as ensure, self.assertRaises(ValueError):
            TextChunkStore(db).replace([TextChunk(file_id='f1',chunk_id='c1',embedding=[1.,0.])], expected_file=expected)
        ensure.assert_not_called()
        for call in cur.execute.call_args_list:
            self.assertNotRegex(call.args[0], r'(?i)\b(INSERT|DELETE|UPDATE\s+pdf_text)\b')
