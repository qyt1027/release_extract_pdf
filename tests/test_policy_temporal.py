"""制度文档时间治理与版本检索测试。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from policy.governance import apply_effective_date_governance
from policy.temporal import (
    classify_temporal_status,
    extract_effective_date,
    normalize_family_title,
    rank_temporal_candidates,
)


class PolicyTemporalTests(unittest.TestCase):
    def test_default_current_does_not_require_effective_date(self):
        self.assertEqual(classify_temporal_status({'validity_status': 'current'}, '2026-09-28'), 'applicable')

    def test_confirmed_invalid_without_date_is_not_currently_applicable(self):
        from datetime import date
        self.assertEqual(classify_temporal_status({'validity_status': 'invalid'}, date.today().isoformat()), 'inapplicable')
        self.assertEqual(classify_temporal_status({'validity_status': 'invalid'}, '2000-01-01'), 'unknown')

    def test_future_abolition_keeps_previous_period_applicable(self):
        document = {'validity_status': 'invalid', 'expiry_date': '2030-01-01'}
        self.assertEqual(classify_temporal_status(document, '2026-09-28'), 'applicable')
        self.assertEqual(classify_temporal_status(document, '2030-01-01'), 'inapplicable')

    def test_explicit_review_state_is_not_assumed_current(self):
        self.assertEqual(classify_temporal_status({'validity_status': 'unknown'}, '2026-09-28'), 'unknown')
        self.assertEqual(classify_temporal_status({'validity_status': 'unknown', 'effective_date': '2020-01-01'}, '2026-09-28'), 'unknown')

    @patch('policy.governance.insert_review_item')
    @patch('policy.governance.storage.relational.update_rows')
    def test_date_conflict_requires_review_without_restoring_invalid(self, update, review):
        result = apply_effective_date_governance('policy_1',
            ['自2020年1月1日起施行。', '自2021年1月1日起执行。'], None)
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(update.call_args.args[1], {'validity_status': 'unknown'})
        self.assertEqual(update.call_args.args[3], ('policy_1', 'invalid'))
        review.assert_called_once()
    @patch("policy.governance.insert_review_item")
    @patch("policy.governance.storage.relational.update_rows")
    def test_new_document_effective_date_is_saved(self, update_rows, insert_review) -> None:
        result = apply_effective_date_governance(
            "policy_1", ["本办法自2022年10月1日起施行。"], None
        )
        self.assertEqual(result["effective_date"], "2022-10-01")
        update_rows.assert_called_once()
        insert_review.assert_not_called()

    @patch("policy.governance.insert_review_item")
    @patch("policy.governance.storage.relational.update_rows")
    def test_existing_effective_date_is_not_overwritten(self, update_rows, insert_review) -> None:
        result = apply_effective_date_governance(
            "policy_1", ["本办法自2022年10月1日起施行。"], None, "2020-01-01"
        )
        self.assertEqual(result["status"], "preserved")
        update_rows.assert_not_called()
        insert_review.assert_not_called()

    def test_extracts_unique_explicit_effective_date(self) -> None:
        result = extract_effective_date(["本办法自2022年10月1日起施行。"], None)
        self.assertEqual(result, {"effective_date": "2022-10-01", "status": "identified"})

    def test_implementation_date_is_identified(self):
        result = extract_effective_date([
            "（六）本办法自2024年1月1日起实施，学院相关年度考核及绩效分配办法自行废止。",
        ], "2023-12-21")
        self.assertEqual(result, {"effective_date": "2024-01-01", "status": "identified"})

    def test_effective_date_accepts_yu_and_shixing(self):
        result = extract_effective_date(["本办法于2023年9月9日起实行，由研究生办公室负责解释。"], "2023-09-05")
        self.assertEqual(result, {"effective_date": "2023-09-09", "status": "identified"})

    def test_public_announcement_relative_date_uses_issue_date(self):
        result = extract_effective_date(["第十五条 本规定自公布之日起实施。"], "2023-02-06")
        self.assertEqual(result, {"effective_date": "2023-02-06", "status": "identified"})

    def test_year_only_and_meeting_conditions_require_review_without_invented_day(self):
        for text in (
            "本办法从2026年度开始执行，由学院党政联席会议负责解释。",
            "本办法自2025年度起实施。",
            "本办法经2024年3月21日学院教代会通过，2024年度开始执行。",
            "本办法自党政联席会通过之日起施行。",
            "本文件自学院党委会会议审议通过起试行。",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_effective_date([text], "2023-07-06"),
                                 {"effective_date": None, "status": "needs_review"})

    def test_implementation_from_publication_date_uses_issue_date(self):
        for trigger in ("发布", "印发", "发文", "下发"):
            with self.subTest(trigger=trigger):
                result = extract_effective_date([f"本办法自{trigger}之日起实施。"], "2023-12-21")
                self.assertEqual(result, {"effective_date": "2023-12-21", "status": "identified"})

    def test_relative_implementation_without_issue_date_requires_review(self):
        for trigger in ("印发", "发文"):
            with self.subTest(trigger=trigger):
                result = extract_effective_date([f"本办法自{trigger}之日起实施。"], None)
                self.assertEqual(result, {"effective_date": None, "status": "needs_review"})

    def test_implementation_and_other_effective_dates_conflict(self):
        result = extract_effective_date(["本办法自2024年1月1日起实施。", "本办法自2025年1月1日起施行。"], None)
        self.assertEqual(result, {"effective_date": None, "status": "conflict"})

    @patch("policy.governance.insert_review_item")
    @patch("policy.governance.storage.relational.update_rows")
    def test_implementation_date_is_saved_by_governance(self, update_rows, insert_review):
        result = apply_effective_date_governance("policy_1", ["本办法自2024年1月1日起实施。"], "2023-12-21")
        self.assertEqual(result["effective_date"], "2024-01-01")
        self.assertEqual(update_rows.call_args.args[1], {"effective_date": "2024-01-01"})
        insert_review.assert_not_called()

    def test_resolves_issue_date_relative_effective_date(self) -> None:
        result = extract_effective_date(["本办法自印发之日起施行。"], "2022-09-20")
        self.assertEqual(result, {"effective_date": "2022-09-20", "status": "identified"})

    def test_conflicting_dates_are_not_selected(self) -> None:
        result = extract_effective_date([
            "自2020年1月1日起施行。", "自2021年1月1日起执行。"
        ], None)
        self.assertEqual(result, {"effective_date": None, "status": "conflict"})

    def test_normalizes_notice_and_version_markers_for_family_candidate(self) -> None:
        self.assertEqual(
            normalize_family_title("关于印发《武汉大学财务管理办法（修订）》的通知"),
            "武汉大学财务管理办法",
        )

    def test_temporal_interval_is_left_closed_right_open(self) -> None:
        document = {"effective_date": "2016-01-01", "expiry_date": "2022-10-01"}
        self.assertEqual(classify_temporal_status(document, "2016-01-01"), "applicable")
        self.assertEqual(classify_temporal_status(document, "2022-10-01"), "inapplicable")

    def test_relevant_unknown_dates_survive_candidate_limit(self) -> None:
        candidates = [
            {"metadata": {"policy_id": "unknown"}, "score": 0.99},
            {"metadata": {"policy_id": "known"}, "score": 0.50},
        ]
        documents = {
            "unknown": {"policy_id": "unknown", "effective_date": None, "expiry_date": None},
            "known": {"policy_id": "known", "effective_date": "2020-01-01", "expiry_date": None},
        }
        ranked, warnings = rank_temporal_candidates(candidates, documents, "2021-01-01", 1)
        self.assertEqual([item["metadata"]["policy_id"] for item in ranked], ["unknown"])
        self.assertEqual(ranked[0]["temporal_status"], "unknown")
        self.assertEqual(warnings, [])

    def test_future_and_expired_versions_are_excluded(self) -> None:
        candidates = [
            {"metadata": {"policy_id": "old"}, "score": 0.9},
            {"metadata": {"policy_id": "future"}, "score": 0.8},
            {"metadata": {"policy_id": "current"}, "score": 0.7},
        ]
        documents = {
            "old": {"effective_date": "2010-01-01", "expiry_date": "2020-01-01"},
            "future": {"effective_date": "2030-01-01", "expiry_date": None},
            "current": {"effective_date": "2020-01-01", "expiry_date": None},
        }
        ranked, _ = rank_temporal_candidates(candidates, documents, "2025-01-01", 10)
        self.assertEqual([item["metadata"]["policy_id"] for item in ranked], ["current"])

    def test_same_family_overlap_produces_warning(self) -> None:
        candidates = [
            {"metadata": {"policy_id": "v1"}, "score": 0.9},
            {"metadata": {"policy_id": "v2"}, "score": 0.8},
        ]
        documents = {
            "v1": {"family_id": "family_1", "effective_date": "2020-01-01"},
            "v2": {"family_id": "family_1", "effective_date": "2021-01-01"},
        }
        ranked, warnings = rank_temporal_candidates(candidates, documents, "2022-01-01", 10)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("family_1", warnings[0])


if __name__ == "__main__":
    unittest.main()
