"""
文本处理管线：分块 → Embedding → 存入 pgvector 向量索引
"""
import re
from typing import Optional

from core.config import app_config
from core.models import BlockType, ContentBlock, TextChunk
from core.policy_signatures import (
    has_policy_footer_page_number,
    is_policy_closing_heading,
    policy_closing_provisions_start,
    policy_footer_size,
)
from storage.adapters import storage
# 懒加载 Embedding 模型，避免未安装时阻塞导入
_embedding_model: Optional[object] = None


# ============================================================
# 针对不同文档类型的重组逻辑
# ============================================================

def _merge_by_heading(text_blocks: list) -> list:
    """
    学术论文：按章节标题合并
    判断标准（按优先级）：
    1. MinerU 返回的 text_level == 2（二级标题）
    2. 正则匹配（作为兜底，应对 MinerU 漏标的情况）
    3. 排除过长文本（>80字，避免把正文段落误判为标题）
    """
    # ===== 写入处理前完整内容 =====
    with open("before.txt", "w", encoding="utf-8") as f:
        f.write(f"===== 处理前原始块 (共 {len(text_blocks)} 个) =====\n\n")
        for idx, block in enumerate(text_blocks):
            f.write(f"【块 {idx + 1}】页码: {block.page_num}\n")
            f.write(f"内容:\n{block.content}\n")
            f.write(f"原始json内容:\n{block.raw}\n")
            f.write("-" * 80 + "\n\n")

    heading_pattern = re.compile(
        r'^(Abstract|Introduction|Method|Experiment|Conclusion|References|'
        r'附录|第[一二三四五六七八九十]+章|'
        r'\d+\.?\s+[A-Za-z])',  # 数字 + 可选点 + 空格 + 字母
        re.I
    )
    sorted_blocks = sorted(text_blocks, key=lambda x: x.page_num)
    merged = []
    if not sorted_blocks:
        return merged


    current = {"text": "", "page_num": sorted_blocks[0].page_num}

    for block in sorted_blocks:
        text = block.content.strip()
        if not text:
            continue


        # ===== 核心判断逻辑（三个标准） =====
        # 标准 1：类型是 text（已满足，因为传入的就是 text_blocks）
        #            且 text_level == 2（MinerU 的二级标题标记）
        text_level = (block.raw or {}).get("text_level", 0) # 如果没有该属性，默认 0
        is_heading_by_level = (text_level == 2)

        # 标准 2：正则匹配
        is_heading_by_regex = bool(heading_pattern.match(text))

        # 标准 3：长度不过长（真正的标题一般不会超过 80 个字）
        is_too_long = len(text) > 80

        # 最终判定：符合 level 或 正则，且不能太长
        is_heading = (is_heading_by_level or is_heading_by_regex) and not is_too_long
        # ========================================

        if is_heading:
            # 遇到标题：保存上一个章节
            if current["text"]:
                merged.append(current)
            # 开启新章节（标题作为新 chunk 的开头）
            current = {"text": text, "page_num": block.page_num}
        else:
            # 普通段落：追加到当前章节
            if current["text"]:
                current["text"] += "\n" + text
            else:
                current["text"] = text
                current["page_num"] = block.page_num

    # 保存最后一个章节
    if current["text"]:
        merged.append(current)

    # ===== 写入处理后完整内容 =====
    with open("after.txt", "w", encoding="utf-8") as f:
        f.write(f"===== 处理后合并单元 (共 {len(merged)} 个) =====\n\n")
        for idx, chunk in enumerate(merged):
            f.write(f"【章节 {idx + 1}】起始页码: {chunk['page_num']}\n")
            f.write(f"内容:\n{chunk['text']}\n")
            f.write("=" * 80 + "\n\n")
    return merged


_POLICY_ARTICLE_HEADING = re.compile(
    r"^[ \t]*(?:\*\*)?第[ \t]*[0-9一二三四五六七八九十百千万零〇两]+[ \t]*条(?!款)", re.MULTILINE,
)


def _merge_by_article(text_blocks: list[ContentBlock]) -> list[dict]:
    """按条号断开正文，文末落款和版记独立保存。"""
    return _merge_policy_lines(text_blocks, _POLICY_ARTICLE_HEADING)


def _merge_by_policy_heading(text_blocks: list) -> list:
    """无正式条号的制度，按章标题和原有编号分割，保留完整正文。"""
    heading_pattern = re.compile(
        r"^(?:第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*(?:编|章|节)|"
        r"[一二三四五六七八九十百千万零〇两]+\s*[、．.]\s*|"
        r"[（(]\s*(?:[一二三四五六七八九十百千万零〇两]+|\d+)\s*[）)]\s*|"
        r"\d+\s*[、．.](?!\d)\s*|\d+(?:[.．]\d+)+[ \t]+)"
    )
    return _merge_policy_lines(text_blocks, heading_pattern, split_unnumbered_closing=True)


