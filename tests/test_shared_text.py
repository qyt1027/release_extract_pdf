"""共享文本存储的验证、检索和迁移回归测试。"""
import unittest
from unittest.mock import MagicMock, patch

from core.models import TextChunk


class SharedTextTests(unittest.TestCase):
    def test_source_inspection_keeps_closing_table_identifier_quote(self):
        from core.config import app_config
        from storage.text_migration import inspect_source
        cur=MagicMock()
        cur.fetchone.side_effect=[(None,), (3,2,2,0), None]
        table='pdf_pdf_00466f29396ee6ff_text'
        self.assertEqual(inspect_source(cur, table, 'pdf_00466f29396ee6ff', app_config.embedding.model_name), (3,2))
        inspection_sql=cur.execute.call_args_list[1].args[0]
        self.assertIn('FROM "' + table + '"', inspection_sql)

    def test_store_chunks_uses_shared_repository(self):
        from processing.text import store_chunks
        chunks = [TextChunk(file_id="f1", chunk_id="c1", text="正文", embedding=[1., 0.])]
        with patch("storage.text_chunks.TextChunkStore.replace", return_value=1) as replace:
            self.assertEqual(store_chunks(chunks), 1)
        replace.assert_called_once_with(chunks)

    def test_incomplete_embeddings_are_rejected_before_database_access(self):
        from storage.text_chunks import validate_chunks
        chunks = [TextChunk(file_id="f1", chunk_id="c1", text="正文", embedding=[1., 0.]),
                  TextChunk(file_id="f1", chunk_id="c2", text="缺向量")]
        with self.assertRaises(ValueError):
            validate_chunks(chunks)

    def test_mixed_files_and_duplicate_ids_are_rejected(self):
        from storage.text_chunks import validate_chunks
        for file_id, chunk_id in [("f2", "c2"), ("f1", "c1")]:
            with self.subTest(file_id=file_id, chunk_id=chunk_id), self.assertRaises(ValueError):
                validate_chunks([TextChunk(file_id="f1", chunk_id="c1", text="甲", embedding=[1., 0.]),
                                 TextChunk(file_id=file_id, chunk_id=chunk_id, text="乙", embedding=[1., 0.])])

    def test_single_file_search_materializes_filter_before_distance_sort(self):
        from storage.text_chunks import TextChunkStore
        adapter = MagicMock()
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [("pdf_text_chunks",), ("BAAI/bge-m3", 2)]
        cur.fetchall.return_value = []
        TextChunkStore(adapter).search([1., 0.], 10, "f1")
        sql, params = cur.execute.call_args.args
        self.assertIn("MATERIALIZED", sql)
        self.assertIn("WHERE file_id = %s", sql)
        self.assertIn("f1", params)

    def test_migration_cli_dispatch(self):
        from commands.entry import main
        with patch("commands.entry.run_migrate_text_chunks") as run:
            main(["--migrate-text-chunks", "--text-migration-dry-run", "--legacy-embedding-model", "BAAI/bge-m3"])
        run.assert_called_once_with(dry_run=True, legacy_model="BAAI/bge-m3")

    def test_source_unknown_or_wrong_model_is_rejected(self):
        from storage.text_migration import inspect_source
        for model in [None, "different-model"]:
            cur = MagicMock()
            cur.fetchone.return_value = (None,)
            with self.subTest(model=model), self.assertRaises(ValueError):
                inspect_source(cur, "pdf_f1_text", "f1", model)

    def test_dry_run_does_not_create_or_copy_tables(self):
        from storage.text_migration import migrate_text_chunks
        adapter = MagicMock()
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("pdf_f1_text",)]
        cur.fetchone.side_effect = [(None,), (None,), (None,)]
        with patch("storage.text_migration.inspect_source", return_value=(3, 2)):
            report = migrate_text_chunks(adapter=adapter, dry_run=True)
        self.assertEqual(report["files"][0]["status"], "ready")
        for call in cur.execute.call_args_list:
            self.assertNotRegex(call.args[0], r"(?i)\b(CREATE|INSERT|UPDATE|DELETE)\b")

    def test_migration_failure_is_reported_and_next_file_is_processed(self):
        from storage.text_migration import migrate_text_chunks
        adapter = MagicMock()
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("pdf_f1_text",), ("pdf_f2_text",)]
        cur.fetchone.return_value = (None,)
        with patch("storage.text_migration.inspect_source", side_effect=[ValueError("数据损坏"), (3, 2)]):
            report = migrate_text_chunks(adapter=adapter, dry_run=True)
        self.assertEqual(report["errors"][0]["file_id"], "f1")
        self.assertEqual(report["files"][0]["file_id"], "f2")

    def test_migrated_or_native_file_is_not_overwritten(self):
        from storage.text_migration import migrate_text_chunks
        adapter = MagicMock()
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("pdf_f1_text",)]
        cur.fetchone.side_effect = [("pdf_text_imports",), ("native",)]
        with patch("storage.text_migration.inspect_source") as inspect:
            report = migrate_text_chunks(adapter=adapter)
        inspect.assert_not_called()
        self.assertEqual(report["files"][0]["status"], "skipped")

    def test_commit_failure_is_not_reported_as_success(self):
        from storage.text_migration import migrate_text_chunks
        adapter = MagicMock()
        adapter.transaction.return_value.__exit__.side_effect = ValueError("提交失败")
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("pdf_f1_text",)]
        cur.fetchone.side_effect = [(None,), (0,), (0,), (None,)]
        cur.rowcount = 3
        with patch("storage.text_migration.inspect_source", return_value=(3, 2)), \
             patch("storage.text_chunks.TextChunkStore.ensure"):
            report = migrate_text_chunks(adapter=adapter)
        self.assertEqual(report["files"], [])
        self.assertEqual(len(report["errors"]), 1)

    def test_invalid_dimension_does_not_block_next_valid_file(self):
        from storage.text_migration import migrate_text_chunks
        adapter = MagicMock()
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("pdf_f1_text",), ("pdf_f2_text",)]
        cur.fetchone.side_effect = [(None,), ("settings",), (None,), ("settings",), (None,)]
        with patch("storage.text_migration.inspect_source", side_effect=[(3, 3), (3, 2)]), \
             patch("storage.text_chunks.TextChunkStore._check_model", side_effect=[ValueError("维度错误"), None]):
            report = migrate_text_chunks(adapter=adapter, dry_run=True)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["files"], [{"file_id": "f2", "status": "ready", "rows": 3}])

    def test_dry_run_reports_untracked_target_conflict(self):
        from storage.text_migration import migrate_text_chunks
        adapter = MagicMock()
        cur = adapter.conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("pdf_f1_text",)]
        cur.fetchone.side_effect = [(None,), (None,), ("target",), (2,)]
        with patch("storage.text_migration.inspect_source", return_value=(3, 2)):
            report = migrate_text_chunks(adapter=adapter, dry_run=True)
        self.assertEqual(report["files"], [])
        self.assertEqual(len(report["errors"]), 1)

    def test_search_api_supports_file_filter_and_global_search(self):
        import asyncio
        import httpx
        from web.api import app
        for file_id in [None, "f1"]:
            async def request():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    params = {"q": "正文", "top_k": 5}
                    if file_id:
                        params["file_id"] = file_id
                    return await client.get("/search", params=params)
            model = MagicMock()
            model.encode.return_value.__getitem__.return_value.tolist.return_value = [1., 0.]
            with patch("processing.text._get_embedding_model", return_value=model), \
                 patch("storage.text_chunks.TextChunkStore.search", return_value=[]) as search:
                response = asyncio.run(request())
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with([1., 0.], 5, file_id)


if __name__ == "__main__":
    unittest.main()
