"""以研究决定设定一般管理规则的通知分类回归测试。"""
import unittest

from classification.document import classify_document


class DocumentDecisionClassificationTests(unittest.TestCase):
    title = "基础医学院关于收回退休及相关人员公房的通知"
    opening = (
        "为加强学院公房管理，优化资源配置，更好地为引进人才服务，"
        "为教学、科研及师资队伍建设服务，经学院研究决定，"
        "对院内涉及以下情况人员公房予以收回，由学院统筹安排使用。"
    )
    rules = (
        "1、退休人员需在办理退休手续后一个月内清理出办公用房和科研用房，"
        "由系室协助学院收回公房交由学院统一管理。\n"
        "2、调动或离职离开学院人员，需在办理调动手续离职前清理好原使用学院公房，"
        "由系室协助学院收回公房交由学院统一管理。院内调动人员，"
        "在新单位安排办公用房后，需清退出原办公用房，交由学院统一管理。"
        "长期因病而不能工作者，由系室协助学院收回公房交由学院统一管理。\n"
        "3、退休人员返聘从事教学工作，系室提供集体办公场所。退休人员，"
        "如有未完成国家级科研项目或有未毕业研究生，根据科研项目及学生人数，"
        "可以保留部分实验室；或科研项目和未毕业研究生归并到其他在职人员。"
        "其他公房由系室协助学院收回交由学院统一管理。\n"
        "4、学院公房未经学院同意，不得私自转让和占用。"
    )

    def test_housing_recovery_notice_establishes_recurring_rules(self):
        """原通知针对不同人员情形设置清退期限、例外和禁令，应判为制度。"""
        result = classify_document(
            "missing.docx", self.title + ".docx",
            parsed_text=(self.title + "\n武大基医[2016]8号\n全院各单位：\n"
                         + self.opening + "\n" + self.rules
                         + "\n武汉大学基础医学院\n2016年7月5日"),
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_decision_rules_do_not_depend_on_filename_or_purpose_paragraph(self):
        """正文决策与一般情形下的多项要求可以独立分类。"""
        result = classify_document(
            "missing.docx", "工作通知.docx",
            parsed_text="经学院研究决定，对院内涉及下列情形人员公房予以收回。\n" + self.rules,
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_relative_deadline_requirements_count_as_obligations(self):
        """只有“需在”“需于”两项相对期限要求时也应识别，避免依赖额外禁令。"""
        result = classify_document(
            "missing.docx", "工作通知.docx",
            parsed_text="为规范管理，特制定本规定。\n"
                        "1、退休人员需在退休后一个月内交还钥匙。\n"
                        "2、离职人员需于离职前交还钥匙。",
        )
        self.assertEqual(result["doc_type"], "policy_regulation")

    def test_decision_without_own_multiple_rules_is_not_policy(self):
        """不采纳拟议、转述、附件条款、空标题或仅有一项要求。"""
        for text in (
            self.title,
            self.opening,
            self.opening + "\n1、退休人员需在退休后一个月内清退公房。",
            self.opening.replace("研究决定", "拟研究决定") + "\n" + self.rules,
            "现转述原文件，“" + self.opening + "”\n" + self.rules,
            "现转述原文件，" + self.opening + "\n" + self.rules,
            self.opening + "\n一、工作目标\n二、时间安排\n附件：原文摘录\n" + self.rules,
        ):
            with self.subTest(text=text):
                result = classify_document("missing.docx", self.title + ".docx", parsed_text=text)
                self.assertEqual(result["doc_type"], "other")

    def test_one_time_or_individual_decision_is_not_policy(self):
        """按次开展的清退和针对具名人员的个案决定不构成一般管理规则。"""
        for opening in (
            self.opening.replace("对院内", "对本次活动中"),
            self.opening + "\n本通知仅适用于本次集中清退。",
            self.opening + "\n本通知只适用于本年度公房清退。",
            "经学院研究决定，对张三、李四使用的公房予以收回。",
            "经学院研究决定，召开公房管理工作会议。",
        ):
            with self.subTest(opening=opening):
                result = classify_document(
                    "missing.docx", self.title + ".docx", parsed_text=opening + "\n" + self.rules,
                )
                self.assertEqual(result["doc_type"], "other")

    def test_academic_identifier_keeps_priority_over_decision_rules(self):
        result = classify_document(
            "missing.docx", self.title + ".docx",
            parsed_text=self.opening + "\n" + self.rules + "\nDOI: 10.1234/example",
        )
        self.assertEqual(result["doc_type"], "academic_paper")


if __name__ == "__main__":
    unittest.main()
