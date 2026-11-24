"""通过本地 OpenAI 兼容服务调用 MinerU 的 PDF 解析器。"""
from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import fitz
import httpx

from core.config import MinerUConfig, app_config
from core.models import BlockType, ContentBlock, MinerUTaskStatus
from core.policy_signatures import has_policy_footer_page_number
from core.structured_tables import merge_continued_tables
from .base import ParserStrategy
from .pdf_tables import extract_structured_page


_PAGE_NUMBER_RE = re.compile(
    r'(?:(?P<plain>[0-9]{1,5})|第(?P<label>[0-9]{1,5})页(?:[，,、/]?共[0-9]{1,5}页)?|'
    r'(?P<dash>[-—–－])(?P<framed>[0-9]{1,5})(?P=dash))'
)


class MinerUTruncatedOutput(RuntimeError):
    """服务端明确以长度限制结束，正文不能作为完整解析结果使用。"""


def _extract_text_table_page(page: fitz.Page) -> Optional[str]:
    """只对有完整文字层的简单网格表恢复 Markdown，保留表外文字与空单元格。"""
    source = page.get_text()
    if not source.strip() or '\ufffd' in source or page.get_images():
        return None
    tables = page.find_tables().tables
    if not tables:
        return None
    boxes = [fitz.Rect(table.bbox) for table in tables]
    if any(left.intersects(right) for i, left in enumerate(boxes) for right in boxes[i + 1:]):
        return None
    parts = []
    recovered_text = []
    for table in tables:
        # 合并单元格需要额外还原跨度，交给分区 OCR，避免伪造普通网格。
        if any(cell is None for row in table.rows for cell in row.cells):
            return None
        rows = table.extract()
        if not rows or any(len(row) != table.col_count for row in rows):
            return None
        recovered_text.extend(cell or '' for row in rows for cell in row)
        markdown_rows = []
        for index, row in enumerate(rows):
            cells = [(cell or '').replace('\\', '\\\\').replace('|', '\\|').replace('\n', '<br>')
                     for cell in row]
            markdown_rows.append('| ' + ' | '.join(cells) + ' |')
            if index == 0:
                markdown_rows.append('| ' + ' | '.join(['---'] * table.col_count) + ' |')
        parts.append((table.bbox[1], table.bbox[0], '\n'.join(markdown_rows)))
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            if any(fitz.Rect(line['bbox']).intersects(box) for box in boxes):
                continue
            text = ''.join(span['text'] for span in line['spans'])
            recovered_text.append(text)
            parts.append((line['bbox'][1], line['bbox'][0], text))
    # 逐字符核对文字层，拒绝丢行、重复、缺字的恢复结果；不比较原始存储顺序。
    characters = lambda value: Counter(char for char in value if not char.isspace())
    if characters(source) != characters(''.join(recovered_text)):
        return None
    return '\n\n'.join(text for _, _, text in sorted(parts))


def _split_page_region(page: fitz.Page, region: fitz.Rect, dpi: int) -> list[fitz.Rect]:
    """在中间区域墨迹最少的横线上切分，不重叠、不丢失页面区域。"""
    pixmap = page.get_pixmap(dpi=dpi, clip=region, colorspace=fitz.csGRAY)
    samples = pixmap.samples
    middle = pixmap.height // 2
    candidates = range(int(pixmap.height * 0.35), int(pixmap.height * 0.65) + 1)
    cut = min(candidates, key=lambda y: (
        sum(pixel < 200 for pixel in samples[y * pixmap.stride:y * pixmap.stride + pixmap.width]),
        abs(y - middle),
    ))
    y = (pixmap.y + cut) * 72 / dpi
    return [fitz.Rect(region.x0, region.y0, region.x1, y),
            fitz.Rect(region.x0, y, region.x1, region.y1)]


