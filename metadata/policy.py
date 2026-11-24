# metadata/policy.py
import re
from typing import Any, Dict, List

from core.models import BlockType, ContentBlock
from core.policy_titles import (
    compact_title_text, is_direct_policy_title, is_policy_institution_heading, is_policy_notice_title, is_policy_issuance_notice_title,
    is_regulatory_title,
    normalize_policy_title, split_policy_title_and_number,
)
from core.policy_signatures import (
    POLICY_DATE_PATTERN, SIGNATURE_ORGANIZATION_PATTERN, normalize_policy_date, policy_terminal_date,
)
from core.unit_aliases import applicable_unit_paths
from .document_number import display_document_number
from .title import infer_document_title


_BODY_HEADING_RE = re.compile(r"^第[一二三四五六七八九十百千万零〇\d]+(?:编|章|节|条)")
_POLICY_TITLE_RE = re.compile(r"^[^《》。；：:，,]{4,100}(?:办法|细则|规定|规则|条例|章程|意见|方案|制度|标准|工作要求|具体条件)(?:[（(][^）)]{1,30}[）)])?$")
_VERSION_TAG_RE = re.compile(r"[（(]((?:(?:19|20)\d{2}(?:年(?:\d{1,2}月)?)?)?(?:修订版?|发布|试行|暂行)|(?:19|20)\d{2}版)[）)]")
_NUMBERED_BODY_START_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)]|\d+[.、])")


def _body_follows_title(lines: list[str], index: int) -> bool:
    """允许标题后的版本说明和一段前言，不要求制度必须采用正式章条。"""
    following = lines[index + 1:index + 5]
    if following and _VERSION_TAG_RE.fullmatch(following[0]):
        following = following[1:]
    if following and re.match(r"^(?:为|根据|依据|结合)", following[0]):
        following = following[1:]
    return bool(following and (_BODY_HEADING_RE.match(following[0]) or _NUMBERED_BODY_START_RE.match(following[0])))


def _policy_title_metadata(blocks: List[ContentBlock], source_title: str = "") -> Dict[str, str]:
    """以独立正文标题及条款起始确认制度名称，通知标题单独保留。"""
    lines = [compact_title_text(line) for block in blocks if block.type == BlockType.TEXT
             for line in block.content.splitlines() if line.strip()]
    source_title = normalize_policy_title(source_title)
    opening_title = source_title if is_policy_notice_title(source_title) else infer_document_title(blocks)
    notice = opening_title if is_policy_notice_title(opening_title) else ""
    titles = set()
    notice_titles = re.findall(r"《([^《》]+)》", notice)
    for i, line in enumerate(lines):
        title = normalize_policy_title(re.sub(r"^附件\s*[一二三四五六七八九十\d]*[：:]?", "", line))
        # 通知书名与独立正文标题相互印证时，允许前言和编号结构，无需正式章条。
        confirmed = ""
        for count in range(1, 5):
            if i - count + 1 < 0:
                break
            candidate = "".join(lines[i - count + 1:i + 1])
            candidate = re.sub(r"^附件\s*[一二三四五六七八九十\d]*[：:]?", "", candidate)
            if candidate in notice_titles and _POLICY_TITLE_RE.fullmatch(candidate):
                confirmed = candidate
                break
        if confirmed:
            titles.add(confirmed)
            continue
        # 与分类复用完整标题规则，兼容机构前缀及“一、二、”编号的标准类制度。
        if is_direct_policy_title(title):
            titles.add(title)
            continue
        if not _POLICY_TITLE_RE.fullmatch(title) or title.startswith("关于") or _BODY_HEADING_RE.match(title) or _NUMBERED_BODY_START_RE.match(title):
            continue
        if _body_follows_title(lines, i):
            # 标题可能跨段换行，只拼接有独立机构抬头或与通知书名一致的片段。
            for count in range(2, 5):
                if i - count + 1 < 0:
                    break
                candidate = "".join(lines[i - count + 1:i + 1])
                candidate = re.sub(r"^附件\s*[一二三四五六七八九十\d]*[：:]?", "", candidate)
                prefix = "".join(lines[i - count + 1:i])
                institutional_prefix = re.fullmatch(r"[\u4e00-\u9fff]{1,40}(?:大学|学院)[\u4e00-\u9fff]{0,40}", prefix)
                if (candidate in notice_titles and _POLICY_TITLE_RE.fullmatch(candidate)) or (
                    not re.search(r"大学|学院", title)
                    and (is_policy_institution_heading(prefix) or institutional_prefix)
                ):
                    title = candidate
                    break
            titles.add(title)
    # 首页已确认的跨行完整标题优先，逐行命中的标题尾部不再覆盖它。
    if is_regulatory_title(opening_title):
        titles = {opening_title if opening_title.endswith(title) else title for title in titles}
    result = {}
    if notice:
        result['title'] = notice
        if is_policy_issuance_notice_title(notice):
            result['notice_title'] = notice
    if len(titles) == 1:
        result["title"] = next(iter(titles))
    return result