def _merge_policy_lines(
    text_blocks: list[ContentBlock], heading_pattern: re.Pattern, *, split_unnumbered_closing: bool = False,
) -> list[dict]:
    """逐行检查条款边界，沿用结构化条款的文末边界。"""
    lines = [
        (line.strip(), block.page_num)
        for block in sorted(text_blocks, key=lambda item: item.page_num)
        for line in ([block.content] if (block.raw or {}).get('structured_table') else block.content.splitlines())
        if line.strip()
    ]
    texts = [text for text, _ in lines]
    if has_policy_footer_page_number(texts):
        # 旧解析块也可能残留末页页号，识别已确认的落款后先移除再划分检索单元。
        lines.pop()
        texts.pop()
    footer_start = len(texts) - policy_footer_size(texts, include_standalone_date=True)
    closing_start = policy_closing_provisions_start(texts, footer_start) if split_unnumbered_closing else footer_start
    merged = []
    current = {"text": "", "page_num": 0}
    for index, (text, page_num) in enumerate(lines):
        split_closing = False
        if index == closing_start < footer_start:
            first_line, separator, _ = current["text"].partition("\n")
            heading = heading_pattern.match(first_line)
            split_closing = bool(separator and heading and not is_policy_closing_heading(first_line[heading.end():]))
        # 解析器可能将多个编号放在同一块中，逐行检查编号和文末边界。
        if current["text"] and (heading_pattern.match(text) or split_closing or index == footer_start):
            merged.append(current)
            current = {"text": "", "page_num": page_num}
        if not current["text"]:
            current["page_num"] = page_num
        current["text"] = f"{current['text']}\n{text}".strip()
    if current["text"]:
        merged.append(current)
    return merged


def _merge_by_page(text_blocks: list) -> list:
    """
    行政表单：按页码合并（不跨页），每一页作为一个独立的逻辑单元
    """
    from collections import defaultdict
    page_map = defaultdict(list)
    for block in text_blocks:
        page_map[block.page_num].append(block.content.strip())

    merged = []
    for page_num, texts in sorted(page_map.items()):
        merged.append({
            "text": "\n".join([t for t in texts if t]),
            "page_num": page_num
        })
    return merged

def _get_embedding_model():
    """懒加载 sentence-transformers 模型"""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        try:
            # 先尝试仅本地加载
            _embedding_model=SentenceTransformer(
            app_config.embedding.model_name,
            device=app_config.embedding.device,
            local_files_only=True,
            )
            print(f"成功从本地加载模型: {app_config.embedding.model_name}")
            return _embedding_model
        except Exception as e:
            print(f"本地未找到模型 {app_config.embedding.model_name}，尝试在线下载...")
            _embedding_model = SentenceTransformer(
                app_config.embedding.model_name,
                device=app_config.embedding.device,
            )
            print(f"成功下载模型: {app_config.embedding.model_name}")
            return _embedding_model
    # 模型已经缓存时也必须返回实例，不能隐式返回 None。
    return _embedding_model

def chunk_text(
    text: str, file_id: str, block_id: str, page_num: int = 0
) -> list[TextChunk]:
    """
    将文本按段落切分为固定大小的块。
    策略：优先按段落边界切分，单段过长则强制按 chunk_size 截断。
    """
    chunk_size = app_config.embedding.chunk_size
    chunk_overlap = app_config.embedding.chunk_overlap

    # 按段落切分（双换行或单换行）
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[TextChunk] = []
    current_chunk = ""
    chunk_index = 0

    for para in paragraphs:
        # 如果加入当前段落后不超过 chunk_size，合并
        if len(current_chunk) + len(para) + 1 <= chunk_size:
            current_chunk = (current_chunk + "\n" + para).strip() if current_chunk else para
        else:
            # 保存当前块
            if current_chunk:
                chunks.append(_make_chunk(
                    current_chunk, file_id, block_id, page_num, chunk_index
                ))
                chunk_index += 1
            # 新段落作为新块的开始（如果段落本身超长，强制截断）
            if len(para) > chunk_size:
                # 超长段落强制按 chunk_size 截断，带 overlap
                start = 0
                while start < len(para):
                    sub = para[start:start + chunk_size]
                    chunks.append(_make_chunk(sub, file_id, block_id, page_num, chunk_index))
                    chunk_index += 1
                    start += chunk_size - chunk_overlap
                current_chunk = ""
            else:
                current_chunk = para

    # 最后一个块
    if current_chunk:
        chunks.append(_make_chunk(current_chunk, file_id, block_id, page_num, chunk_index))

    return chunks


