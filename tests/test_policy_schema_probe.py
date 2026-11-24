"""结构约束小试验的来源验证测试。"""
import unittest


class SchemaProbeTests(unittest.TestCase):
    def test_omitted_actor_can_remain_unknown(self):
        from scripts.probe_policy_schema import validate_rules

        source = {"c1": "不得随意调换床位。"}
        result = validate_rules({"rules": [{"modality": "prohibited", "actor": None,
            "action": {"text": "调换", "clause_id": "c1", "quote": "不得随意调换床位。"}}]}, source)
        self.assertEqual(len(result["valid"]), 1)

    def test_invented_actor_is_rejected_even_when_action_has_evidence(self):
        from scripts.probe_policy_schema import validate_rules

        source = {"c1": "学生应提出申请。"}
        result = validate_rules({"rules": [{"modality": "required",
            "actor": {"text": "学院", "clause_id": "c1", "quote": "学生应提出申请。"},
            "action": {"text": "提出申请", "clause_id": "c1", "quote": "学生应提出申请。"}}]}, source)
        self.assertEqual(len(result["invalid"]), 1)

    def test_field_cannot_quote_a_clause_not_provided_to_model(self):
        from scripts.probe_policy_schema import validate_rules

        result = validate_rules({"rules": [{"modality": "required", "action": {
            "text": "申请", "clause_id": "c2", "quote": "申请"}}]}, {"c1": "申请"})
        self.assertEqual(len(result["invalid"]), 1)


if __name__ == "__main__":
    unittest.main()
