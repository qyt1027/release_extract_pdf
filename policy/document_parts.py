"""根据印发通知书名及独立正文标题，划分同一源文件中的制度。"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from core.models import BlockType, ContentBlock
from core.policy_titles import normalize_policy_title, is_policy_notice_title, is_policy_issuance_notice_title
from metadata.policy_scope import infer_applicable_unit
from core.unit_aliases import applicable_unit_paths, registered_applicable_units, unit_aliases

_BODY_START_RE = re.compile(
    r'^(?:第[\d一二三四五六七八九十百千万零〇]+[编章节条]|'
    r'[一二三四五六七八九十百千万]+、|\d+[.．、]|[（(][\d一二三四五六七八九十百千万]+[）)])'
)


def confirm_folder_applicable_units(
    parts: list[dict], file_path: str, confirmation: Callable[[str, str, str], bool],
) -> None:
    """在保存前逐项确认院级制度的目录学院，保留已有的适用范围。"""
    college = PureWindowsPath(file_path).parent.name
    if unit_aliases().get(college) != college or not re.search(r'学院(?:[（(].+[）)])?$', college):
        return
    for part in parts:
        metadata = part['metadata']
        if metadata['applicable_unit']:
            continue
        title = metadata['title']
        text = '\n'.join(block.content for block in part['blocks'] if block.type == BlockType.TEXT)
        units = infer_applicable_unit(title, text, source_unit=college, college_fallback=college)
        if units == [college] and confirmation(file_path, title, college):
            metadata['applicable_unit'] = units
            metadata['applicable_unit_paths'] = applicable_unit_paths(units)


def split_policy_document(
    blocks: list[ContentBlock], metadata: dict, file_name: str, *, source_path: str = "",
) -> list[dict]:
    source_unit = unit_aliases().get(PureWindowsPath(source_path).parent.name, "") if source_path else ""
    fallback_meta = dict(metadata)
    fallback_meta['applicable_unit'] = registered_applicable_units(metadata.get('applicable_unit')) or infer_applicable_unit(
        str(metadata.get('title') or Path(file_name).stem),
        '\n'.join(block.content for block in blocks if block.type == BlockType.TEXT),
        source_unit=source_unit,
    )
    fallback_meta['applicable_unit_paths'] = applicable_unit_paths(fallback_meta['applicable_unit'])
    fallback = [{'blocks': blocks, 'metadata': fallback_meta}]
    notice = normalize_policy_title(metadata.get('notice_title') or metadata.get('title') or file_name)
    if not is_policy_notice_title(notice) or not re.search(r'关于.*(?:印发|发布).*的通知$', notice):
        return fallback
    titles = list(dict.fromkeys(re.findall(r'《([^《》]+)》', notice)))
    if len(titles) < 2:
        return fallback
    # 按原解析顺序保留表格和图片；只将文本块按行展开，方便识别跨行标题。
    expanded = []
    for block in sorted(blocks, key=lambda b: b.page_num):
        if block.type == BlockType.TEXT:
            expanded.extend(block.model_copy(update={'content': line.strip()})
                            for line in block.content.splitlines() if line.strip())
        else:
            expanded.append(block)
    starts = []
    title_end = 0
    for i, block in enumerate(expanded):
        if block.type != BlockType.TEXT or i < title_end:
            continue
        candidate = ''
        for count in range(1, 5):
            if i + count > len(expanded) or expanded[i+count-1].type != BlockType.TEXT:
                break
            candidate += ''.join(expanded[i+count-1].content.split())
            title = re.sub(r'^附件[一二三四五六七八九十\d]*[：:]?', '', candidate)
            if title not in titles:
                continue
            # 允许标题后的简短前言及中文、括号、数字编号；不越过下一附件标题。
            following = []
            for following_block in expanded[i+count:i+count+8]:
                if following_block.type != BlockType.TEXT:
                    continue
                compact = ''.join(following_block.content.split())
                if compact in titles:
                    break
                following.append(compact)
            if any(_BODY_START_RE.match(text) for text in following):
                starts.append((i, title))
                title_end = i + count
            break
    # 引用书名或缺失附件不能充当边界；同一标题出现多次时拒绝猜选。
    if len(starts) != len(titles) or {title for _,title in starts} != set(titles):
        return fallback
    parts = []
    for index, (start,title) in enumerate(starts):
        end = starts[index+1][0] if index+1 < len(starts) else len(expanded)
        body = expanded[start:end]
        meta = dict(metadata)
        # 聚合字段属于源文件，不能复制到每项制度的元数据中。
        meta.pop('policies', None)
        meta.update(title=title,
                    document_key='' if index == 0 else hashlib.sha256(title.encode('utf-8')).hexdigest()[:24],
                    source_page_start=min(b.page_num for b in body),
                    source_page_end=max(b.page_num for b in body))
        # 拆分边界与展示字段分开：发布多制度仍拆分，但 notice_title 只用于印发。
        if is_policy_issuance_notice_title(notice):
            meta['notice_title'] = notice
        else:
            meta.pop('notice_title', None)
        # 施行、废止日期由各附件正文独立识别，不能继承另一个制度的效力信息。
        for field in ('effective_date', 'expiry_date', 'validity_status'):
            meta.pop(field, None)
        # 每项制度独立确定适用范围，不能继承通知或其他附件的学院名称。
        meta['applicable_unit'] = infer_applicable_unit(
            title, '\n'.join(block.content for block in body if block.type == BlockType.TEXT),
            source_unit=source_unit,
        )
        meta['applicable_unit_paths'] = applicable_unit_paths(meta['applicable_unit'])
        parts.append({'blocks': body, 'metadata': meta})
    return parts