_DOC_NUMBER_PATTERN = (
    r"[\u4e00-\u9fa5]{2,12}\s*[〔\[［﹝【（(]\s*\d{4}\s*[〕\]］﹞】）)]\s*\d+\s*号"
)
_DOC_NUMBER_LINE_RE = re.compile(
    rf"(?:文号|发文字号)\s*[：:]\s*({_DOC_NUMBER_PATTERN})|^[ \t]*({_DOC_NUMBER_PATTERN})[ \t]*$",
    re.M,
)


def _normalize_doc_number(value: str) -> str:
    """将文号的括号和内部空白统一为入库格式。"""
    return display_document_number(value)


_ISSUE_DATE_LABEL_RE = re.compile(rf"(?:发布日期|发文日期|印发日期)[：:]{POLICY_DATE_PATTERN}")
_DATE_LINE_RE = re.compile(rf"{POLICY_DATE_PATTERN}[。.]?$")
_SIGNATURE_ORG = SIGNATURE_ORGANIZATION_PATTERN
_SIGNATURE_DATE_RE = re.compile(rf"{_SIGNATURE_ORG}{POLICY_DATE_PATTERN}[。.]?$")
_DATE_BODY_START_RE = re.compile(r"^(?:第[一二三四五六七八九十百千万零〇\d]+[编章节条]|[一二三四五六七八九十]+、|\d+[.．、])")


def _extract_issue_date(header_text: str, signature_text: str = "") -> str | None:
    """依次参考日期标注、机关落款、文首独立日期行和末行日期。"""
    candidates: list[set[str]] = [set(), set(), set()]
    previous_line = ""
    for raw_line in header_text.splitlines():
        line = "".join(raw_line.split())
        if not line:
            continue
        standalone = _DATE_LINE_RE.fullmatch(line)
        if not standalone and _DATE_BODY_START_RE.match(line):
            break
        signature = _SIGNATURE_DATE_RE.fullmatch(line)
        if standalone and re.fullmatch(_SIGNATURE_ORG, previous_line):
            signature = standalone
        for priority, match in enumerate((_ISSUE_DATE_LABEL_RE.search(line), signature, standalone)):
            if match:
                normalized = normalize_policy_date(match)
                if normalized:
                    candidates[priority].add(normalized)
        previous_line = line
    # 机关署名可与日期同行或分行。
    signature_lines = ["".join(line.split()) for line in signature_text.splitlines() if line.strip()]
    previous_line = ""
    for line in signature_lines:
        match = _SIGNATURE_DATE_RE.fullmatch(line)
        if not match and re.fullmatch(_SIGNATURE_ORG, previous_line):
            match = _DATE_LINE_RE.fullmatch(line)
        if match:
            normalized = normalize_policy_date(match)
            if normalized:
                candidates[1].add(normalized)
        previous_line = line
    for dates in candidates:
        if dates:
            precise_dates = {value for value in dates if len(value) == 10}
            if len(precise_dates) == 1 and len({value[:7] for value in dates}) == 1:
                return next(iter(precise_dates))
            return next(iter(dates)) if len(dates) == 1 else None
    return policy_terminal_date(signature_lines[-1]) if signature_lines else None


def _attach_policy_metadata(
    blocks: List[ContentBlock], meta: dict, file_name: str = "", *, source_path: str = "",
) -> dict:
    """已确认多个附件时，分别返回制度元数据，不以通知名代替制度名。"""
    from policy.document_parts import split_policy_document
    if meta.get('notice_title') and not is_policy_issuance_notice_title(meta['notice_title']):
        meta.pop('notice_title')
    if not meta.get('title'):
        meta['title'] = infer_document_title(blocks, file_name)
        if is_policy_issuance_notice_title(meta['title']):
            meta.setdefault('notice_title', meta['title'])
    parts = split_policy_document(blocks, meta, file_name, source_path=source_path)
    units = parts[0]['metadata']['applicable_unit']
    meta['applicable_unit'] = units if all(set(part['metadata']['applicable_unit']) == set(units) for part in parts) else []
    meta['applicable_unit_paths'] = applicable_unit_paths(meta['applicable_unit'])
    if len(parts) > 1:
        meta['policies'] = [part['metadata'] for part in parts]
        wrapper_notice = parts[0]['metadata'].get('notice_title')
        if wrapper_notice:
            meta.setdefault('notice_title', wrapper_notice)
            meta.pop('title', None)
        elif not meta.get('title'):
            # 非印发类仍保留源文档标题，不能因不填 notice_title 而丢掉拆分依据。
            meta['title'] = normalize_policy_title(file_name)
    if len(parts) == 1 and not meta.get('version'):
        versions = set()
        lines = [compact_title_text(line) for block in blocks if block.type == BlockType.TEXT for line in block.content.splitlines()]
        # 先定位实际制度标题，避免通知自身的“一、二、”提前截断正文版本。
        body_title = _VERSION_TAG_RE.sub('', str(meta.get('title') or ''))
        title_ends = [index for index in range(len(lines)) for count in range(1, 5)
                      if index - count + 1 >= 0 and body_title
                      and _VERSION_TAG_RE.sub('', ''.join(lines[index - count + 1:index + 1])) == body_title]
        version_start = max(title_ends) if title_ends else 0
        for line in lines[version_start:]:
            if _BODY_HEADING_RE.match(line) or _NUMBERED_BODY_START_RE.match(line):
                break
            match = _VERSION_TAG_RE.fullmatch(line)
            if match:
                versions.add(match.group(1))
        if not versions:
            for value in (meta.get('title', ''), normalize_policy_title(file_name)):
                match = _VERSION_TAG_RE.search(value)
                if match and match.end() == len(value):
                    versions.add(match.group(1))
                    break
        if len(versions) == 1:
            meta['version'] = next(iter(versions))
    return meta