def _make_chunk(
    text: str, file_id: str, block_id: str, page_num: int, chunk_index: int
) -> TextChunk:
    """构造 TextChunk 对象"""
    return TextChunk(
        chunk_id=f"{block_id}_chunk_{chunk_index}",
        file_id=file_id,
        block_id=block_id,
        page_num=page_num,
        text=text,
        chunk_index=chunk_index,
        token_count=len(text),  # 中文字符数近似 token 数
    )


def embed_chunks(chunks: list[TextChunk]) -> list[TextChunk]:
    """
    对文本块批量生成 Embedding 向量。
    使用 Embedding 模型生成向量。
    """
    if not chunks:
        return chunks

    model = _get_embedding_model()
    if model is None:
        raise RuntimeError("Embedding 模型未加载，请检查 sentence-transformers 安装")

    texts = [c.text for c in chunks]
    embeddings = model.encode(texts, normalize_embeddings=True).tolist()

    for chunk, emb in zip(chunks, embeddings):
        chunk.embedding = emb

    return chunks


def store_chunks(chunks: list[TextChunk], *, update_provenance: bool = False, expected_file: dict | None = None) -> int:
    """将文本块及其向量写入 pgvector"""
    if not chunks or not any(c.embedding for c in chunks):
        return 0

    from storage.text_chunks import TextChunkStore
    if expected_file is not None:
        return TextChunkStore().replace(chunks, update_provenance=update_provenance, expected_file=expected_file)
    if update_provenance:
        return TextChunkStore().replace(chunks, update_provenance=True)
    return TextChunkStore().replace(chunks)


def process_text_blocks(
    blocks: list[ContentBlock], file_id: str,doc_type: str = "other", *, update_provenance: bool = False, expected_file: dict | None = None
) -> tuple[int, list[TextChunk]]:
    """
    文本块处理主入口：筛选文本块 → 重组(按照逻辑分大块，比如一个论文章节分为一大块） → 分块 → Embedding → 存储
    返回 (存入的块数, TextChunk列表)
    """

    text_blocks = [b for b in blocks if b.type == BlockType.TEXT
               and b.content.strip()
               and (b.raw or {}).get("type") not in (
                    "header",
                    "footer",
                    "page_number",
                    "page_footnote",
                ) #过滤页眉页脚
               ]

    if not text_blocks:
        return 0, []
    # ========== 【新增逻辑】根据文档类型进行重组 ==========
    if doc_type == "academic_paper":
        merged_units = _merge_by_heading(text_blocks)
        print(f"[重组] 学术论文: {len(text_blocks)} 个原始块 → {len(merged_units)} 个章节单元")
    elif doc_type == "policy_regulation":
        number = r"[0-9一二三四五六七八九十百千万零〇两]+"
        chapter_pattern = re.compile(rf"^\s*第\s*{number}\s*章", re.M)
        chapter_count = sum(len(chapter_pattern.findall(block.content)) for block in text_blocks)
        article_count = sum(len(_POLICY_ARTICLE_HEADING.findall(block.content)) for block in text_blocks)
        if article_count == 0:
            merged_units = _merge_by_policy_heading(text_blocks)
            unit_name = "编号单元"
        else:
            merged_units = _merge_by_article(text_blocks)
            unit_name = "条款单元"
        print(
            f"[重组] 政策制度: {len(text_blocks)} 个原始块 → {len(merged_units)} 个{unit_name}"
            f"（{chapter_count} 章，{article_count} 条）"
        )
    elif doc_type == "admin_form":
        merged_units = _merge_by_page(text_blocks)
        print(f"[重组] 行政表单: {len(text_blocks)} 个原始块 → {len(merged_units)} 个页面单元")
    else:
        # 其他类型：不做合并，每个原始块独立处理（保持你原有的行为）
        merged_units = [{"text": b.content, "page_num": b.page_num} for b in text_blocks]
        print(f"[重组] 其他类型: 不合并，保留 {len(merged_units)} 个独立块")
    # ====================================================

    all_chunks: list[TextChunk] = []
    for unit_index, unit in enumerate(merged_units):
        text = unit.get("text", "").strip()
        if not text:
            continue

        page_num = unit.get("page_num", 0)
        block_id = unit.get(
            "block_id",
            f"{file_id}_merged_{unit_index}"
        )

        chunks = chunk_text(
            text=text,
            file_id=file_id,
            block_id=block_id,
            page_num=page_num,
        )
        all_chunks.extend(chunks)

    if not all_chunks:
        return 0, []

    # Embedding
    all_chunks = embed_chunks(all_chunks)

    # 存储
    if expected_file is not None:
        stored = store_chunks(all_chunks, update_provenance=update_provenance, expected_file=expected_file)
    else:
        stored = store_chunks(all_chunks, update_provenance=True) if update_provenance else store_chunks(all_chunks)

    return stored, all_chunks
