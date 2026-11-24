"""面向制度库页面的只读数据接口。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from storage.adapters import storage
from core.unit_aliases import applicable_unit_paths, applicable_unit_variants, normalize_applicable_units
from metadata.policy_scope import query_applicable_units
from .storage import (
    TABLE_POLICY_DOCUMENTS,
    ensure_policy_tables,
    get_policy_clauses,
    get_policy_document,
)


PUBLIC_DOCUMENT_FIELDS = (
    "policy_id", "title", "doc_number", "issuing_department", "applicable_unit", "issue_date",
    "issue_month", "effective_date", "expiry_date", "validity_status", "version",
    "original_pdf_url", "structure_status", "notice_title", "source_page_start", "source_page_end",
)
PUBLIC_CLAUSE_FIELDS = (
    "clause_id", "parent_clause_id", "level", "chapter_path", "article_no",
    "paragraph_no", "item_no", "raw_text", "page_start", "page_end", "sequence_no",
)


def _public_row(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """只向浏览器发送展示字段，并将日期转换为 JSON 可编码字符串。"""
    result = {}
    for field in fields:
        value = row.get(field)
        result[field] = value.isoformat() if isinstance(value, (date, datetime)) else value
        if field == 'applicable_unit':
            result[field] = normalize_applicable_units(value)
            result['applicable_unit_paths'] = applicable_unit_paths(result[field])
    return result


def list_policies(query: str = "", status: str = "", limit: int = 30, offset: int = 0) -> dict[str, Any]:
    """按标题、文号、发布部门和适用单位检索制度，返回稳定分页结果。"""
    ensure_policy_tables()
    # 清理后保留的空标题占位记录不属于可浏览制度；计数和分页使用同一条件。
    conditions: list[str] = [f'''NOT (
        COALESCE(TRIM(title), '') = '' AND structure_status = 'pending'
        AND NOT EXISTS (
            SELECT 1 FROM "policy_clauses" AS current_clause
            WHERE current_clause.policy_id = "{TABLE_POLICY_DOCUMENTS}".policy_id
              AND current_clause.structure_version = "{TABLE_POLICY_DOCUMENTS}".structure_version
              AND current_clause.is_active = TRUE
        )
    )''']
    params: list[Any] = []
    if query.strip():
        search_condition = (
            "title ILIKE %s OR doc_number ILIKE %s OR issuing_department ILIKE %s "
            "OR EXISTS (SELECT 1 FROM unnest(applicable_unit) AS units(unit) WHERE unit ILIKE %s)"
        )
        pattern = f"%{query.strip()}%"
        params.extend([pattern, pattern, pattern, pattern])
        units = query_applicable_units(query, set())
        variants = sorted({value for unit in units for value in applicable_unit_variants(unit)})
        if variants:
            search_condition += " OR applicable_unit && %s"
            params.append(variants)
        conditions.append('(' + search_condition + ')')
    if status:
        conditions.append("validity_status = %s")
        params.append(status)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    from psycopg2.extras import RealDictCursor

    with storage.relational.conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(f'SELECT COUNT(*) AS total FROM "{TABLE_POLICY_DOCUMENTS}"{where}', tuple(params))
        total = int(cursor.fetchone()["total"])
        cursor.execute(
            f'SELECT * FROM "{TABLE_POLICY_DOCUMENTS}"{where} '
            'ORDER BY title, policy_id LIMIT %s OFFSET %s',
            (*params, limit, offset),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [_public_row(row, PUBLIC_DOCUMENT_FIELDS) for row in rows],
    }


def get_policy_detail(policy_id: str) -> dict[str, Any] | None:
    """返回制度元数据和当前结构版本的有序条款。"""
    document = get_policy_document(policy_id=policy_id)
    if document is None:
        return None
    clauses = get_policy_clauses(policy_id)
    return {
        "policy": _public_row(document, PUBLIC_DOCUMENT_FIELDS),
        "clauses": [_public_row(item, PUBLIC_CLAUSE_FIELDS) for item in clauses],
    }
