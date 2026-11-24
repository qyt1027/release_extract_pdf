"""文件内容相同且已完成时，只有用户明确确认后才能覆盖。"""

import hashlib
import io
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import mock_open, patch


class FileDuplicateImportTests(unittest.TestCase):
    def _process_with_records(self, records, data=b"same-pdf-content", overwrite=None):
        """只替换数据库和外部服务边界，保留真实哈希查找及文件登记逻辑。"""
        from core.config import app_config
        from processing.pipeline import process_pdf
        from storage.adapters import storage

        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch("builtins.open", mock_open(read_data=data)))
            stack.enter_context(patch("storage.file_records._ensure_meta_tables"))
            stack.enter_context(patch.object(app_config.minio, "enabled", True))
            query = stack.enter_context(patch.object(storage.relational, "query", side_effect=records))
            execute = stack.enter_context(patch.object(storage.relational, "execute"))
            update = stack.enter_context(patch.object(storage.relational, "update_rows"))
            upload = stack.enter_context(patch.object(storage.object, "upload"))
            parser = stack.enter_context(patch("processing.pipeline.PDFParser"))
            parser.return_value.parse.side_effect = RuntimeError("模拟解析失败")
            failed = stack.enter_context(patch("processing.pipeline.record_file_failed"))
            done = stack.enter_context(patch("processing.pipeline.record_file_done"))
            text = stack.enter_context(patch("processing.pipeline.process_text_blocks"))
            kwargs = {} if overwrite is None else {"file_overwrite_confirmation": lambda _: overwrite}
            result = process_pdf("改名后的同一文件.pdf", page_count=10, **kwargs)
        return result, output.getvalue(), {
            "query": query, "execute": execute, "update": update, "upload": upload,
            "parser": parser, "failed": failed, "done": done, "text": text,
        }

    def test_completed_file_without_confirmation_preserves_old_data(self):
        from core.config import app_config

        for status in ("done", "succeeded"):
            for backend in ("mineru", "cloudmineru"):
                with self.subTest(status=status, backend=backend), patch.object(
                    app_config.parser, "parser_backend", backend
                ):
                    existing = {
                        "file_id": "old-file", "file_name": "原文件.pdf", "status": status,
                        "file_hash": hashlib.sha256(b"same-pdf-content").hexdigest(),
                    }
                    before = dict(existing)
                    result, output, calls = self._process_with_records([[existing]])
                    self.assertEqual(result.status.value, "pending_confirmation")
                    self.assertEqual(result.file_id, "old-file")
                    self.assertIn("确认", result.message)
                    self.assertIn("原文件.pdf", output)
                    self.assertEqual(existing, before)
                    self.assertEqual(calls["query"].call_args.kwargs["params"], (existing["file_hash"],))
                    for name in ("execute", "update", "upload", "parser", "failed", "done", "text"):
                        calls[name].assert_not_called()

    def test_declining_overwrite_skips_without_changing_the_completed_record(self):
        existing = {"file_id": "old-file", "file_name": "原文件.pdf", "status": "done"}
        result, _, calls = self._process_with_records([[existing]], overwrite=False)
        self.assertEqual(result.status.value, "skipped")
        self.assertEqual(result.file_id, "old-file")
        self.assertEqual(existing["status"], "done")
        for name in ("execute", "update", "upload", "parser", "failed", "done", "text"):
            calls[name].assert_not_called()

    def test_confirmed_overwrite_reuses_the_file_id_and_enters_the_parser(self):
        existing = {"file_id": "old-file", "file_name": "原文件.pdf", "status": "done"}
        result, _, calls = self._process_with_records([[existing]], overwrite=True)
        self.assertEqual(result.file_id, "old-file")
        self.assertEqual(result.status.value, "failed")
        calls["execute"].assert_not_called()
        calls["parser"].return_value.parse.assert_called_once()
        calls["failed"].assert_called_once_with("old-file", "模拟解析失败")

    def test_overwrite_prompt_requires_yes_and_handles_unavailable_input(self):
        from commands.handlers import prompt_file_overwrite

        record = {"file_id": "old-file", "file_name": "原文件.pdf"}
        for answer, expected in (("y", True), (" Y ", True), ("n", False), ("", False)):
            with self.subTest(answer=answer), redirect_stdout(io.StringIO()), patch("builtins.input", return_value=answer):
                self.assertIs(prompt_file_overwrite(record), expected)
        for error in (EOFError, OSError):
            with self.subTest(error=error), redirect_stdout(io.StringIO()), patch("builtins.input", side_effect=error):
                self.assertIsNone(prompt_file_overwrite(record))

    def test_single_file_command_wires_the_overwrite_prompt(self):
        from commands.handlers import run_process
        from core.models import ProcessingResult, ProcessingStatus

        record = {"file_id": "old-file", "file_name": "原文件.pdf"}

        def process(*args, **kwargs):
            confirm = kwargs.get("file_overwrite_confirmation")
            self.assertTrue(callable(confirm))
            self.assertIs(confirm(record), False)
            return ProcessingResult(file_id="old-file", status=ProcessingStatus.SKIPPED)

        with (
            patch("processing.pipeline.process_pdf", side_effect=process),
            patch("builtins.input", return_value="n"),
            patch("policy.abolition.prompt_abolition_relation_insertion"),
            redirect_stdout(io.StringIO()),
        ):
            run_process("原文件.docx")

    def test_unfinished_file_still_enters_the_parser_for_retry(self):
        for status in ("failed", "pending", "processing", "pending_confirmation"):
            with self.subTest(status=status):
                existing = {"file_id": "old-file", "status": status}
                result, _, calls = self._process_with_records([[existing]])
                self.assertEqual(result.status.value, "failed")
                self.assertEqual(result.file_id, "old-file")
                calls["parser"].return_value.parse.assert_called_once()
                calls["failed"].assert_called_once_with("old-file", "模拟解析失败")

    def test_new_content_still_creates_a_record_and_enters_the_parser(self):
        new_record = {"file_id": "new-file", "status": "pending"}
        result, _, calls = self._process_with_records([[], [new_record]], data=b"changed-pdf-content")
        self.assertEqual(result.file_id, "new-file")
        self.assertEqual(result.status.value, "failed")
        calls["execute"].assert_called_once()
        calls["parser"].return_value.parse.assert_called_once()
        self.assertEqual(calls["query"].call_args.kwargs["params"],
                         (hashlib.sha256(b"changed-pdf-content").hexdigest(),))


if __name__ == "__main__":
    unittest.main()
