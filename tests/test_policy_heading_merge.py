import unittest

from core.models import BlockType, ContentBlock
from processing.text import _merge_by_article, _merge_by_policy_heading


def block(text):
    return ContentBlock(type=BlockType.TEXT, content=text)


class PolicyHeadingMergeTests(unittest.TestCase):
    def test_fifth_clause_is_separate_from_signature_with_terminal_page_number(self):
        last = '五、 此规定的解释权为学院学位评定委员会。'
        footer = ('武汉大学电气与自动化学院\n2024年12月9日\n'
                  '武汉大学电气与自动化学院党政办公室 2024年12月17日印发')
        for merge, clause in ((_merge_by_policy_heading, last), (_merge_by_article, '第五条 解释权归学院。')):
            with self.subTest(merge=merge.__name__):
                units = merge([block(clause + '\n' + footer + '\n4')])
                self.assertEqual([unit['text'] for unit in units], [clause, footer])

    def test_numbered_headings_group_following_paragraphs(self):
        blocks = [block(text) for text in [
            "武汉大学全员聘用制实施意见", "引言", "一、指导思想", "指导思想正文。",
            "二、基本原则", "（一）按需设岗", "原则说明。", "（二）公开招聘", "招聘说明。",
            "三、适用范围", "适用范围正文。",
        ]]
        units = _merge_by_policy_heading(blocks)
        self.assertEqual(len(units), 6)
        self.assertTrue(units[2]["text"].startswith("二、基本原则"))
        self.assertIn("原则说明。", units[3]["text"])
        self.assertNotIn("招聘说明。", units[3]["text"])

    def test_article_documents_keep_article_grouping(self):
        units = _merge_by_article([block("第一条 总则"), block("内容"), block("第二条 范围")])
        self.assertEqual(len(units), 2)

    def test_article_and_document_footer_have_separate_search_units(self):
        first = "第七条 其他事项按规定办理。"
        last = "第八条 本办法自发布之日起执行。"
        footer = "武汉大学水利水电学院\n2022年5月17日\n武汉大学水利水电学院\n2022年5月17日印发"
        units = _merge_by_article([block(f"{first}\n{last}\n{footer}")])
        self.assertEqual([unit["text"] for unit in units], [first, last, footer])

    def test_terminal_standalone_date_has_its_own_search_unit(self):
        for merge, last in ((_merge_by_article, '第八条 按规定办理。'), (_merge_by_policy_heading, '2. 按规定办理。')):
            for terminal in ('二〇〇六年一月', '2020.9.29', '二○○六年三月（修订）'):
                with self.subTest(merge=merge.__name__, terminal=terminal):
                    units = merge([block(f'{last}\n{terminal}')])
                    self.assertEqual([unit['text'] for unit in units], [last, terminal])

    def test_numbered_full_sentences_remain_separate_units(self):
        first = "一、本通告所指航空器主要包括轻型飞机、无人机、航空模型等多种类型，应遵守校园安全管理规定。"
        blocks = [block(text) for text in [
            "航空器管理通告", "现将有关事项通告如下：", first,
            "二、放飞前须报学校审批。", "五、禁止下列行为：",
            "（一）未经许可拍摄保密设施；", "（二）扰乱教学、科研秩序。",
            "六、违规行为按规定处理。",
        ]]
        units = _merge_by_policy_heading(blocks)
        self.assertEqual([unit["text"] for unit in units], [
            "航空器管理通告\n现将有关事项通告如下：", first,
            "二、放飞前须报学校审批。", "五、禁止下列行为：",
            "（一）未经许可拍摄保密设施；", "（二）扰乱教学、科研秩序。",
            "六、违规行为按规定处理。",
        ])

    def test_arabic_numbering_and_multiline_blocks_keep_boundaries(self):
        blocks = [
            ContentBlock(type=BlockType.TEXT, page_num=1,
                         content="管理说明\n1. 审核材料。\n补充说明\n（1）提交申请；\n2、办理审批。"),
            ContentBlock(type=BlockType.TEXT, page_num=2, content="1.1 适用范围\n范围正文。"),
        ]
        units = _merge_by_policy_heading(blocks)
        self.assertEqual([unit["text"] for unit in units], [
            "管理说明", "1. 审核材料。\n补充说明", "（1）提交申请；", "2、办理审批。", "1.1 适用范围\n范围正文。",
        ])
        self.assertEqual([unit["page_num"] for unit in units], [1, 1, 1, 1, 2])

    def test_unnumbered_text_and_decimal_values_stay_together(self):
        units = _merge_by_policy_heading([block("管理说明"), block("3.14米为示例数值。"), block("普通正文。")])
        self.assertEqual([unit["text"] for unit in units], ["管理说明\n3.14米为示例数值。\n普通正文。"])

    def test_closing_provisions_and_signature_are_separate_from_numbered_body(self):
        closing = "本办法自发布之日起施行。"
        interpretation = "本办法由数学与统计学院负责解释。"
        units = _merge_by_policy_heading([
            block("三、材料归档\n相关材料应当归档。"),
            block(closing + "\n" + interpretation),
            block("数学与统计学院\n2025年5月8日"),
        ])
        self.assertEqual([unit["text"] for unit in units], [
            "三、材料归档\n相关材料应当归档。", closing + "\n" + interpretation,
            "数学与统计学院\n2025年5月8日",
        ])

    def test_closing_under_its_own_heading_stays_with_that_heading(self):
        units = _merge_by_policy_heading([
            block("三、附则"), block("本办法自发布之日起施行。"), block("数学与统计学院\n2025年5月8日"),
        ])
        self.assertEqual([unit["text"] for unit in units], [
            "三、附则\n本办法自发布之日起施行。", "数学与统计学院\n2025年5月8日",
        ])


if __name__ == "__main__":
    unittest.main()
