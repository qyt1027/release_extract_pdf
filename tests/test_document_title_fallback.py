"""通用标题不依赖制度后缀或通知类型。"""
import unittest

from core.models import BlockType, ContentBlock
from metadata import extract_document_metadata
from metadata.policy import extract_policy_metadata


def blocks(*lines):
    return [ContentBlock(type=BlockType.TEXT, content=line) for line in lines]


class DocumentTitleFallbackTests(unittest.TestCase):
    def test_wrapped_regulatory_title_keeps_institution_and_subject(self):
        from metadata.title import infer_document_title

        title = '武汉大学电气与自动化学院关于加强研究生学位质量管理的规定'
        layouts = (
            ('武汉大学电气与自动化学院', '关于加强研究生学位质量管理的规定'),
            ('武汉大学电气与自动化学院', '关于加强研究生学位', '质量管理的规定'),
            ('武汉大学', '电气与自动化学院', '关于加强研究生学位质量管理的规定'),
        )
        for lines in layouts:
            for grouped in (False, True):
                with self.subTest(lines=lines, grouped=grouped):
                    content = ('武汉大学电气与自动化学院', '武大电气函〔2024〕15号', *lines,
                               '根据有关文件精神，制定本规定。', '一、严把学位论文质量关',
                               '武汉大学电气与自动化学院', '2024年12月9日')
                    items = blocks('\n'.join(content)) if grouped else blocks(*content)
                    self.assertEqual(infer_document_title(items), title)
                    for filename in ('download.pdf', title + '.pdf'):
                        for doc_type in ('other', 'policy_regulation'):
                            with self.subTest(filename=filename, doc_type=doc_type):
                                result = extract_document_metadata(items, doc_type, filename)
                                self.assertEqual(result['title'], title)
                                if doc_type == 'policy_regulation':
                                    self.assertEqual(result['applicable_unit'], ['电气与自动化学院'])
                                    self.assertEqual(result['applicable_unit_paths'], ['电气与自动化学院'])
                                    self.assertEqual(result['doc_number'], '武大电气函〔2024〕15号')

    def test_recovered_title_preserves_original_file_format(self):
        from storage.file_records import choose_display_file_name
        for suffix in ['pdf', 'doc', 'docx']:
            with self.subTest(suffix=suffix):
                self.assertEqual(choose_display_file_name('download.' + suffix, '设备借用须知'), '设备借用须知.' + suffix)

    def test_non_notice_title_without_policy_suffix_is_preserved(self):
        title='外语学院接待工作补充说明'
        result=extract_policy_metadata(blocks(title, '一、须先审批。'), 'download.docx')
        self.assertEqual(result['title'], title)
        self.assertNotIn('notice_title', result)

    def test_generic_title_is_available_even_for_other_classification(self):
        title='设备借用须知'
        result=extract_document_metadata(blocks(title, '一、先办理手续。'), 'other', 'download.docx')
        self.assertEqual(result['title'], title)

    def test_attachment_marker_before_wrapped_title_with_filename_date_suffix(self):
        first_line = '武汉大学城市设计学院推荐2027届优秀本科毕业生'
        second_line = '免试攻读研究生综合成绩计算方法'
        title = first_line + second_line
        for label in ('【附件】', '附件：', '【附件2】', '附件二：'):
            with self.subTest(label=label):
                items = blocks(label, first_line, second_line, '根据有关文件精神，特制定本计算方法。')
                items[0].raw = {'type': 'title'}
                result = extract_document_metadata(items, 'other', f'附件：{title}0513.docx')
                self.assertEqual(result['title'], title)

    def test_attachment_markers_do_not_hide_real_titles_starting_with_attachment(self):
        title = '附件上传操作说明'
        result = extract_document_metadata(blocks('【附件】', title, '一、先登录系统。'), 'other', 'download.pdf')
        self.assertEqual(result['title'], title)
        result = extract_document_metadata(blocks('【附件】', '一、先登录系统。'), 'other', '附件.docx')
        self.assertEqual(result['title'], '未命名文档')

    def test_independent_body_title_has_priority_over_filename(self):
        result=extract_policy_metadata(blocks('设备借用须知', '一、先办理手续。'), '旧文件名称.docx')
        self.assertEqual(result['title'], '设备借用须知')

    def test_valid_filename_fills_missing_header_without_policy_suffix(self):
        result=extract_policy_metadata(blocks('一、先办理手续。'), '设备借用须知.docx')
        self.assertEqual(result['title'], '设备借用须知')

    def test_organization_number_date_and_body_are_not_titles(self):
        result=extract_policy_metadata(blocks('外语学院', '武大字〔2023〕1号', '2023年3月1日',
            '为贯彻落实要求提升管理水平', '一、先办理手续。'), '设备借用须知.docx')
        self.assertEqual(result['title'], '设备借用须知')

    def test_hash_filename_is_not_used_as_title(self):
        result=extract_policy_metadata(blocks('一、先办理手续。'), '1234567890abcdef.docx')
        self.assertEqual(result['title'], '未命名文档')

    def test_wrapped_notice_title_is_completed_before_using_filename(self):
        title = '关于印发《研究生联合培养办法（试行）》的通知'
        for filename in ('附件12：' + title + '.doc', 'download.doc'):
            with self.subTest(filename=filename):
                result = extract_document_metadata(blocks(
                    '**关于印发《研究生联合**', '**培养办法（试行）》的通知**',
                    '各培养单位：', '请认真贯彻执行。',
                ), 'other', filename)
                self.assertEqual(result['title'], title)

    def test_unclosed_title_fragment_is_not_returned_as_a_title(self):
        result = extract_document_metadata(blocks(
            '关于印发《联合培养', '各培养单位：', '一、请按要求办理。',
        ), 'other', '附件3：关于印发《联合培养办法》的通知.pdf')
        self.assertEqual(result['title'], '关于印发《联合培养办法》的通知')

    def test_prefixed_filename_fallback_keeps_the_document_title(self):
        result = extract_document_metadata([], 'other', '〔行政2024〕21—学院教学质量评定办法.pdf')
        self.assertEqual(result['title'], '学院教学质量评定办法')

    def test_complete_title_about_issuing_a_document_can_be_a_decision(self):
        title = '关于印发《年度工作方案》的决定'
        result = extract_document_metadata(blocks(title, '一、按既定安排办理。'), 'other', 'download.doc')
        self.assertEqual(result['title'], title)

    def test_recovers_full_heading_when_file_name_omits_title_details(self):
        title_lines = ('武汉大学文学院', '关于表彰优秀学生的', '2024—2025学年度工作决定')
        filename = '〔行政2025〕07—关于表彰优秀学生的决定.pdf'
        for raw_type in ('text', 'header'):
            with self.subTest(raw_type=raw_type):
                items = blocks('武汉大学文学院文件', '武大文字〔2025〕7号', '签发人：张某', *title_lines,
                               '各有关单位：', '经研究决定，表彰优秀学生。', '特此通知')
                for item in items[3:6]:
                    item.raw = {'type': raw_type}
                result = extract_document_metadata(items, 'other', filename)
                self.assertEqual(result['title'], ''.join(title_lines))

    def test_closing_and_following_attachment_cannot_be_titles(self):
        for closing in ('特此通知', '特此通报', '此复', '专此函复'):
            with self.subTest(closing=closing):
                items = blocks('武汉大学文学院文件', '文院字〔2024〕2号', closing, '武汉大学文学院')
                items[2].raw = {'type': 'title'}
                items.append(ContentBlock(type=BlockType.TEXT, page_num=1, content='获奖名单'))
                filename = '〔行政2024〕02—奖项评审结果.pdf'
                self.assertEqual(extract_document_metadata(items, 'other', filename)['title'], '奖项评审结果')
                self.assertEqual(extract_document_metadata(items, 'other', 'download.pdf')['title'], '未命名文档')

    def test_parser_title_block_can_recover_generic_multiline_title(self):
        items = blocks('校内公共资源的\n开放与共享', '在本次调查中，我们记录了资源共享的使用情况。')
        items[0].raw = {'type': 'title'}
        result = extract_document_metadata(items, 'other', 'download.pdf')
        self.assertEqual(result['title'], '校内公共资源的开放与共享')

    def test_does_not_join_two_independently_marked_headings(self):
        title = '关于校内公共资源'
        items = blocks(title, '关于公布项目评审结果的公告', '请各单位查阅。')
        items[0].raw = items[1].raw = {'type': 'title'}
        self.assertEqual(extract_document_metadata(items, 'other', 'download.pdf')['title'], title)

    def test_complete_file_title_beats_an_unconfirmed_fragment(self):
        items = blocks('关于开展项目评审', '各有关单位：', '请按要求报送材料。')
        result = extract_document_metadata(items, 'other', '关于开展项目评审的公告.pdf')
        self.assertEqual(result['title'], '关于开展项目评审的公告')

    def test_policy_and_general_document_use_the_same_opening_title(self):
        items = blocks('教务处文件', '签发人：张某', '各教学单位：', '根据《校内管理办法》，现将要求明确如下。',
                       '关于印发《设备管理细则》的通知')
        filename = '实验室开放时间说明.pdf'
        for doc_type in ('other', 'policy_regulation'):
            with self.subTest(doc_type=doc_type):
                result = extract_document_metadata(items, doc_type, filename)
                self.assertEqual(result['title'], '实验室开放时间说明')
                self.assertNotIn('notice_title', result)
