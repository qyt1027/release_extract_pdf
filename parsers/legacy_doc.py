"""在本地直接提取旧版二进制 DOC 正文，无需 Word 或中间转换文件。"""
import hashlib
from pathlib import Path

from core.models import BlockType, ContentBlock


def parse_legacy_doc(file_path: str) -> list[ContentBlock]:
    """读取文字片段表并按原文顺序返回段落，不推测排版页码。"""
    try:
        from legacy_doc import LegacyDocError, extract_text
    except ImportError as error:
        raise RuntimeError(
            '本地 DOC 解析需要 legacy-doc，请执行 python -m pip install -r requirements.txt'
        ) from error

    path = Path(file_path)
    data = path.read_bytes()
    try:
        result = extract_text(data)
    except LegacyDocError as error:
        raise ValueError(f'旧版 DOC 解析失败（{path.name}）：{error}') from error
    paragraphs = [line.strip() for line in result.text.splitlines() if line.strip()]
    if not paragraphs:
        raise ValueError(f'旧版 DOC 正文为空：{path.name}')

    file_hash = hashlib.sha256(data).hexdigest()[:12]
    blocks = [
        ContentBlock(
            block_id=f'legacy_doc_{file_hash}_{index}', type=BlockType.TEXT,
            content=text, page_num=0,
            raw={'parser': result.parser, 'source_format': 'doc', 'source_file': path.name,
                 'page_mapping': 'unavailable'},
        )
        for index, text in enumerate(paragraphs)
    ]
    # 保存原文件的统计信息供追溯，不能用缓存的总页数伪造逐段页码。
    blocks[0].raw.update({
        'parser_version': result.version, 'document_metadata': dict(result.metadata),
        'source_metadata': {'title': paragraphs[0]},
        'warnings': list(result.warnings),
    })
    print(
        f'[本地 DOC] {path.name}：直接读取 {len(blocks)} 个段落，'
        f'{len(result.text)} 个字符（{result.parser}）',
        flush=True,
    )
    return blocks
