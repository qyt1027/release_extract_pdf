"""元数据和制度正文重组共用的落款及末尾条款边界。"""

import re
from collections.abc import Sequence
from datetime import date

SIGNATURE_PREFIX_GUARD = (
    r"(?!报送|上报|提交|抄送|主送|送交|送达|呈报|报请|转交|联系|通知|向|由|根据|按照|依照|印发|印制|本规定|本办法)"
    r"(?!.*(?:负责|应当|必须))"
)
SIGNATURE_ORGANIZATION_PATTERN = (
    SIGNATURE_PREFIX_GUARD
    + r"[\u4e00-\u9fffA-Za-z（）()·]{1,60}"
    r"(?:委员会|党总支|党支部|党委|大学|学院|学校|政府|办公室|办公厅|秘书处|部|处|局|会)"
)

CHINESE_DATE_NONZERO_DIGITS = "一二三四五六七八九"
CHINESE_DATE_DIGITS = "〇○零Oo" + CHINESE_DATE_NONZERO_DIGITS
_CHINESE_DATE_TRANSLATION = str.maketrans(CHINESE_DATE_DIGITS, "00000123456789")
_CHINESE_DIGIT = rf"[{CHINESE_DATE_NONZERO_DIGITS}]"
_MONTH_OR_DAY = rf"(?:\d{{1,2}}|{_CHINESE_DIGIT}(?:十{_CHINESE_DIGIT}?)?|[十廿卅]{_CHINESE_DIGIT}?)"
POLICY_DATE_PATTERN = (
    rf"(?P<date>(?:\d{{4}}|[{CHINESE_DATE_DIGITS}]{{4}})年{_MONTH_OR_DAY}月"
    rf"(?:{_MONTH_OR_DAY}日|(?![\d{CHINESE_DATE_DIGITS}十廿卅]))"
    r"|\d{4}[.．]\d{1,2}[.．]\d{1,2}(?!\d|[.．]\d))"
)
_FINAL_DATE_RE = re.compile(rf"{POLICY_DATE_PATTERN}(?:[（(]修订版?[）)]|修订版?)?[。.]?")

_SIGNATURE_YEAR_MONTH = (
    rf"(?:[12]\d{{3}}|[{CHINESE_DATE_DIGITS}]{{4}})年"
    r"(?:\d{1,2}|[一二三四五六七八九十]{1,3})月"
)
_SIGNATURE_DAY = r"(?:\d{1,2}|[一二三四五六七八九十廿卅]{1,3})日"
SIGNATURE_DATE_PATTERN = rf"{_SIGNATURE_YEAR_MONTH}(?:{_SIGNATURE_DAY})?[。.]?"
_DATED_SIGNATURE_RE = re.compile(
    rf"(?:{SIGNATURE_ORGANIZATION_PATTERN}{SIGNATURE_DATE_PATTERN}|"
    rf"{SIGNATURE_DATE_PATTERN}{SIGNATURE_ORGANIZATION_PATTERN})"
)
_PUBLICATION_DATE = rf"{_SIGNATURE_YEAR_MONTH}{_SIGNATURE_DAY}印(?:制|发)[。.]?"
_DISCLOSURE = r"(?:主动公开|依申请公开|不予公开|不公开)?"
_PUBLICATION_FOOTER_RE = re.compile(
    rf"(?:{SIGNATURE_ORGANIZATION_PATTERN}{_DISCLOSURE}{_PUBLICATION_DATE}|"
    rf"{_PUBLICATION_DATE}{SIGNATURE_ORGANIZATION_PATTERN}{_DISCLOSURE})"
)
_EMPTY_PAGE_NOTICE_RE = re.compile(r"[（(]?(?:此|本)页无正文[）)]?[。.]?")
_FOOTER_LAYOUT_RE = re.compile(r"\s+|\*\*|__")
_FOOTER_PAGE_NUMBER_RE = re.compile(
    r'(?:[0-9]{1,5}|[-—–－][0-9]{1,5}[-—–－]|第[0-9]{1,5}页(?:共[0-9]{1,5}页)?)'
)
PUBLICATION_ACTION_PATTERN = r"(?:发布|公布|印发|颁布|下发|发文)"
_CLOSING_PROVISION_RE = re.compile(
    r"(?:本(?:管理|实施|工作|试行|暂行|补充){0,2}(?:办法|规定|制度|细则|条例|规则|章程|规程|意见|通知)"
    r"\s*(?:"
    r"(?:自|从)\s*(?:\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
    rf"{PUBLICATION_ACTION_PATTERN}之日|即日)\s*起?\s*(?:开始)?(?:施行|实施|执行|生效)"
    r"|由[^，,。；;！？\n]{1,60}?解释)"
    r"|原(?:《[^》\n]{2,100}》|[^，,。；;！？\n]{0,45}(?:办法|规定|制度|细则|条例))"
    r"(?:同时|即行|一并|自行|即)?(?:废止|作废))(?=[，,。；;！？.!?]|$)"
)
_CLOSING_HEADING_RE = re.compile(
    r"(?:附\s*则|(?:施行|实施|生效)(?:时间|日期)?|解释(?:与施行|及施行)?)\s*[：:]?"
)


