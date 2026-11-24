"""官网院系初版映射的覆盖与歧义保护。"""
import json
from pathlib import Path
import unittest

from core.paths import PROJECT_ROOT


class OfficialUnitCatalogTests(unittest.TestCase):
    def groups(self):
        return json.loads((PROJECT_ROOT / 'core/unit_aliases.json').read_text(encoding='utf-8'))

    def test_catalog_covers_official_directory_and_common_aliases(self):
        from core.unit_aliases import normalize_applicable_unit
        groups = self.groups()
        self.assertEqual(len(groups), 43)
        for alias, official in {
            '经管院':'经济与管理学院', '政管院':'政治与公共管理学院',
            '数统院':'数学与统计学院', '资环院':'资源与环境科学学院',
            '动机院':'动力与机械学院', '电信院':'电子信息学院',
            '网安院':'国家网络安全学院', '基础医学院':'泰康医学院(基础医学院)',
            '艺术学院':'艺术学院（艺术教育中心）', '卓工院':'国家卓越工程师学院',
        }.items():
            self.assertEqual(normalize_applicable_unit(alias), official)
        for ambiguous in ['法院','医学院','机院','人民医院','中南医院','高等研究院']:
            self.assertEqual(normalize_applicable_unit(ambiguous), ambiguous)

    def test_every_official_name_can_be_inferred_from_its_title_and_query(self):
        from metadata.policy_scope import infer_applicable_unit, query_applicable_units
        for name in self.groups():
            with self.subTest(name=name):
                self.assertEqual(infer_applicable_unit(name + '设备管理办法'), [name])
                self.assertEqual(query_applicable_units(name + '如何报销', set()), {name})

    def test_each_configured_alias_works_for_inference_and_questions(self):
        from core.unit_aliases import normalize_applicable_unit, normalize_unit_query
        from metadata.policy_scope import infer_applicable_unit, query_applicable_units
        for name, aliases in self.groups().items():
            for alias in aliases:
                if not ''.join(alias.split()):
                    continue
                with self.subTest(alias=alias, official=name):
                    self.assertEqual(normalize_applicable_unit(alias), name)
                    self.assertEqual(infer_applicable_unit(alias + '设备管理办法'), [name])
                    self.assertEqual(query_applicable_units('请问' + alias + '如何报销', set()), {name})
                    expanded = normalize_unit_query(alias + '如何报销')
                    self.assertEqual(normalize_unit_query(expanded), expanded)

    def test_short_name_does_not_consume_a_person_title(self):
        from core.unit_aliases import normalize_unit_query
        from metadata.policy_scope import query_applicable_units
        for query in ['马院长如何办理报销', '文院士如何办理报销']:
            self.assertEqual(normalize_unit_query(query), query)
            self.assertEqual(query_applicable_units(query, set()), set())

    def test_official_units_with_school_prefix_in_scope_and_question(self):
        from metadata.policy_scope import infer_applicable_unit, query_applicable_units
        for name in self.groups():
            prefixed = name if name.startswith('武汉大学') else '武汉大学' + name
            with self.subTest(name=name):
                self.assertEqual(infer_applicable_unit('设备管理办法', '第一条 本办法适用于' + prefixed + '。'), [name])
                self.assertEqual(query_applicable_units('我在' + prefixed + '，怎么报销', set()), {name})

    def test_registered_and_unregistered_colleges_still_conflict(self):
        from metadata.policy_scope import infer_applicable_unit
        self.assertEqual(infer_applicable_unit('计算机学院和数学学院设备管理办法'), [])

    def test_child_unit_hierarchy_is_independent_of_college_alias_catalog(self):
        from core.unit_aliases import applicable_unit_paths, unit_aliases
        from metadata.policy_scope import query_applicable_units

        groups = self.groups()
        self.assertEqual(groups["前沿交叉学科研究院"], ["前沿交叉研究院", "交叉学科研究院"])
        self.assertNotIn("中国传统文化研究中心", unit_aliases())
        self.assertNotIn("心理学系", unit_aliases())
        path = "前沿交叉学科研究院-心理学系"
        self.assertEqual(applicable_unit_paths(["心理学系"]), [path])
        self.assertEqual(query_applicable_units(path + "如何申请", set()), {"前沿交叉学科研究院心理学系"})
