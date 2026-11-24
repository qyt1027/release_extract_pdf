"""文档制度标题识别及分类失败原因的回归测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from classification.document import classify_document


class DocumentClassificationRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(directory.cleanup)
        self.pdf_path = str(Path(directory.name) / "document.pdf")
        with fitz.open() as document:
            document.new_page()
            document.new_page()
            document.save(self.pdf_path)

    def test_implementation_scheme_with_recurring_duties_is_policy(self):
        """本科生导师方案中的持续职责和审核程序应构成制度，兼容原文换行。"""
        title = '电子信息学院本科生学业导师实施方案（2023年修订）'
        text = (
            '电子信息学院本科生学业导师实施方案\n（2023 年修订）\n'
            '为进一步发挥教师在学生培养中的主导作用和学生的主体\n'
            '作用，倡导高水平教师更多地参与本科生人才培养工作，促进学\n'
            '生全面健康发展，提升学院本科教学与人才培养的质量，现根据\n'
            '我院工作实际，制定以下实施意见。\n'
            '一、组织保障\n组长：李德识 倪彬彬\n'
            '二、实施范围\n'
            '1．本科生学业导师制面向学院全体本科生。从2022 级本科\n'
            '生开始试行，逐步覆盖全体本科生。\n'
            '3．学院受聘教师均应积极参与本科生学业导师工作，承担\n'
            '学院所要求的担任本科生学业导师的任务。\n'
            '五、实施办法\n'
            '2．学业导师如因特殊原因，如请假、访学超过半年的，需\n'
            '委托一位导师代管；如中途需要更换学业导师，需经学生申请、\n'
            '学业导师同意后，提交学院学业导师工作小组审核决定。\n'
            '七、考核与奖励\n'
            '1．学院对学业导师工作开展情况进行年度考核，考核结果\n'
            '作为教师年度考核的重要内容之一。'
        )
        for adoption in ('制定以下实施意见', '制定如下实施方案', '制定本实施方案'):
            with self.subTest(adoption=adoption):
                result = classify_document(
                    self.pdf_path, title + '.pdf',
                    parsed_text=text.replace('制定以下实施意见', adoption),
                )
                self.assertEqual(result['doc_type'], 'policy_regulation')

    def test_implementation_scheme_requires_own_recurring_rules(self):
        """方案名称或编号本身不能把临时活动、引文和拟议文件判为制度。"""
        title = '电子信息学院本科生学业导师实施方案（2023年修订）'
        cases = (
            title + '\n一、工作目标\n二、时间安排\n三、工作分工',
            title + '\n制定以下实施意见。\n一、工作目标\n二、时间安排',
            title + '\n拟制定以下实施意见。\n'
            '一、教师应积极参与指导。\n二、更换导师需经审核。',
            title + '\n现转述原文件：“制定以下实施意见。”\n'
            '一、教师应积极参与指导。\n二、更换导师需经审核。',
            title + '\n制定以下实施意见。\n本方案仅适用于本次交流活动。\n'
            '一、教师应积极参加。\n二、学生需提交报名表。',
        )
        for text in cases:
            with self.subTest(text=text):
                result = classify_document(self.pdf_path, title + '.pdf', parsed_text=text)
                self.assertEqual(result['doc_type'], 'other')

    def test_seal_management_regulation_is_policy_without_article_numbers(self) -> None:
        title = "关于计算机学院印章使用与管理的规定"
        result = classify_document(self.pdf_path, title + ".pdf", parsed_text=title)

        self.assertEqual(result["doc_type"], "policy_regulation")
        self.assertIn("[强信号]文件名为直接制度标题", result["signals"])

    def test_direct_policy_title_is_recognized_without_pdf_text(self) -> None:
        for filename in (
            "关于实验室使用的办法.doc",
            "关于学生管理的条例.docx",
            "关于设备借用的细则.PDF",
            "关于印章保管的制度",
            "关于印章管理的规定（试行）.pdf",
        ):
            with self.subTest(filename=filename):
                result = classify_document(self.pdf_path, filename, parsed_text="")
                self.assertEqual(result["doc_type"], "policy_regulation")

    def test_institution_policy_title_does_not_require_about_or_article_numbers(self):
        for title in (
            '外语学院语言实验室管理制度', '武汉大学会议费管理办法',
            '外国语言文学学院本科生班级导师工作实施细则',
            '计算机学院实验室安全规则', '计算机学院设备使用办法（试行）',
            '外语学院研究生管理制度',
        ):
            with self.subTest(title=title):
                result=classify_document(self.pdf_path, title + '.docx', parsed_text=title + '\n一、爱护设备。\n二、不得违规。')
                self.assertEqual(result['doc_type'], 'policy_regulation')
                self.assertIn('[强信号]文件名为直接制度标题', result['signals'])

    def test_institution_policy_commentary_or_form_is_not_direct_policy(self):
        from core.policy_titles import is_direct_policy_title
        for title in (
            '解读外语学院语言实验室管理制度', '外语学院语言实验室管理制度解读',
            '浅谈外语学院语言实验室管理制度', '论外语学院语言实验室管理制度',
            '关于解读外语学院语言实验室管理制度', '外语学院语言实验室管理制度调查表',
            '外语学院解读语言实验室管理制度', '武汉大学关于如何理解学生管理制度',
            '外语学院关于如何理解计算机学院学生管理制度',
        ):
            with self.subTest(title=title):
                self.assertFalse(is_direct_policy_title(title))
                result=classify_document(self.pdf_path, title + '.docx', parsed_text='')
                self.assertNotEqual(result['doc_type'], 'policy_regulation')

    def test_academic_evidence_still_wins_for_new_direct_title(self):
        result=classify_document(self.pdf_path, '外语学院语言实验室管理制度.docx', parsed_text='DOI: 10.1234/example')
        self.assertEqual(result['doc_type'], 'academic_paper')

    def test_appendix_item_numbers_do_not_override_policy_classification(self):
        title = "城市设计学院硕士研究生指导教师上岗办法"
        numbered_notes = "\n".join(f"  [{i}] 硕导须提供成果认定材料。" for i in range(1, 11))
        result = classify_document(
            self.pdf_path, title + ".docx",
            parsed_text=(f"{title}\n武大城设函〔2022〕16号\n"
                         "一、上岗条件\n申请人必须具备导师资格。\n"
                         "二、审核程序\n申请人须提交证明材料。\n"
                         f"附录：科研成果评分说明\n{numbered_notes}"),
        )

        self.assertEqual(result["doc_type"], "policy_regulation")
        self.assertFalse(any("引用" in signal or "方括号" in signal for signal in result["signals"]))

    def test_inline_numbered_citations_support_papers_without_identifiers(self):
        citations = "\n".join(f"Previous work [{i}] used this method." for i in range(1, 11))
        result = classify_document(
            "missing.pdf", "Feature Learning.pdf",
            parsed_text=f"Abstract\nKeywords\nIntroduction\n{citations}",
        )

        self.assertEqual(result["doc_type"], "academic_paper")
        self.assertIn("检测到10处行内方括号编号", result["signals"])

    def test_institution_prefixed_policy_and_standard_titles_are_recognized(self) -> None:
        for filename in (
            "计算机学院研究生党总支关于党员民主评议合格的标准（试行）.docx",
            "文学院党委关于党员考核的标准.doc",
            "武汉大学关于教师考核的标准.pdf",
            "计算机学院关于印章使用的规定.pdf",
            "2021计字22号 计算机学院关于印章使用的规定.pdf",
        ):
            with self.subTest(filename=filename):
                result = classify_document(self.pdf_path, filename, parsed_text="")
                self.assertEqual(result["doc_type"], "policy_regulation")

    def test_technical_standards_and_commentaries_are_not_direct_policies(self) -> None:
        for filename in (
            "关于图像压缩的标准.pdf",
            "图像压缩标准研究.pdf",
            "解读计算机学院关于党员考核的标准.pdf",
            "计算机学院关于党员考核的标准解读.pdf",
        ):
            with self.subTest(filename=filename):
                result = classify_document(self.pdf_path, filename, parsed_text="")
                self.assertEqual(result["doc_type"], "other")

    def test_policy_commentary_titles_do_not_trigger_direct_policy_signal(self) -> None:
        for filename in (
            "关于印章管理的规定解读.pdf",
            "关于印章管理的规定的研究.pdf",
            "解读关于印章管理的规定.pdf",
        ):
            with self.subTest(filename=filename):
                result = classify_document(self.pdf_path, filename, parsed_text="")
                self.assertEqual(result["doc_type"], "other")

    def test_policy_related_survey_keeps_form_classification(self) -> None:
        result = classify_document(
            self.pdf_path, "关于印章管理规定的意见征集调查表.pdf", parsed_text="",
        )
        self.assertEqual(result["doc_type"], "admin_form")

    def test_numbered_learning_plan_is_general_document(self) -> None:
        title = "2018年哲学学院党委理论学习中心组学习计划"
        result = classify_document(
            self.pdf_path, title + ".docx",
            parsed_text=f"{title}\n哲院党字[2018]7号\n一、指导思想和主要任务\n"
                        "二、学习内容\n第一专题：专题学习\n时间安排：2018年3月",
        )
        self.assertEqual(result["doc_type"], "other")
        self.assertIn("学习计划", result["reason"])

    def test_plan_filename_alone_does_not_override_document_evidence(self) -> None:
        for filename in ("学习计划.docx", "2022年党委工作计划.pdf"):
            with self.subTest(filename=filename):
                result = classify_document(
                    self.pdf_path, filename,
                    parsed_text="武汉大学理论学习中心组学习规定\n武大字〔2024〕1号\n"
                                "第一条 本规定适用于学校各级党委理论学习中心组。\n"
                                "第二条 中心组成员每年须参加规定次数的学习。\n"
                                "第三条 本规定自2024年9月1日起施行。",
                )
                self.assertEqual(result["doc_type"], "policy_regulation")

    def test_learning_plan_title_without_timed_topics_has_no_decisive_signal(self) -> None:
        title = "2018年哲学学院党委理论学习中心组学习计划"
        result = classify_document(
            self.pdf_path, title + ".docx", parsed_text=f"{title}\n哲院党字[2018]7号",
        )
        self.assertEqual(result["doc_type"], "other")
        self.assertEqual(result["confidence"], 0.0)

    def test_numbered_meeting_notice_with_official_format_is_general_document(self) -> None:
        result = classify_document(
            self.pdf_path, "关于召开科研工作会议的通知.pdf",
            parsed_text="武汉大学文件\n武大字〔2024〕1号\n主送：各学院\n"
                        "经研究决定召开科研工作会议。请于9月1日参会。特此通知。\n"
                        "抄送：学校办公室",
        )
        self.assertEqual(result["doc_type"], "other")

    def test_notice_with_applicability_and_printing_expense_rules_is_policy(self) -> None:
        result = classify_document(
            self.pdf_path, "关于进一步加强印刷费管理的通知.pdf",
            parsed_text="本通知适用于各类经费中印刷费的使用和管理。"
                        "报销时须提供支付记录。超预算的，不得列支印刷费。",
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_document_that_establishes_multiple_numbered_rules_is_policy(self) -> None:
        cases = (
            (
                "外语学院交换生课程成绩认定的通知（试行）.docx",
                "为规范成绩认定，结合学院实际，特制定本管理办法。\n"
                "一、认定范围\n交换生境外所修课程由所在专业负责审核。\n"
                "二、申请条件\n申请人需根据接收学校要求提交成绩单。\n"
                "三、审核程序\n申请材料不得重复提交。",
            ),
            (
                "图书馆读者服务工作要求.pdf",
                "为规范读者服务，依据《图书馆管理条例》制定本规定。\n"
                "一．借阅管理\n读者应按期归还借阅资料。\n"
                "二．遗失处理\n读者应在发现遗失后办理登记。\n"
                "附件：借阅登记表\n□ □ □ □ □",
            ),
        )
        for filename, body in cases:
            with self.subTest(filename=filename):
                result = classify_document(self.pdf_path, filename, parsed_text=body)
                self.assertEqual(result["doc_type"], "policy_regulation")

    def test_policy_adoption_can_follow_multiple_citations_with_document_numbers(self) -> None:
        openings = (
            "依据《馆藏管理办法》（校办字〔2021〕8号）、"
            "《借阅服务规范》(校办字[2022] 6 号)和《财产登记规定》制定本工作规定。",
            "按照《馆藏管理办法》校办字［2021］8号制定本工作规定。",
        )
        for opening in openings:
            with self.subTest(opening=opening):
                result = classify_document(
                    self.pdf_path, "图书资料遗失处理工作通知.docx",
                    parsed_text=opening + "\n一、读者须办理遗失登记。\n二、馆员不得擅自注销借阅记录。",
                )
                self.assertEqual(result["doc_type"], "policy_regulation")

    def test_equipment_purchase_notice_with_narrative_adoption_is_policy(self) -> None:
        """复现基础医学院购置通知：叙述式制定表述和多项审批要求构成制度。"""
        title = "基础医学院关于仪器设备购置有关规定的通知"
        result = classify_document(
            self.pdf_path, title + ".docx",
            parsed_text=(
                title + "\n武大基医函[2014]22号\n全院各单位：\n"
                "为规范学院仪器设备采购程序，加强学院仪器设备管理，优化学院仪器设备配置，"
                "学院制定了有关仪器设备购置的相关规定，现通知如下：\n"
                "1. 所有经费来源中凡预算在10万元人民币/台(套)以上的仪器设备的购置，"
                "需经仪器管理专家委员会审批，最后提交党政联席会讨论通过。\n"
                "2. 使用学院预算经费购置学院公用型设备时，均需经仪器管理专家委员会审批。"
                "其中仪器预算在10万元人民币/台(套)以上的，需提交党政联席会讨论通过方可购置。\n"
                "3. 凡申请单一来源的设备采购，需经仪器设备管理专家委员会主任审定，"
                "再提交党政联席会讨论通过和学院负责人签字。\n"
                "4. 上述设备的预算与执行结果，交由学院党政办公室统一备案。\n"
                "武汉大学基础医学院\n2014年12月9日"
            ),
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_narrative_adoption_requires_own_multiple_recurring_rules(self) -> None:
        """不能把拟议、转述、单次安排或没有执行条款的通知当成制度。"""
        requirements = "\n1. 购置设备需经专家委员会审批。\n2. 审批后方可购置。"
        for body in (
            "学院制定了有关仪器设备购置的相关规定，现通知如下。",
            "学院拟制定了有关仪器设备购置的相关规定，现征求意见。" + requirements,
            "拟由学院制定有关仪器设备购置的相关规定，现征求意见。" + requirements,
            "现摘录原文件：“学院制定了有关仪器设备购置的相关规定。”" + requirements,
            "现转述原文件，学院制定了有关仪器设备购置的相关规定。" + requirements,
            "请学习学院制定了有关仪器设备购置的相关规定。" + requirements,
            "学院制定了有关仪器设备购置的相关规定，现通知如下。\n"
            "本规定仅适用于本次交流活动。" + requirements,
        ):
            with self.subTest(body=body):
                result = classify_document(
                    self.pdf_path, "基础医学院关于仪器设备购置有关规定的通知.docx",
                    parsed_text=body,
                )
                self.assertEqual(result["doc_type"], "other")

    def test_numbered_notice_requires_its_own_rules_in_the_main_text(self) -> None:
        cases = (
            "根据《交流管理办法》，现将本次交流报名事项通知如下。\n"
            "一、报名时须填写报名表。\n二、参会时不得迟到。",
            "根据《交流管理办法》（校办字〔2021〕8号）及《交流工作指引》"
            "拟制定本工作规定，现征求意见。\n"
            "一、学生须填写报名表。\n二、材料不得重复提交。",
            "现摘录既有制度的制定说明：“为规范管理，特制定本办法。”\n"
            "一、报名时须填写报名表。\n二、参会时不得迟到。",
            "教务办公室拟制定本办法，现征求意见。\n"
            "一、学生须提交成绩单。\n二、材料不得重复提交。",
            "为做好工作，特制定本办法。\n本办法仅适用于本届交流活动。\n"
            "一、报名时须填写报名表。\n二、参会时不得迟到。",
            "为做好工作，特制定本规定。\n本规定仅适用于本学期交流活动。\n"
            "一、报名时须填写报名表。\n二、参会时不得迟到。",
            "为做好工作，特制定本办法。\n一、工作目标\n二、时间安排\n"
            "附件：报名说明\n一、学生须填写报名表。\n二、材料不得重复提交。",
            "现转述原文件。\n一、文件开头写道，特制定本办法。\n"
            "二、学生须填写报名表。\n三、材料不得重复提交。",
        )
        for body in cases:
            with self.subTest(body=body):
                result = classify_document(
                    self.pdf_path, "教务办公室关于交流工作的通知（试行）.docx",
                    parsed_text=body,
                )
                self.assertEqual(result["doc_type"], "other")

    def test_facility_rules_with_promulgation_clause_are_policy(self) -> None:
        title = "振华楼地下车库管理制度"
        result = classify_document(
            self.pdf_path, title + ".docx",
            parsed_text=f"{title}\n1、外来车辆未经许可，不得进出。\n"
                        "2、取得授权资格后方可入内。\n"
                        "15、本制度经文学院、历史学院、哲学学院党政联席会批准后，自颁布之日起实施。",
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_referencing_effective_date_of_other_rules_does_not_make_a_policy(self) -> None:
        result = classify_document(
            self.pdf_path, "关于召开停车管理工作会议的通知.pdf",
            parsed_text="会上将说明《车库管理制度》，其中规定：本制度自颁布之日起实施。"
                        "参会人员应当提前签到。特此通知。",
        )
        self.assertEqual(result["doc_type"], "other")

    def test_applicability_limited_to_one_meeting_does_not_make_a_policy(self) -> None:
        result = classify_document(
            self.pdf_path, "关于召开科研工作会议的通知.pdf",
            parsed_text="武大字〔2024〕1号\n本通知仅适用于本次会议。参会人员应当提前签到。特此通知。",
        )
        self.assertEqual(result["doc_type"], "other")

    def test_plan_management_regulation_is_still_policy(self) -> None:
        title = "武汉大学学习计划管理办法"
        for filename in (f"{title}.pdf", f"关于印发《{title}》的通知.pdf"):
            with self.subTest(filename=filename):
                result = classify_document(self.pdf_path, filename, parsed_text="武大字〔2024〕1号")
                self.assertEqual(result["doc_type"], "policy_regulation")

    def test_academic_strong_signal_keeps_priority(self) -> None:
        result = classify_document(
            self.pdf_path, "关于印章管理的规定.pdf",
            parsed_text="DOI: 10.1234/example",
        )
        self.assertEqual(result["doc_type"], "academic_paper")

    def test_operational_requirements_corroborate_a_generic_policy_title(self):
        title = '【学位工作】工程硕士学位论文评审规定'
        body = (title + '\n一、申请条件\n1、申请人必须完成规定的课程。'
                '\n2、材料审核通过后方可申请。')
        result = classify_document(self.pdf_path, title + '.docx', parsed_text=body)
        self.assertEqual(result['doc_type'], 'policy_regulation')
        self.assertEqual(classify_document(
            self.pdf_path, title + '.docx', parsed_text=body.removeprefix('【学位工作】'),
        )['doc_type'], 'policy_regulation')
        self.assertEqual(classify_document(self.pdf_path, title + '.docx', parsed_text=title)['doc_type'], 'other')
        self.assertEqual(classify_document(
            self.pdf_path, title + '.docx', parsed_text=body + '\nDOI: 10.1234/example',
        )['doc_type'], 'academic_paper')
        self.assertEqual(classify_document(
            self.pdf_path, title + '.docx', parsed_text='论文答辩工作情况调查\n' + body.split('\n', 1)[1],
        )['doc_type'], 'other')

    def test_collector_prefix_does_not_hide_an_institutional_policy_title(self):
        result = classify_document(
            self.pdf_path, '〔行政2023〕09—武汉大学文学院学位论文评优办法.pdf',
            parsed_text='摘要、讨论、结果、结论均属于论文评审项目。',
        )
        self.assertEqual(result['doc_type'], 'policy_regulation')

    def test_issuance_notice_with_version_in_quoted_title_is_policy(self):
        result = classify_document(
            self.pdf_path, '附件2：关于印发《联合培养实施办法（试行）》的通知.doc',
            parsed_text='关于印发《联合培养\n实施办法（试行）》的通知\n请遵照执行。',
        )
        self.assertEqual(result['doc_type'], 'policy_regulation')

    def test_draft_or_policy_commentary_with_numbered_requirements_is_not_a_policy(self):
        for title in ('学位论文答辩规定（征求意见稿）', '如何理解学位论文答辩规定'):
            with self.subTest(title=title):
                result = classify_document(
                    self.pdf_path, title + '.docx',
                    parsed_text=title + '\n1、申请人必须提交材料。\n2、审核通过后方可申请。',
                )
                self.assertEqual(result['doc_type'], 'other')

    def test_insufficient_soft_signals_report_scores_instead_of_no_signals(self) -> None:
        result = classify_document(
            self.pdf_path, "印章管理规定解读.pdf", parsed_text="计算机学院\n印章使用说明",
        )

        self.assertEqual(result["doc_type"], "other")
        self.assertEqual(result["confidence"], 0.0)
        self.assertNotIn("未触发", result["reason"])
        for value in ("2.5", "3.5", "1.0", "2.0"):
            self.assertIn(value, result["reason"])

    def test_ambiguous_soft_signals_report_small_gap(self) -> None:
        result = classify_document(
            self.pdf_path, "印章使用说明.pdf",
            parsed_text="计算机学院\n第一条 姓名 性别 年龄 联系电话\n第二条\n第三条",
        )

        self.assertEqual(result["doc_type"], "other")
        self.assertNotIn("未触发", result["reason"])
        self.assertIn("4.0", result["reason"])
        self.assertIn("0.0", result["reason"])

    def test_no_signals_still_reports_no_effective_signals(self) -> None:
        result = classify_document("missing.pdf", "无特征文档.pdf", parsed_text="")

        self.assertEqual(result["doc_type"], "other")
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["reason"], "未触发任何有效分类信号")


if __name__ == "__main__":
    unittest.main()
