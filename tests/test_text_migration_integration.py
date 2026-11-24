"""仅在显式指定的隔离测试库验证真实 PostgreSQL/pgvector 迁移。"""
import os
import unittest
import uuid
from unittest.mock import patch

from core.config import app_config
from core.models import TextChunk
from storage.adapters import PgStorageAdapter
from storage.text_chunks import TextChunkStore
from storage.text_migration import migrate_text_chunks


@unittest.skipUnless(os.getenv("TEXT_MIGRATION_TEST_DATABASE"), "未配置独立文本迁移测试库")
class TextMigrationIntegrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        database = os.environ["TEXT_MIGRATION_TEST_DATABASE"]
        if not (database == "test" or database.startswith("test_") or database.endswith("_test")):
            self.skipTest("只允许名称明确的隔离测试库")
        cfg = app_config.postgres
        self.conn = psycopg2.connect(host=cfg.host, port=cfg.port, user=cfg.user,
                                     password=cfg.password, dbname=database, connect_timeout=5)
        self.conn.autocommit = True
        self.schema = "test_text_" + uuid.uuid4().hex
        self.db = PgStorageAdapter()
        self.db._conn = self.conn
        with self.conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{self.schema}"')
            cur.execute(f'SET search_path TO "{self.schema}", public')
            cur.execute("""CREATE TABLE pdf_f1_text (id SERIAL, embedding vector(2),
                metadata JSONB, created_at TIMESTAMP DEFAULT NOW())""")
            cur.execute("""INSERT INTO pdf_f1_text (embedding, metadata) VALUES
                ('[1,0]', '{"file_id":"f1","chunk_id":"c1","text":"正文","page_num":1}'),
                ('[1,0]', '{"file_id":"f1","chunk_id":"c1","text":"正文","page_num":1}'),
                ('[0,1]', '{"file_id":"f1","chunk_id":"c2","text":"第二段","page_num":2}')""")
        self.addCleanup(self.cleanup_database)

    def cleanup_database(self):
        self.conn.rollback()
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.conn.close()

    def migrate(self, **kwargs):
        return migrate_text_chunks(adapter=self.db, legacy_model=app_config.embedding.model_name, **kwargs)

    def test_dry_run_then_migrate_repeat_search_and_preserve_source(self):
        self.assertEqual(self.migrate(dry_run=True)["files"][0]["status"], "ready")
        with self.conn.cursor() as cur:
            cur.execute("SELECT to_regclass('pdf_text_chunks')")
            self.assertIsNone(cur.fetchone()[0])
        report = self.migrate()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["files"][0]["duplicates_removed"], 1)
        self.assertEqual(self.migrate()["files"][0]["status"], "skipped")
        rows = TextChunkStore(self.db).search([1., 0.], 10, "f1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["metadata"]["chunk_id"], "c1")
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pdf_f1_text")
            self.assertEqual(cur.fetchone()[0], 3)

    def test_failure_after_copy_rolls_back_all_file_changes(self):
        with patch.object(TextChunkStore, "mark", side_effect=ValueError("模拟登记失败")):
            report = self.migrate()
        self.assertEqual(len(report["errors"]), 1)
        with self.conn.cursor() as cur:
            cur.execute("SELECT to_regclass('pdf_text_chunks')")
            self.assertIsNone(cur.fetchone()[0])
        self.assertEqual(self.migrate()["errors"], [])

    def test_new_write_is_idempotent_and_migration_does_not_restore_old_data(self):
        store = TextChunkStore(self.db)
        chunks = [TextChunk(file_id="f1", chunk_id="new", text="新正文", embedding=[1., 0.])]
        store.replace(chunks)
        store.replace(chunks)
        self.assertEqual(self.migrate()["files"][0]["status"], "skipped")
        self.assertEqual(len(store.search([1., 0.], 10)), 1)
        self.assertEqual(store.search([1., 0.], 10)[0]["metadata"]["text"], "新正文")

    def test_conflicting_duplicate_is_rejected(self):
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE pdf_f1_text SET metadata=jsonb_set(metadata, '{text}', '"冲突正文"')
                WHERE id=2""")
        report = self.migrate()
        self.assertEqual(len(report["errors"]), 1)

    def test_model_mismatch_rejected_without_deleting_current_data(self):
        store = TextChunkStore(self.db)
        store.replace([TextChunk(file_id="f2", chunk_id="c1", text="其他文件", embedding=[1., 0.])])
        with patch.object(app_config.embedding, "model_name", "different-model"):
            with self.assertRaises(ValueError):
                store.replace([TextChunk(file_id="f2", chunk_id="c2", text="新正文", embedding=[1., 0.])])
        self.assertEqual(store.search([1., 0.], 10)[0]["metadata"]["text"], "其他文件")