def _remove_page_numbers(blocks: List[ContentBlock]) -> List[ContentBlock]:
    """只清理逐页结果的页边界，纯数字须有相邻页的连续编号佐证。"""
    candidates = []
    numbered_edges = set()
    for index, block in enumerate(blocks):
        raw = block.raw or {}
        if raw.get('page_start') != raw.get('page_end'):
            # 合并返回的多页没有可靠的内部页边界，不能按独立数字猜测页码。
            continue
        lines = block.content.splitlines()
        nonempty = [i for i, line in enumerate(lines) if line.strip()]
        if not nonempty:
            continue
        for side, line_index in (('header', nonempty[0]), ('footer', nonempty[-1])):
            value = ''.join(lines[line_index].split()).strip('*')
            match = _PAGE_NUMBER_RE.fullmatch(value)
            if not match:
                continue
            number = int(match['plain'] or match['label'] or match['framed'])
            if number != block.page_num + 1:
                continue
            if match['plain']:
                if len(nonempty) < 2:
                    continue
                # 冒号后的独立数字可能是正文给出的数量，不能作为页码证据。
                if side == 'footer' and lines[nonempty[-2]].rstrip().endswith((':', '：')):
                    continue
            signed_footer = side == 'footer' and has_policy_footer_page_number([lines[i] for i in nonempty])
            candidates.append((index, line_index, block.page_num, side, not match['plain'] or signed_footer))
            numbered_edges.add((block.page_num, side))

    removed = {}
    for index, line_index, page, side, explicit in candidates:
        if explicit or (page - 1, side) in numbered_edges or (page + 1, side) in numbered_edges:
            removed.setdefault(index, set()).add(line_index)
    cleaned = list(blocks)
    for index, line_indices in removed.items():
        block = blocks[index]
        content = '\n'.join(line for i, line in enumerate(block.content.splitlines()) if i not in line_indices).strip()
        cleaned[index] = block.model_copy(update={'content': content})
    return cleaned


