"""制度问答盲评的隔离与报告测试。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from policy import answering


class PolicyComparisonTests(unittest.TestCase):
    def test_pilot_exact_search_cannot_alter_official_index(self):
        from scripts.pilot_dormitory_knowledge import prepare_exact_search

        with self.assertRaises(ValueError):
            prepare_exact_search("policy_assertion_search_v2", None)

    def test_extraction_prompts_specify_qualifier_element_types(self):
        from policy.knowledge_v2.logic import build_assertion_prompt
        from policy.knowledge_v2.runner import build_batch_assertion_prompt

        for prompt in (build_assertion_prompt({}), build_batch_assertion_prompt([])):
            self.assertIn("conditions、materials、exceptions 必须是字符串数组", prompt)
            self.assertIn("不能填写对象数组", prompt)

    def test_custom_index_and_failure_are_observable(self):
        from policy.knowledge_v2.retrieval import enhance_clause_candidates_v2

        with patch("policy.knowledge_v2.retrieval.search_assertions_v2", side_effect=RuntimeError("测试失败")) as search:
            candidates, info = enhance_clause_candidates_v2("宿舍", [], knowledge_index_name="pilot")
        search.assert_called_once_with("宿舍", index_name="pilot")
        self.assertEqual(candidates, [])
        self.assertEqual(info["knowledge_status"], "failed")
        self.assertEqual(info["knowledge_error_type"], "RuntimeError")

    def test_baseline_does_not_invoke_knowledge(self):
        with patch.object(answering, "search_indexed_policy_clauses", return_value=[]), patch(
            "policy.knowledge_v2.retrieval.enhance_clause_candidates_v2"
        ) as enhance:
            result = answering.answer_policy_question("如何办理？", use_knowledge_v2=False)
        enhance.assert_not_called()
        self.assertEqual(result["retrieval_mode"], "clause_only")

    def test_comparison_blinds_modes_preserves_errors_and_resume(self):
        from scripts.compare_policy_answers import run_comparison, write_report

        calls = []

        def answer(question, requested_as_of=None, *, use_knowledge_v2=True):
            calls.append(use_knowledge_v2)
            if use_knowledge_v2:
                raise RuntimeError("断言服务失败")
            return {"answer": "<script>原文</script>", "citations": [], "retrieval_mode": "clause_only"}

        cases = [{"id": "q1", "question": "测试", "group": "g1", "references": []}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = run_comparison(cases, path, "2026-10-26", answer_fn=answer)
            run_comparison(cases, path, "2026-10-26", answer_fn=answer)
            self.assertEqual(len(calls), 2)
            report = write_report(rows, path).read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", report)
        self.assertNotIn("<script>原文", report)
        self.assertNotIn("clause_only", report)
        self.assertIn("执行失败", report)
        self.assertIn("导出评价", report)


if __name__ == "__main__":
    unittest.main()
