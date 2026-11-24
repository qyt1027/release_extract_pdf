"""制度族标题、生效日期和时间适用性的确定性规则。"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from core.policy_signatures import PUBLICATION_ACTION_PATTERN


_EFFECTIVE_VERB = r"(?:施行|实施|实行|执行|试行|生效)"
_ABSOLUTE_DATE_RE = re.compile(
    rf"(?:自|于|从)\s*(\d{{4}})\s*年\s*(\d{{1,2}})\s*月\s*(\d{{1,2}})\s*日\s*起\s*{_EFFECTIVE_VERB}"
)
_RELATIVE_DATE_RE = re.compile(rf"自\s*{PUBLICATION_ACTION_PATTERN}\s*之日\s*起\s*{_EFFECTIVE_VERB}")
_UNRESOLVED_EFFECTIVE_RE = re.compile(
    rf"\d{{4}}\s*年(?:度|\s*\d{{1,2}}\s*月)?\s*(?:起|开始)\s*{_EFFECTIVE_VERB}|"
    rf"(?:自|从)[^。；;\n]{{0,40}}通过\s*(?:之日)?\s*(?:起|开始)?\s*{_EFFECTIVE_VERB}"
)


def extract_effective_date(texts: Iterable[str], issue_date: str | None) -> dict[str, str | None]:
    """只在证据唯一时返回文档生效日期。"""
    dates: set[str] = set()
    relative = False
    unresolved = False
    for text in texts:
        value = str(text or "")
        relative = relative or bool(_RELATIVE_DATE_RE.search(value))
        unresolved = unresolved or bool(_UNRESOLVED_EFFECTIVE_RE.search(value))
        for match in _ABSOLUTE_DATE_RE.finditer(value):
            try:
                dates.add(date(int(match[1]), int(match[2]), int(match[3])).isoformat())
            except ValueError:
                continue
    if relative and issue_date:
        try:
            dates.add(date.fromisoformat(str(issue_date)).isoformat())
        except ValueError:
            pass
    if len(dates) > 1:
        return {"effective_date": None, "status": "conflict"}
    if len(dates) == 1:
        return {"effective_date": next(iter(dates)), "status": "identified"}
    return {"effective_date": None, "status": "needs_review" if relative or unresolved else "unknown"}


def normalize_family_title(title: str) -> str:
    """移除通知包装和版本标记，仅用于提出人工归族候选。"""
    value = "".join(str(title or "").split())
    match = re.fullmatch(r"关于印发《?(.+?)》?的通知", value)
    if match:
        value = match.group(1)
    value = re.sub(r"[（(](?:修订|试行|暂行)[）)]$", "", value)
    value = re.sub(r"(?:修订版|试行|暂行)$", "", value)
    return value.strip("《》")


def classify_temporal_status(document: dict[str, Any], as_of: str) -> str:
    """按左闭右开区间判断文档在指定日期是否适用。"""
    query_date = date.fromisoformat(as_of)
    effective = document.get("effective_date")
    expiry = document.get("expiry_date")
    effective_date = date.fromisoformat(str(effective)) if effective else None
    expiry_date = date.fromisoformat(str(expiry)) if expiry else None
    if effective_date and query_date < effective_date:
        return "inapplicable"
    if expiry_date and query_date >= expiry_date:
        return "inapplicable"
    if document.get('validity_status') == 'invalid' and not expiry_date:
        # 已确认废止但日期未知：当前排除，历史区间无法推定。
        return 'inapplicable' if query_date >= date.today() else 'unknown'
    if document.get('validity_status') == 'unknown':
        return 'unknown'
    if document.get('validity_status') == 'current' or (
        document.get('validity_status') == 'invalid' and expiry_date
    ):
        return 'applicable'
    return "applicable" if effective_date else "unknown"


def rank_temporal_candidates(
    candidates: list[dict[str, Any]],
    documents: dict[str, dict[str, Any]],
    as_of: str,
    top_k: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """排除明确不适用文档，按相关度保留候选并附加适用性信息。"""
    ranked: list[dict[str, Any]] = []
    applicable_by_family: dict[str, list[str]] = {}
    for candidate in candidates:
        policy_id = str((candidate.get("metadata") or {}).get("policy_id") or "")
        document = documents.get(policy_id, {})
        status = classify_temporal_status(document, as_of)
        if status == "inapplicable":
            continue
        item = {**candidate, "temporal_status": status, "policy_document": document}
        ranked.append(item)
        family_id = str(document.get("family_id") or "")
        if status == "applicable" and family_id:
            applicable_by_family.setdefault(family_id, []).append(policy_id)
    ranked.sort(key=lambda item: (-float(item.get("score") or 0), item["temporal_status"] != "applicable"))
    warnings = [
        f"制度族 {family_id} 在 {as_of} 存在多个适用版本: {', '.join(sorted(set(ids)))}"
        for family_id, ids in applicable_by_family.items() if len(set(ids)) > 1
    ]
    return ranked[:top_k], warnings