def _parse_date_part(part: str) -> int:
    digits = part.replace("廿", "二十").replace("卅", "三十").translate(_CHINESE_DATE_TRANSLATION)
    tens, separator, units = digits.partition("十")
    if separator:
        return int(tens or "1") * 10 + int(units or "0")
    return int(digits)


def normalize_policy_date(match: re.Match[str]) -> str | None:
    """验证日期并按原文精度输出 ISO 日期或年月。"""
    parts = [_parse_date_part(part) for part in re.split(r"[年月.．]", match["date"].rstrip("月日"))]
    if len(parts) == 2:
        year, month = parts
        return f"{year:04d}-{month:02d}" if 1 <= year <= 9999 and 1 <= month <= 12 else None
    try:
        return date(*parts).isoformat()
    except ValueError:
        return None


def policy_terminal_date(line: str) -> str | None:
    """识别文档末行单独写出的日期，兼容修订后缀。"""
    match = _FINAL_DATE_RE.fullmatch("".join(line.split()))
    return normalize_policy_date(match) if match else None


def policy_footer_size(
    lines: Sequence[str], *, include_publication: bool = True, include_standalone_date: bool = False,
) -> int:
    """从文末反向识别落款和版记，可在整份正文结束时识别独立日期。"""
    end = len(lines)
    found_footer = False
    trailing_page = bool(end and _FOOTER_PAGE_NUMBER_RE.fullmatch(_FOOTER_LAYOUT_RE.sub('', lines[end - 1])))
    if trailing_page:
        # 暂时越过末尾页号；只有随后确认落款或版记，才承认它属于文末排版。
        end -= 1
    while end:
        if _EMPTY_PAGE_NOTICE_RE.fullmatch(_FOOTER_LAYOUT_RE.sub("", lines[end - 1])):
            end -= 1
            continue
        footer = ""
        for count, line in enumerate(reversed(lines[max(0, end - 6):end]), start=1):
            footer = _FOOTER_LAYOUT_RE.sub("", line) + footer
            if (_DATED_SIGNATURE_RE.fullmatch(footer)
                    or (include_publication and _PUBLICATION_FOOTER_RE.fullmatch(footer))):
                found_footer = True
                end -= count
                break
        else:
            break
    if trailing_page and not found_footer:
        return 0
    if not found_footer and include_standalone_date and end and policy_terminal_date(lines[end - 1]):
        return len(lines) - end + 1
    return len(lines) - end if found_footer else 0


def has_policy_footer_page_number(lines: Sequence[str]) -> bool:
    """末行页号须有紧邻的具名日期落款或印发版记佐证，单独日期不算。"""
    return bool(lines and _FOOTER_PAGE_NUMBER_RE.fullmatch(_FOOTER_LAYOUT_RE.sub('', lines[-1]))
                and policy_footer_size(lines))


def policy_closing_provisions_start(lines: Sequence[str], end: int) -> int:
    """从正文末尾向前找连续的施行、解释和废止规定。"""
    while end > 0 and _CLOSING_PROVISION_RE.match(lines[end - 1].strip()):
        end -= 1
    return end


def is_policy_closing_heading(text: str) -> bool:
    """已有附则等标题时，末尾条款继续归入该标题。"""
    return _CLOSING_HEADING_RE.fullmatch(text.strip()) is not None
