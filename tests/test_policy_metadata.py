import unittest

from core.models import BlockType, ContentBlock
from metadata.policy import extract_policy_metadata


class PolicyMetadataDocumentNumberTests(unittest.TestCase):
    def blocks(self, *texts):
        return [ContentBlock(type=BlockType.TEXT, page_num=0, content=text) for text in texts]

    def test_institution_prefixed_notice_keeps_full_title(self):
        title='外语学院关于进一步严格国内公务接待要求的通知'
        meta=extract_policy_metadata(self.blocks(title,
            '按照学校要求，现就公务接待作进一步说明，请遵照执行。',
            '1、国内公务接待按照《旧管理细则》执行。'), title + '.docx')
        self.assertEqual(meta.get('title'), title)
        self.assertNotIn('notice_title', meta)
        self.assertEqual(meta.get('applicable_unit'), ['外国语言文学学院'])

    def test_split_institution_prefixed_notice_title(self):
        title='外语学院关于进一步严格国内公务接待要求的通知'
        meta=extract_policy_metadata(self.blocks('外语学院', '关于进一步严格国内公务接待', '要求的通知', '1、须先审批。'))
        self.assertEqual(meta.get('title'), title)
        self.assertNotIn('notice_title', meta)

    def test_notice_filename_fills_missing_header_title(self):
        title='外语学院关于进一步严格国内公务接待要求的通知'
        meta=extract_policy_metadata(self.blocks('1、须先审批。', '2、不得违规报销。'), title + '.docx')
        self.assertEqual(meta.get('title'), title)
        self.assertNotIn('notice_title', meta)

    def test_vehicle_notice_has_title_without_wrapper_notice_title(self):
        title='外语学院关于进一步规范公务用车的通知'
        meta=extract_policy_metadata(self.blocks(title, '一、公务用车须提前审批。'), title + '.docx')
        self.assertEqual(meta.get('title'), title)
        self.assertNotIn('notice_title', meta)

    def test_issuance_notice_keeps_wrapper_and_actual_policy_title(self):
        title='武汉大学工程项目招标资格预审及评定分离实施办法'
        notice=f'关于印发《{title}》的通知'
        meta=extract_policy_metadata(self.blocks(notice, title, '第一条 正文。'))
        self.assertEqual(meta.get('title'), title)
        self.assertEqual(meta.get('notice_title'), notice)

    def test_non_issuance_verbs_do_not_set_notice_title(self):
        title='武汉大学工程项目招标资格预审及评定分离实施办法'
        for verb in ['发布', '颁布', '公布', '执行', '引发']:
            notice=f'关于{verb}《{title}》的通知'
            with self.subTest(verb=verb):
                meta=extract_policy_metadata(self.blocks(notice, '一、按要求办理。'), notice + '.docx')
                self.assertEqual(meta.get('title'), notice)
                self.assertNotIn('notice_title', meta)

    def test_mhtml_ordinary_notice_does_not_inherit_notice_title(self):
        title='外语学院关于进一步规范公务用车的通知'
        items=self.blocks(title, '一、公务用车须提前审批。')
        items[0].raw={'source_format':'mhtml', 'source_metadata':{'title':title, 'notice_title':title}}
        meta=extract_policy_metadata(items)
        self.assertEqual(meta.get('title'), title)
        self.assertNotIn('notice_title', meta)

    def test_prefixed_notice_with_two_policies_still_splits(self):
        titles=['外语学院甲管理办法', '外语学院乙管理办法']
        notice='外语学院关于印发《'+titles[0]+'》和《'+titles[1]+'》的通知'
        meta=extract_policy_metadata(self.blocks(notice, titles[0], '第一条 甲正文。', titles[1], '第一条 乙正文。'))
        self.assertNotIn('title', meta)
        self.assertEqual(meta.get('notice_title'), notice)
        self.assertEqual([part['title'] for part in meta.get('policies', [])], titles)

    def test_publishing_two_policies_still_splits_without_notice_title(self):
        from policy.document_parts import split_policy_document
        titles=['武汉大学甲管理办法', '武汉大学乙管理办法']
        notice=f'关于发布《{titles[0]}》和《{titles[1]}》的通知'
        items=self.blocks(notice, titles[0], '第一条 甲正文。', titles[1], '第一条 乙正文。')
        meta=extract_policy_metadata(items)
        self.assertEqual(meta.get('title'), notice)
        self.assertNotIn('notice_title', meta)
        self.assertEqual([part['title'] for part in meta.get('policies', [])], titles)
        parts=split_policy_document(items, meta, 'download.pdf')
        self.assertEqual(len(parts), 2)
        self.assertTrue(all('notice_title' not in part['metadata'] for part in parts))

    def test_notice_referenced_in_numbered_body_does_not_become_title(self):
        meta=extract_policy_metadata(self.blocks('外语学院公务接待管理办法',
            '第一条 正文。', '外语学院关于接待要求的通知', '第二条 正文。'))
        self.assertEqual(meta.get('title'), '外语学院公务接待管理办法')
        self.assertNotIn('notice_title', meta)

    def test_title_and_document_number_on_same_line(self):
        metadata = extract_policy_metadata(self.blocks(
            "武汉大学会议费管理办法 武大财字[2023]10号", "第一章 总则",
            "第一条 为加强会议费管理，制定本办法。",
            "第三十五条 《武汉大学会议费管理办法》（武大财字[2019]32号）同时废止。",
        ), "武汉大学会议费管理办法 武大财字[2023]10号.docx")
        self.assertEqual(metadata.get("title"), "武汉大学会议费管理办法")
        self.assertEqual(metadata.get("doc_number"), "武大财字〔2023〕10号")
        self.assertEqual(metadata.get("applicable_unit"), ["全校"])

    def test_filename_title_with_trailing_document_number_is_not_erased(self):
        from core.policy_titles import normalize_policy_title
        self.assertEqual(normalize_policy_title("武汉大学会议费管理办法 武大财字[2023]10号.docx"),
                         "武汉大学会议费管理办法")
        self.assertEqual(normalize_policy_title("武大财字[2023]10号 武汉大学会议费管理办法.docx"),
                         "武汉大学会议费管理办法")

    def test_body_reference_does_not_supply_current_document_number(self):
        metadata = extract_policy_metadata(self.blocks(
            "武汉大学会议费管理办法", "第一条 正文。",
            "武汉大学旧管理办法 武大财字[2019]32号",
        ))
        self.assertNotIn("doc_number", metadata)

    def test_multiple_policy_keywords_do_not_truncate_title(self):
        metadata = extract_policy_metadata(self.blocks(
            "武汉大学规章制度管理办法 武大财字[2023]10号", "第一条 正文。",
        ))
        self.assertEqual(metadata.get("title"), "武汉大学规章制度管理办法")
        self.assertEqual(metadata.get("doc_number"), "武大财字〔2023〕10号")

    def test_numbered_body_reference_is_not_current_document_number(self):
        metadata = extract_policy_metadata(self.blocks(
            "武汉大学会议费管理办法", "一、管理职责",
            "依据武汉大学财务管理办法 武大财字[2019]32号", "二、报销标准",
        ))
        self.assertNotIn("doc_number", metadata)

    def test_numbered_body_and_version_keep_actual_policy_title_separate_from_notice(self):
        notice = "关于印发《计算机学院研究生专项奖学金评定办法》的通知"
        actual = "计算机学院研究生专项奖学金评选办法"
        metadata = extract_policy_metadata(self.blocks(
            notice, "武汉大学计算机学院", "2023年12月22日", actual,
            "（2023年12月发布）", "为鼓励研究生全面发展，制定本办法。", "一、申请条件", "（一）诚实守信。",
        ))
        self.assertEqual(metadata.get("title"), actual)
        self.assertEqual(metadata.get("notice_title"), notice)
        self.assertEqual(metadata.get("version"), "2023年12月发布")

    def test_split_actual_title_need_not_equal_book_title_in_notice(self):
        metadata = extract_policy_metadata(self.blocks(
            "关于印发《计算机学院研究生优秀学业奖学金实施细则》的通知",
            "计算机学院研究生", "优秀学业奖学金评定实施细则", "（2023年12月修订）",
            "为规范评选工作，制订本细则。", "一、参评对象", "在籍研究生。",
        ))
        self.assertEqual(metadata.get("title"), "计算机学院研究生优秀学业奖学金评定实施细则")
        self.assertEqual(metadata.get("version"), "2023年12月修订")

    def test_work_requirements_body_title_does_not_become_notice_title(self):
        title = "计算机学院教师岗位工作要求"
        metadata = extract_policy_metadata(self.blocks(
            f"关于印发《{title}》的通知", "现印发给你们，请遵照执行。", title, "一、教学工作要求", "应当完成教学工作。",
        ))
        self.assertEqual(metadata.get("title"), title)

    def test_closing_signature_can_supply_issue_date_after_body(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院研究生党总支关于党员民主评议合格的标准（试行）",
            "一、思想觉悟", "应当遵守纪律。", "计算机学院研究生党总支", "2023年7月6日",
        ))
        self.assertEqual(metadata.get("issue_date"), "2023-07-06")

    def test_dotted_issue_date_is_recognized_in_header_and_closing_signature(self):
        title = "武汉大学社会学博士研究生申请博士学位创新成果暂行规定"
        body = "六、本规定自2021年入学的博士研究生开始实施。"
        for lines in (
            ("2020.9.29", body),
            ("发布日期：2020.9.29", body),
            (body, "武汉大学社会学院", "2020.9.29"),
            (body, "武汉大学社会学院2020．9．29"),
        ):
            with self.subTest(lines=lines):
                metadata = extract_policy_metadata(self.blocks(title, *lines))
                self.assertEqual(metadata.get("issue_date"), "2020-09-29")

    def test_dotted_issue_date_requires_valid_date_and_publication_context(self):
        title = "武汉大学社会学院管理办法"
        body = "第一条 应按学校规定办理。"
        for lines in (
            (body, "2020.9.29", "第二条 正文。"),
            (body, "报送武汉大学社会学院", "2020.9.29", "第二条 正文。"),
            (body, "武汉大学社会学院", "2020.2.30"),
            ("发布日期：2020.9.291", body),
        ):
            with self.subTest(lines=lines):
                metadata = extract_policy_metadata(self.blocks(title, *lines))
                self.assertNotIn("issue_date", metadata)

    def test_chinese_issue_date_is_recognized_in_publication_context(self):
        title = "武汉大学社会学院管理办法"
        body = "第一条 应按学校规定办理。"
        for lines, expected in (
            ((body, "武汉大学社会学院", "二〇一四年六月十八日"), "2014-06-18"),
            (("发布日期：二○一四年十月一日", body), "2014-10-01"),
            (("二零一四年十二月三十一日", body), "2014-12-31"),
            ((body, "武汉大学社会学院", "二OO六年十一月十八日"), "2006-11-18"),
            ((body, "武汉大学社会学院2014年六月廿八日"), "2014-06-28"),
        ):
            with self.subTest(lines=lines):
                metadata = extract_policy_metadata(self.blocks(title, *lines))
                self.assertEqual(metadata.get("issue_date"), expected)

    def test_chinese_issue_date_requires_valid_date_and_publication_context(self):
        title = "武汉大学社会学院管理办法"
        body = "第一条 应按学校规定办理。"
        for lines in (
            (body, "二〇一四年六月十八日", "第二条 正文。"),
            ("本办法于二〇一四年六月十八日审议通过。", body),
            (body, "武汉大学社会学院", "二〇一四年二月二十九日"),
        ):
            with self.subTest(lines=lines):
                metadata = extract_policy_metadata(self.blocks(title, *lines))
                self.assertNotIn("issue_date", metadata)

    def test_month_precision_publication_date_preserves_available_precision(self):
        title = "学院管理人员绩效考核办法与实施细则"
        body = "第一条 考核对象为全院在册在岗管理人员。"
        for lines in (
            (body, "第八条 本办法由院党政联席会负责解释。", "二〇一三年三月"),
            (body, "信息管理学院", "2013年3月"),
            ("发布日期：二〇一三年三月", body),
            ("二〇一三年三月", body),
        ):
            with self.subTest(lines=lines):
                metadata = extract_policy_metadata(self.blocks(title, *lines))
                self.assertEqual(metadata.get("issue_month"), "2013-03")
                self.assertNotIn("issue_date", metadata)

    def test_publication_month_requires_valid_and_unambiguous_evidence(self):
        title = "学院管理人员绩效考核办法与实施细则"
        body = "第一条 考核对象为全院在册在岗管理人员。"
        for lines in (
            (body, "二〇一三年三月", "第二条 正文。"),
            (body, "本办法于二〇一三年三月审议通过。"),
            (body, "二〇一三年十三月"),
            (body, "信息管理学院", "二〇一三年十三月"),
            ("发布日期：2013年3月", "发布日期：2013年4月18日", body),
        ):
            with self.subTest(lines=lines):
                metadata = extract_policy_metadata(self.blocks(title, *lines))
                self.assertNotIn("issue_month", metadata)
                self.assertNotIn("issue_date", metadata)

    def test_final_standalone_date_is_a_fallback_regardless_of_previous_line(self):
        for previous, terminal, field, expected in (
            ("第二条 公务车辆应按规定停放。", "二〇一一年三月", "issue_month", "2011-03"),
            ("第八条本规定自发文之日起实施。", "二〇一一年三月", "issue_month", "2011-03"),
            ("报送武汉大学社会学院", "2020.9.29", "issue_date", "2020-09-29"),
            ("第二条 应按规定办理。", "二〇一四年六月十八日", "issue_date", "2014-06-18"),
        ):
            with self.subTest(previous=previous, terminal=terminal):
                metadata = extract_policy_metadata(self.blocks(
                    "学院公车使用管理规定", "第一条 为加强学院公车使用管理，特制定本规定。",
                    previous, terminal, "  ",
                ))
                self.assertEqual(metadata.get(field), expected)
                self.assertNotIn("issue_date" if field == "issue_month" else "issue_month", metadata)

    def test_agreeing_publication_dates_keep_the_day_when_known(self):
        metadata = extract_policy_metadata(self.blocks(
            "学院管理人员绩效考核办法", "发布日期：2013年3月", "发布日期：2013年3月18日", "第一条 正文。",
        ))
        self.assertEqual(metadata.get("issue_date"), "2013-03-18")
        self.assertNotIn("issue_month", metadata)

    def test_numbered_heading_ending_in_standard_is_not_another_policy_title(self):
        title = "计算机学院研究生学业奖学金评定实施细则"
        metadata = extract_policy_metadata(self.blocks(
            f"关于印发《{title}》的通知", title, "（2025年12月发布）",
            "为进一步规范评选工作，制订本细则。", "一、参评对象", "在籍研究生。",
            "二、评定比例及奖励标准", "（一）奖励比例。",
        ))
        self.assertEqual(metadata.get("title"), title)

    def test_body_version_note_does_not_become_document_version(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院管理办法", "第一条 依据旧文件办理。", "（2020年修订）",
        ))
        self.assertNotIn("version", metadata)

    def test_final_revision_date_is_used_as_publication_date(self):
        title = "学院教授委员会议事规则"
        body = "第一条 学院教授委员会设主席一人。"
        for terminal, expected_date, expected_month in (
            ("二○○六年三月（修订）", None, "2006-03"),
            ("二○○六年三月十八日(修订版)", "2006-03-18", None),
            ("二○○六年三月修订", None, "2006-03"),
            ("二○○六年十三月（修订）", None, None),
            ("二○○六年三月（正文引用）", None, None),
        ):
            with self.subTest(terminal=terminal):
                metadata = extract_policy_metadata(self.blocks(title, body, terminal, "  "))
                self.assertEqual(metadata.get("issue_date"), expected_date)
                self.assertEqual(metadata.get("issue_month"), expected_month)
                self.assertNotIn("version", metadata)

    def test_explicit_publication_date_takes_priority_over_final_revision_date(self):
        metadata = extract_policy_metadata(self.blocks(
            "学院教授委员会议事规则", "发布日期：2006年3月21日", "第一条 正文。", "二○○六年三月（修订）",
        ))
        self.assertEqual(metadata.get("issue_date"), "2006-03-21")
        self.assertNotIn("issue_month", metadata)
        self.assertNotIn("version", metadata)

    def test_numbered_notice_does_not_hide_body_version(self):
        title = "计算机学院管理办法"
        metadata = extract_policy_metadata(self.blocks(
            f"关于印发《{title}》的通知", "一、请认真执行本办法。", title,
            "（2023年修订）", "第一条 正文。",
        ))
        self.assertEqual(metadata.get("version"), "2023年修订")

    def test_reporting_instruction_is_not_a_signature_date(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院管理办法", "第一条 材料应按以下示例填写：",
            "报送武汉大学计算机学院", "2023年12月21日", "第二条 按流程办理。",
        ))
        self.assertNotIn("issue_date", metadata)

    def test_notice_signature_date_wins_over_meeting_approval_date(self):
        metadata = extract_policy_metadata(self.blocks(
            "关于印发《计算机学院教师岗位年度考核办法》的通知",
            "武大计字〔2023〕14号",
            "本办法已经2023年11月2日教代会审议通过，现印发给你们。",
            "计算机学院", "2023年12月21日",
            "一、考核内容", "本办法自2024年1月1日起实施。",
        ))
        self.assertEqual(metadata.get("issue_date"), "2023-12-21")

    def test_approval_date_alone_is_not_publication_date(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院教师岗位年度考核办法",
            "本办法已经2023年11月2日教代会审议通过。",
            "第一条 本办法自2024年1月1日起实施。",
        ))
        self.assertNotIn("issue_date", metadata)

    def test_explicit_publication_date_takes_priority_over_other_header_dates(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院教师岗位年度考核办法",
            "本办法于2023年11月2日审议通过。", "发布日期：2023年12月21日",
            "2023年12月22日", "第一条 正文。", "2024年1月",
        ))
        self.assertEqual(metadata.get("issue_date"), "2023-12-21")

    def test_joined_signature_and_date_are_recognized(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院教师岗位年度考核办法", "2023年11月2日审议通过。",
            "计算机学院2023年12月21日", "第一条 正文。",
        ))
        self.assertEqual(metadata.get("issue_date"), "2023-12-21")

    def test_dates_after_numbered_body_start_are_not_publication_dates(self):
        metadata = extract_policy_metadata(self.blocks(
            "计算机学院教师岗位年度考核办法", "一、考核内容",
            "发布日期：2020年1月1日", "2024年1月1日", "二、考核要求",
        ))
        self.assertNotIn("issue_date", metadata)

    def test_mhtml_notice_can_fill_missing_date_from_signature(self):
        blocks = self.blocks("本办法已经2023年11月2日审议通过。", "计算机学院", "2023年12月21日", "第一条 正文。")
        blocks[0].raw = {"source_format": "mhtml", "source_metadata": {"title": "计算机学院教师岗位年度考核办法"}}
        self.assertEqual(extract_policy_metadata(blocks).get("issue_date"), "2023-12-21")

    def test_mhtml_explicit_source_date_is_preserved(self):
        blocks = self.blocks("计算机学院", "2023年12月22日", "第一条 正文。")
        blocks[0].raw = {"source_format": "mhtml", "source_metadata": {"issue_date": "2023-12-21"}}
        self.assertEqual(extract_policy_metadata(blocks).get("issue_date"), "2023-12-21")

    def test_invalid_or_conflicting_publication_dates_remain_unknown(self):
        for dates in (("2023年2月30日",), ("2023年12月21日", "2023年12月22日")):
            with self.subTest(dates=dates):
                metadata = extract_policy_metadata(self.blocks("计算机学院教师岗位年度考核办法", *dates, "第一条 正文。"))
                self.assertNotIn("issue_date", metadata)

    def test_notice_with_attached_policy_uses_body_title(self):
        blocks = self.blocks("关于修订印发", "《武汉大学学术委员会章程》的通知", "全校各单位：",
                             "现将修订后的章程印发，请遵照执行。", "武 汉 大 学", "2026年8月1日",
                             "武汉大学学术委员会章程", "第一章 总则", "第一条 正文",
                             "第三十条 原《旧章程》（武大发字〔2020〕1号）同时废止。")
        meta = extract_policy_metadata(blocks)
        self.assertEqual(meta['title'], '武汉大学学术委员会章程')
        self.assertEqual(meta['notice_title'], '关于修订印发《武汉大学学术委员会章程》的通知')
        self.assertEqual(meta['issue_date'], '2026-08-01')
        self.assertNotIn('doc_number', meta)

    def test_quoted_reference_without_body_heading_is_not_source_title(self):
        meta = extract_policy_metadata(self.blocks("关于执行《旧办法》的通知", "按照《旧办法》办理。"))
        self.assertEqual(meta.get('title'), '关于执行《旧办法》的通知')

    def test_split_body_title_is_confirmed_by_notice(self):
        for parts in [("武汉大学中层领导班子和领导干部", "考核工作办法"),
                      ("武汉大学中层领导班子", "和领导干部", "考核工作办法")]:
            with self.subTest(parts=parts):
                meta = extract_policy_metadata(self.blocks(
                    "关于印发《武汉大学中层领导班子和领导干部考核工作办法》的通知",
                    "全校各单位：", "现印发给你们，请认真执行。", "2026年8月3日",
                    *parts, "第一章 总则", "第一条 正文"))
                self.assertEqual(meta['title'], '武汉大学中层领导班子和领导干部考核工作办法')

    def test_notice_title_does_not_replace_different_body_title(self):
        meta = extract_policy_metadata(self.blocks("关于印发《武汉大学旧管理办法》的通知",
            "武汉大学新管理办法", "第一章 总则", "第一条 正文"))
        self.assertEqual(meta['title'], '武汉大学新管理办法')

    def test_mhtml_notice_with_preamble_and_numbered_policy(self):
        title = '武汉大学关于促进毕业生高质量充分就业的实施意见'
        notice = f'关于印发《{title}》的通知'
        blocks = self.blocks('全校各单位：', f'学校制定了《{title}》，现印发给你们。',
            '武汉大学', '2026年6月24日', title, '就业是民生之本。现提出如下意见。',
            '一、总体要求和目标', '正文', '二、优化培养供给')
        blocks[0].raw = {'source_format': 'mhtml', 'source_metadata': {
            'title': notice, 'issuer': '学生就业指导与服务中心', 'doc_number': '武大毕字〔2026〕4号'}}
        meta = extract_policy_metadata(blocks)
        self.assertEqual(meta['title'], title)
        self.assertEqual(meta['notice_title'], notice)
        self.assertEqual(meta['doc_number'], '武大毕字〔2026〕4号')
        self.assertEqual(meta['issuer'], '学生就业指导与服务中心')

    def test_mhtml_notice_with_only_quoted_policy_keeps_notice_title(self):
        notice = '关于印发《武汉大学管理办法》的通知'
        blocks = self.blocks('现将《武汉大学管理办法》印发给你们，请认真执行。')
        blocks[0].raw = {'source_format': 'mhtml', 'source_metadata': {'title': notice}}
        self.assertEqual(extract_policy_metadata(blocks)['title'], notice)

    def test_mhtml_source_title_removes_all_whitespace(self):
        blocks = self.blocks('第一条 正文')
        blocks[0].raw = {'source_format': 'mhtml', 'source_metadata': {
            'title': '武汉大学教职工代表大会提案工作规则 \t（修订）'}}
        self.assertEqual(extract_policy_metadata(blocks)['title'],
                         '武汉大学教职工代表大会提案工作规则（修订）')

    def test_notice_with_multiple_policies_does_not_pick_one(self):
        meta = extract_policy_metadata(self.blocks("关于印发两项办法的通知", "武汉大学甲办法",
                                                  "第一条 甲正文", "武汉大学乙办法", "第一条 乙正文"))
        self.assertEqual(meta.get('title'), '关于印发两项办法的通知')

    def test_confirmed_multiple_policies_have_individual_metadata(self):
        notice = '关于印发《武汉大学甲办法》和《武汉大学乙办法》的通知'
        blocks = self.blocks(notice, '武大字〔2026〕1号', '武汉大学甲办法',
                             '第一条 甲正文', '武汉大学乙办法', '第一条 乙正文')
        meta = extract_policy_metadata(blocks)
        self.assertNotIn('title', meta)
        self.assertEqual(meta['notice_title'], notice)
        self.assertEqual([p['title'] for p in meta['policies']], ['武汉大学甲办法', '武汉大学乙办法'])
        self.assertTrue(all(p['doc_number'] == '武大字〔2026〕1号' for p in meta['policies']))

    def test_five_policy_notice_can_span_more_than_three_lines(self):
        titles = ['武汉大学'+name+'管理办法' for name in ['甲','乙','丙','丁','戊']]
        header = ['关于印发《'+titles[0]+'》'] + ['《'+t+'》' for t in titles[1:]] + ['的通知']
        body = [part for title in titles for part in [title,'一、管理职责']]
        meta = extract_policy_metadata(self.blocks(*(header+body)))
        self.assertEqual([p['title'] for p in meta['policies']],titles)

    def test_standalone_policy_title_and_header_date_only(self):
        meta = extract_policy_metadata(self.blocks("武汉大学管理办法", "第一条 依据2020年1月1日发布的规定制定。"))
        self.assertEqual(meta.get('title'), '武汉大学管理办法')
        self.assertNotIn('issue_date', meta)

    def test_chapter_names_are_not_additional_policy_titles(self):
        meta = extract_policy_metadata(self.blocks("关于印发章程的通知", "武汉大学学术委员会章程",
            "第一章 总则", "第一条 正文", "第二章 组成规则", "第二条 正文",
            "第四章 运行制度", "第三条 正文"))
        self.assertEqual(meta['title'], '武汉大学学术委员会章程')

    def test_mhtml_source_number_accepts_black_lenticular_brackets(self) -> None:
        blocks = [ContentBlock(type=BlockType.TEXT, content="正文", raw={
            "source_format": "mhtml", "source_metadata": {"doc_number": "武大字【 2006 】 17号"},
        })]
        self.assertEqual(extract_policy_metadata(blocks)["doc_number"], "武大字〔2006〕17号")

    def test_mhtml_source_number_uses_standard_brackets_and_no_spaces(self) -> None:
        blocks = [ContentBlock(
            type=BlockType.TEXT, content="正文",
            raw={"source_format": "mhtml", "source_metadata": {
                "title": "本科人才培养方案", "doc_number": "武大本字[ 2024 ] 41 号",
            }},
        )]
        metadata = extract_policy_metadata(blocks)
        self.assertEqual(metadata["doc_number"], "武大本字〔2024〕41号")
        self.assertEqual(metadata["title"], "本科人才培养方案")

    def test_header_number_accepts_fullwidth_square_brackets(self) -> None:
        blocks = [ContentBlock(type=BlockType.TEXT, page_num=0,
                               content="武大本字［ 2024 ］ 41 号\n关于培养质量的通知")]
        self.assertEqual(extract_policy_metadata(blocks)["doc_number"], "武大本字〔2024〕41号")

    def test_keeps_complete_five_character_issuer_prefix(self) -> None:
        blocks = [ContentBlock(
            type=BlockType.TEXT, page_num=0,
            content="武大学工字〔2026〕11 号\n关于修订印发办法的通知\n依据财教〔2024〕188号文件制定。",
        )]

        metadata = extract_policy_metadata(blocks)

        self.assertEqual(metadata["doc_number"], "武大学工字〔2026〕11号")

    def test_accepts_bracketed_document_number_without_word_zi(self) -> None:
        blocks = [ContentBlock(type=BlockType.TEXT, page_num=0, content="财教〔2024〕188号")]

        self.assertEqual(extract_policy_metadata(blocks)["doc_number"], "财教〔2024〕188号")


if __name__ == "__main__":
    unittest.main()
