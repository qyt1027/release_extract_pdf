"""显式统一历史制度的 applicable_unit，保留标题、原文和向量。"""
from core.unit_aliases import normalize_applicable_units
from storage.adapters import storage


def normalize_stored_applicable_units(*, dry_run=False, adapter=None):
    if adapter is None:
        from policy.storage import ensure_policy_tables
        ensure_policy_tables()
    db = adapter if adapter is not None else storage.relational
    report = {'dry_run': dry_run, 'updated': 0, 'changes': []}
    with db.transaction(), db.conn.cursor() as cur:
        cur.execute("SELECT applicable_unit, count(*) FROM policy_documents GROUP BY applicable_unit")
        for old, count in cur.fetchall():
            canonical = normalize_applicable_units(old)
            if canonical == old:
                continue
            report['changes'].append({'from': old, 'to': canonical, 'count': count})
            if not dry_run:
                cur.execute("UPDATE policy_documents SET applicable_unit=%s, updated_at=NOW() WHERE applicable_unit=%s",
                            (canonical, old))
                report['updated'] += cur.rowcount
    if not dry_run:
        from policy.retrieval import invalidate_policy_clause_bm25_index
        invalidate_policy_clause_bm25_index()
    return report
