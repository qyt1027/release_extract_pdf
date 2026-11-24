"""验证同名制度版本匹配不能造成新制度自我废止。"""
import unittest
from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from policy import storage
from policy.abolition import (
    build_abolition_relations,
    extract_abolition_candidates,
    prompt_abolition_relation_insertion,
    reconcile_unresolved_abolition_relations,
    resolve_abolition_target,
)


class AbolitionVersionTests(unittest.TestCase):
    def test_source_is_excluded_from_title_and_number_matches(self):
        for number in ("", "武大党字〔2021〕98号"):
            with patch("policy.abolition.find_policy_documents_by_doc_number", return_value=[{"policy_id":"new"}]), patch(
                "policy.abolition.find_policy_documents_by_normalized_title", return_value=[{"policy_id":"new"}]
            ):
                self.assertIsNone(resolve_abolition_target("细则", number, source_policy_id="new"))

    def test_quoted_publication_year_selects_old_version_without_effective_date(self):
        documents = [{"policy_id":"new", "doc_number":"武大党字〔2021〕98号"},
                     {"policy_id":"old", "doc_number":"武大党字〔2017〕10号"}]
        with patch("policy.abolition.find_policy_documents_by_normalized_title", return_value=documents):
            relation = build_abolition_relations({"policy_id":"new", "clause_id":"c",
                "raw_text":"2017年印发的《细则》废止。"})[0]
        self.assertEqual(relation.target_policy_id,"old")
        self.assertIsNone(relation.effective_date)

    def test_parenthetical_edition_year_selects_old_version_without_document_number(self):
        documents = [
            {"policy_id": "newer", "doc_number": "校发〔2022〕10号"},
            {"policy_id": "old", "issue_date": "2014-03-14"},
        ]
        for annotation in ("（2014年制定）", "(2014 年 3 月发布)", "（2014年修订）"):
            with (
                self.subTest(annotation=annotation),
                patch("policy.abolition.find_policy_documents_by_normalized_title", return_value=documents),
                patch("policy.abolition.find_policy_documents_by_doc_number", return_value=[]) as by_number,
            ):
                text = f"原《设备管理细则》{annotation}同时废止。"
                relation = build_abolition_relations({"policy_id": "source", "raw_text": text})[0]
                self.assertEqual(relation.target_doc_number, "")
                self.assertEqual(relation.target_policy_id, "old")
                self.assertIsNone(relation.effective_date)
                self.assertEqual(relation.evidence_text, text)
                by_number.assert_not_called()

    def test_parenthetical_comments_and_document_numbers_are_distinguished(self):
        text = ("原《甲办法》（内部印发），《依据办法》仍有效。"
                "《甲办法》（2014年实施）和《乙办法》（教育部令第41号）同时废止。")
        candidates = extract_abolition_candidates({"raw_text": text})
        self.assertEqual(
            [(candidate["target_title"], candidate["target_doc_number"]) for candidate in candidates],
            [("甲办法", ""), ("乙办法", "教育部令第41号")],
        )

    def test_historical_year_in_number_column_can_match_a_later_import_by_year(self):
        stored = {
            "relation_id": "relation_a", "source_policy_id": "new", "review_status": "pending",
            "target_title": "设备管理细则", "target_doc_number": "2014年制定",
            "evidence_text": "《设备管理细则》（2014年制定）同时废止。",
        }
        with (
            patch("policy.abolition.list_policy_document_relations", return_value=[stored]),
            patch("policy.abolition.find_policy_documents_by_normalized_title", return_value=[
                {"policy_id": "old", "doc_number": "校发〔2014〕1号"},
                {"policy_id": "middle", "doc_number": "校发〔2018〕1号"},
            ]),
            patch("policy.abolition.find_policy_documents_by_doc_number", return_value=[]) as by_number,
        ):
            result = reconcile_unresolved_abolition_relations("old", lambda _: "skip")
        self.assertEqual(result, {"matched": 1, "approved": 0, "skipped": 1})
        by_number.assert_not_called()

    def test_terminal_displays_edition_year_in_its_own_field(self):
        relation = {
            "target_title": "设备管理细则", "target_doc_number": "2014年制定",
            "evidence_text": "《设备管理细则》（2014年制定）同时废止。",
        }
        with (
            patch("policy.abolition.get_policy_document", return_value={}),
            patch("builtins.input", return_value="n"),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            prompt_abolition_relation_insertion()(relation)
        self.assertIn("目标文号: 未识别", output.getvalue())
        self.assertIn("目标版本年份: 2014", output.getvalue())

    def test_mismatching_year_is_unresolved_even_if_title_unique(self):
        with patch("policy.abolition.find_policy_documents_by_normalized_title", return_value=[
            {"policy_id":"other", "doc_number":"武大党字〔2021〕98号"}
        ]):
            relation = build_abolition_relations({"policy_id":"new", "raw_text":"2017年印发的《细则》废止。"})[0]
        self.assertIsNone(relation.target_policy_id)

    def test_multiple_versions_same_year_remain_unresolved(self):
        with patch("policy.abolition.find_policy_documents_by_normalized_title", return_value=[
            {"policy_id":"a","doc_number":"字〔2017〕1号"}, {"policy_id":"b","doc_number":"字〔2017〕2号"}
        ]):
            self.assertIsNone(resolve_abolition_target("细则","",source_policy_id="new",target_issue_year=2017))

    def test_publication_year_falls_back_to_issue_date_but_not_effective_date(self):
        for field, expected in (("issue_date","old"),("effective_date",None)):
            with patch("policy.abolition.find_policy_documents_by_normalized_title",return_value=[
                {"policy_id":"old",field:"2017-01-01"}
            ]):
                self.assertEqual(resolve_abolition_target("细则","",target_issue_year=2017),expected)

    def test_approval_rejects_self_abolition_before_any_write(self):
        relation = {"review_status":"pending", "source_policy_id":"new", "target_policy_id":"new"}
        fake = SimpleNamespace(relational=SimpleNamespace(transaction=nullcontext))
        with patch.object(storage,"storage",fake), patch.object(storage,"lock_policy_document_relation",return_value=relation):
            with self.assertRaisesRegex(ValueError,"自身"):
                storage.review_policy_document_relation("r","approved","reviewer")

    def test_explicit_doc_number_does_not_fall_back_to_conflicting_title(self):
        with patch("policy.abolition.find_policy_documents_by_doc_number",return_value=[]), patch(
            "policy.abolition.find_policy_documents_by_normalized_title",return_value=[{"policy_id":"wrong"}]
        ):
            self.assertIsNone(resolve_abolition_target("细则","字〔2017〕1号"))

    def test_approval_rejects_publication_year_conflict(self):
        relation = {"review_status":"pending", "source_policy_id":"new", "target_policy_id":"wrong",
                    "target_title":"细则", "evidence_text":"2017年印发的《细则》废止。"}
        fake = SimpleNamespace(relational=SimpleNamespace(transaction=nullcontext))
        with patch.object(storage,"storage",fake), patch.object(storage,"lock_policy_document_relation",return_value=relation), patch.object(
            storage,"lock_policy_document",return_value={"policy_id":"wrong","doc_number":"字〔2021〕1号"}
        ):
            with self.assertRaisesRegex(ValueError,"年份"):
                storage.review_policy_document_relation("r","approved","reviewer")

    def test_self_abolition_is_rejected_when_saving_candidate(self):
        from core.models import PolicyDocumentRelation
        relation = PolicyDocumentRelation(relation_id="r",source_policy_id="new",target_policy_id="new",
                                          target_title="细则",evidence_clause_id="c",evidence_text="《细则》废止。")
        with patch.object(storage,"ensure_policy_tables",side_effect=AssertionError("不应写库")):
            with self.assertRaisesRegex(ValueError,"自身"):
                storage.upsert_policy_document_relation(relation)
