# metadata/__init__.py
from typing import Any, Dict, List

from core.models import ContentBlock
from .academic import extract_academic_metadata
from .form import extract_form_metadata
from .policy import extract_policy_metadata

def extract_document_metadata(
    blocks: List[ContentBlock], doc_type: str, file_name: str = "", *, source_path: str = "",
) -> Dict[str, Any]:
    """
    根据文档类型路由到对应的元数据抽取模块
    """
    if doc_type == "academic_paper":
        meta = extract_academic_metadata(blocks)
    elif doc_type == "policy_regulation":
        meta = extract_policy_metadata(blocks, file_name, source_path=source_path)
    elif doc_type == "admin_form":
        meta = extract_form_metadata(blocks)
    else:
        meta = {}
    if not meta.get('title') and not meta.get('policies'):
        from .title import infer_document_title
        meta['title'] = infer_document_title(blocks, file_name)
    return meta
