"""原文补全试验的证据去重与实验标识测试。"""
import tempfile
import unittest
from pathlib import Path


class EvidenceCompletionTests(unittest.TestCase):
    def test_supplement_does_not_repeat_existing_related_clause(self):
        from scripts.compare_policy_evidence import append_evidence

        baseline = [{"evidence_id": "E1", "clause_id": "a", "related_clauses": [{"clause_id": "b"}]}]
        complete = [{"clause_id": "b"}, {"clause_id": "c", "raw_text": "补充原文"}]
        result = append_evidence(baseline, complete)
        self.assertEqual([e["clause_id"] for e in result], ["a", "c"])
        self.assertEqual(result[1]["evidence_id"], "E2")
        self.assertEqual(len(baseline), 1)

    def test_report_describes_completion_without_claiming_v2(self):
        from scripts.compare_policy_answers import write_report

        result = {"answer": "回答", "citations": [], "retrieval_mode": "clause_plus_evidence"}
        rows = [{"case": {"id": "q04", "question": "福利费？"}, "left_is_completed": True,
                 "results": {"baseline": {"result": result}, "completed": {"result": result}}}]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            report = write_report(rows, directory, experiment="evidence_completion").read_text(encoding="utf-8")
        self.assertIn("人工核实的原文补全", report)
        self.assertNotIn("未形成有效增强对比", report)


if __name__ == "__main__":
    unittest.main()
