"""验证无章条编号层级，并保护既有正式条款父子关系。"""
import unittest

from core.models import BlockType, ContentBlock
from policy.pipeline import build_policy_clauses


def clauses_from(*lines):
    return build_policy_clauses("policy_test", [
        ContentBlock(type=BlockType.TEXT, content=line, page_num=1) for line in lines
    ])


class PolicyClauseHierarchyTests(unittest.TestCase):
    def test_last_numbered_clause_excludes_signature_publication_and_page_number(self):
        last = '五、 此规定的解释权为学院学位评定委员会。'
        footer = ('武汉大学电气与自动化学院', '2024年12月9日',
                  '武汉大学电气与自动化学院党政办公室 2024年12月17日印发', '4')
        clauses = clauses_from(last, *footer)
        self.assertEqual([clause.raw_text for clause in clauses], [last])

    def test_terminal_body_value_without_confirmed_signature_is_preserved(self):
        for tail in (('最终数量为', '4'), ('2024年12月9日', '4'),
                     ('武汉大学电气与自动化学院负责审批。', '4')):
            with self.subTest(tail=tail):
                clauses = clauses_from('五、 填报要求。', *tail)
                self.assertEqual(clauses[-1].raw_text, '\n'.join(('五、 填报要求。', *tail)))

    def test_parenthesized_versions_and_explanations_are_not_numbered_items(self):
        clauses = clauses_from("计算机学院优秀研究生（标兵）评选办法", "（2023年12月发布）",
                               "一、评选条件", "（一）提交申请。", "（由研究生办公室负责审核）")
        self.assertEqual([clause.level for clause in clauses], ["preamble", "item", "item"])
        self.assertIn("（2023年12月发布）", clauses[0].raw_text)
        self.assertIn("（由研究生办公室负责审核）", clauses[-1].raw_text)

    def test_complete_numbers_and_paragraph_ancestry_are_kept(self):
        clauses = clauses_from("第一章 岗位管理", "第一条 工作要求", "第二款 材料要求", "（一）申请表")
        self.assertEqual(clauses[-1].article_no, "第一条")
        self.assertEqual(clauses[-1].paragraph_no, "第二款")
        self.assertEqual(clauses[-1].chapter_path, ["第一章 岗位管理"])

    def test_page_zero_is_not_overwritten_when_clause_continues_on_next_page(self):
        clauses = build_policy_clauses("p", [
            ContentBlock(type=BlockType.TEXT, content="第一条 开始。", page_num=0),
            ContentBlock(type=BlockType.TEXT, content="续写内容。", page_num=1),
        ])
        self.assertEqual((clauses[0].page_start, clauses[0].page_end), (0, 1))

    def test_chapter_path_contains_heading_but_not_following_introduction(self):
        clauses = clauses_from("第一章 申请范围", "本章作出如下安排。", "第一条 申请人应提交材料。")
        self.assertEqual(clauses[-1].chapter_path, ["第一章 申请范围"])

    def test_preamble_does_not_invent_text_not_in_source(self):
        clauses = clauses_from("制度标题", "制定说明。", "一、基本条件")
        self.assertEqual(clauses[0].raw_text, "制度标题\n制定说明。")

    def test_appendix_is_separate_from_effective_date_article_and_remains_searchable(self):
        from policy.retrieval import is_searchable_policy_clause
        clauses = clauses_from("第十六条 本办法自2024年1月1日起实施。", "附件：计算机学院高水平成果奖励条件",
                               "附件", "计算机学院高水平成果奖励条件", "[表格]\n项目 | 金额\n奖励 | 1000")
        self.assertEqual(clauses[0].raw_text, "第十六条 本办法自2024年1月1日起实施。")
        self.assertEqual([clause.level for clause in clauses], ["article", "appendix"])
        self.assertIsNone(clauses[1].parent_clause_id)
        self.assertIn("奖励 | 1000", clauses[1].raw_text)
        self.assertTrue(is_searchable_policy_clause(clauses[1].model_dump()))

    def test_numbered_appendix_starts_new_scope_for_items(self):
        clauses = clauses_from("一、附则", "（一）本办法由学院解释。", "附件1", "评分表",
                               "1. 教学评分", "（1）课堂教学", "附件2", "团队评分表", "1. 团队评分")
        self.assertEqual([clause.level for clause in clauses], ["item", "item", "appendix", "item", "item", "appendix", "item"])
        self.assert_parents(clauses, [None, 0, None, 2, 3, None, 5])
        self.assertEqual(clauses[3].article_no, "")
        self.assertIn("附件1", " ".join(clauses[3].chapter_path))

    def test_repeated_appendix_reference_does_not_capture_remaining_body(self):
        clauses = clauses_from(
            "一、审核要求", "1. 核对登记信息。", "附件：登记示例",
            "二、材料归档", "（一）保存登记记录。",
            "三、复核", "每学期复核一次。",
            "外国语言文学学院\n2024年3月11日\n附件: 登记示例\n1. 填写登记日期。",
        )
        self.assertEqual([c.level for c in clauses], ["item"] * 5 + ["appendix", "item"])
        self.assert_parents(clauses, [None, 0, None, 2, None, None, 5])
        self.assertEqual(clauses[4].raw_text, "三、 复核\n每学期复核一次。")
        self.assertEqual(clauses[5].raw_text, "附件 登记示例")
        self.assertEqual(clauses[6].chapter_path, ["附件 登记示例"])
        self.assertTrue(all(not c.chapter_path for c in clauses[:5]))

    def test_dated_signature_before_an_explicit_appendix_is_excluded(self):
        clauses = clauses_from(
            "第一条 应提交材料。", "武汉大学计算机学院 2025年1月6日",
            "附件1：材料清单", "1. 登记表。",
        )
        self.assert_parents(clauses, [None, None, 1])
        self.assertEqual(clauses[0].raw_text, "第一条 应提交材料。")

    def test_numbered_supplementary_table_headings_end_the_last_article(self):
        article = "第九条 本规定由院研究生工作办公室负责解释，自通过之日起施行。"
        first_title = "附表一《武汉大学城市设计学院研究生前沿学术讲座签到表》"
        second_title = "附表二 2022、2023 级研究生参加前沿学术讲座次数要求"
        for table_block in (
            ContentBlock(type=BlockType.TEXT, content="2023 级 博士 10\n硕士 8"),
            ContentBlock(type=BlockType.TABLE, content="<table><tr><td>博士</td><td>10</td></tr></table>"),
        ):
            with self.subTest(block_type=table_block.type):
                items = [
                    ContentBlock(type=BlockType.TEXT, content=text)
                    for text in (article, "武汉大学城市设计学院\n2024年9月27日",
                                 first_title, "时间 地点 讲座名称 演讲人 盖章", second_title)
                ]
                clauses = build_policy_clauses("policy_test", [*items, table_block])
                self.assertEqual([c.level for c in clauses], ["article", "appendix", "appendix"])
                self.assert_parents(clauses, [None, None, None])
                self.assertEqual(clauses[0].raw_text, article)
                self.assertEqual([c.item_no for c in clauses[1:]], ["附表一", "附表二"])
                self.assertIn("盖章", clauses[1].raw_text)
                self.assertIn("博士", clauses[2].raw_text)
                self.assertEqual(clauses[2].chapter_path, [second_title])
                self.assertTrue(all("2024年9月27日" not in c.raw_text for c in clauses))

    def test_supplementary_table_reference_in_prose_stays_with_article(self):
        line = "附表一所列数据由学院核实。"
        clauses = clauses_from("第一条 数据审核。", line)
        self.assertEqual([c.raw_text for c in clauses], ["第一条 数据审核。\n" + line])

    def test_earlier_appendix_with_content_is_kept_when_title_recurs_after_footer(self):
        clauses = clauses_from(
            "第一条 应提交材料。", "附件：登记表", "本校登记所需字段：姓名、工号。",
            "武汉大学计算机学院 2025年1月6日", "附件：登记表", "外校登记所需字段：单位、姓名。",
        )
        self.assertEqual([c.level for c in clauses], ["article", "appendix", "appendix"])
        self.assert_parents(clauses, [None, None, None])
        self.assertIn("本校登记所需字段", clauses[1].raw_text)
        self.assertIn("外校登记所需字段", clauses[2].raw_text)

    def test_party_branch_signature_is_not_part_of_last_requirement(self):
        clauses = clauses_from("一、基本要求", "应当遵守纪律。", "计算机学院研究生党总支", "2023年7月6日")
        self.assertNotIn("2023年7月6日", clauses[-1].raw_text)
        self.assertNotIn("计算机学院研究生党总支", clauses[-1].raw_text)

    def test_unnumbered_final_provisions_are_independent_of_the_last_numbered_heading(self):
        closing = "本办法自2025年5月8日起施行，由学院负责解释，原办法即行废止。"
        clauses = clauses_from(
            "一、申请条件", "申请人须提交材料。",
            "二、奖励发放", "奖金发至学生本人。",
            closing, "化学与分子科学学院", "2025年5月8日",
        )
        self.assertEqual([c.raw_text for c in clauses], [
            "一、 申请条件\n申请人须提交材料。", "二、 奖励发放\n奖金发至学生本人。", closing,
        ])
        self.assert_parents(clauses, [None, None, None])
        self.assertEqual(clauses[-1].level, "paragraph")
        self.assertEqual(clauses[-1].item_no, "")

    def test_final_provisions_stay_with_their_own_heading_or_article(self):
        closing = "本办法自2025年5月8日起施行，由学院负责解释。"
        for heading in ("二、附则", "第二条 附则"):
            with self.subTest(heading=heading):
                clauses = clauses_from(heading, closing, "计算机学院", "2025年5月8日")
                self.assertEqual(len(clauses), 1)
                self.assertTrue(clauses[0].raw_text.endswith("\n" + closing))

    def test_general_procedure_at_end_is_not_an_independent_final_provision(self):
        line = "本办法由各系组织申报，学院审核后发放。"
        clauses = clauses_from("三、奖励发放", "审核后进行公示。", line, "计算机学院", "2025年5月8日")
        self.assertEqual([c.raw_text for c in clauses], ["三、 奖励发放\n审核后进行公示。\n" + line])

    def test_table_after_closing_signature_is_a_separate_appendix(self):
        article = "第十六条 本规定自发布之日起生效。"
        clauses = build_policy_clauses("p", [
            ContentBlock(type=BlockType.TEXT, content=article),
            ContentBlock(type=BlockType.TEXT, content="武汉大学计算机学院"),
            ContentBlock(type=BlockType.TEXT, content="2025年1月6日"),
            ContentBlock(type=BlockType.TABLE, content="<table><tr><td>事故等级</td><td>处理要求</td></tr></table>"),
        ])
        self.assertEqual([clause.level for clause in clauses], ["article", "appendix"])
        self.assertEqual(clauses[0].raw_text, article)
        self.assertIn("事故等级", clauses[1].raw_text)
        self.assertNotIn("2025年1月6日", clauses[1].raw_text)

    def test_reporting_instruction_and_date_example_are_not_removed(self):
        for prefix in ("报送", "提交", "上报", "向"):
            with self.subTest(prefix=prefix):
                instruction = prefix + "武汉大学计算机学院"
                clauses = clauses_from("第一条 材料应按以下示例填写：", instruction, "2023年12月21日", "请按以上格式填写。")
                self.assertIn(instruction, clauses[-1].raw_text)
                self.assertIn("2023年12月21日", clauses[-1].raw_text)

    def test_appendix_contains_book_and_section_hierarchies(self):
        for heading in ("第一节 申请条件", "第一编 申请条件"):
            with self.subTest(heading=heading):
                clauses = clauses_from("第一条 正文。", "附件1：办理指南", heading, "第一条 提交材料。")
                self.assert_parents(clauses, [None, None, 1, 2])
                self.assertIn("附件1 办理指南", clauses[-1].chapter_path)

    def test_publication_footer_with_disclosure_status_is_excluded(self):
        """公开属性与单位、日期共同组成版记，不能追加到解释条款。"""
        article = '第十五条 本办法由本科生院负责解释。'
        for status in ('主动公开', '依申请公开', '不予公开'):
            for footer in [(f'武汉大学党政办公室  {status}  2017年10月11日印制',),
                           ('武汉大学党政办公室', status, '2017年10月11日', '印制')]:
                with self.subTest(status=status, footer=footer):
                    clauses = clauses_from('第四章 附则', article, *footer)
                    self.assertEqual(len(clauses), 2)
                    self.assertEqual(clauses[-1].raw_text, article)

    def test_disclosure_requirement_in_body_is_retained(self):
        continuation = '武汉大学党政办公室应当主动公开有关信息。'
        clauses = clauses_from('第十五条 本办法由本科生院负责解释。', continuation)
        self.assertIn(continuation, clauses[-1].raw_text)

    def test_dated_committee_signature_is_excluded_from_last_item(self):
        """清廉学校建设意见的署名日期不应混入最后一项。"""
        item = '（三）营造良好氛围。各单位应做好宣传教育。'
        for footer in [('中共武汉大学委员会', '2021年11月27日'),
                       ('中共武汉大学委员会 2021年11月27日',)]:
            with self.subTest(footer=footer):
                clauses = clauses_from('三、组织保障', item, *footer)
                self.assertEqual(len(clauses), 2)
                self.assertEqual(clauses[-1].raw_text, '（三） 营造良好氛围。各单位应做好宣传教育。')

    def test_terminal_standalone_date_is_excluded_from_last_numbered_item(self):
        item = '2.除教学教分以“年”为单位进行计算外，平均数、兼职教分数均按“人年数”计算。'
        for terminal in ('二〇〇六年一月', '2021年11月27日', '2020.9.29', '二○○六年三月（修订）'):
            with self.subTest(terminal=terminal):
                clauses = clauses_from('七、有关具体规定：', '1. 按月计算。', f'{item}\n{terminal}')
                self.assertEqual(len(clauses), 3)
                self.assertEqual(clauses[-1].raw_text, item.replace('2.', '2. ', 1))
                self.assertNotIn(terminal, clauses[-1].search_text)

    def test_body_dates_and_organizational_requirements_are_retained(self):
        for continuation in [('2021年11月27日', '按前述日期办理。'),
                             ('由中共武汉大学委员会负责解释', '按规定落实。'),
                             ('本规定由武汉大学校长办公室负责印制。',),
                             ('二〇〇六年十三月',)]:
            with self.subTest(continuation=continuation):
                clauses = clauses_from('第十九条 工作要求。', *continuation)
                self.assertTrue(all(line in clauses[-1].raw_text for line in continuation))

    def test_organizational_requirement_before_terminal_date_is_retained(self):
        requirement = '由中共武汉大学委员会负责解释'
        clauses = clauses_from('第十九条 工作要求。', requirement, '2021年11月27日')
        self.assertEqual(clauses[-1].raw_text, '第十九条 工作要求。\n' + requirement)

    def test_publication_footer_is_excluded_from_last_article(self):
        """单行或跨块印制落款不应成为最后一条的正文。"""
        article = '第十九条 本规定自发布之日起施行，由保卫部负责解释。'
        for footer in [('武汉大学校长办公室               2013年6月17日印制',),
                       ('武汉大学校长办公室', '2013年6月17日印制'),
                       ('武汉大学校长办公室', '2013年6月17日', '印制')]:
            with self.subTest(footer=footer):
                blocks = [ContentBlock(type=BlockType.TEXT, content=text, page_num=1)
                          for text in ('第四章 附则', article, *footer)]
                clauses = build_policy_clauses('policy_test', blocks)
                self.assertEqual(len(clauses), 2)
                self.assertEqual(clauses[-1].raw_text, article)
                self.assertEqual(blocks[-1].content, footer[-1])

    def test_consecutive_signature_and_publication_footer_are_excluded(self):
        article = '第八条 本办法自发布之日起执行。'
        for footer in (
            ('武汉大学水利水电学院', '2022年5月17日', '武汉大学水利水电学院', '2022年5月17日印发'),
            ('武汉大学计算机学院 2025年5月8日', '武汉大学校长办公室', '主动公开', '2025年5月8日', '印制'),
            ('2022年5月17日', '武汉大学水利水电学院', '（此页无正文）',
             '2022年5月17日印发', '武汉大学水利水电学院'),
        ):
            with self.subTest(footer=footer):
                clauses = clauses_from('第七条 其他事项按规定办理。', '\n'.join((article, *footer)))
                self.assertEqual(len(clauses), 2)
                self.assertEqual(clauses[-1].raw_text, article)
                self.assertNotIn(footer[-1], clauses[-1].search_text)

    def test_printing_rules_and_unconfirmed_signatures_are_retained(self):
        """不根据单位名称或印制关键词删除真实制度要求。"""
        for continuation in ('武汉大学校长办公室负责印制并分发本规定。',
                             '武汉大学校长办公室',
                             '2013年6月17日施行。'):
            with self.subTest(continuation=continuation):
                clauses = clauses_from('第十九条 本规定由保卫部负责解释。', continuation)
                self.assertIn(continuation, clauses[-1].raw_text)

    def test_bold_article_labels_do_not_merge_into_chapter(self):
        """解析器输出加粗条号时，章与各条仍须分别保留。"""
        clauses = clauses_from('第一章 总  则\n**第一条** 学生宿舍是公共场所。\n'
                               '**第二条** 本规定适用于全日制学生。\n'
                               '**第三条** 安全管理实行责任制。\n'
                               '**第四条** 学生是寝室安全的直接责任人。')
        self.assertEqual([c.level for c in clauses], ['chapter'] + ['article'] * 4)
        self.assertEqual(clauses[0].raw_text, '第一章 总  则')
        self.assertEqual([c.article_no for c in clauses[1:]], ['第一条', '第二条', '第三条', '第四条'])
        self.assert_parents(clauses, [None, 0, 0, 0, 0])
        self.assertTrue(all(c.chapter_path == ['第一章 总  则'] for c in clauses[1:]))

    def test_bold_headings_preserve_body_emphasis_and_inline_article_boundaries(self):
        """只消除编号周围的格式，不改写正文中的加粗内容。"""
        clauses = clauses_from('**第一章 总则**',
                               '**第一条** 应当**保障安全**。 **第二条** 提交材料。',
                               '__第三条__审核申请。')
        self.assertEqual([c.level for c in clauses], ['chapter', 'article', 'article', 'article'])
        self.assertEqual(clauses[1].raw_text, '第一条 应当**保障安全**。')
        self.assertEqual(clauses[2].raw_text, '第二条 提交材料。')
        self.assert_parents(clauses, [None, 0, 0, 0])

    def test_emphasized_prose_is_not_a_clause_heading(self):
        clauses = clauses_from('第一章 总则', '第一条 工作要求。', '**依照第二条**执行。')
        self.assertEqual(len(clauses), 2)
        self.assertIn('**依照第二条**执行。', clauses[1].raw_text)

    def test_formal_article_nested_numbers_do_not_require_colon(self):
        clauses = clauses_from('第一章 条件', '第七条 申报资格', '一、学历学位条件',
            '（一）教授要求。', '（二）副教授要求。', '二、任职年限',
            '（一）教授年限。', '1. 具体要求。', '第八条 业绩', '（一）论文要求。')
        self.assert_parents(clauses, [None, 0, 1, 2, 2, 1, 5, 6, 0, 8])

    def test_formal_headings_without_spaces_keep_hierarchy(self):
        clauses = clauses_from('第一编管理', '第一章总 则', '第一节适用范围',
                              '第一条适用对象。', '第二章岗位设置', '第二条岗位要求。')
        self.assert_parents(clauses, [None, 0, 1, 2, 0, 4])
        self.assertEqual(clauses[3].chapter_path, ['第一编 管理', '第一章 总 则', '第一节 适用范围'])

    def test_formal_article_numbered_duties_keep_parent_and_siblings(self):
        clauses = clauses_from('第一章 职责', '第一条 委员分工',
            '（一）组织委员职责是：', '1. 组织工作。', '2. 管理工作。',
            '（二）宣传委员职责是：', '1. 宣传工作。', '2. 教育工作。',
            '第二条 其他事项', '1. 第一项。')
        self.assert_parents(clauses, [None, 0, 1, 2, 2, 1, 5, 5, 0, 8])

    def assert_parents(self, clauses, indexes):
        expected = [clauses[index].clause_id if index is not None else None for index in indexes]
        self.assertEqual([clause.parent_clause_id for clause in clauses], expected)

    def test_chinese_headings_parent_arabic_items_and_reset_between_sections(self):
        clauses = clauses_from(
            "制定说明", "一、总体要求", "1. 坚持质量导向。", "2. 坚持创新引领。",
            "二、具体措施", "1. 明确学制与学习年限。", "2. 优化培养过程。",
            "三、实施保障", "1. 深入研究。",
        )
        self.assert_parents(clauses, [None, None, 1, 1, None, 4, 4, None, 7])
        self.assertEqual(clauses[5].item_no, "1.")
        self.assertEqual(clauses[5].raw_text, "1. 明确学制与学习年限。")

    def test_four_numbering_styles_form_nested_levels_without_chaining_siblings(self):
        clauses = clauses_from(
            "一、工作要求", "（一）申请要求", "1. 提交材料", "（1）身份证明", "（2）申请表",
            "2. 审核材料", "（二）审批要求", "1. 主管部门审批", "二、附则", "（一）解释部门",
        )
        self.assert_parents(clauses, [None, 0, 1, 2, 2, 1, 0, 6, None, 8])

    def test_fullwidth_dotted_items_are_siblings_under_their_chinese_heading(self):
        clauses = clauses_from(
            "二、总体规划", "1．规划目标", "三、工作机制",
            "1．建立协同机制。", "构建分班、分阶段的工作体系。",
            "2．开展考核和激励。", "3．加大经费投入。",
            "3．5万元用于相关工作。", "四、组织领导",
        )
        self.assertEqual([c.item_no for c in clauses], ["二、", "1.", "三、", "1.", "2.", "3.", "四、"])
        self.assert_parents(clauses, [None, 0, None, 2, 2, 2, None])
        self.assertIn("构建分班、分阶段的工作体系。", clauses[3].raw_text)
        self.assertIn("3．5万元用于相关工作。", clauses[5].raw_text)

    def test_numbered_items_without_higher_heading_remain_siblings(self):
        for lines in [("1. 第一项。", "2. 第二项。"), ("（一）第一项。", "（二）第二项。")]:
            with self.subTest(lines=lines):
                self.assert_parents(clauses_from(*lines), [None, None])

    def test_formal_book_chapter_section_article_paragraph_item_hierarchy_is_unchanged(self):
        clauses = clauses_from(
            "第一编 管理", "第一章 总则", "第一节 范围", "第一条 申请要求", "第一款 材料要求",
            "一、身份证明", "1. 材料复印件。", "（一）申请表。", "（二）证明材料。",
            "第二款 审核要求", "（一）审核身份。", "第二条 办理要求", "（一）办理登记。",
            "第二章 附则", "第三条 生效规定。",
        )
        self.assert_parents(clauses, [None, 0, 1, 2, 3, 4, 5, 5, 5, 3, 9, 2, 11, 0, 13])
        self.assertEqual(clauses[8].chapter_path, ["第一编 管理", "第一章 总则", "第一节 范围"])
        self.assertEqual(clauses[8].article_no, "第一条")
        self.assertEqual(clauses[12].article_no, "第二条")

    def test_multiline_blocks_use_same_numbered_hierarchy(self):
        clauses = clauses_from("一、总体要求\n1. 质量导向。\n说明正文。\n2. 创新引领。\n二、具体措施\n1. 明确学制。")
        self.assert_parents(clauses, [None, 0, 0, None, 3])
        self.assertIn("说明正文。", clauses[1].raw_text)

    def test_chapter_only_document_keeps_existing_rules(self):
        clauses = clauses_from("第一章 总则", "一、管理要求", "1. 办理申请。")
        self.assert_parents(clauses, [None, None, None])

    def test_same_numbering_style_never_becomes_a_child_of_previous_item(self):
        clauses = clauses_from("一、要求", "二、措施", "三、保障")
        self.assert_parents(clauses, [None, None, None])
