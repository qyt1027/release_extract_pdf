"""文件关系图谱的来源、版本和遍历边界测试。"""
import unittest


def doc(pid, title, number=""):
    return {"policy_id": pid, "title": title, "doc_number": number, "structure_version": "v1"}


def clause(pid, text, cid="c1"):
    return {"policy_id": pid, "clause_id": cid, "raw_text": text, "structure_version": "v1", "is_active": True}


class DocumentGraphTests(unittest.TestCase):
    def test_explicit_year_never_resolves_to_wrong_version(self):
        from policy.document_graph import build_document_graph

        graph = build_document_graph([doc("a", "甲办法"), doc("new", "乙办法", "武大〔2025〕1号")], [clause("a", "2020年印发的《乙办法》同时废止。")], [])
        self.assertNotEqual(graph["edges"][0]["target"], "new")

    def test_parenthesized_year_is_used_for_version_resolution(self):
        from policy.document_graph import build_document_graph

        graph = build_document_graph([doc("a", "甲办法"), doc("old", "乙办法", "武大〔2020〕1号"), doc("new", "乙办法", "武大〔2025〕1号")], [clause("a", "依据《乙办法》（武大（2020）1号）执行。")], [])
        self.assertEqual(graph["edges"][0]["target"], "old")
        graph = build_document_graph([doc("a", "甲办法"), doc("old", "乙办法", "武大〔2020〕1号")], [clause("a", "《乙办法》（武大（2020）1号）同时废止。")], [])
        self.assertEqual(graph["edges"][0]["type"], "abolishes")

    def test_historical_edition_annotation_keeps_reviewed_abolition_edge(self):
        from policy.document_graph import build_document_graph

        text = "《乙办法》（2020年制定）同时废止。"
        documents = [
            doc("source", "甲办法"), doc("old", "乙办法", "武大〔2020〕1号"),
            doc("new", "乙办法", "武大〔2025〕1号"),
        ]
        relation = {
            "relation_id": "r", "source_policy_id": "source", "evidence_clause_id": "c1",
            "target_title": "乙办法", "target_doc_number": "2020年制定",
            "evidence_text": text, "review_status": "approved", "relation_type": "abolishes",
        }
        graph = build_document_graph(documents, [clause("source", text)], [relation])
        self.assertEqual(
            [(edge["target"], edge["type"], edge["review_status"]) for edge in graph["edges"]],
            [("old", "abolishes", "approved")],
        )

    def test_explicit_unfamiliar_number_cannot_fall_back_to_title(self):
        from policy.document_graph import build_document_graph

        for number in ("教育部令第41号", "〔2020〕1号", "武大字〔2020〕第1号"):
            graph = build_document_graph([doc("a", "甲办法"), doc("new", "乙办法", "武大〔2025〕1号")], [clause("a", f"依据《乙办法》（{number}）执行。")], [])
            self.assertNotEqual(graph["edges"][0]["target"], "new")

    def test_same_sentence_references_to_other_version_are_not_suppressed(self):
        from policy.document_graph import build_document_graph

        documents = [doc("a", "甲办法"), doc("old", "乙办法", "武大〔2020〕1号"), doc("new", "乙办法", "武大〔2025〕1号")]
        graph = build_document_graph(documents, [clause("a", "依据《乙办法》（武大〔2025〕1号）修订，原《乙办法》（武大〔2020〕1号）同时废止。")], [])
        self.assertEqual({(e["target"], e["type"]) for e in graph["edges"]}, {("new", "cites"), ("old", "abolishes")})
        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法")], [clause("a", "依据《乙办法》完成修订，原《乙办法》同时废止。")], [])
        self.assertEqual({e["type"] for e in graph["edges"]}, {"cites", "abolishes"})

    def test_local_citation_scope_and_independent_abolition_occurrence(self):
        from policy.document_graph import build_document_graph

        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法"), doc("c", "丙办法")], [clause("a", "不得按照《乙办法》执行，应依据《丙办法》执行。")], [])
        self.assertEqual({e["target"]: e["type"] for e in graph["edges"]}, {"b": "mentions", "c": "cites"})
        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法")], [clause("a", "依据《乙办法》完成修订。原《乙办法》同时废止。")], [])
        self.assertEqual({e["type"] for e in graph["edges"]}, {"cites", "abolishes"})
        graph = build_document_graph([doc("a", "甲办法")], [clause("a", "根据工作要求填写《处理报告》。")], [])
        self.assertEqual(graph["edges"][0]["type"], "mentions")

    def test_words_in_titles_do_not_turn_mentions_into_citations(self):
        from policy.document_graph import build_document_graph

        graph = build_document_graph([doc("a", "甲办法")], [clause("a", "归档《乙执行办法》和《丙办法》的副本。")], [])
        self.assertTrue(all(e["type"] == "mentions" for e in graph["edges"]))

    def test_view_never_embeds_raw_script_closing_tag(self):
        from policy.document_graph_view import render_document_graph

        page = render_document_graph({"nodes": [{"id": "x", "title": "</script><script>alert(1)</script>"}], "edges": []})
        self.assertNotIn("</script><script>alert(1)</script>", page)
        self.assertIn("\\u003c/script\\u003e", page)

    def test_negative_reference_is_only_mention(self):
        from policy.document_graph import build_document_graph

        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法")], [clause("a", "不得按照《乙办法》执行。")], [])
        self.assertEqual(graph["edges"][0]["type"], "mentions")

    def test_citation_and_unresolved_target_preserve_evidence(self):
        from policy.document_graph import build_document_graph

        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法")], [clause("a", "依据《乙办法》和《丙规定》，制定本办法。")], [])
        self.assertEqual(len(graph["edges"]), 2)
        self.assertTrue(all(e["type"] == "cites" for e in graph["edges"]))
        self.assertEqual({e["target"] for e in graph["edges"]} & {"b"}, {"b"})
        self.assertTrue(all(e["citations"][0]["clause_id"] == "c1" for e in graph["edges"]))
        self.assertEqual(sum(n["resolution"] == "not_in_corpus" for n in graph["nodes"]), 1)

    def test_number_disambiguates_versions_and_mismatch_never_falls_back(self):
        from policy.document_graph import build_document_graph

        documents = [doc("a", "甲办法"), doc("old", "乙办法", "武大〔2020〕1号"), doc("new", "乙办法", "武大〔2025〕1号")]
        graph = build_document_graph(documents, [clause("a", "依据《乙办法》（武大〔2020〕1号）执行。")], [])
        self.assertEqual(graph["edges"][0]["target"], "old")
        graph = build_document_graph(documents, [clause("a", "依据《乙办法》（武大〔2010〕1号）执行。")], [])
        self.assertNotIn(graph["edges"][0]["target"], {"old", "new"})
        graph = build_document_graph(documents, [clause("a", "依据《乙办法》执行。")], [])
        self.assertEqual(next(n for n in graph["nodes"] if n["id"] == graph["edges"][0]["target"])["resolution"], "ambiguous")

    def test_approved_abolition_wins_and_no_validity_is_propagated(self):
        from policy.document_graph import build_document_graph, graph_neighborhood

        relation = {"relation_id": "r", "source_policy_id": "b", "target_policy_id": "c", "target_title": "丙办法", "evidence_clause_id": "bc", "evidence_text": "《丙办法》同时废止。", "review_status": "approved", "relation_type": "abolishes"}
        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法"), doc("c", "丙办法")], [clause("a", "依据《乙办法》执行。"), clause("b", "《丙办法》同时废止。", "bc")], [relation])
        self.assertEqual(len(graph["edges"]), 2)
        abolishes = next(e for e in graph["edges"] if e["type"] == "abolishes")
        self.assertEqual(abolishes["review_status"], "approved")
        result = graph_neighborhood(graph, "a", depth=2)
        self.assertEqual(len(result["edges"]), 2)
        self.assertFalse(any(e["source"] == "a" and e["target"] == "c" for e in result["edges"]))

    def test_partial_or_rejected_abolition_is_not_whole_document_abolition(self):
        from policy.document_graph import build_document_graph

        for text in ("《乙办法》第三条废止。", "不得废止《乙办法》。"):
            graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法")], [clause("a", text)], [])
            self.assertFalse(any(e["type"] == "abolishes" for e in graph["edges"]))
        rejected = {"source_policy_id": "a", "target_title": "乙办法", "evidence_clause_id": "c1", "review_status": "rejected", "relation_type": "abolishes"}
        graph = build_document_graph([doc("a", "甲办法"), doc("b", "乙办法")], [clause("a", "《乙办法》同时废止。")], [rejected])
        self.assertFalse(any(e["type"] == "abolishes" for e in graph["edges"]))
        self.assertEqual([e["type"] for e in graph["edges"]], ["mentions"])

    def test_old_structure_and_self_title_are_excluded(self):
        from policy.document_graph import build_document_graph

        old = {**clause("a", "依据《乙办法》执行。"), "structure_version": "v0"}
        graph = build_document_graph([doc("a", "甲办法")], [old, clause("a", "关于印发《甲办法》的通知。")], [])
        self.assertEqual(graph["edges"], [])

    def test_directions_cycles_and_truncation(self):
        from policy.document_graph import graph_neighborhood

        graph = {"nodes": [{"id": x} for x in "abcd"], "edges": [
            {"id": "ab", "source": "a", "target": "b"}, {"id": "ca", "source": "c", "target": "a"},
            {"id": "bd", "source": "b", "target": "d"}, {"id": "ba", "source": "b", "target": "a"}]}
        self.assertEqual({e["id"] for e in graph_neighborhood(graph, "a", direction="outgoing", depth=1)["edges"]}, {"ab"})
        result = graph_neighborhood(graph, "a", depth=3, limit=1)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["edges"]), 1)
        with self.assertRaises(ValueError):
            graph_neighborhood(graph, "a", depth=9)


if __name__ == "__main__":
    unittest.main()
