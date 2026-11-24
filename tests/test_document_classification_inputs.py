"""文档分类数据来源与 Word 批处理回归测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import BlockType, ContentBlock


class DocumentClassificationInputTests(unittest.TestCase):
    def test_local_doc_uses_verified_body_title_despite_collector_filename(self):
        from classification.document import classify_document

        title = '电子信息学院院务公开实施办法'
        result = classify_document(
            'example.doc', '（行政）电子信息学院院务公开的实施办法.doc',
            parsed_text=title + '\n一、院务公开列入学院年度工作的重要事项。',
            source_metadata={'title': title},
        )
        self.assertEqual(result['doc_type'], 'policy_regulation')

    def test_source_title_without_matching_opening_cannot_make_a_policy(self):
        from classification.document import classify_document

        for text in ('', '制度解读材料\n电子信息学院院务公开实施办法\n相关要求说明。'):
            with self.subTest(text=text):
                result = classify_document(
                    'example.doc', '研讨资料.doc', parsed_text=text,
                    source_metadata={'title': '电子信息学院院务公开实施办法'},
                )
                self.assertEqual(result['doc_type'], 'other')

    def test_mhtml_source_doc_number_alone_does_not_make_a_policy(self) -> None:
        from classification.document import classify_document

        result = classify_document(
            "example.doc", "武汉大学工作安排.doc",
            parsed_text="一、总体要求\n二、具体措施",
            source_metadata={"doc_number": "武大研字[2023]7号"},
        )
        self.assertEqual(result["doc_type"], "other")
        self.assertIn("检测到公文发文字号", result["signals"])

    def test_numbered_implementation_opinion_with_scope_and_requirements_is_policy(self) -> None:
        from classification.document import classify_document

        result = classify_document(
            "example.doc", "武汉大学关于博士研究生学制改革的实施意见.doc",
            parsed_text="本意见适用于学校各培养单位。各单位应当按照规定学制组织培养。",
            source_metadata={"doc_number": "武大研字[2023]7号"},
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_cloudmineru_text_is_used_for_policy_classification(self) -> None:
        from classification.document import classify_document

        parsed_text = (
            "武汉大学文件\n关于印发《武汉大学教师管理办法》的通知\n"
            "第一条 本办法适用于本校教师。\n第二条 教师应当遵守有关规定。\n"
            "第三条 本办法自2024年1月1日起施行。"
        )
        result = classify_document(
            "scan-without-text-layer.pdf",
            "教师管理文件.pdf",
            parsed_text=parsed_text,
        )

        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_notice_printing_policy_filename_is_strong_policy_signal(self) -> None:
        from classification.document import classify_document

        result = classify_document(
            "missing.pdf",
            "武大人字〔2024〕28号关于印发《武汉大学教师校内兼职聘任管理暂行办法》的通知.pdf",
            parsed_text="",
        )

        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_pipeline_builds_classification_text_from_text_blocks(self) -> None:
        from processing.pipeline import build_document_classification_text

        blocks = [
            ContentBlock(type=BlockType.TEXT, page_num=1, content="第二条 应当提交材料。"),
            ContentBlock(type=BlockType.TABLE, page_num=0, content="<table></table>"),
            ContentBlock(type=BlockType.TEXT, page_num=0, content="第一条 总则。"),
        ]

        self.assertEqual(
            build_document_classification_text(blocks),
            "第一条 总则。\n第二条 应当提交材料。",
        )


class WordBatchDiscoveryTests(unittest.TestCase):
    def test_batch_discovers_pdf_doc_and_docx_only(self) -> None:
        from processing.batch import _list_supported_files

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a.pdf", "b.doc", "c.docx", "ignore.json"):
                (root / name).write_bytes(b"test")

            found = _list_supported_files(root)

        self.assertEqual([path.name for path in found], ["a.pdf", "b.doc", "c.docx"])


if __name__ == "__main__":
    unittest.main()
