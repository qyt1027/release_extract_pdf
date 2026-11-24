"""验证无章条编号层级，并保护既有正式条款父子关系。"""
import unittest

from core.models import BlockType, ContentBlock
from policy.pipeline import build_policy_clauses


def clauses_from(*lines):
    return build_policy_clauses("policy_test", [
        ContentBlock(type=BlockType.TEXT, content=line, page_num=1) for line in lines
    ])


class PolicyClauseHierarchyTests(unittest.TestCase):
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

    def test_date_alone_or_organizational_requirement_is_not_removed(self):
        for continuation in [('2021年11月27日',),
                             ('由中共武汉大学委员会负责解释', '2021年11月27日'),
                             ('本规定由武汉大学校长办公室', '2021年11月27日')]:
            with self.subTest(continuation=continuation):
                clauses = clauses_from('第十九条 工作要求。', *continuation)
                self.assertTrue(all(line in clauses[-1].raw_text for line in continuation))

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
        self.assertEqual([c.article_no for c in clauses[1:]], ['一', '二', '三', '四'])
        self.assert_parents(clauses, [None, 0, 0, 0, 0])
        self.assertTrue(all(c.chapter_path == ['第一章'] for c in clauses[1:]))

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
        self.assertEqual(clauses[3].chapter_path, ['第一编', '第一章', '第一节'])

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
        self.assertEqual(clauses[8].chapter_path, ["第一编", "第一章", "第一节"])
        self.assertEqual(clauses[8].article_no, "一")
        self.assertEqual(clauses[12].article_no, "二")

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
