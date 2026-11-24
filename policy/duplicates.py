"""同标题、同文号制度的导入确认，不自动判断正文是否相同。"""
from core.policy_titles import normalize_policy_title
from metadata.document_number import normalize_document_number


def find_duplicate_policies(file_id: str, title: str, doc_number: str) -> list[dict]:
    """仅匹配其他文件的已完成制度，文号兼容括号和顺序号格式。"""
    from .storage import ensure_policy_tables, TABLE_POLICY_DOCUMENTS
    from storage.adapters import storage
    ensure_policy_tables()
    rows = storage.relational.query(
        TABLE_POLICY_DOCUMENTS,
        "regexp_replace(title, '[[:space:]]', '', 'g') = %s "
        "AND file_id <> %s AND structure_status = 'succeeded' ORDER BY policy_id",
        10001, (title, file_id),
    )
    if len(rows) >= 10001:
        raise ValueError("同名制度超过核对上限，已停止导入，请先检查数据")
    return [row for row in rows if normalize_document_number(row.get('doc_number') or '') == doc_number]


def confirm_policy_import(file_id, file_name, metadata, confirmation=None):
    """单独确认一项制度；没有交互回调时保留待确认。"""
    title = normalize_policy_title(metadata.get('title') or '')
    number = normalize_document_number(metadata.get('doc_number') or '')
    if not title or not number:
        return 'continue', []
    candidates = [
        {key: existing.get(key) for key in ('policy_id', 'file_id', 'file_name', 'title', 'doc_number')}
        for existing in find_duplicate_policies(file_id, title, number)
    ]
    if not candidates:
        return 'continue', []
    report = {
        'file_id': file_id, 'file_name': file_name, 'title': metadata['title'],
        'doc_number': metadata['doc_number'], 'candidates': candidates,
    }
    action = confirmation(report) if confirmation is not None else 'pending'
    if action not in {'continue', 'skip', 'pending'}:
        action = 'pending'
    return action, candidates


def prompt_duplicate_import(report: dict) -> str:
    """回车默认跳过；输入流不可用时保留待确认，不擅自入库。"""
    print('\n检测到标题、文号相同的已入库制度')
    print(f"新文件：{report['file_name']}")
    print(f"当前制度：{report['title']}（{report['doc_number']}）")
    for candidate in report['candidates']:
        print(f"已有文件：{candidate.get('file_name') or candidate.get('file_id')}")
        print(f"制度标题：{candidate.get('title', '')}")
        print(f"文号：{candidate.get('doc_number', '')}")
    print('继续将保留当前制度的两份来源；跳过仅影响当前制度。')
    while True:
        try:
            answer = input('是否导入当前制度？[y]继续 [n]跳过（默认） [q]稍后确认此文件：').strip().lower()
        except (EOFError, OSError):
            print('无法读取确认输入，已保留为待确认。')
            return 'pending'
        if answer == 'y':
            return 'continue'
        if answer in {'', 'n'}:
            return 'skip'
        if answer == 'q':
            return 'pending'
        print('请输入 y、n 或 q。')
