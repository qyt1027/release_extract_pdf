"""规章制度的文档元数据与条款结构化管线。

本阶段只处理结构，不调用大模型。实体和关系由 policy.graph.extraction 单独处理。
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.models import BlockType, ContentBlock, PolicyClause, PolicyStructureStatus, ReviewItem
from core.policy_signatures import (
    is_policy_closing_heading,
    policy_closing_provisions_start,
    policy_footer_size,
    policy_terminal_date,
)
from .storage import (
    insert_review_item,
    mark_policy_structure_failed,
    replace_policy_clauses,
    upsert_policy_document,
)


STRUCTURE_VERSION = os.getenv("POLICY_STRUCTURE_VERSION", "policy-structure-v1")

_NUMBER = r"[0-9一二三四五六七八九十百千万零〇两]+"
# 标题可能紧接层级号，不能以是否有空格决定编、章、节的存在。
_BOOK_RE = re.compile(rf"^第\s*({_NUMBER})\s*编[：:、.\s]*(.*)$", re.S)
_CHAPTER_RE = re.compile(rf"^第\s*({_NUMBER})\s*章[：:、.\s]*(.*)$", re.S)
_SECTION_RE = re.compile(rf"^第\s*({_NUMBER})\s*节[：:、.\s]*(.*)$", re.S)
_ARTICLE_RE = re.compile(rf"^第\s*({_NUMBER})\s*条(?!款)[：:、.\s]*(.*)$", re.S)
_ARTICLE_INLINE_RE = re.compile(rf"(?<!\S)(?:\*\*|__)?(第\s*{_NUMBER}\s*条)(?!款)")
_LEADING_BOLD_RE = re.compile(r"^(\*\*|__)(.+?)\1")
_PAREN_ITEM_RE = re.compile(rf"^[（(]\s*({_NUMBER})\s*[）)]\s*(?:[：:、.]\s*)?(.*)$", re.S)
_APPENDIX_RE = re.compile(
    rf"^((?:附件|附表|附录)(?:\s*{_NUMBER})?)(?:(?:[：:、.．\s]+|(?=[《〈]))(.*))?$"
)
_CN_ITEM_RE = re.compile(r"^([一二三四五六七八九十百千万]+)、(?:\s*)(.*)$", re.S)
_NUM_ITEM_RE = re.compile(r"^(\d+)(?:[.．](?!\d)|、)\s*(.*)$", re.S)
_PARAGRAPH_RE = re.compile(rf"^第\s*({_NUMBER})\s*款(?:[：:、.\s]+(.*))?$", re.S)


@dataclass
class _ClauseDraft:
    """条款构建过程中的内部节点。"""

    sequence_no: int
    policy_id: str
    structure_version: str
    level: str
    label: str
    parent: Optional["_ClauseDraft"] = None
    raw_parts: list[str] = field(default_factory=list)
    page_start: int = 0
    page_end: int = 0
    bboxes: list[list[float]] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    article_no: str = ""
    paragraph_no: str = ""
    item_no: str = ""

    @property
    def clause_id(self) -> str:
        content_hash = hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()[:16]
        seed = f"{self.policy_id}:{self.structure_version}:{self.sequence_no}:{content_hash}"
        return f"clause_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"

    @property
    def raw_text(self) -> str:
        return "\n".join(part for part in self.raw_parts if part.strip()).strip()

    @property
    def chapter_path(self) -> list[str]:
        path: list[str] = []
        node: Optional[_ClauseDraft] = self
        while node:
            if node.level in {"book", "chapter", "section", "appendix"} and node.label:
                heading = node.raw_parts[0] if node.raw_parts else ""
                path.append(heading if heading and not heading.startswith("[表格]\n") else node.label)
            node = node.parent
        return list(reversed(path))

    def append(self, text: str, page_num: int, bbox: Any = None, table: Optional[dict] = None) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self.raw_parts.append(text)
        if len(self.raw_parts) == 1:
            self.page_start = page_num or 0
        self.page_end = max(self.page_end, page_num or 0)
        if table and not any(item['table_id'] == table['table_id'] for item in self.tables):
            self.tables.append(table)
            self.page_end = max(self.page_end, table['page_end'])
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                normalized = [float(v) for v in bbox[:4]]
                if normalized not in self.bboxes:
                    self.bboxes.append(normalized)
            except (TypeError, ValueError):
                pass


def _html_to_text(value: str) -> str:
    """把表格HTML转成适合检索和抽取的纯文本。"""
    if not value:
        return ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(value, "html.parser")
        rows = []
        for tr in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows) or soup.get_text(" ", strip=True)
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", " ", value))


def _lines_from_block(block: ContentBlock) -> list[str]:
    """按行处理文本块，并拆出同一块中紧邻的第X条标记。"""
    content = str(block.content or "").replace("\r\n", "\n")
    if (block.raw or {}).get('structured_table'):
        return [content] if content.strip() else []
    if block.type == BlockType.TABLE:
        table_text = _html_to_text(block.table_html or content)
        return [f"[表格]\n{table_text}".strip()] if table_text.strip() else []

    lines: list[str] = []
    for raw_line in content.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # 部分解析结果把连续条款放在同一行，按条号前的空白切开。
        matches = list(_ARTICLE_INLINE_RE.finditer(line))
        if len(matches) <= 1 or matches[0].start() != 0:
            lines.append(line)
            continue
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            part = line[start:end].strip()
            if part:
                lines.append(part)
    return lines


def _marker(line: str) -> Optional[tuple[str, str, str]]:
    """识别层级标记，返回(level, label, remainder)。"""
    # 解析器可能用 Markdown 加粗编号；只规范识别用的行首，保留正文格式。
    line = _LEADING_BOLD_RE.sub(r"\2", line, count=1)
    for level, pattern in (
        ("book", _BOOK_RE),
        ("chapter", _CHAPTER_RE),
        ("section", _SECTION_RE),
        ("article", _ARTICLE_RE),
        ("paragraph", _PARAGRAPH_RE),
    ):
        match = pattern.match(line)
        if match:
            number = match.group(1).replace(" ", "")
            remainder = (match.group(2) or "").strip()
            label_word = {"book": "编", "chapter": "章", "section": "节", "article": "条", "paragraph": "款"}[level]
            return level, f"第{number}{label_word}", remainder

    match = _APPENDIX_RE.fullmatch(line)
    if match:
        return "appendix", "".join(match.group(1).split()), (match.group(2) or "").strip()

    match = _PAREN_ITEM_RE.match(line)
    if match:
        return "item", f"（{match.group(1).strip()}）", (match.group(2) or "").strip()
    match = _CN_ITEM_RE.match(line)
    if match:
        return "item", f"{match.group(1)}、", (match.group(2) or "").strip()
    match = _NUM_ITEM_RE.match(line)
    if match:
        return "item", f"{match.group(1)}.", (match.group(2) or "").strip()
    return None


def _numbered_item_rank(label: str) -> Optional[int]:
    """只为实际编号分配层级，避免把括号中的普通说明当作编号。"""
    chinese_number = r"[一二三四五六七八九十百千万零〇两]+"
    for rank, pattern in (
        (1, rf"{chinese_number}、"),
        (2, rf"[（(]{chinese_number}[）)]"),
        (3, r"\d+[.、]"),
        (4, r"[（(]\d+[）)]"),
    ):
        if re.fullmatch(pattern, label):
            return rank
    return None


def _nearest_parent(
    current: Optional[_ClauseDraft], level: str, label: str = "", *, numbered_hierarchy: bool = False
) -> Optional[_ClauseDraft]:
    """寻找新节点的最近合法父节点。"""
    allowed = {
        "book": {"appendix"},
        "chapter": {"book", "appendix"},
        "section": {"book", "chapter", "appendix"},
        "article": {"book", "chapter", "section", "appendix"},
        "paragraph": {"article", "appendix"},
        "item": {"article", "paragraph", "appendix"},
        "appendix": set(),
        "preamble": set(),
    }
    node = current
    rank = _numbered_item_rank(label) if level == "item" else None
    scope = current
    while scope and scope.level == "item":
        scope = scope.parent
    # 条、款内部统一使用编号层级；正式边界仍由原有章条规则管理。
    nested_numbers = numbered_hierarchy or bool(scope and scope.level in {"article", "paragraph", "appendix"})
    while node:
        if rank is not None and node.level == "item":
            parent_rank = _numbered_item_rank(node.label)
            if parent_rank is not None and parent_rank < rank and (
                nested_numbers
            ):
                return node
        if node.level in allowed.get(level, set()):
            return node
        node = node.parent
    return None


def _closing_footer_size(
    lines: list[tuple[ContentBlock, str, tuple[str, str, str] | None]],
    end: int,
    *,
    include_publication: bool = True,
    include_standalone_date: bool = False,
) -> int:
    """识别边界前的落款和版记，也可识别整份正文末尾的独立日期。"""
    texts = []
    for index in range(end - 1, -1, -1):
        block, text, marker = lines[index]
        if block.type != BlockType.TEXT:
            break
        if marker and not (include_standalone_date and index == end - 1 and policy_terminal_date(text)):
            break
        texts.append(text)
    return policy_footer_size(
        texts[::-1], include_publication=include_publication, include_standalone_date=include_standalone_date,
    )


def build_policy_clauses(
    policy_id: str,
    blocks: list[ContentBlock],
    structure_version: str = STRUCTURE_VERSION,
) -> list[PolicyClause]:
    """从解析块建立带父子层级的制度条款。"""
    drafts: list[_ClauseDraft] = []
    current: Optional[_ClauseDraft] = None
    sequence = 0
    ordered_blocks = [item for _, item in sorted(
        enumerate(blocks), key=lambda pair: (pair[1].page_num, pair[0])
    )]
    prepared_lines = [
        (block, line, _marker(line))
        for block in ordered_blocks if block.type in {BlockType.TEXT, BlockType.TABLE}
        for line in _lines_from_block(block)
    ]
    footer_lines: set[int] = set()
    implicit_appendices: set[int] = set()
    appendix_after_footer: dict[tuple[str, str, str], int] = {}
    for index, (block, _, marker) in enumerate(prepared_lines):
        is_table = block.type == BlockType.TABLE
        is_appendix = marker is not None and marker[0] == "appendix"
        if not (is_table or is_appendix):
            continue
        size = _closing_footer_size(prepared_lines, index, include_publication=not is_table)
        if not size:
            continue
        footer_lines.update(range(index - size, index))
        if is_table:
            implicit_appendices.add(index)
        elif marker and marker[2]:
            appendix_after_footer.setdefault(marker, index)
    end = len(prepared_lines)
    body_end = end - _closing_footer_size(prepared_lines, end, include_standalone_date=True)
    footer_lines.update(range(body_end, end))
    closing_start = policy_closing_provisions_start([text for _, text, _ in prepared_lines], body_end)
    # 正式章条制度继续使用原规则，仅为没有正式层级的编号文档补充父子关系。
    formal_levels = {"book", "chapter", "section", "article", "paragraph"}
    numbered_hierarchy = not any(
        marker and marker[0] in formal_levels
        for _, _, marker in prepared_lines
    )

    def create_node(level: str, label: str, remainder: str, block: ContentBlock, raw_line: str | None = None) -> _ClauseDraft:
        nonlocal sequence, current
        parent = _nearest_parent(current, level, label, numbered_hierarchy=numbered_hierarchy)
        sequence += 1
        draft = _ClauseDraft(
            sequence_no=sequence,
            policy_id=policy_id,
            structure_version=structure_version,
            level=level,
            label=label,
            parent=parent,
        )
        draft.article_no = label if level == "article" else (parent.article_no if parent else "")
        draft.paragraph_no = label if level == "paragraph" else (parent.paragraph_no if parent else "")
        if level in {"item", "appendix"}:
            draft.item_no = label
        draft.append(raw_line if raw_line is not None else remainder if level == "preamble"
                     else f"{label} {remainder}".strip(), block.page_num, block.bbox,
                     (block.raw or {}).get('structured_table'))
        drafts.append(draft)
        current = draft
        return draft

    for index, (block, line, marker) in enumerate(prepared_lines):
        if index in footer_lines:
            continue
        if index in implicit_appendices:
            # “附表”仅用于引用定位，原文不添加不存在的标题。
            create_node("appendix", "附表", "", block, raw_line="")
        if marker:
            level, label, remainder = marker
            # 紧接正文大项的同名附件预告，由落款后的正式附件标题代表。
            if index < appendix_after_footer.get(marker, index):
                following = prepared_lines[index + 1][2]
                if following and (
                    following[0] in formal_levels
                    or (following[0] == "item" and _numbered_item_rank(following[1]) == 1)
                ):
                    continue
            # 附件说明紧接重复的“附件”封面标记时保留为同一附件。
            if level == "appendix" and current and current.level == "appendix" and current.label == label and len(current.raw_parts) == 1:
                current.append(line, block.page_num, block.bbox)
                continue
            create_node(level, label, remainder, block)
            continue

        if current is None:
            create_node("preamble", "前言", line, block)
        elif (
            index == closing_start
            and numbered_hierarchy
            and current.level == "item"
            and not current.chapter_path
            and len(current.raw_parts) > 1
            and not is_policy_closing_heading(current.raw_parts[0][len(current.label):])
        ):
            create_node("paragraph", "", "", block, raw_line=line)
        else:
            current.append(line, block.page_num, block.bbox, (block.raw or {}).get('structured_table'))

    clauses: list[PolicyClause] = []
    for draft in drafts:
        raw_text = draft.raw_text
        if not raw_text:
            continue
        prefix = " / ".join(draft.chapter_path)
        search_text = " ".join(
            part for part in (prefix, draft.label, raw_text) if part
        ).strip()
        confidence = 0.95 if draft.level in {"book", "chapter", "section", "article", "paragraph", "item", "appendix"} else 0.75
        clauses.append(
            PolicyClause(
                clause_id=draft.clause_id,
                policy_id=policy_id,
                parent_clause_id=draft.parent.clause_id if draft.parent else None,
                level=draft.level,
                chapter_path=draft.chapter_path,
                article_no=draft.article_no,
                paragraph_no=draft.paragraph_no,
                item_no=draft.item_no,
                raw_text=raw_text,
                search_text=search_text,
                page_start=draft.page_start,
                page_end=draft.page_end,
                bboxes=draft.bboxes,
                tables=draft.tables,
                confidence=confidence,
                content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                sequence_no=draft.sequence_no,
                structure_version=structure_version,
            )
        )
    return clauses


def calculate_policy_parse_quality(blocks: list[ContentBlock], clauses: list[PolicyClause]) -> float:
    """根据文本覆盖、坐标和OCR异常计算结构化质量分数。"""
    meaningful = [
        b for b in blocks
        if b.type in {BlockType.TEXT, BlockType.TABLE}
        and (b.content or b.table_html or "").strip()
    ]
    if not meaningful:
        return 0.0
    block_texts = [str(b.content or b.table_html or "") for b in meaningful]
    total_chars = sum(len(text) for text in block_texts)
    replacement_chars = sum(text.count("�") for text in block_texts)
    bbox_ratio = sum(1 for b in meaningful if len(b.bbox) >= 4) / len(meaningful)
    coverage = min(1.0, sum(len(c.raw_text) for c in clauses) / max(total_chars, 1))
    ocr_score = max(0.0, 1.0 - replacement_chars / max(total_chars, 1) * 20)
    return round(max(0.0, min(1.0, coverage * 0.45 + bbox_ratio * 0.25 + ocr_score * 0.30)), 4)


def _guess_title(file_name: str, blocks: list[ContentBlock]) -> str:
    """优先使用可信文件名，否则按通知首页规则寻找正文标题。"""
    from storage.file_records import _is_low_confidence_source_name

    source_name = Path(file_name).name
    file_title = "".join(Path(source_name).stem.split())
    if file_title and not _is_low_confidence_source_name(source_name):
        return file_title

    page_lines: dict[int, list[str]] = {}
    for _, block in sorted(enumerate(blocks), key=lambda pair: (pair[1].page_num, pair[0])):
        if block.type != BlockType.TEXT:
            continue
        page_lines.setdefault(block.page_num, []).extend(
            line.strip() for line in str(block.content).splitlines() if line.strip()
        )

    first_page = min(page_lines, default=0)
    first_page_text = "".join(page_lines.get(first_page, []))
    has_notice_cover = bool(re.search(r"关于.{2,100}的通知", first_page_text))
    target_page = first_page + 1 if has_notice_cover else first_page

    def title_candidates(page_num: int) -> list[str]:
        candidates: list[str] = []
        for text in page_lines.get(page_num, []):
            compact = "".join(text.split())
            if not 4 <= len(compact) <= 100:
                continue
            if re.fullmatch(r"[\u4e00-\u9fa5]{2,20}(?:文件|公文)", compact):
                continue
            if re.search(r"〔\s*\d{4}\s*〕\s*\d+\s*号", compact):
                continue
            if re.match(r"^第\s*" + _NUMBER + r"\s*(?:编|章|节|条)", compact):
                continue
            candidates.append(text)
        return candidates

    candidates = title_candidates(target_page)
    title_suffix = re.compile(r"(?:办法|规定|细则|通知|决定|意见|章程|条例)(?:[（(].+?[）)])?$")
    for text in candidates:
        if title_suffix.search("".join(text.split())):
            return text
    if candidates:
        return candidates[0]

    # 第二页缺少可靠标题时，保留通知标题作为最后的正文线索。
    if has_notice_cover:
        notice_candidates = title_candidates(first_page)
        for text in notice_candidates:
            if re.search(r"关于.{2,100}的通知", "".join(text.split())):
                return text
    return file_title or "未命名制度"


def structure_policy_file(
    file_id: str, file_name: str, blocks: list[ContentBlock],
    metadata: Optional[dict[str, Any]] = None, structure_version: str = STRUCTURE_VERSION,
    *, parts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """拆分同一文件中的制度，分别建立条款、效力和检索索引。"""
    if parts is None:
        from .document_parts import split_policy_document
        parts = split_policy_document(blocks, dict(metadata or {}), file_name)
    old_relations = []
    if len(parts) > 1:
        from .storage import get_policy_documents_for_file
        from storage.adapters import storage
        document_keys = {part['metadata'].get('document_key', '') for part in parts}
        for old in get_policy_documents_for_file(file_id):
            if old.get('document_key', '') not in document_keys:
                continue
            old_relations.extend(storage.relational.query(
                'policy_document_relations', where='source_policy_id = %s',
                params=(old['policy_id'],), limit=100000))
    documents = [structure_policy_document(file_id, file_name, part['blocks'],
                    part['metadata'], structure_version) for part in parts]
    if old_relations:
        from .storage import get_policy_clauses
        current_clauses = [clause for doc in documents for clause in get_policy_clauses(doc['policy_id'])]
        for relation in old_relations:
            evidence = ''.join(str(relation.get('evidence_text') or '').split())
            matches = [clause for clause in current_clauses if evidence and
                       evidence in ''.join(str(clause.get('raw_text') or '').split())]
            # 只迁移原文证据唯一匹配的关系，保留人工审核结论和关系 ID。
            if len(matches) == 1:
                clause = matches[0]
                storage.relational.update_rows('policy_document_relations', {
                    'source_policy_id': clause['policy_id'], 'evidence_clause_id': clause['clause_id'],
                    'page_start': clause['page_start'], 'page_end': clause['page_end'],
                }, 'relation_id = %s', (relation['relation_id'],))
            else:
                insert_review_item(ReviewItem(review_id=f'review_{uuid.uuid4().hex}',
                    policy_id=relation['source_policy_id'], issue_type='split_relation_needs_review',
                    description='拆分制度后无法唯一定位原废止证据，请复核关系归属。',
                    payload={'relation_id': relation['relation_id']}))
    return {
        'documents': documents,
        'clause_count': sum(d['clause_count'] for d in documents),
        'parse_quality': min(d['parse_quality'] for d in documents),
    }


def structure_policy_document(
    file_id: str,
    file_name: str,
    blocks: list[ContentBlock],
    metadata: Optional[dict[str, Any]] = None,
    structure_version: str = STRUCTURE_VERSION,
) -> dict[str, Any]:
    """自动保存一份制度及其条款，返回结构化统计。"""
    metadata = dict(metadata or {})
    metadata.setdefault("title", _guess_title(file_name, blocks))
    policy_id = upsert_policy_document(
        file_id=file_id,
        file_name=file_name,
        metadata=metadata,
        parse_quality=0.0,
        structure_version=structure_version,
        structure_status=PolicyStructureStatus.RUNNING,
    )
    try:
        clauses = build_policy_clauses(policy_id, blocks, structure_version)
        quality = calculate_policy_parse_quality(blocks, clauses)
        if not clauses:
            raise ValueError("未识别到任何制度条款")
        replace_policy_clauses(policy_id, clauses, structure_version)
        try:
            # 时间治理失败不应推翻已经完成的条款结构化结果。
            from .governance import apply_effective_date_governance

            apply_effective_date_governance(
                policy_id,
                [str(block.content or "") for block in blocks if block.type == BlockType.TEXT],
                str(metadata.get("issue_date") or "") or None,
                str(metadata.get("effective_date") or "") or None,
            )
        except Exception as exc:
            try:
                insert_review_item(ReviewItem(
                    review_id=f"review_{uuid.uuid4().hex}", policy_id=policy_id,
                    issue_type="effective_date_governance_error",
                    description=f"制度生效日期识别失败: {str(exc)[:1000]}",
                ))
            except Exception:
                pass
        # replace_policy_clauses 已标记成功，这里只补写实际质量分数。
        from storage.adapters import storage
        storage.relational.update_rows(
            "policy_documents",
            {"parse_quality": quality},
            '"policy_id" = %s',
            (policy_id,),
        )
        if quality < 0.75:
            insert_review_item(
                ReviewItem(
                    review_id=f"review_{uuid.uuid4().hex}",
                    policy_id=policy_id,
                    issue_type="low_parse_quality",
                    description=f"制度结构化质量分数为 {quality:.3f}",
                    payload={"parse_quality": quality, "structure_version": structure_version},
                )
            )
        try:
            # 索引失败不影响结构化结果，后续可通过批次重建命令恢复。
            from .retrieval import sync_policy_clause_index

            indexed_clause_count = sync_policy_clause_index(policy_id)
            index_status = "succeeded"
            index_error = ""
        except Exception as exc:
            indexed_clause_count = 0
            index_status = "failed"
            index_error = str(exc)
            insert_review_item(
                ReviewItem(
                    review_id=f"review_{uuid.uuid4().hex}",
                    policy_id=policy_id,
                    issue_type="policy_clause_index_error",
                    description=f"条款索引同步失败: {index_error[:1000]}",
                    payload={"structure_version": structure_version},
                )
            )
        return {
            "policy_id": policy_id,
            "clause_count": len(clauses),
            "indexed_clause_count": indexed_clause_count,
            "index_status": index_status,
            "parse_quality": quality,
            "structure_version": structure_version,
            "status": PolicyStructureStatus.SUCCEEDED.value,
        }
    except Exception as exc:
        mark_policy_structure_failed(policy_id, str(exc), structure_version)
        raise
