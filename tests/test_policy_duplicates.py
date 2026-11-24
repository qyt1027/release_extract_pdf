"""同标题、同文号制度的导入确认回归。"""
import io
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch, mock_open

from core.models import BlockType, ContentBlock


class PolicyDuplicateTests(unittest.TestCase):
    def test_lookup_normalizes_number_and_excludes_same_file(self):
        from policy.duplicates import find_duplicate_policies
        from unittest.mock import MagicMock
        db = MagicMock()
        db.relational.query.return_value = [
            {"policy_id":"same", "doc_number":"武大财字（2023）010号"},
            {"policy_id":"other", "doc_number":"武大财字〔2022〕10号"},
        ]
        with patch("policy.storage.ensure_policy_tables"), patch("storage.adapters.storage", db):
            rows = find_duplicate_policies("new", "武汉大学管理办法", "武大财字[2023]10号")
        self.assertEqual([row['policy_id'] for row in rows], ['same'])
        self.assertIn('file_id <> %s', db.relational.query.call_args.args[1])
        self.assertEqual(db.relational.query.call_args.args[3], ("武汉大学管理办法", "new"))

    def test_prompt_defaults_to_skip_and_eof_defers(self):
        from policy.duplicates import prompt_duplicate_import
        report = {"file_name": "新.docx", "title": "办法", "doc_number": "文号",
                  "candidates": [{"file_name": "旧.pdf", "title": "办法", "doc_number": "文号"}]}
        with redirect_stdout(io.StringIO()), patch("builtins.input", return_value=""):
            self.assertEqual(prompt_duplicate_import(report), "skip")
        with redirect_stdout(io.StringIO()), patch("builtins.input", side_effect=EOFError):
            self.assertEqual(prompt_duplicate_import(report), "pending")

    def test_missing_title_or_number_does_not_prompt(self):
        from policy.duplicates import confirm_policy_import
        with patch("policy.duplicates.find_duplicate_policies", return_value=[]) as find, patch("builtins.input") as ask:
            self.assertEqual(confirm_policy_import("f", "新.docx", {}), ("continue", []))
        find.assert_not_called()
        ask.assert_not_called()

    def test_matching_file_without_callback_is_pending(self):
        from policy.duplicates import confirm_policy_import
        metadata={"title": "武汉大学会议费管理办法", "doc_number": "武大财字[2023]10号"}
        with patch("policy.duplicates.find_duplicate_policies", return_value=[{"policy_id": "old", "file_name": "旧.pdf"}]):
            action, candidates = confirm_policy_import("f", "新.docx", metadata)
        self.assertEqual(action, "pending")
        self.assertEqual(len(candidates), 1)

    def test_matching_file_uses_explicit_choice_even_when_format_differs(self):
        from policy.duplicates import confirm_policy_import
        metadata={"title":"武汉大学会议费管理办法", "doc_number":"武大财字〔2023〕10号"}
        existing={"policy_id":"old", "file_name":"原文件.pdf", "title":metadata['title'], "doc_number":metadata['doc_number']}
        for choice in ['continue', 'skip', 'invalid']:
            with self.subTest(choice=choice), patch("policy.duplicates.find_duplicate_policies", return_value=[existing]):
                action, candidates=confirm_policy_import("new", "新文件.docx", metadata, lambda _: choice)
            self.assertEqual(action, choice if choice != 'invalid' else 'pending')
            self.assertEqual(candidates[0]['file_name'], '原文件.pdf')

    def test_pending_duplicate_stops_before_policy_and_vector_writes(self):
        from processing.pipeline import process_pdf
        from core.config import app_config
        blocks=[ContentBlock(type=BlockType.TEXT, content="第一条 正文")]
        with patch("builtins.open", mock_open(read_data=b"source")), \
             patch.object(app_config.minio, "enabled", False), \
             patch("processing.pipeline.ensure_file_record", return_value={"file_id": "new", "status": "pending"}), \
             patch("processing.pipeline.PDFParser") as parser, \
             patch("processing.pipeline.classify_document", return_value={"doc_type":"policy_regulation", "confidence":1}), \
             patch("processing.pipeline.extract_document_metadata", return_value={"title":"武汉大学管理办法", "doc_number":"文号"}), \
             patch("policy.duplicates.confirm_policy_import", return_value=("pending", [{"file_name":"旧.pdf"}])), \
             patch("storage.file_records.record_file_duplicate_status") as status, \
             patch("policy.pipeline.structure_policy_file") as structure, \
             patch("processing.pipeline.process_text_blocks") as text, redirect_stdout(io.StringIO()):
            parser.return_value.parse.return_value=blocks
            result=process_pdf("新.docx")
        self.assertEqual(result.status.value, "pending_confirmation")
        status.assert_called_once()
        structure.assert_not_called()
        text.assert_not_called()

    def test_pending_batch_requires_explicit_resume(self):
        from processing.batch import _eligible, _summarize_batch_items
        item={"status":"pending_confirmation"}
        self.assertFalse(_eligible(item, False))
        self.assertTrue(_eligible(item, True))
        self.assertEqual(_summarize_batch_items([item])["status"], "pending_confirmation")

    def run_two_attachments(self, duplicate_titles, choices):
        from core.config import app_config
        from policy.duplicates import prompt_duplicate_import
        from processing.pipeline import process_pdf

        first = "武汉大学自然科学科研项目管理办法"
        second = "武汉大学自然科学科研项目外协管理办法"
        notice = f"关于印发《{first}》《{second}》的通知"
        number = "武大科理字〔2021〕43号"
        # 两个附件共用同一页、同一个文本块，不能按页过滤。
        blocks = [
            ContentBlock(type=BlockType.TEXT, content=notice),
            ContentBlock(type=BlockType.TEXT, page_num=1, block_id="body",
                         content=f"{first}\n第一条 科研项目正文。\n{second}\n第一条 外协项目正文。"),
        ]
        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(patch("builtins.open", mock_open(read_data=b"source")))
            stack.enter_context(patch("builtins.input", side_effect=choices))
            stack.enter_context(patch.object(app_config.minio, "enabled", False))
            parser = stack.enter_context(patch("processing.pipeline.PDFParser"))
            parser.return_value.parse.return_value = blocks
            stack.enter_context(patch("processing.pipeline.ensure_file_record", return_value={"file_id": "new", "status": "pending"}))
            stack.enter_context(patch("processing.pipeline.record_file_done"))
            stack.enter_context(patch("storage.file_records.record_file_duplicate_status"))
            stack.enter_context(patch("processing.pipeline.classify_document",
                                      return_value={"doc_type": "policy_regulation", "confidence": 1}))
            stack.enter_context(patch("processing.pipeline.extract_document_metadata",
                                      return_value={"notice_title": notice, "doc_number": number}))
            stack.enter_context(patch("policy.duplicates.find_duplicate_policies", side_effect=lambda _, title, __:
                                      [{"policy_id": title, "file_name": f"{title}.doc",
                                        "title": title, "doc_number": number}] if title in duplicate_titles else []))
            stack.enter_context(patch("policy.storage.get_policy_documents_for_file", return_value=[]))
            structure = stack.enter_context(patch("policy.pipeline.structure_policy_document", return_value={
                "policy_id": "new_policy", "clause_count": 1, "parse_quality": 1.0,
            }))
            text = stack.enter_context(patch("processing.pipeline.process_text_blocks", return_value=(0, [])))
            stack.enter_context(patch("processing.pipeline.process_image_blocks", return_value=(0, [])))
            stack.enter_context(patch("processing.pipeline.process_table_blocks", return_value=(0, 0, 0)))
            stack.enter_context(patch("processing.pipeline.record_block_storage"))
            result = process_pdf("科研项目通知.pdf", duplicate_confirmation=prompt_duplicate_import)
        return result, [call.args[3] for call in structure.call_args_list], text, output.getvalue()

    def test_skip_one_duplicate_imports_the_other_attachment(self):
        duplicate = "武汉大学自然科学科研项目外协管理办法"
        result, written, text, output = self.run_two_attachments({duplicate}, ["n"])
        self.assertEqual(result.status.value, "done")
        self.assertEqual([meta["title"] for meta in written], ["武汉大学自然科学科研项目管理办法"])
        indexed_text = "\n".join(block.content for block in text.call_args.args[0])
        self.assertIn("科研项目正文。", indexed_text)
        self.assertNotIn("外协项目正文。", indexed_text)
        self.assertEqual(output.count("检测到标题、文号相同的已入库制度"), 1)

    def test_two_duplicates_get_separate_choices_and_keep_original_document_key(self):
        first = "武汉大学自然科学科研项目管理办法"
        second = "武汉大学自然科学科研项目外协管理办法"
        result, written, text, output = self.run_two_attachments({first, second}, ["n", "y"])
        self.assertEqual(result.status.value, "done")
        self.assertEqual([meta["title"] for meta in written], [second])
        self.assertEqual(written[0]["document_key"], "f6ac31f417c440424e294fab")
        self.assertEqual(output.count("检测到标题、文号相同的已入库制度"), 2)
        indexed_text = "\n".join(block.content for block in text.call_args.args[0])
        self.assertIn("外协项目正文。", indexed_text)
        self.assertNotIn("科研项目正文。", indexed_text)

    def test_deferring_a_duplicate_leaves_the_file_pending_for_resume(self):
        result, written, text, _ = self.run_two_attachments({"武汉大学自然科学科研项目外协管理办法"}, ["q"])
        self.assertEqual(result.status.value, "pending_confirmation")
        self.assertEqual(written, [])
        text.assert_not_called()