class MinerUParser(ParserStrategy):
    """把 PDF 页面转为图像后交给本地 MinerU 服务解析。"""

    def __init__(
        self,
        config: Optional[MinerUConfig] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.config = config or app_config.mineru
        self._client = client
        self._owns_client = client is None
        self._result_cache: Dict[str, List[ContentBlock]] = {}

    @property
    def client(self) -> httpx.Client:
        """延迟创建 HTTP 客户端，避免未使用解析器时建立资源。"""
        if self._client is None:
            self._client = httpx.Client(timeout=httpx.Timeout(self.config.timeout_seconds))
        return self._client

    def submit(self, file_path: str) -> str:
        """本地服务同步返回结果，因此提交后任务立即完成。"""
        task_id = f"local_mineru_{uuid.uuid4().hex[:12]}"
        self._result_cache[task_id] = self._parse_pdf(file_path)
        return task_id

    def get_status(self, task_id: str) -> MinerUTaskStatus:
        """读取已完成的本地解析结果。"""
        blocks = self._result_cache.get(task_id)
        if blocks is None:
            return MinerUTaskStatus(
                task_id=task_id,
                status="failed",
                progress=0.0,
                error="未找到本地 MinerU 任务",
            )
        return MinerUTaskStatus(
            task_id=task_id,
            status="done",
            progress=100.0,
            result=blocks,
        )

    def poll_until_done(
        self,
        task_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> MinerUTaskStatus:
        """本地请求是同步调用，无需轮询。"""
        return self.get_status(task_id)

    def parse(self, file_path: str, page_count: int = 0) -> List[ContentBlock]:
        """分批解析完整 PDF，按原页序返回供后续文本流程处理的块。"""
        return self._parse_pdf(file_path)

    def _parse_pdf(self, file_path: str) -> List[ContentBlock]:
        pages_per_request = self.config.pages_per_request
        if pages_per_request < 1:
            raise ValueError("MINERU_PAGES_PER_REQUEST 必须是大于等于 1 的整数")
        # 只展示接口位置，隐藏 URL 中可能携带的用户凭据、查询参数和片段。
        url = urlsplit(self.config.api_url)
        display_url = url._replace(netloc=url.netloc.rsplit("@", 1)[-1], query="", fragment="").geturl()
        print("[本地 MinerU] 已启用 backend=mineru", flush=True)
        print(f"[本地 MinerU] 接口：{display_url}；模型：{self.config.model}", flush=True)
        print(
            f"[本地 MinerU] DPI={self.config.dpi}；每次请求最多 {pages_per_request} 页；"
            f"处理完整 PDF；单次请求超时={self.config.timeout_seconds:g} 秒",
            flush=True,
        )
        blocks: List[ContentBlock] = []
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:12]
        with fitz.open(file_path) as document:
            page_count = len(document)
            if not page_count:
                raise RuntimeError("PDF 不包含可供 MinerU 解析的页面")
            native_pages = {}
            for page_index in range(page_count):
                try:
                    native = extract_structured_page(document[page_index], file_hash, Path(file_path).name)
                except Exception:
                    native = None
                if native is not None:
                    native_pages[page_index] = native
            # 结构化表格页独立处理，其余页面仍按原配置批量请求。
            batches = []
            start = 0
            while start < page_count:
                end = start + 1 if start in native_pages else min(start + pages_per_request, page_count)
                end = next((index for index in range(start + 1, end) if index in native_pages), end)
                batches.append((start, end))
                start = end
            batch_count = len(batches)
            print(f"[本地 MinerU] PDF 总页数={len(document)}，本次解析={page_count} 页", flush=True)
            for batch_index, (page_start, page_end) in enumerate(batches, 1):
                if page_start in native_pages:
                    native = native_pages[page_start]
                    try:
                        for block in native:
                            region = (block.raw or {}).get('ocr_region')
                            if region is not None:
                                # 表外图片可能含附件标题等文字，仅识别该区域，不能丢弃。
                                clip = fitz.Rect(region)
                                pixmap = document[page_start].get_pixmap(dpi=self.config.dpi, clip=clip)
                                encoded = base64.b64encode(pixmap.tobytes('png')).decode('ascii')
                                try:
                                    block.content = self._request_mineru([encoded])
                                except MinerUTruncatedOutput as error:
                                    block.content = self._recognize_split_regions(document[page_start], clip, error)
                    except (httpx.HTTPError, RuntimeError) as error:
                        raise RuntimeError(f'本地 MinerU 第 {page_start + 1} 页表外区域解析失败：{error}') from error
                    blocks.extend(native)
                    print(f'[本地 MinerU] 第 {batch_index}/{batch_count} 批，第 {page_start + 1}/{page_count} 页：合并单元格校验通过，保留结构与说明', flush=True)
                    continue
                if page_end - page_start == 1:
                    # 可靠文字层网格表直接还原，避免空白填报表诱发模型长输出或虚构数据。
                    try:
                        native_markdown = _extract_text_table_page(document[page_start])
                    except Exception:
                        # 网格检测失败时仍交给 MinerU，不能阻断正常页面识别。
                        native_markdown = None
                    if native_markdown is not None:
                        print(
                            f"[本地 MinerU] 第 {batch_index}/{batch_count} 批，第 {page_start + 1}/{page_count} 页："
                            f"文字层网格表校验通过，直接提取 {len(native_markdown)} 个字符",
                            flush=True,
                        )
                        blocks.append(ContentBlock(
                            block_id=f"mineru_{file_hash}_{page_start}", type=BlockType.TEXT,
                            page_num=page_start, content=native_markdown,
                            raw={"parser": "mineru", "source_file": Path(file_path).name,
                                 "page_start": page_start, "page_end": page_start,
                                 "extraction": "native_table"},
                        ))
                        continue
                pages = []
                sizes = []
                for page_index in range(page_start, page_end):
                    pixmap = document[page_index].get_pixmap(dpi=self.config.dpi)
                    pages.append(base64.b64encode(pixmap.tobytes("png")).decode("ascii"))
                    sizes.append(f"{pixmap.width}x{pixmap.height}")
                page_range = str(page_start + 1) if len(pages) == 1 else f"{page_start + 1}-{page_end}"
                print(
                    f"[本地 MinerU] 第 {batch_index}/{batch_count} 批，第 {page_range}/{page_count} 页："
                    f"PNG={','.join(sizes)}，发送 {len(pages)} 页，正在请求…",
                    flush=True,
                )
                try:
                    try:
                        markdown = self._request_mineru(pages)
                    except MinerUTruncatedOutput as error:
                        print(f"[本地 MinerU] 第 {page_range} 页输出截断，开始逐页恢复：{error}", flush=True)
                        blocks.extend(self._recover_truncated_batch(
                            document, page_start, page_end, file_path, file_hash, error,
                        ))
                        continue
                except (httpx.HTTPError, RuntimeError) as error:
                    raise RuntimeError(f"本地 MinerU 第 {page_range} 页解析失败：{error}") from error
                print(
                    f"[本地 MinerU] 第 {batch_index}/{batch_count} 批解析完成：{len(markdown)} 个字符",
                    flush=True,
                )
                blocks.append(ContentBlock(
                    block_id=f"mineru_{file_hash}_{page_start}",
                    type=BlockType.TEXT,
                    page_num=page_start,
                    content=markdown,
                    # 多页请求返回合并正文，记录实际范围，不伪造逐页对应关系。
                    raw={"parser": "mineru", "source_file": Path(file_path).name,
                         "page_start": page_start, "page_end": page_end - 1},
                ))
        blocks = _remove_page_numbers(merge_continued_tables(blocks))
        print(f"[本地 MinerU] 全文解析结束，共 {page_count} 页，按批次顺序返回 {len(blocks)} 个文本块", flush=True)
        return blocks

    def _recover_truncated_batch(
        self, document: fitz.Document, start: int, end: int, file_path: str,
        file_hash: str, error: MinerUTruncatedOutput,
    ) -> List[ContentBlock]:
        """多页批次先拆为单页，单页截断时优先文字层网格表，其次有限分区 OCR。"""
        blocks = []
        for index in range(start, end):
            page = document[index]
            recovery = 'single_page_retry'
            try:
                if end - start == 1:
                    raise error
                pixmap = page.get_pixmap(dpi=self.config.dpi)
                markdown = self._request_mineru([base64.b64encode(pixmap.tobytes('png')).decode('ascii')])
            except MinerUTruncatedOutput as truncated:
                # 文字层不可靠、图像页或复杂合并表格均继续走分区识别。
                try:
                    markdown = _extract_text_table_page(page)
                except Exception:
                    markdown = None
                if markdown is not None:
                    recovery = 'native_table'
                else:
                    recovery = 'split_regions'
                    markdown = self._recognize_split_regions(page, page.rect, truncated)
            print(f"[本地 MinerU] 第 {index + 1} 页恢复完成：{recovery}，{len(markdown)} 个字符", flush=True)
            blocks.append(ContentBlock(
                block_id=f'mineru_{file_hash}_{index}', type=BlockType.TEXT,
                page_num=index, content=markdown,
                raw={'parser': 'mineru', 'source_file': Path(file_path).name,
                     'page_start': index, 'page_end': index, 'recovery': recovery},
            ))
        return blocks

    def _recognize_split_regions(
        self, page: fitz.Page, region: fitz.Rect,
        error: MinerUTruncatedOutput, depth: int = 0,
    ) -> str:
        """最多二层切分（四个区域）；仍截断则失败，不能返回缺失内容。"""
        if depth >= 2 or region.height < 72:
            raise RuntimeError(f'第 {page.number + 1} 页分区识别仍被截断，已达到恢复上限：{error}') from error
        results = []
        for index, clip in enumerate(_split_page_region(page, region, self.config.dpi), 1):
            print(f'[本地 MinerU] 第 {page.number + 1} 页分区识别：层级 {depth + 1}，区域 {index}/2', flush=True)
            pixmap = page.get_pixmap(dpi=self.config.dpi, clip=clip)
            image = base64.b64encode(pixmap.tobytes('png')).decode('ascii')
            try:
                text = self._request_mineru([image])
            except MinerUTruncatedOutput as truncated:
                text = self._recognize_split_regions(page, clip, truncated, depth + 1)
            results.append(text)
        return '\n\n'.join(results)

    def _request_mineru(self, pages: List[str]) -> str:
        """发送 OpenAI 兼容的多模态请求并验证 MinerU 返回内容。"""
        if not self.config.api_key.strip():
            raise RuntimeError("MINERU_API_KEY 未配置，无法调用本地 MinerU 服务")
        max_retries = self.config.max_retries
        if max_retries < 0:
            raise ValueError("MINERU_MAX_RETRIES 必须是大于等于 0 的整数")

        content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{page}"},
            }
            for page in pages
        ]
        content.append(
            {
                "type": "text",
                # 保留文字识别任务前缀，只补充页码忽略和正文数字保留要求。
                "text": (
                    "\nText Recognition:\n"
                    "忽略页眉、页脚中用于标记页次的页码（如独立的1、- 1 -、第1页），不要将其混入正文。"
                    "保留正文中的所有数字和条款编号（如1、和（1）），包括数量、年份和表格数据。"
                    "按原文顺序输出识别文本，不改写、不概括、不添加解释。"
                    "只输出图中可见内容，不补写被裁掉的表头或行列，不重复生成，识别完成即停止。"
                ),
            }
        )
        # 只重试当前图像请求；之前已成功的页面和分区保留，不重跑整份文件。
        for attempt in range(max_retries + 1):
            try:
                response = self.client.post(
                    self.config.api_url,
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json={
                        "model": self.config.model,
                        "messages": [{"role": "user", "content": content}],
                    },
                )
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
                if attempt == max_retries:
                    print(
                        f"[本地 MinerU] 网络请求失败（{type(error).__name__}），已达到重试上限（{max_retries} 次）；"
                        "请检查 MinerU 接口及 HTTP_PROXY/HTTPS_PROXY/NO_PROXY 代理配置。",
                        flush=True,
                    )
                    raise
                delay = 2 ** min(attempt, 3)
                # 不输出异常原文，避免 URL 中的凭据或查询参数进入重试日志。
                print(
                    f"[本地 MinerU] 网络请求异常（{type(error).__name__}），"
                    f"{delay} 秒后重试当前请求（{attempt + 1}/{max_retries}），已完成页保留。",
                    flush=True,
                )
                time.sleep(delay)
            else:
                break

        try:
            response_data = response.json()
        except ValueError as error:
            raise RuntimeError("MinerU 服务返回了无效 JSON") from error

        try:
            choice = response_data["choices"][0]
            markdown = choice["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            raise RuntimeError("MinerU 服务响应缺少解析正文") from error

        if choice.get("finish_reason") == "length":
            usage = response_data.get("usage")
            token_details = ""
            if isinstance(usage, dict):
                token_details = "；" + "，".join(
                    f"{key}={usage[key]}"
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if isinstance(usage.get(key), int)
                )
            raise MinerUTruncatedOutput(
                f"输出被长度限制截断（finish_reason=length{token_details}），"
                "请检查模型是否重复生成及服务端长度限制"
            )
        if not isinstance(markdown, str):
            raise RuntimeError("MinerU 服务响应缺少解析正文")
        # 空白页正常结束时允许空正文，保留页码并继续处理后续页面。
        if not markdown.strip() and choice.get("finish_reason") != "stop":
            raise RuntimeError("MinerU 服务响应缺少解析正文")
        return markdown

    def close(self) -> None:
        """关闭由解析器创建的 HTTP 客户端。"""
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None
