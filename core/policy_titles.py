"""文档分类及元数据提取共用的直接制度标题规则。"""
from __future__ import annotations

import re

from core.unit_aliases import normalize_unit_query, unit_aliases


_LEADING_DOC_NUMBER_RE = re.compile(
    r"^(?:[\u4e00-\u9fff]{1,20}[〔\[［﹝【（(](?:19|20)\d{2}[〕\]］﹞】）)]\d+号|"
    r"(?:19|20)\d{2}[\u4e00-\u9fff]{1,12}\d+号)"
)
_INSTITUTION_PREFIX = (
    r"(?!解读|研究|分析|评述|综述|比较|探讨)"
    r"[\u4e00-\u9fff]{1,40}(?:大学|学院|学校|研究院|学堂|中心|研究所|学系)"
    r"(?:[\u4e00-\u9fff]{0,20}(?:党总支|党支部|党委|委员会))?"
)
_INSTITUTION_COMMENTARY_RE = re.compile(
    rf'^{_INSTITUTION_PREFIX}(?:解读|浅谈|浅析|评析|评述|综述|探讨|分析研究|比较研究|'
    r'如何|怎么|怎样|关于(?:如何|怎么|怎样|解读|理解))'
)
_POLICY_NOTICE_TITLE_RE = re.compile(rf'(?:{_INSTITUTION_PREFIX})?关于[^\r\n]{{2,500}}的通知')
_REGULATORY_ENDING = (
    r"(?:规定|办法|条例|细则|制度|规则|章程|规程)"
    r"(?:[（(](?:(?:(?:19|20)\d{2}年(?:\d{1,2}月)?)?(?:试行|暂行|修订版?)|(?:19|20)\d{2}版)[）)])?"
)
_COMMENTARY_START_RE = re.compile(
    r"^(?:关于)?(?:解读|研究(?!生)|分析|评述|综述|比较|探讨|浅析|浅谈|评析|论(?!文)|如何|怎么|怎样|理解)"
)
_DIRECT_TITLE_RE = re.compile(
    rf"(?:(?:{_INSTITUTION_PREFIX})?关于[^《》〈〉\r\n]{{1,100}}的(?:规定|办法|条例|细则|制度)|"
    rf"{_INSTITUTION_PREFIX}关于[^《》〈〉\r\n]{{1,100}}的标准|"
    rf"{_INSTITUTION_PREFIX}[^《》〈〉\r\n]{{1,100}}(?:规定|办法|条例|细则|制度|规则|章程))"
    r"(?:[（(](?:试行|暂行|修订)[）)])?$"
)
_TITLE_DOCUMENT_NUMBER_RE = re.compile(
    r"^(?P<title>.+(?:办法|细则|规定|规则|条例|章程|意见|方案|制度|标准|工作要求|具体条件|通知)"
    r"(?:[（(][^）)]{1,30}[）)])?)"
    r"(?:(?P<wrapper>[（(])?"
    r"(?P<number>(?!详见|参见|参照|依据|根据)[\u4e00-\u9fff]{2,12}"
    r"[〔\[［﹝【（(](?:19|20)\d{2}[〕\]］﹞】）)]\d+号)"
    r"(?(wrapper)[）)]))$"
)
_ATTACHMENT_FILE_ORDER_RE = re.compile(r"^\d{1,3}[-－]")
_SOURCE_TITLE_PREFIX_RE = re.compile(
    r"^(?:附件[一二三四五六七八九十\d]+[：:]|"
    r"[〔\[［][\u4e00-\u9fff]{1,12}(?:19|20)\d{2}[〕\]］]\d{1,5}[-—–－])"
)
_TOPIC_LABEL_RE = re.compile(r"^(?:【[^】]{1,20}】)+")
_REGULATORY_TITLE_RE = re.compile(rf"[^《》〈〉。；：:,，]{{2,120}}{_REGULATORY_ENDING}$")
_ISSUED_REGULATORY_TITLE_RE = re.compile(rf"[《〈][^《》〈〉]{{1,150}}(?:{_REGULATORY_ENDING}|意见)[》〉]")


