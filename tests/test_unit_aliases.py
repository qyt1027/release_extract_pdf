"""学院别名在入库、历史候选和问答中的统一行为。"""
import unittest
from unittest.mock import patch


class UnitAliasTests(unittest.TestCase):
    def test_explicit_aliases_share_one_canonical_name(self):
        from core.unit_aliases import normalize_applicable_unit
        for value in ['外语学院', '外院', '外国语言文学学院', ' 外语 学院 ']:
            self.assertEqual(normalize_applicable_unit(value), '外国语言文学学院')
        self.assertEqual(normalize_applicable_unit('某某学院'), '某某学院')
        self.assertEqual(normalize_applicable_unit(''), '')
        self.assertEqual(normalize_applicable_unit('计院'), '计算机学院')

    def test_title_and_scope_infer_canonical_unit_without_rewriting_title(self):
        from metadata.policy_scope import infer_applicable_unit
        self.assertEqual(infer_applicable_unit('外语学院关于公务接待的通知'), ['外国语言文学学院'])
        self.assertEqual(infer_applicable_unit('外院设备管理办法'), ['外国语言文学学院'])
        self.assertEqual(infer_applicable_unit('计院设备管理办法'), ['计算机学院'])
        self.assertEqual(infer_applicable_unit('设备管理规定', '第一条 本规定适用于外院。'), ['外国语言文学学院'])

    def test_query_alias_and_full_name_match_old_and_new_metadata(self):
        from policy.retrieval import filter_candidates_by_applicable_unit
        rows=[{'metadata': {'applicable_unit': unit}} for unit in ['外语学院','外国语言文学学院','全校','计算机学院','']]
        for query in ['外院怎么报销', '外语学院怎么报销', '外国语言文学学院怎么报销']:
            self.assertEqual(filter_candidates_by_applicable_unit(query, rows), rows[:3])
        self.assertEqual(filter_candidates_by_applicable_unit('计院怎么报销', rows), [rows[2], rows[3]])

    def test_hybrid_search_expands_alias_before_vector_and_keyword_retrieval(self):
        from types import SimpleNamespace
        from policy.retrieval import search_indexed_policy_clauses
        from core.config import app_config
        row={'metadata': {'clause_id':'c1', 'applicable_unit':['计算机学院']}}
        vector=SimpleNamespace(count_vectors=lambda _:1, search=lambda *args, **kwargs:[row])
        with patch('storage.adapters.storage', SimpleNamespace(vector=vector)), \
             patch('policy.retrieval._encode_policy_clause_texts', return_value=[[1.]]) as encode, \
             patch('policy.retrieval.search_policy_clauses_bm25', return_value=[]) as keyword, \
             patch('policy.retrieval.rerank_clause_candidates', side_effect=lambda q, rows, *args, **kwargs:rows), \
             patch('policy.retrieval.attach_clause_hierarchy_context', side_effect=lambda rows:rows), \
             patch.object(app_config.answer_llm, 'rerank_enabled', False):
            search_indexed_policy_clauses('计院怎么报销', top_k=1)
        encode.assert_called_once_with(['计算机学院怎么报销'])
        self.assertEqual(keyword.call_args.args[0], '计算机学院怎么报销')

    def test_index_uses_canonical_unit_and_preserves_evidence(self):
        from policy.retrieval import build_clause_metadata
        result=build_clause_metadata({'raw_text':'外院应当审批。'}, {'title':'外院规定','applicable_unit':['外语学院']})
        self.assertEqual(result['applicable_unit'], ['外国语言文学学院'])
        self.assertEqual(result['raw_text'], '外院应当审批。')
        self.assertIn('外国语言文学学院', result['search_text'])

    def test_query_expansion_does_not_repeat_full_name(self):
        from core.unit_aliases import normalize_unit_query
        self.assertEqual(normalize_unit_query('请问外院和外语学院怎么报销'), '请问外国语言文学学院和外国语言文学学院怎么报销')
        full='外国语言文学学院怎么报销'
        self.assertEqual(normalize_unit_query(full), full)

    def test_alias_inside_other_words_or_unknown_institution_is_not_expanded(self):
        from core.unit_aliases import normalize_unit_query
        from metadata.policy_scope import query_applicable_units, infer_applicable_unit
        for query in ['我在规划设计院，怎么报销', '校外院系人员怎么报销', '国际外语学院怎么报销',
                      '对外院校开展交流有哪些规定', '对外院系开展交流有哪些规定']:
            self.assertEqual(normalize_unit_query(query), query)
            self.assertNotIn('计算机学院', query_applicable_units(query, {'计算机学院','外国语言文学学院'}))
            self.assertNotIn('外国语言文学学院', query_applicable_units(query, {'计算机学院','外国语言文学学院'}))
        self.assertEqual(infer_applicable_unit('规划设计院设备管理办法'), [])

    def test_alias_in_common_question_context_is_expanded(self):
        from core.unit_aliases import normalize_unit_query
        for query in ['计院如何报销', '请问计院如何报销', '我在计院，怎么报销', '想了解计院的规定', '关于计院设备管理的办法']:
            self.assertIn('计算机学院', normalize_unit_query(query))
        self.assertEqual(normalize_unit_query('对外院的规定'), '对外国语言文学学院的规定')

    def test_unit_normalization_command_dispatch(self):
        from commands.entry import main
        with patch('commands.entry.run_normalize_applicable_units') as run:
            main(['--normalize-applicable-units', '--unit-normalization-dry-run'])
        run.assert_called_once_with(dry_run=True)

    def test_catalog_display_uses_canonical_name_and_keeps_title(self):
        from policy.web_catalog import _public_row, PUBLIC_DOCUMENT_FIELDS
        result=_public_row({'title':'外院管理规定', 'applicable_unit':['外语学院']}, PUBLIC_DOCUMENT_FIELDS)
        self.assertEqual(result['applicable_unit'], ['外国语言文学学院'])
        self.assertEqual(result['title'], '外院管理规定')

    def test_backfill_is_dry_run_safe_and_idempotent(self):
        import json
        import sqlite3
        from contextlib import contextmanager
        from types import SimpleNamespace
        from policy.unit_normalization import normalize_stored_applicable_units
        connection=sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE policy_documents(applicable_unit TEXT, updated_at TEXT)")
        connection.executemany("INSERT INTO policy_documents(applicable_unit) VALUES (?)", (
            (json.dumps(units),) for units in (["外语学院", "哲学学院"], ["外院"], ["计院"], ["全校"], ["未知学院"])
        ))
        @contextmanager
        def transaction():
            with connection:
                yield
        class Cursor:
            def __enter__(self):
                self.cur=connection.cursor()
                return self
            def __exit__(self, *_args):
                self.cur.close()
            def execute(self, sql, params=()):
                self.cur.execute(sql.replace('%s','?').replace('NOW()', 'CURRENT_TIMESTAMP'),
                                 tuple(json.dumps(value) for value in params))
            def fetchall(self):
                return [(json.loads(units), count) for units, count in self.cur.fetchall()]
            @property
            def rowcount(self):
                return self.cur.rowcount
        adapter=SimpleNamespace(transaction=transaction, conn=SimpleNamespace(cursor=Cursor))
        preview=normalize_stored_applicable_units(adapter=adapter, dry_run=True)
        self.assertEqual(sum(row['count'] for row in preview['changes']), 3)
        self.assertEqual(connection.execute("SELECT count(*) FROM policy_documents WHERE applicable_unit=?",
                                            (json.dumps(["外语学院", "哲学学院"]),)).fetchone()[0], 1)
        self.assertEqual(normalize_stored_applicable_units(adapter=adapter)['updated'], 3)
        self.assertEqual(normalize_stored_applicable_units(adapter=adapter)['updated'], 0)
