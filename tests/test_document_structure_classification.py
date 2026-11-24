"""验证多章、多条的正文结构可以独立构成规章制度强信号。"""
import unittest

from classification.document import classify_document


class DocumentStructureClassificationTests(unittest.TestCase):
    body = (
        '第一章 总则\n'
        '第一条 学业导师制面向学院全体本科生。\n'
        '第二条 学业导师由学院在职教师担任。\n'
        '第二章 考核\n'
        '第三条 考核结果作为教师年度考核的重要内容之一。'
    )

    def test_multiple_chapters_and_articles_are_an_independent_strong_signal(self):
        """没有制度标题、制定表述或义务词时，完整章条结构也应直接分类。"""
        result = classify_document('missing.pdf', '教学工作材料.pdf', parsed_text=self.body)
        self.assertEqual(result['doc_type'], 'policy_regulation')
        self.assertEqual(result['confidence'], 1.0)
        self.assertTrue(any('[强信号]' in signal and '章条结构' in signal for signal in result['signals']))

    def test_many_articles_without_chapters_are_also_a_strong_signal(self):
        """兼容只设条款的制度及 Markdown、阿拉伯数字、排版空格。"""
        body = (
            '## 第 1 条 学业导师制面向学院全体本科生。\n'
            '**第 2 条** 学业导师由学院在职教师担任。\n'
            '第 3 条 学院每年组织学业导师考核。\n'
            '第 4 条 考核结果纳入年度考核。\n'
            '第 5 条 优秀导师获得表彰奖励。'
        )
        result = classify_document('missing.pdf', '未命名.pdf', parsed_text=body)
        self.assertEqual(result['doc_type'], 'policy_regulation')
        self.assertEqual(result['confidence'], 1.0)

    def test_sparse_or_empty_headings_are_not_a_strong_signal(self):
        for body in (
            self.body.replace('第二章 考核\n', ''),
            '第一章 总则\n第二章 实施\n第三章 总结',
            '第一章 总则\n第一条\n第二条\n第二章 考核\n第三条\n第四条\n第五条',
        ):
            with self.subTest(body=body):
                result = classify_document('missing.pdf', '工作材料.pdf', parsed_text=body)
                self.assertEqual(result['doc_type'], 'other')

    def test_repeated_same_article_is_not_counted_as_many_articles(self):
        body = ('第一章 总则\n第一条 学业导师由学院在职教师担任。\n' * 6)
        result = classify_document('missing.pdf', '工作材料.pdf', parsed_text=body)
        self.assertEqual(result['doc_type'], 'other')

    def test_inline_and_quoted_references_do_not_create_a_strong_signal(self):
        cases = (
            '报告分析第一章、第二章、第三章及第一条、第二条、第三条、第四条、第五条的关系。',
            '会议材料\n引用内容：“' + self.body + '”\n以上内容供研讨。',
            '\n'.join('> ' + line for line in self.body.splitlines()),
        )
        for body in cases:
            with self.subTest(body=body):
                result = classify_document('missing.pdf', '研讨材料.pdf', parsed_text=body)
                self.assertEqual(result['doc_type'], 'other')

    def test_table_of_contents_is_not_body_structure(self):
        body = (
            '目录\n第一章 总则……1\n第一条 范围……1\n第二条 职责……2\n'
            '第二章 考核……3\n第三条 要求……3\n第四条 办理……4\n第五条 奖励……5'
        )
        result = classify_document('missing.pdf', '工作材料.pdf', parsed_text=body)
        self.assertEqual(result['doc_type'], 'other')

    def test_academic_identifier_keeps_priority_over_chapter_article_structure(self):
        result = classify_document(
            'missing.pdf', '研究材料.pdf', parsed_text='DOI: 10.1234/example\n' + self.body,
        )
        self.assertEqual(result['doc_type'], 'academic_paper')