def compact_title_text(value: str) -> str:
    """清理解析器在标题行中输出的空白、Markdown 标题和加粗标记。"""
    return "".join(value.split()).lstrip("#").replace("**", "").strip("*")


def split_policy_title_and_number(value: str) -> tuple[str, str]:
    """只拆分完整标题末尾的文号，避免贪婪匹配吞掉标题。"""
    compact = "".join(str(value or "").split())
    match = _TITLE_DOCUMENT_NUMBER_RE.fullmatch(compact)
    return (match['title'], match['number']) if match else (compact, "")


def normalize_policy_title(value: str) -> str:
    """去掉文件扩展名、排版空白及标题前后文号，保留制度名称。"""
    title = re.sub(r"\.(?:pdf|docx?)$", "", str(value or "").strip(), flags=re.I)
    title, _ = split_policy_title_and_number(compact_title_text(title))
    title = _SOURCE_TITLE_PREFIX_RE.sub("", title, count=1)
    return _LEADING_DOC_NUMBER_RE.sub("", title, count=1)


def policy_title_subject(value: str) -> str:
    """取用于分类和范围判断的标题主体，展示标题仍保留栏目标签。"""
    title = _ATTACHMENT_FILE_ORDER_RE.sub("", normalize_policy_title(value))
    return _TOPIC_LABEL_RE.sub("", title)


def is_regulatory_title(value: str) -> bool:
    """识别制度标题的句式，供正文执行要求佐证。"""
    title = policy_title_subject(value)
    return (
        _REGULATORY_TITLE_RE.fullmatch(title) is not None
        and not _COMMENTARY_START_RE.match(title)
        and not _INSTITUTION_COMMENTARY_RE.match(title)
    )


def is_direct_policy_title(value: str) -> bool:
    """完整机构制度标题不必包含“关于”；排除解读、研究等文章标题。"""
    title = normalize_unit_query(policy_title_subject(value))
    if _COMMENTARY_START_RE.match(title):
        return False
    # 学院名称后也可能是解读文章；不能据“研究”二字排除研究生管理制度。
    if _INSTITUTION_COMMENTARY_RE.match(title):
        return False
    return _DIRECT_TITLE_RE.fullmatch(title) is not None


def is_policy_institution_heading(value: str) -> bool:
    """识别独立的机构标题行，兼容多个单位并列。"""
    names = re.split(r"[、，,]", normalize_unit_query("".join(value.split())))
    aliases = unit_aliases()
    return all(name in aliases or re.fullmatch(_INSTITUTION_PREFIX, name) for name in names)


def is_policy_notice_title(value: str) -> bool:
    """通知可带机构前缀；此规则不负责决定文档是否具有通用标题。"""
    title = normalize_policy_title(value)
    if re.match(r'^(?:依据|根据|参照|按照|遵照|请参照|现转发|解读|浅谈|浅析)', title):
        return False
    return _POLICY_NOTICE_TITLE_RE.fullmatch(title) is not None


def is_policy_issuance_notice_title(value: str, *, regulatory_only: bool = False) -> bool:
    """仅识别印发具名制度的外层通知，用于 notice_title。"""
    title = normalize_policy_title(value)
    if not is_policy_notice_title(title):
        return False
    issuance = re.search(
        r'关于(?:修订并|重新修订|修订|重新|修正|调整|同意|正式|予以|制定){0,3}'
        r'印发([《〈].+)', title,
    )
    return issuance is not None and (
        bool(_ISSUED_REGULATORY_TITLE_RE.search(issuance[1])) if regulatory_only
        else bool(re.match(r'《[^《》]+》|〈[^〈〉]+〉', issuance[1]))
    )
