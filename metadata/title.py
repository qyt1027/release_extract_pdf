"""从文档首页的标题区提取通用标题。"""
import re
from dataclasses import dataclass

from core.models import BlockType, ContentBlock
from core.policy_signatures import SIGNATURE_DATE_PATTERN
from core.policy_titles import (
    compact_title_text, is_policy_institution_heading, is_regulatory_title, normalize_policy_title,
)

_BODY_START = re.compile(
    r'^(?:第[一二三四五六七八九十百千万零〇\d]+[编章节条款]|'
    r'[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)]|\d+[.．、])'
)
_BODY_OPENING = re.compile(
    r'^(?:为(?:了|进一步|贯彻|落实|加强|规范|做好|便于)|根据|依据|按照|经[^。；]{0,30}(?:研究|审议|批准|评审)|'
    r'现将|现就|现印发|请遵照|请认真|本(?:学院|校|办法|规定|制度|通知|细则)|抄送)'
)
_ATTACHMENT_LABEL = r'附件[一二三四五六七八九十百\d]*'
_ATTACHMENT_MARKER = re.compile(
    rf'(?:【{_ATTACHMENT_LABEL}】[：:]?|{_ATTACHMENT_LABEL}(?:[：:]|$))'
)
_FILENAME_DATE_SUFFIX = re.compile(r'(?:20\d{2})?(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])')
_CLOSING = re.compile(
    r'(?:(?:特此|专此|谨此)(?:通知|通告|通报|公告|函告|函复|批复|报告|说明|告知|请示)|'
    r'此(?:复|函|致|令))[。！.!]?$'
)
_DATE = re.compile(rf'(?:{SIGNATURE_DATE_PATTERN}|\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}[。.]?)')
_DOC_NUMBER = re.compile(r'[\u4e00-\u9fff]{2,20}[〔\[［﹝【（(]\d{4}[〕\]］﹞】）)]\d+号')
_ORGANIZATION = re.compile(r'[\u4e00-\u9fff]{2,50}(?:大学|学院|学校|研究院|学堂|党委|办公室|委员会|文件|公文)$')
_HEADER_FIELD = re.compile(r'^(?:发布机构|发文机关|印发单位|发文字号|文号|发布日期|发文日期|签发人|密级|紧急程度|份号)[：:]')
_INCOMPLETE_NOTICE = re.compile(r'关于[^。；！？]{0,30}(?:印发|发布)[《〈].+[》〉]的?$')
_OFFICIAL_TITLE = re.compile(
    r'关于[^。；！？!?：:]{2,140}(?:通知|通告|公告|公示|通报|决定|批复|意见|函|纪要|报告|方案)'
    r'(?:[（(][^）)]{1,20}[）)])?$'
)
_SENTENCE_END = re.compile(r'[。；;！!?？：:][”」）)]?$')
_NON_TITLE_PUNCTUATION = re.compile(r'[。；;！!?？：:，,]')


@dataclass(frozen=True)
class _HeaderLine:
    text: str
    block: int
    heading: bool
    page_header: bool


def _is_incomplete_title(title: str) -> bool:
    return (
        any(title.count(left) != title.count(right) for left, right in ('《》', '〈〉', '（）', '()'))
        or _INCOMPLETE_NOTICE.search(title) is not None
    )


def _is_official_title(title: str) -> bool:
    issuer, about, subject = title.partition('关于')
    return bool(about and (not issuer or is_policy_institution_heading(issuer))
                and _OFFICIAL_TITLE.fullmatch(about + subject))