def extract_policy_metadata(
    blocks: List[ContentBlock], file_name: str = "", *, source_path: str = "",
) -> Dict[str, Any]:
    header_text = "\n".join(block.content for block in blocks if block.page_num <= 2)
    full_text = "\n".join(block.content for block in blocks if block.type == BlockType.TEXT)
    for block in blocks:
        raw = block.raw if isinstance(block.raw, dict) else {}
        if raw.get("source_format") == "mhtml":
            source_metadata = raw.get("source_metadata")
            meta = dict(source_metadata) if isinstance(source_metadata, dict) else {}
            if meta.get("title"):
                meta["title"] = "".join(str(meta["title"]).split())
            if meta.get("doc_number"):
                meta.setdefault("doc_number_raw", meta["doc_number"])
                meta["doc_number"] = _normalize_doc_number(meta["doc_number"])
            titles = _policy_title_metadata(blocks, meta.get("title", ""))
            if titles.get("notice_title") or is_policy_notice_title(meta.get('title', '')):
                meta.update(titles)
            if not (meta.get("issue_date") or meta.get("issue_month")):
                issue_date = _extract_issue_date(header_text, full_text)
                if issue_date:
                    meta['issue_date' if len(issue_date) == 10 else 'issue_month'] = issue_date
            return _attach_policy_metadata(blocks, meta, file_name, source_path=source_path)

    meta = _policy_title_metadata(blocks)

    # 页码缺失时可能把全文都纳入首页块，因此文号只在正文标题之前查找。
    body_start = re.search(
        r"(?<!\S)第[一二三四五六七八九十百千万零〇\d]+(?:章|条)",
        header_text,
    )
    document_header = header_text[:body_start.start()] if body_start else header_text
    # 中文、括号和数字编号同样标志正文开始，不能把其后的引用当作文件抬头。
    offset = 0
    for line in document_header.splitlines(keepends=True):
        compact_line = ''.join(line.split())
        if _NUMBERED_BODY_START_RE.match(compact_line) and not _DATE_LINE_RE.fullmatch(compact_line):
            document_header = document_header[:offset]
            break
        offset += len(line)
    # 文号必须单独成行或带明确字段标签，避免把正文引用误认成本文件文号。
    doc_num_match = _DOC_NUMBER_LINE_RE.search(document_header)
    if doc_num_match:
        doc_number = doc_num_match.group(1) or doc_num_match.group(2)
        meta['doc_number_raw'] = doc_number
        meta['doc_number'] = _normalize_doc_number(doc_number)
    else:
        # 采集到的 Word 常把标题与文号放在同一段，只检查正文开始前的完整标题行。
        for line in document_header.splitlines():
            title, doc_number = split_policy_title_and_number(line)
            if (doc_number and title == meta.get('title') and _POLICY_TITLE_RE.fullmatch(title)
                    and not _BODY_HEADING_RE.match(title) and not _NUMBERED_BODY_START_RE.match(title)):
                meta['doc_number_raw'] = doc_number
                meta['doc_number'] = _normalize_doc_number(doc_number)
                break

    # 仅从明确标注的字段提取发布机构，引用依据不是发文单位。
    org_match = re.search(r'(?:发布机构|发文机关|印发单位)\s*[：:]\s*([\u4e00-\u9fa5（）()]{2,40})', header_text)
    if org_match:
        meta['issuer'] = org_match.group(1)

    issue_date = _extract_issue_date(document_header, full_text)
    if issue_date:
        meta['issue_date' if len(issue_date) == 10 else 'issue_month'] = issue_date

    return _attach_policy_metadata(blocks, meta, file_name, source_path=source_path)
