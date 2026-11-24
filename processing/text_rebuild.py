"""为迁移冲突文件单独重建通用文本，不重置制度、条款或审核数据。"""
import hashlib
from pathlib import Path

from core.config import app_config
from parsers import PDFParser
from storage.adapters import storage
from .text import process_text_blocks


def _file_hash(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def rebuild_file_text(file_id: str, source_path: str | None = None) -> dict:
    """校验来源身份后，直接生成共享表文本，旧向量表保留供回查。"""
    db=storage.relational
    records=db.query('pdf_files', 'file_id=%s', 1, (file_id,))
    if not records:
        raise ValueError('文件记录不存在：' + file_id)
    record=records[0]
    if record.get('status') in {'running','processing'}:
        raise ValueError('文件正在处理，请先停止相关任务并释放占用')
    if record.get('embedding_model') and record['embedding_model'] != app_config.embedding.model_name:
        raise ValueError('文件登记模型与当前模型不一致，请切回原模型后重建文本')
    expected_hash=record.get('file_hash')
    if not expected_hash:
        raise ValueError('原文件没有 SHA256 记录，无法安全核对来源，已停止重建')
    if source_path:
        candidates=[Path(source_path).resolve()]
    else:
        items=db.query('pdf_batch_items', '(file_id=%s OR reuse_file_id=%s)', 10001, (file_id,file_id))
        if len(items) >= 10001:
            raise ValueError('来源记录超过读取上限，请使用 --text-source 指定原文件')
        candidates=sorted({Path(item['file_path']).resolve() for item in items if item.get('file_path')})
    source=None
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in {'.pdf','.doc','.docx'} and _file_hash(candidate)==expected_hash:
            source=candidate
            break
    if source is None:
        raise ValueError('未找到 SHA256 与原记录一致的源文件；请使用 --text-source 指定未修改的原文件')
    page_count=int(record.get('page_count') or 0)
    if source.suffix.lower()=='.pdf' and page_count<=0:
        import fitz
        with fitz.open(str(source)) as document:
            page_count=len(document)
    blocks=PDFParser().parse(str(source),page_count)
    if _file_hash(source)!=expected_hash:
        raise ValueError('源文件在解析过程中发生变化，已停止重建')
    for block in blocks:
        block.file_id=file_id
    documents=db.query('policy_documents', 'file_id=%s', 1, (file_id,))
    if documents:
        doc_type='policy_regulation'
    else:
        from classification.document import classify_document
        from .pipeline import build_document_classification_text
        doc_type=classify_document(str(source),record['file_name'],
            parsed_text=build_document_classification_text(blocks))['doc_type']
    count, _=process_text_blocks(blocks,file_id,doc_type,update_provenance=True,expected_file=record)
    if count<1:
        raise ValueError('没有可写入的文本向量，未替换现有文本')
    return {'file_id':file_id,'source_path':str(source),'text_chunks_stored':count,
            'storage_location':'pdf_text_chunks','legacy_tables_preserved':True}