def _opening_lines(blocks: list[ContentBlock]) -> list[_HeaderLine | None]:
    """保留首页标题行及其版式，遇主送、正文或结语即停止。"""
    text_blocks = [block for block in blocks if block.type == BlockType.TEXT and block.content.strip()]
    if not text_blocks:
        return []
    first_page = min(block.page_num for block in text_blocks)
    lines = []
    for index, block in enumerate(text_blocks):
        if block.page_num != first_page:
            continue
        raw = block.raw or {}
        role = raw.get('type')
        if role in {'footer', 'page_number', 'page_footnote'}:
            continue
        for line in block.content.splitlines():
            text = compact_title_text(line)
            if not text:
                continue
            if _ATTACHMENT_MARKER.fullmatch(text):
                if any(item is not None for item in lines):
                    return lines
                continue
            # 文号、版头、签发字段等把独立行隔开，防止它们被并入标题。
            if (_HEADER_FIELD.match(text) or _DATE.fullmatch(text)
                    or (_DOC_NUMBER.match(text) and not normalize_policy_title(text))
                    or (_ORGANIZATION.fullmatch(text) and text.endswith(('文件', '公文')))):
                lines.append(None)
            elif (_BODY_START.match(text) or _BODY_OPENING.match(text)
                  or _CLOSING.fullmatch(text) or _SENTENCE_END.search(text)):
                return lines
            else:
                heading = (role == 'title' or raw.get('text_level') in (1, '1')
                           or bool(re.match(r'^\s{0,3}#{1,6}\s', line)))
                lines.append(_HeaderLine(text, index, heading, role == 'header'))
            if len(lines) >= 16:
                return lines
    return lines


def infer_document_title(blocks: list[ContentBlock], file_name: str = '') -> str:
    """用版式、标题句式或来源文件名确认标题，保留普通独立标题作为兜底。"""
    from storage.file_records import _is_low_confidence_source_name
    source_name = str(file_name or '').replace('\\', '/').rsplit('/', 1)[-1]
    file_title = _ATTACHMENT_MARKER.sub('', normalize_policy_title(source_name), count=1)
    if (_is_low_confidence_source_name(source_name) or _is_incomplete_title(file_title)
            or _CLOSING.fullmatch(file_title)):
        file_title = ''

    lines = _opening_lines(blocks)
    plain_title = ''
    for index, first in enumerate(lines):
        if first is None:
            continue
        combined = ''
        marked_title = ''
        continued = _is_incomplete_title(first.text)
        same_heading = first.heading
        for offset, line in enumerate(lines[index:index + 6]):
            if line is None:
                break
            same_heading = same_heading and line.heading and line.block == first.block
            # 新的标题起句只在同一标题块、机关前缀或书名尚未闭合时参与续接。
            if (offset and line.text.startswith('关于') and not same_heading
                    and not _is_incomplete_title(combined) and not is_policy_institution_heading(combined)):
                break
            combined += line.text
            candidate = _ATTACHMENT_MARKER.sub('', normalize_policy_title(combined), count=1)
            if len(candidate) > 160:
                break
            if len(candidate) < 4 or _is_incomplete_title(candidate) or _ORGANIZATION.fullmatch(candidate):
                continue
            # 只有与正文标题相互印证时，才把文件名末尾的月日或年月日视为日期后缀。
            matches_filename = file_title.startswith(candidate) and (
                candidate == file_title or _FILENAME_DATE_SUFFIX.fullmatch(file_title[len(candidate):])
            )
            if matches_filename or _is_official_title(candidate):
                return candidate
            # 机构前缀和“关于”起句可跨行续接，不能只接受单行制度标题。
            if is_regulatory_title(candidate) and (
                offset == 0 or is_policy_institution_heading(first.text)
                or first.text.startswith('关于') or continued or same_heading
            ):
                return candidate
            if same_heading:
                marked_title = candidate
            if not plain_title and (offset == 0 or continued) and not first.page_header and (
                not _NON_TITLE_PUNCTUATION.search(candidate) and not candidate.endswith('的')
                and not (file_title.startswith(candidate) or file_title.endswith(candidate))
            ):
                plain_title = candidate
        if marked_title:
            return marked_title
    if _is_official_title(file_title) or is_regulatory_title(file_title):
        return file_title
    return plain_title or file_title or '未命名文档'
