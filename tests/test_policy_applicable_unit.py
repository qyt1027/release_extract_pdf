"""制度适用单位的提取、持久化和检索回归测试。"""
from __future__ import annotations

import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.models import BlockType, ContentBlock, PolicyDocument
from metadata.policy import extract_policy_metadata
from policy.document_parts import split_policy_document


def text_blocks(*lines: str) -> list[ContentBlock]:
    return [ContentBlock(type=BlockType.TEXT, content=line, page_num=index)
            for index, line in enumerate(lines)]


class ApplicableUnitExtractionTests(unittest.TestCase):
    def test_electrical_college_source_title_variant_preserves_title_and_resolves_scope(self):
        title = '电气与自动学院兼职教授聘任管理办法'
        file_name = title + '.docx'
        blocks = text_blocks(title, '通讯地址：中国湖北省武汉市武昌珞珈山',
                             '邮政编码：430072', '联系电话：027-68772279',
                             '学院邮箱：wddqxy@whu.edu.cn')
        for source_path in ('', 'D:/采集结果/电气与自动化学院/' + file_name):
            with self.subTest(source_path=source_path):
                metadata = extract_policy_metadata(blocks, file_name, source_path=source_path)
                self.assertEqual(metadata['title'], title)
                self.assertEqual(metadata['applicable_unit'], ['电气与自动化学院'])
                self.assertEqual(metadata['applicable_unit_paths'], ['电气与自动化学院'])
                parts = split_policy_document(blocks, metadata, file_name, source_path=source_path)
                self.assertEqual(parts[0]['metadata']['title'], title)
                self.assertEqual(parts[0]['metadata']['applicable_unit'], ['电气与自动化学院'])
                self.assertEqual(parts[0]['metadata']['applicable_unit_paths'], ['电气与自动化学院'])

    def test_folder_college_requires_confirmation_for_unresolved_local_scope(self):
        from policy.document_parts import confirm_folder_applicable_units

        cases = (
            ('本办法仅适用于本院师生。', '计算机学院', True, ['计算机学院']),
            ('本办法仅适用于本院。', '计算机学院', True, ['计算机学院']),
            ('本办法适用于学院教职工。', '计算机学院', True, ['计算机学院']),
            ('本办法仅适用于本院师生。', '计算机学院', False, []),
            ('本办法仅适用于本院师生。', '未知学院', None, []),
            ('本办法仅适用于本院师生。', '计院', None, []),
            ('本办法仅适用于本院师生。', '前沿交叉学科研究院', None, []),
            ('应按规定办理。', '计算机学院', None, []),
            ('本办法适用于由学院面向全日制学生开设的所有课程。', '计算机学院', None, []),
            ('本办法适用于数学与统计学院。', '计算机学院', None, ['数学与统计学院']),
            ('本办法适用于全校各单位。', '计算机学院', None, ['全校']),
            ('本办法适用于未知学院。', '计算机学院', None, []),
            ('本办法适用于本院师生。\n适用范围：哲学学院。\n适用范围：文学院。', '计算机学院', None, []),
        )
        for body, folder, decision, expected in cases:
            with self.subTest(body=body, folder=folder, decision=decision):
                title = '教学管理办法'
                path = f'D:/采集结果/{folder}/{title}.docx'
                blocks = text_blocks(title, f'第一条 {body}')
                meta = extract_policy_metadata(blocks, title + '.docx', source_path=path)
                parts = split_policy_document(blocks, meta, title + '.docx', source_path=path)
                with patch('builtins.input', side_effect=AssertionError('提取过程不应直接读取终端')):
                    calls = []

                    def confirm(file_path, policy_title, college):
                        calls.append((file_path, policy_title, college))
                        return decision

                    confirm_folder_applicable_units(parts, path, confirm)
                self.assertEqual(calls, [] if decision is None else [(path, title, folder)])
                self.assertEqual(parts[0]['metadata']['applicable_unit'], expected)
                self.assertEqual(parts[0]['metadata']['applicable_unit_paths'], expected)

    def test_folder_college_confirmation_uses_local_adoption_and_governance(self):
        from policy.document_parts import confirm_folder_applicable_units

        title = '学院教师延、返聘暂行办法'
        adoption = '第一条 根据《武汉大学教职工离退休暂行办法》文件精神，结合我院实际情况，特制定本办法。'
        explanation = '第九条 本办法由院党政联席会议负责解释。'
        cases = (
            (title, adoption, True),
            (title, explanation, True),
            ('学院教职工年终劳酬分配办法', '坐班人员的奖励分配由院党政联席会议决定。', True),
            ('学院公车使用管理规定', '结合学院实际，特制定如下公车使用管理规定。', True),
            (title, '评审材料引述：“结合我院实际情况，特制定本办法。”', False),
            (title, '各学院结合本院实际制定实施办法。', False),
            (title, adoption + '\n适用范围：全校各单位。', False),
            ('学校教师延、返聘暂行办法', '奖励分配由院党政联席会议决定。', False),
        )
        for policy_title, body, should_ask in cases:
            with self.subTest(title=policy_title, body=body):
                file_name = policy_title + '.docx'
                path = 'D:/采集结果/信息管理学院/' + file_name
                blocks = text_blocks(policy_title, body)
                metadata = extract_policy_metadata(blocks, file_name, source_path=path)
                parts = split_policy_document(blocks, metadata, file_name, source_path=path)
                calls = []
                confirm_folder_applicable_units(parts, path, lambda *args: calls.append(args) or True)
                self.assertEqual(calls, [(path, policy_title, '信息管理学院')] if should_ask else [])
                if should_ask:
                    self.assertEqual(metadata['applicable_unit'], [])
                    self.assertEqual(parts[0]['metadata']['applicable_unit'], ['信息管理学院'])

    def test_numbered_attachments_use_original_title_and_specific_institution_scope(self):
        from classification.document import classify_document
        from metadata import extract_document_metadata

        subject = "2026年度“研究生学术创新奖”评选细则"
        cases = (
            ("中国传统文化研究中心", "中国传统文化研究中心", ["中国传统文化研究中心"]),
            ("中国边界与海洋研究院、国际问题研究院", "中国边界与海洋研究院及国际问题研究院",
             ["中国边界与海洋研究院", "国际问题研究院"]),
            ("高等研究院", "高等研究院", ["武汉大学高等研究院"]),
            ("新型电力系统与国际标准研究院", "新标院", ["新型电力系统与国际标准研究院"]),
            ("武汉大学前沿交叉学科研究院心理学系", "心理学系", ["前沿交叉学科研究院心理学系"]),
        )
        for index, (heading, file_unit, units) in enumerate(cases, start=1):
            with self.subTest(heading=heading):
                lines = ("附件一：", heading, subject, "结合本单位实际，制定本细则。", "一、评选对象",
                         "前沿交叉学科研究院统筹评审，各单位分别组织申报。")
                blocks = text_blocks(*lines)
                filename = f"{index}-{file_unit}2026年研究生学术创新奖评选细则.docx"
                path = f"D:/采集结果/前沿交叉学科研究院/{filename}"
                result = classify_document(path, filename, parsed_text="\n".join(lines))
                self.assertEqual(result["doc_type"], "policy_regulation")
                metadata = extract_document_metadata(blocks, result["doc_type"], filename, source_path=path)
                self.assertEqual(metadata["title"], heading + subject)
                self.assertEqual(metadata["applicable_unit"], units)
                self.assertEqual(metadata["applicable_unit_paths"], [
                    "前沿交叉学科研究院-" + unit.removeprefix("前沿交叉学科研究院") for unit in units
                ])

    def test_ambiguous_institute_short_name_is_resolved_only_with_context(self):
        from metadata.policy_scope import infer_applicable_unit

        title = "高等研究院评选细则"
        self.assertEqual(infer_applicable_unit(title), [])
        self.assertEqual(infer_applicable_unit(title, source_unit="任意学院"), [])
        self.assertEqual(infer_applicable_unit(title, source_unit="前沿交叉学科研究院"), ["武汉大学高等研究院"])

    def test_program_specific_international_student_policy_uses_corroborated_source_college(self):
        from metadata import extract_document_metadata

        title = "武汉大学网络空间安全留学生管理制度"
        blocks = text_blocks(
            title, "培养德、智、体全面发展的网络空间安全领域的国际人才。",
            "在培养方案设置上，除了网络空间安全专业课程外，还开设汉语综合等公共必修课程。",
            "学院还通过开展校园文化活动促进交流。",
        )
        for folder, expected in (
            ("国家网络安全学院", ["国家网络安全学院"]), ("计算机学院", []), ("下载", []),
        ):
            with self.subTest(folder=folder):
                metadata = extract_document_metadata(
                    blocks, "policy_regulation", title + ".docx",
                    source_path=f"D:/采集结果/{folder}/{title}.docx",
                )
                self.assertEqual(metadata["applicable_unit"], expected)

    def test_college_folder_does_not_override_university_wide_policy(self):
        from metadata import extract_document_metadata

        title = "武汉大学关于研究生导师第一责任人制度的实施意见"
        meta = extract_document_metadata(
            text_blocks(title, "各培养单位负责落实。"), "policy_regulation", title + ".docx",
            source_path=f"D:/采集结果/国家网络安全学院/{title}.docx",
        )
        self.assertEqual(meta["applicable_unit"], ["全校"])

    def test_parking_garage_scope_uses_all_colleges_named_as_eligible(self):
        title = "振华楼地下车库管理制度"
        metadata = extract_policy_metadata(text_blocks(
            title, "文学院、历史学院和哲学学院共同成立管理委员会。",
            "1、振华楼地下车库开放对象为文学院、历史学院、哲学学院在职教职工。外来车辆未经许可，不得进出。",
            "武汉大学哲学学院", "2024年10月28日",
        ), title + ".docx")
        self.assertEqual(metadata.get("applicable_unit"), ["文学院", "历史学院", "哲学学院"])

    def test_university_title_without_college_is_school_wide(self):
        from metadata.policy_scope import infer_applicable_unit

        for title in (
            "武汉大学关于教授为本科生授课的规定",
            "武汉大学教师年度工作安排",
            "关于印发《武汉大学工作安排》的通知",
            "武大字〔2022〕60号 武汉大学教师管理规定.pdf",
        ):
            with self.subTest(title=title):
                self.assertEqual(infer_applicable_unit(title), ["全校"])

    def test_college_takes_priority_when_title_also_contains_university(self):
        from metadata.policy_scope import infer_applicable_unit

        for title, expected in (
            ("武汉大学计算机学院工作安排", "计算机学院"),
            ("关于印发《武汉大学文学院工作职责》的通知", "文学院"),
            ("武汉大学各学院工作安排", ""),
        ):
            with self.subTest(title=title):
                self.assertEqual(infer_applicable_unit(title), [expected] if expected else [])

    def test_title_college_does_not_require_policy_suffix_or_fixed_position(self):
        from metadata.policy_scope import infer_applicable_unit

        for title, expected in (
            ("计算机学院工作职责", "计算机学院"),
            ("计算机学院2026年度工作安排", "计算机学院"),
            ("2026-11-02_计算机学院实验室开放时间", "计算机学院"),
            ("附件2：武汉大学文学院工作分工", "文学院"),
            ("关于加强计算机学院实验室安全检查", "计算机学院"),
            ("关于印发《武汉大学数学与统计学院工作分工》的通知", "数学与统计学院"),
        ):
            with self.subTest(title=title):
                self.assertEqual(infer_applicable_unit(title), [expected] if expected else [])

    def test_nonstandard_first_title_and_filename_can_supply_college(self):
        for file_name in ("", "计算机学院工作职责.pdf"):
            with self.subTest(file_name=file_name):
                metadata = extract_policy_metadata(text_blocks("计算机学院工作职责", "第一条 应按流程办理。"), file_name)
                self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_year_in_policy_title_is_kept_out_of_applicable_unit(self):
        title = "2018年哲学学院党委理论学习中心组学习计划"
        metadata = extract_policy_metadata(text_blocks(
            title, "哲院党字[2018]7号", "一、指导思想和主要任务", "结合学院工作实际制定本计划。",
        ), title + ".docx")
        self.assertEqual(metadata.get("title"), title)
        self.assertEqual(metadata.get("applicable_unit"), ["哲学学院"])

    def test_year_prefix_keeps_unit_boundaries_in_other_titles(self):
        from metadata.policy_scope import infer_applicable_unit

        for title, expected in (
            ("关于2025年度哲学学院工作安排的通知", "哲学学院"),
            ("2025年度星光学院工作安排", ""),
            ("关于2025年度哲学学院和数学学院的工作安排", ""),
        ):
            with self.subTest(title=title):
                self.assertEqual(infer_applicable_unit(title), [expected] if expected else [])

    def test_loose_title_matching_still_ignores_generic_colleges(self):
        from metadata.policy_scope import infer_applicable_unit

        for title in ("各学院工作职责", "本学院工作安排", "有关学院工作分工"):
            with self.subTest(title=title):
                self.assertEqual(infer_applicable_unit(title), [])

    def test_policy_titles_keep_distinct_college_names(self):
        for title, unit in (
            ("关于计算机学院印章使用与管理的规定", "计算机学院"),
            ("武汉大学数学与统计学院设备管理办法", "数学与统计学院"),
            ("外国语言文学学院会议管理细则", "外国语言文学学院"),
            ("文学院设备管理办法", "文学院"),
        ):
            with self.subTest(title=title):
                metadata = extract_policy_metadata(text_blocks(title, "第一条 应按流程办理。"))
                self.assertEqual(metadata.get("applicable_unit"), [unit])

    def test_filename_is_used_when_scanned_text_has_no_title(self):
        parts = split_policy_document(text_blocks("第一条 应按流程办理。"), {},
                                      "关于计算机学院印章使用与管理的规定.pdf")
        self.assertEqual(parts[0]["metadata"].get("applicable_unit"), ["计算机学院"])

    def test_leading_document_numbers_do_not_hide_college_in_filename(self):
        from metadata.policy_scope import infer_applicable_unit

        for prefix in ("2021计字22号 ", "武大计字〔2021〕22号 ", "武大计字[2021]22号 "):
            with self.subTest(prefix=prefix):
                title = prefix + "武汉大学计算机学院疫情常态化下实验室使用管理办法"
                self.assertEqual(infer_applicable_unit(title), ["计算机学院"])

    def test_scanned_policy_uses_clean_filename_for_missing_title_and_unit(self):
        title = "武汉大学计算机学院疫情常态化下实验室使用管理办法"
        metadata = extract_policy_metadata(text_blocks("武大计字〔2021〕22号", "一、实验室管理要求"),
                                           "2021计字22号 " + title + ".pdf")

        self.assertEqual(metadata.get("title"), title)
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])
        self.assertEqual(metadata.get("doc_number"), "武大计字〔2021〕22号")

    def test_filename_fallback_does_not_replace_confirmed_body_title(self):
        metadata = extract_policy_metadata(text_blocks("数学与统计学院设备管理规定", "第一条 应按流程办理。"),
                                           "2021计字22号 计算机学院设备管理规定.pdf")
        self.assertEqual(metadata.get("title"), "数学与统计学院设备管理规定")
        self.assertEqual(metadata.get("applicable_unit"), ["数学与统计学院"])

    def test_explicit_school_wide_scope_takes_priority_over_title_and_issuer(self):
        metadata = extract_policy_metadata(text_blocks(
            "计算机学院设备管理规定", "发布机构：计算机学院",
            "第一条 本规定适用于全校各单位。",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["全校"])
        self.assertEqual(metadata.get("issuer"), "计算机学院")

    def test_explicit_college_scope_takes_priority_over_university_in_title(self):
        metadata = extract_policy_metadata(text_blocks(
            "武汉大学实验室管理规定", "第一条 本规定仅适用于武汉大学计算机学院。",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_explicit_college_scope_fills_title_without_institution(self):
        metadata = extract_policy_metadata(text_blocks(
            "实验室管理规定", "第一条 本规定仅适用于武汉大学计算机学院。",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_college_funding_for_its_own_teachers_uses_dated_signature(self):
        title = "关于学院资助教师参加国际国内学术会议的暂行规定"
        metadata = extract_policy_metadata(text_blocks(
            title, "一、学院鼓励本院教师进行学术交流，资助教师参加国际学术会议。",
            "本规定由科研外事办公室负责解释。", "武汉大学哲学学院", "2013年11月15日",
        ), title + ".docx")
        self.assertEqual(metadata.get("applicable_unit"), ["哲学学院"])

    def test_college_audience_and_policy_adoption_resolve_dated_signature(self):
        title = '关于鼓励教师开设全英文课程的办法'
        signature = ('信息管理学院', '二〇一三年三月')
        preamble = '为推进学院国际化战略，鼓励全院教师为本科生与硕士生开设全英文课程，特制订本办法。'
        for opening, closing, expected in (
            (preamble, signature, ['信息管理学院']),
            ('为明确本院师生的职责与分工，现制定本办法。', signature, ['信息管理学院']),
            ('特制定本办法。\n院内教师可申请参加教学改革。', signature, ['信息管理学院']),
            (preamble, (), []),
            ('调研材料称：“' + preamble + '”', signature, ['信息管理学院']),
            ('为鼓励教师开设全英文课程，特制定本办法。', signature, ['信息管理学院']),
            (preamble + '\n适用范围：全校各单位。', signature, ['全校']),
        ):
            with self.subTest(opening=opening, closing=closing):
                metadata = extract_policy_metadata(text_blocks(
                    title, opening, '第一条 全英文授课指用英语讲授专业课程。', *closing,
                ), title + '.docx')
                self.assertEqual(metadata['applicable_unit'], expected)
                self.assertEqual(metadata['applicable_unit_paths'], expected)

    def test_relative_scope_uses_college_signature_with_or_without_date(self):
        from metadata.policy_scope import infer_applicable_unit

        for body, expected in (
            ("第一条 本规定仅适用于本院教师。\n武汉大学哲学学院\n2013年11月15日", "哲学学院"),
            ("第一条 本规定适用于数学与统计学院。\n武汉大学哲学学院\n2013年11月15日", "数学与统计学院"),
            ("第一条 本规定适用于本院教师和数学学院。\n武汉大学哲学学院\n2013年11月15日", ""),
            ("一、学院鼓励本院教师和外院教师参加会议。\n武汉大学哲学学院\n2013年11月15日", "哲学学院"),
            ("第一条 本规定仅适用于本院教师。\n抄送武汉大学哲学学院\n2013年11月15日", ""),
            ("第一条 本规定仅适用于本院教师。\n武汉大学哲学学院", "哲学学院"),
            ("第一条 应当按流程办理。\n武汉大学哲学学院\n2013年11月15日", "哲学学院"),
        ):
            with self.subTest(body=body):
                self.assertEqual(infer_applicable_unit("学术会议资助规定", body), [expected] if expected else [])

    def test_school_wide_recipients_fill_printing_notice_scope(self):
        title = "关于进一步加强印刷费管理的通知"
        metadata = extract_policy_metadata(text_blocks(
            f"武大财字〔2023〕35 号\n{title}\n全校各部门、单位：\n"
            "为进一步规范印刷费使用和管理，现将有关事宜通知如下。\n"
            "一、适用范围。本通知适用于各类经费中印刷费的使用和管理。",
        ), f"{title}（武大财字〔2023〕35号）.pdf")
        self.assertEqual(metadata.get("title"), title)
        self.assertEqual(metadata.get("applicable_unit"), ["全校"])

    def test_body_scope_takes_priority_over_school_wide_recipients(self):
        from metadata.policy_scope import infer_applicable_unit

        for scope, expected in (
            ("计算机学院", ["计算机学院"]),
            ("计算机学院和数学与统计学院", ["计算机学院", "数学与统计学院"]),
            ("各学院", []),
        ):
            with self.subTest(scope=scope):
                text = f"全校各部门、单位：\n第一条 本办法仅适用于{scope}。"
                self.assertEqual(infer_applicable_unit("设备管理办法", text), expected)

    def test_school_wide_recipient_signal_is_limited_to_the_header(self):
        from metadata.policy_scope import infer_applicable_unit

        for text in (
            "各有关部门、单位：\n第一条 应按流程办理。",
            "第一条 应按流程办理。\n全校各部门、单位：",
            "抄送：全校各部门、单位。\n第一条 应按流程办理。",
            "旧通知写明：“全校各部门、单位：”\n第一条 应按流程办理。",
        ):
            with self.subTest(text=text):
                self.assertEqual(infer_applicable_unit("设备管理办法", text), [])

    def test_salary_policy_resolves_college_staff_scope_from_title(self):
        metadata = extract_policy_metadata(text_blocks(
            "关于印发《计算机学院薪酬分配办法》的通知",
            "计算机学院薪酬分配办法",
            "第三条 本办法适用于学院在编在岗人员，其中由学校全额承担薪酬的人员，按照学校相关规定执行。"
            "学院合同聘用制人员、外聘兼职人员薪酬依据与学校、学院签订的合同执行。",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_institution_standard_gets_policy_metadata_after_classification(self):
        from classification.document import classify_document
        from metadata import extract_document_metadata

        title = "计算机学院研究生党总支关于党员民主评议合格的标准（试行）"
        blocks = text_blocks(title, "结合学院工作实际，具体标准如下：", "一、思想觉悟", "应当遵守党的纪律。")
        classification = classify_document("missing.docx", title + ".docx",
                                           parsed_text="\n".join(block.content for block in blocks))
        metadata = extract_document_metadata(blocks, classification["doc_type"], title + ".docx")

        self.assertEqual(metadata.get("title"), title)
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_relative_college_scopes_resolve_only_with_specific_college_title(self):
        for scope in ("本学院全体教师", "本院的学生", "我院教职工", "学院在编在岗人员"):
            for title, expected in (("计算机学院设备管理规定", "计算机学院"),
                                    ("设备管理规定", ""), ("全校设备管理规定", "全校")):
                with self.subTest(scope=scope, title=title):
                    metadata = extract_policy_metadata(text_blocks(title, f"第一条 本规定适用于{scope}。"))
                    self.assertEqual(metadata.get("applicable_unit"), [expected] if expected else [])

    def test_relative_scope_without_named_title_does_not_guess_a_college(self):
        for body in (
            "第一条 本规定适用于学院和数学学院。",
            "第一条 本规定适用于各学院。",
            "第一条 本规定适用于本学院。\n第二条 本规定适用于数学学院。",
        ):
            with self.subTest(body=body):
                metadata = extract_policy_metadata(text_blocks("设备管理规定", body))
                self.assertEqual(metadata.get("applicable_unit"), [])

    def test_multiline_and_alternative_scope_statements_fill_unknown_title_unit(self):
        for body in ("第一条 本规定适用于\n计算机学院。", "第一条 本规定的适用范围为计算机学院。"):
            with self.subTest(body=body):
                metadata = extract_policy_metadata(text_blocks("设备管理规定", body))
                self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_preamble_responsibility_statement_is_not_a_title(self):
        blocks = text_blocks("设备管理规定", "计算机学院负责解释本办法", "办理时应核对身份。")
        blocks[0].raw = {"source_format": "mhtml", "source_metadata": {"title": "设备管理规定"}}
        self.assertEqual(extract_policy_metadata(blocks).get("applicable_unit"), [])

    def test_quoted_scope_of_another_policy_does_not_override_current_title(self):
        metadata = extract_policy_metadata(text_blocks(
            "数学与统计学院设备管理规定", "第一条 旧办法规定：“本办法适用于全校各单位。”",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["数学与统计学院"])

    def test_quoted_unit_name_fills_unknown_title_unit(self):
        metadata = extract_policy_metadata(text_blocks(
            "设备管理规定", "第一条 本规定适用于“计算机学院”。",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])

    def test_scope_field_does_not_consume_following_issuer_field(self):
        metadata = extract_policy_metadata(text_blocks(
            "设备管理规定", "适用范围：全校各单位\n发布机构：计算机学院、数学学院\n第一条 应按流程办理。",
        ))
        self.assertEqual(metadata.get("applicable_unit"), ["全校"])

    def test_college_mention_or_issuer_does_not_define_scope(self):
        for body in (
            "第二条 计算机学院负责提供技术支持。",
            "第二条 本规定不适用于计算机学院。",
            "第二条 依据《计算机学院设备管理办法》办理。",
            "发布机构：计算机学院",
        ):
            with self.subTest(body=body):
                metadata = extract_policy_metadata(text_blocks("设备管理规定", body))
                self.assertEqual(metadata.get("applicable_unit"), [])

    def test_unknown_and_generic_college_names_remain_empty(self):
        for title in ("设备管理规定", "各学院设备管理规定", "学院设备管理规定"):
            with self.subTest(title=title):
                metadata = extract_policy_metadata(text_blocks(title, "第一条 应按流程办理。"))
                self.assertEqual(metadata.get("applicable_unit"), [])

    def test_explicit_college_list_and_conflicting_scopes(self):
        for body, expected in (
            ("第一条 本规定适用于计算机学院和数学与统计学院。", ["计算机学院", "数学与统计学院"]),
            ("第一条 本规定适用于计算机学院。\n第二条 本规定适用于数学学院。", []),
        ):
            with self.subTest(body=body):
                metadata = extract_policy_metadata(text_blocks("设备管理规定", body))
                self.assertEqual(metadata.get("applicable_unit"), expected)

    def test_unregistered_or_relative_scope_is_empty_without_independent_evidence(self):
        title = '本科课程考核规定'
        for scope in ('由学院面向全日制学生开设的所有课程', '星光学院',
                      '计算机学院和星光学院', '全校部分学院'):
            with self.subTest(scope=scope):
                metadata = extract_policy_metadata(
                    text_blocks(title, f'第一条 本规定适用于{scope}。'),
                    title + '.docx', source_path='D:/采集结果/水利水电学院/' + title + '.docx',
                )
                self.assertEqual(metadata['applicable_unit'], [])
                self.assertEqual(metadata['applicable_unit_paths'], [])

    def test_college_local_scope_is_resolved_by_a_chinese_date_signature(self):
        metadata = extract_policy_metadata(text_blocks(
            '科研经费管理补充规定',
            '第九条 本办法适用学院在岗教职工，其他人员参照执行。',
            '武汉大学水利水电学院', '二〇一三年九月六日',
        ))
        self.assertEqual(metadata['applicable_unit'], ['水利水电学院'])
        self.assertEqual(metadata['applicable_unit_paths'], ['水利水电学院'])

    def test_college_operations_and_month_precision_signature_confirm_local_scope(self):
        metadata = extract_policy_metadata(text_blocks(
            '学位论文答辩规定',
            '一、应将论文交院研究生工作室检测。',
            '二、答辩由学院组织，结果由学院审核。',
            '武汉大学水利水电学院', '2011年7月',
        ))
        self.assertEqual(metadata['applicable_unit'], ['水利水电学院'])

    def test_college_retiree_measures_use_month_precision_signature(self):
        title = '学院关于进一步改进和加强离退休教职工工作的若干措施'
        preamble = '学院离退休教职工在学院发展中作出了贡献，为了使他们“老有所学”，经学院研究决定特制订本措施。'
        for opening, signature, expected in (
            (preamble, ('信息管理学院', '二OO六年十一月'), ['信息管理学院']),
            (preamble, ('信息管理学院', '二〇〇六年十一月'), ['信息管理学院']),
            (preamble, ('抄送信息管理学院', '二OO六年十一月'), []),
            ('第一条 应当按规定办理。', ('信息管理学院', '二OO六年十一月'), ['信息管理学院']),
            (preamble + '\n适用范围：全校各单位', ('信息管理学院', '二OO六年十一月'), ['全校']),
        ):
            with self.subTest(opening=opening, signature=signature):
                metadata = extract_policy_metadata(text_blocks(
                    title, opening, '第一条 加强组织领导。', *signature,
                ), title + '.docx', source_path='D:/采集结果/信息管理学院/' + title + '.docx')
                self.assertEqual(metadata['applicable_unit'], expected)
                self.assertEqual(metadata['applicable_unit_paths'], expected)
                self.assertNotIn('issue_date', metadata)

    def test_college_governance_and_signature_confirm_local_scope(self):
        title = '课程建设负责人实施办法'
        signature = ('武汉大学文学院', '二〇一四年六月十八日')
        for clauses, expected in (
            (('1．项目由教研室申报，学院组织专家评审确定。',
              '2．项目负责人由学院聘任。'), ['文学院']),
            (('1．教研室提交建设计划。', '2．项目负责人由学院聘任。'), ['文学院']),
            (('1．各学院组织专家评审确定。', '2．各学院聘任项目负责人。'), ['文学院']),
            (('旧规定写明：“由学院组织专家评审。”', '旧规定同时规定：“项目负责人由学院聘任。”'), ['文学院']),
            (('一、学院组织架构', '二、学院考核办法'), ['文学院']),
        ):
            with self.subTest(clauses=clauses):
                metadata = extract_policy_metadata(text_blocks(title, *clauses, *signature))
                self.assertEqual(metadata['applicable_unit'], expected)
                self.assertEqual(metadata['applicable_unit_paths'], expected)

    def test_named_local_policy_adoption_resolves_dated_college_signature(self):
        title = '关于延长部分专家退休年龄的暂行办法'
        opening = ('第一条 根据《武汉大学教职工离退休暂行办法》文件规定，'
                   '结合我院实际情况，特制定我院延长部分专家退休年龄的暂行办法。')
        for preamble, closing, expected in (
            (opening, ('武汉大学电子信息学院', '二○一二年八月三十日'), ['电子信息学院']),
            (opening.replace('办法。', '办\n法。'),
             ('武汉大学电子信息学院', '二○一二年八月三十日'), ['电子信息学院']),
            (opening, ('抄送武汉大学电子信息学院', '二○一二年八月三十日'), []),
            (opening, (), []),
            ('旧文件写明：“' + opening + '”',
             ('武汉大学电子信息学院', '二○一二年八月三十日'), ['电子信息学院']),
            (opening + '\n适用范围：全校各单位。',
             ('武汉大学电子信息学院', '二○一二年八月三十日'), ['全校']),
            (opening + '\n本办法适用于计算机学院。',
             ('武汉大学电子信息学院', '二○一二年八月三十日'), ['计算机学院']),
        ):
            with self.subTest(preamble=preamble, closing=closing):
                blocks = text_blocks('武汉大学电子信息学院', '武大电信 [2012]2号',
                                     title, preamble, '第二条 申请人需提交证明材料。', *closing)
                filename = '2012-2关于延长退休年龄的暂行办法.pdf'
                metadata = extract_policy_metadata(
                    blocks, filename, source_path='D:/采集结果/电子信息学院/' + filename,
                )
                self.assertEqual(metadata['applicable_unit'], expected)
                self.assertEqual(metadata['applicable_unit_paths'], expected)
                parts = split_policy_document(blocks, metadata, filename)
                self.assertEqual(parts[0]['metadata']['applicable_unit'], expected)

    def test_college_signature_defaults_scope_without_local_wording(self):
        title = '关于延长部分专家退休年龄的暂行办法'
        signatures = (
            ('武汉大学电子信息学院', '二○一二年八月三十日'),
            ('电子信息学院2012年8月30日',),
            ('武汉大学电子信息学院',),
            ('**武汉大学电子信息学院**', '2012年8月'),
            ('武汉大学', '电子信息学院', '2012年8月30日'),
            ('中共武汉大学电子信息学院委员会', '2012年8月30日'),
        )
        for header in ((), ('武汉大学电子信息学院', '武大电信〔2012〕2号')):
            for signature in signatures:
                with self.subTest(header=header, signature=signature):
                    blocks = text_blocks(*header, title, '第一条 申请人需提交证明材料。', *signature)
                    metadata = extract_policy_metadata(
                        blocks, title + '.pdf', source_path='D:/采集结果/计算机学院/' + title + '.pdf',
                    )
                    self.assertEqual(metadata['applicable_unit'], ['电子信息学院'])
                    self.assertEqual(metadata['applicable_unit_paths'], ['电子信息学院'])
                    parts = split_policy_document(blocks, metadata, title + '.pdf')
                    self.assertEqual(parts[0]['metadata']['applicable_unit'], ['电子信息学院'])

    def test_explicit_scope_and_title_take_priority_over_signature_default(self):
        from metadata.policy_scope import infer_applicable_unit

        for title, body, expected in (
            ('设备管理规定', '本规定适用于全校各单位。', ['全校']),
            ('设备管理规定', '本规定适用于计算机学院。', ['计算机学院']),
            ('设备管理规定', '本规定适用于计算机学院和电子信息学院。', ['计算机学院', '电子信息学院']),
            ('设备管理规定', '本规定适用于计算机学院和数学与统计学院。', ['计算机学院', '数学与统计学院']),
            ('设备管理规定', '适用范围：全校部分学院。', []),
            ('设备管理规定', '本规定适用于星光学院。', []),
            ('设备管理规定', '本规定适用于计算机学院。\n本规定适用于哲学学院。', []),
            ('武汉大学设备管理规定', '第一条 申请人需提交材料。', ['全校']),
            ('计算机学院设备管理规定', '第一条 申请人需提交材料。', ['计算机学院']),
            ('设备管理规定', '全校各部门、单位：\n第一条 申请人需提交材料。', ['全校']),
        ):
            with self.subTest(title=title, body=body):
                text = body + '\n武汉大学电子信息学院\n二○一二年八月三十日'
                self.assertEqual(infer_applicable_unit(title, text), expected)

    def test_college_signature_default_ignores_mentions_and_reporting_recipients(self):
        from metadata.policy_scope import infer_applicable_unit

        for closing in (
            '抄送武汉大学电子信息学院\n2012年8月30日',
            '报送武汉大学电子信息学院\n2012年8月30日',
            '发布机构：武汉大学电子信息学院',
            '电子信息学院负责审核。',
            '“武汉大学电子信息学院”\n2012年8月30日',
            '外省大学电子信息学院\n2012年8月30日',
            '武汉大学星光学院\n2012年8月30日',
        ):
            with self.subTest(closing=closing):
                self.assertEqual(infer_applicable_unit('设备管理规定',
                                 '第一条 申请人需提交材料。\n' + closing), [])
        # 题头或采集目录单独出现学院名称仍不能代替文末署名。
        self.assertEqual(infer_applicable_unit('设备管理规定',
                         '武汉大学电子信息学院\n设备管理规定\n第一条 申请人需提交材料。',
                         source_unit='电子信息学院'), [])

    def test_unrelated_university_mention_does_not_establish_school_scope(self):
        from metadata.policy_scope import infer_applicable_unit

        for title in ('大学生课程考核规定', '与其他大学合作的管理规定', '武汉大学星光学院工作安排',
                      '外省大学计算机学院工作安排'):
            with self.subTest(title=title):
                self.assertEqual(infer_applicable_unit(title), [])

    def test_explicit_scope_requires_the_registered_unit_not_a_namesake(self):
        from metadata.policy_scope import infer_applicable_unit

        for scope, expected in (
            ('外省大学计算机学院', []),
            ('由计算机学院面向学生开设的所有课程', ['计算机学院']),
        ):
            with self.subTest(scope=scope):
                self.assertEqual(infer_applicable_unit('课程考核规定', f'本规定适用于{scope}。'), expected)

    def test_preextracted_units_cannot_write_unregistered_scope(self):
        parts = split_policy_document(text_blocks('设备管理规定'), {'applicable_unit': ['由学院']}, '设备管理规定.docx')
        self.assertEqual(parts[0]['metadata']['applicable_unit'], [])

    def test_each_attachment_infers_its_own_unit(self):
        titles = ["计算机学院印章管理规定", "数学与统计学院印章管理规定"]
        notice = "关于印发" + "和".join("《" + title + "》" for title in titles) + "的通知"
        parts = split_policy_document(text_blocks(
            notice, titles[0], "第一条 应当审批。", titles[1], "第一条 应当登记。",
        ), {"notice_title": notice, "applicable_unit": ["计算机学院"]}, "notice.pdf")

        self.assertEqual([part["metadata"].get("applicable_unit") for part in parts],
                         [["计算机学院"], ["数学与统计学院"]])

    def test_mhtml_source_title_is_used(self):
        blocks = text_blocks("第一条 应当审批。")
        blocks[0].raw = {"source_format": "mhtml", "source_metadata": {
            "title": "关于计算机学院印章使用与管理的规定",
        }}
        self.assertEqual(extract_policy_metadata(blocks).get("applicable_unit"), ["计算机学院"])

    def test_document_model_preserves_applicable_unit(self):
        document = PolicyDocument(policy_id="p", file_id="f", applicable_unit=["计算机学院"])
        self.assertEqual(document.model_dump().get("applicable_unit"), ["计算机学院"])


class ApplicableUnitStorageTests(unittest.TestCase):
    def test_upsert_persists_and_replaces_unit_using_real_sql(self):
        from policy.storage import upsert_policy_document

        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.executescript('''
            CREATE TABLE policy_documents (
                policy_id TEXT PRIMARY KEY, file_id TEXT, file_name TEXT, title TEXT,
                notice_title TEXT, doc_number TEXT, doc_number_raw TEXT, issuing_department TEXT,
                issue_date TEXT, issue_month TEXT, effective_date TEXT, expiry_date TEXT, validity_status TEXT,
                version TEXT, original_pdf_url TEXT, parse_quality REAL, structure_status TEXT,
                structure_version TEXT, document_key TEXT, source_page_start INTEGER,
                source_page_end INTEGER, applicable_unit TEXT DEFAULT '', updated_at TEXT,
                UNIQUE(file_id, document_key));
            CREATE TABLE policy_review_items (policy_id TEXT, status TEXT, issue_type TEXT);
        ''')

        def execute(sql, params=()):
            db.execute(sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP"),
                       tuple(json.dumps(value) if isinstance(value, list) else value for value in params))

        with patch("policy.storage.ensure_policy_tables"), patch(
            "policy.storage.storage", SimpleNamespace(relational=SimpleNamespace(execute=execute)),
        ):
            for units, expected in (
                (["文学院", "历院", "哲学学院"], ["文学院", "历史学院", "哲学学院"]),
                (["全校"], ["全校"]), ([], []), (["外语学院"], ["外国语言文学学院"]),
            ):
                upsert_policy_document("f", "test.pdf", {"applicable_unit": units}, 1.0, "v1")
                self.assertEqual(json.loads(db.execute("SELECT applicable_unit FROM policy_documents").fetchone()[0]), expected)
            for dates, expected in (
                ({"issue_month": "2013-03"}, (None, "2013-03")),
                ({"issue_date": "2013-03-18"}, ("2013-03-18", None)),
                ({}, (None, None)),
            ):
                upsert_policy_document("f", "test.pdf", dates, 1.0, "v1")
                self.assertEqual(db.execute("SELECT issue_date, issue_month FROM policy_documents").fetchone(), expected)


class ApplicableUnitRetrievalTests(unittest.TestCase):
    def test_shared_policy_is_retrievable_under_each_eligible_college(self):
        from policy.retrieval import filter_candidates_by_applicable_unit

        shared = {"metadata": {"applicable_unit": ["文学院", "历史学院", "哲学学院"]}}
        school = {"metadata": {"applicable_unit": ["全校"]}}
        unknown = {"metadata": {"applicable_unit": []}}
        rows = [shared, school, unknown]
        for unit in ("文学院", "历史学院", "哲学学院"):
            self.assertEqual(filter_candidates_by_applicable_unit(unit + "车库怎么申请", rows), [shared, school])
        self.assertEqual(filter_candidates_by_applicable_unit("计算机学院车库怎么申请", rows), [school])

    def setUp(self):
        import policy.retrieval as retrieval
        retrieval.invalidate_policy_clause_bm25_index()
        self.addCleanup(retrieval.invalidate_policy_clause_bm25_index)

    def corpus(self):
        return [{
            "clause_id": clause_id, "policy_id": clause_id, "level": "article",
            "raw_text": "用章须提交审批。", "search_text": unit + " 用章须提交审批。",
            "structure_version": "v1",
            "metadata": {"clause_id": clause_id, "policy_id": clause_id,
                         "applicable_unit": [unit] if unit else [], "raw_text": "用章须提交审批。",
                         "search_text": unit + " 用章须提交审批。"},
        } for clause_id, unit in (("math", "数学学院"), ("school", "全校"),
                                  ("cs", "计算机学院"), ("unknown", ""))]

    def test_index_text_and_metadata_include_title_and_unit_without_changing_evidence(self):
        from policy.retrieval import build_clause_metadata
        metadata = build_clause_metadata({"raw_text": "用章须提交审批。"}, {
            "title": "印章管理规定", "applicable_unit": ["计算机学院"],
        })
        self.assertEqual(metadata.get("applicable_unit"), ["计算机学院"])
        self.assertIn("计算机学院", metadata["search_text"])
        self.assertIn("印章管理规定", metadata["search_text"])
        self.assertEqual(metadata["raw_text"], "用章须提交审批。")

    def test_bm25_loader_uses_document_context_even_with_existing_clause_search_text(self):
        import policy.retrieval as retrieval
        clause = {"clause_id": "cs", "policy_id": "cs", "level": "article",
                  "structure_version": "v1", "raw_text": "用章须提交审批。",
                  "search_text": "用章须提交审批。"}
        document = {"policy_id": "cs", "structure_version": "v1",
                    "title": "印章管理规定", "applicable_unit": ["计算机学院"]}

        def query(table, *args):
            return [clause] if table == "policy_clauses" else [document]

        with patch("policy.storage.ensure_policy_tables"), patch(
            "storage.adapters.storage", SimpleNamespace(relational=SimpleNamespace(query=query)),
        ):
            result = retrieval.search_policy_clauses_bm25("计算机学院", top_k=1)
        self.assertEqual([item["id"] for item in result], ["cs"])
        self.assertEqual(result[0]["metadata"].get("applicable_unit"), ["计算机学院"])

    def test_bm25_scopes_before_top_k_and_keeps_university_rules(self):
        import policy.retrieval as retrieval
        with patch.object(retrieval, "load_policy_clauses_for_bm25", return_value=self.corpus()):
            results = retrieval.search_policy_clauses_bm25("计算机学院用章", top_k=2)
        self.assertEqual({row["id"] for row in results}, {"cs", "school"})

    def test_vector_embeddings_receive_the_same_scope_context_as_metadata(self):
        from policy.retrieval import sync_policy_clause_index
        encoded, stored = [], []
        vector = SimpleNamespace(
            create_index=lambda *args: None, delete_vectors_by_metadata=lambda *args: None,
            insert_vectors=lambda name, vectors, metadata: stored.extend(metadata) or len(metadata),
        )

        def encode(texts):
            encoded.extend(texts)
            return [[1.0] for _ in texts]

        with (
            patch("policy.storage.get_policy_document", return_value={
                "title": "印章管理规定", "applicable_unit": ["计算机学院"],
            }),
            patch("policy.storage.get_policy_clauses", return_value=[{
                "clause_id": "cs", "level": "article", "raw_text": "用章须提交审批。",
            }]),
            patch("storage.adapters.storage", SimpleNamespace(vector=vector)),
            patch("policy.retrieval._encode_policy_clause_texts", side_effect=encode),
        ):
            sync_policy_clause_index("cs")
        self.assertIn("计算机学院", encoded[0])
        self.assertEqual(encoded[0], stored[0]["search_text"])

    def test_hybrid_search_filters_other_colleges_before_returning_top_k(self):
        import policy.retrieval as retrieval
        from core.config import app_config
        corpus = self.corpus()
        vector_rows = [{"id": row["clause_id"], "similarity": 1 - i / 10,
                        "metadata": row["metadata"]} for i, row in enumerate(corpus)]
        vector = SimpleNamespace(count_vectors=lambda name: 4, search=lambda *args, **kwargs: vector_rows)
        with (
            patch.object(retrieval, "load_policy_clauses_for_bm25", return_value=corpus),
            patch("storage.adapters.storage", SimpleNamespace(vector=vector)),
            patch.object(retrieval, "_encode_policy_clause_texts", return_value=[[1.0]]),
            patch.object(retrieval, "attach_clause_hierarchy_context", side_effect=lambda rows: rows),
            patch.object(app_config.answer_llm, "rerank_enabled", False),
        ):
            results = retrieval.search_indexed_policy_clauses("计算机学院用章", top_k=2)
        self.assertEqual({row["metadata"]["clause_id"] for row in results}, {"cs", "school"})

    def test_no_college_in_query_keeps_cross_college_retrieval(self):
        import policy.retrieval as retrieval
        with patch.object(retrieval, "load_policy_clauses_for_bm25", return_value=self.corpus()):
            results = retrieval.search_policy_clauses_bm25("用章审批", top_k=4)
        self.assertEqual({row["id"] for row in results}, {"cs", "school", "math", "unknown"})

    def test_unknown_college_in_middle_of_question_does_not_return_other_colleges(self):
        import policy.retrieval as retrieval
        corpus = [row for row in self.corpus() if row["clause_id"] in {"math", "school"}]
        with patch.object(retrieval, "load_policy_clauses_for_bm25", return_value=corpus):
            results = retrieval.search_policy_clauses_bm25("办理用章时，计算机学院需要哪些审批？", top_k=4)
        self.assertEqual({row["id"] for row in results}, {"school"})

    def test_query_can_explicitly_compare_two_colleges(self):
        import policy.retrieval as retrieval
        with patch.object(retrieval, "load_policy_clauses_for_bm25", return_value=self.corpus()):
            results = retrieval.search_policy_clauses_bm25("计算机学院和数学学院的用章规定", top_k=4)
        self.assertEqual({row["id"] for row in results}, {"cs", "math", "school"})

    def test_search_response_and_answer_prompt_expose_applicable_unit(self):
        from policy.answering import _build_answer_prompt, select_answer_evidence
        from policy.retrieval import build_policy_search_response
        row = {"metadata": {"policy_id": "cs", "clause_id": "cs", "title": "印章规定",
                            "applicable_unit": ["计算机学院"], "raw_text": "用章须提交审批。"}}
        result = build_policy_search_response("用章", [row])
        self.assertEqual(result["results"][0]["policy"].get("applicable_unit"), ["计算机学院"])
        evidence = select_answer_evidence([row])
        self.assertEqual(evidence[0].get("applicable_unit"), ["计算机学院"])
        self.assertIn("计算机学院", _build_answer_prompt("用章", "2026-11-01", evidence))

    def test_catalog_exposes_applicable_unit(self):
        from policy.web_catalog import PUBLIC_DOCUMENT_FIELDS, _public_row
        row = _public_row({"policy_id": "cs", "applicable_unit": ["计算机学院"]}, PUBLIC_DOCUMENT_FIELDS)
        self.assertEqual(row.get("applicable_unit"), ["计算机学院"])

    def test_v2_expansion_cannot_reintroduce_other_college_rules(self):
        from policy.knowledge_v2.retrieval import enhance_clause_candidates_v2
        rows = [{"metadata": row["metadata"]} for row in self.corpus()]
        documents = {row["clause_id"]: {"policy_id": row["policy_id"],
                     "applicable_unit": row["metadata"]["applicable_unit"]} for row in self.corpus()}
        matches = [{"clause_id": "math", "policy_id": "math", "score": 0.9}]
        with (
            patch("policy.knowledge_v2.retrieval.search_assertions_v2", return_value=matches),
            patch("policy.knowledge_v2.retrieval.expand_matched_matter_candidates", return_value=rows),
            patch("policy.knowledge_v2.retrieval._load_match_context", return_value={}),
            patch("policy.storage.get_policy_documents_by_ids", return_value=documents),
        ):
            results, info = enhance_clause_candidates_v2("计算机学院用章", [rows[2]])
        self.assertEqual({row["metadata"]["clause_id"] for row in results}, {"cs", "school"})
        self.assertEqual(info["matched_assertions"], [])


if __name__ == "__main__":
    unittest.main()
