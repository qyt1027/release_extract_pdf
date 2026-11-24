"""本地 MinerU 解析器的行为测试。"""
from __future__ import annotations

from contextlib import redirect_stdout
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import fitz
import httpx


for _key, _value in {
    "CLOUDMINERU_API_KEY": "test",
    "PG_HOST": "test",
    "PG_PORT": "5432",
    "PG_USER": "test",
    "PG_PASSWORD": "test",
    "PG_DATABASE": "test",
    "MINIO_ENDPOINT": "test",
    "MINIO_ACCESS_KEY": "test",
    "MINIO_SECRET_KEY": "test",
    "MINIO_BUCKET_PDF": "test",
    "MINIO_BUCKET_IMAGES": "test",
}.items():
    os.environ.setdefault(_key, _value)


class MinerUConfigurationIsolationTests(unittest.TestCase):
    """验证各解析后端只在实际使用时要求自身的凭据。"""

    def test_local_parser_runs_without_a_cloud_key_in_a_fresh_process(self) -> None:
        """防止其他测试预设的云端密钥掩盖全局配置导入错误。"""
        environment = dict(os.environ)
        environment.pop("CLOUDMINERU_API_KEY", None)
        environment.update({
            "MINERU_API_KEY": "local-test-key",
            "MINERU_API_URL": "http://mineru.test/v1/chat/completions",
            "MINERU_PAGES_PER_REQUEST": "1",
            "MINERU_DPI": "72",
            "PG_HOST": "test", "PG_PORT": "5432", "PG_USER": "test",
            "PG_PASSWORD": "test", "PG_DATABASE": "test",
            "MINIO_ENDPOINT": "test", "MINIO_ACCESS_KEY": "test",
            "MINIO_SECRET_KEY": "test", "MINIO_BUCKET_PDF": "test",
            "MINIO_BUCKET_IMAGES": "test",
        })
        script = '''
import sys
import dotenv
import httpx
from unittest.mock import patch
dotenv.load_dotenv = lambda *args, **kwargs: None
from core.config import app_config
from parsers.dispatcher import PDFParser
assert not app_config.cloudmineru.batch_api_key
with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
    200, json={"choices": [{"finish_reason": "stop", "message": {"content": "本地正文"}}]}))) as client:
    with patch("parsers.mineru.httpx.Client", return_value=client):
        parser = PDFParser(backend="mineru")
        try:
            blocks = parser.parse(sys.argv[1])
        finally:
            parser.close()
assert len(blocks) == 1 and blocks[0].content == "本地正文"
print("本地解析成功")
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pdf"
            MinerUParserTests._create_pdf(path, page_count=1)
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", "-c", script, str(path)],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "本地解析成功")

    def test_cloud_batch_rejects_missing_or_blank_keys_when_used(self) -> None:
        """防止延迟配置检查后，云端精准解析匿名请求外部服务。"""
        from core.config import CloudMinerUConfig
        from parsers.cloud_client import CloudMinerUClient
        from parsers.cloud_mineru import CloudMineruParser

        for parser_class in (CloudMineruParser, CloudMinerUClient):
            for value in (None, "", "   "):
                with self.subTest(parser=parser_class.__name__, value=value), patch.dict(os.environ):
                    if value is None:
                        os.environ.pop("CLOUDMINERU_API_KEY", None)
                    else:
                        os.environ["CLOUDMINERU_API_KEY"] = value
                    parser = parser_class(config=CloudMinerUConfig(), mode="v4")
                    try:
                        with self.assertRaisesRegex(ValueError, "CLOUDMINERU_API_KEY"):
                            parser.client
                    finally:
                        parser.close()

    def test_cloud_batch_uses_the_key_from_its_own_configuration(self) -> None:
        """防止实例配置的云端密钥被类加载时的旧值覆盖或漏传。"""
        from core.config import CloudMinerUConfig
        from parsers.cloud_client import CloudMinerUClient
        from parsers.cloud_mineru import CloudMineruParser

        original_client = httpx.Client
        for parser_class in (CloudMineruParser, CloudMinerUClient):
            captured = []

            def handler(request: httpx.Request) -> httpx.Response:
                captured.append(request.headers.get("Authorization"))
                return httpx.Response(200, json={"code": 0})

            def create_client(**kwargs):
                return original_client(transport=httpx.MockTransport(handler), **kwargs)

            with self.subTest(parser=parser_class.__name__), patch.dict(
                os.environ, {"CLOUDMINERU_API_KEY": "configured-cloud-test-key"}
            ):
                config = CloudMinerUConfig(batch_api_url="http://cloudmineru.test/batch")
                parser = parser_class(config=config, mode="v4")
                with patch("httpx.Client", side_effect=create_client):
                    try:
                        parser.client.get("")
                    finally:
                        parser.close()
            self.assertEqual(captured, ["Bearer configured-cloud-test-key"])


class CloudMinerUPollingTests(unittest.TestCase):
    """验证云端轮询状态可观察，完成状态不会被继续等待。"""

    @staticmethod
    def _create_parser(handler):
        from core.config import CloudMinerUConfig
        from parsers.cloud_mineru import CloudMineruParser

        config = CloudMinerUConfig(batch_api_key="test-key")
        parser = CloudMineruParser(config=config, mode="v4")
        parser._client = httpx.Client(transport=httpx.MockTransport(handler))
        return parser

    def test_poll_prints_cloud_states_and_stops_when_done(self) -> None:
        """防止轮询期间只有沉默等待，或已完成仍继续查询。"""
        clock = {"now": 0.0}
        states = iter(["waiting-file", "pending", "running", "done"])
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            clock["now"] += 1
            return httpx.Response(200, json={"code": 0, "data": {"extract_result": [{
                "state": next(states), "err_msg": "", "full_zip_url": "https://mineru.test/result.zip",
            }]}})

        parser = self._create_parser(handler)
        self.addCleanup(parser.close)
        output = io.StringIO()
        with (
            patch("parsers.cloud_mineru.time.time", side_effect=lambda: clock["now"]),
            patch("parsers.cloud_mineru.time.sleep"),
            redirect_stdout(output),
        ):
            status = parser.poll_until_done("batch-test", timeout_seconds=60)
        self.assertEqual(status.status, "done")
        self.assertEqual(len(requests), 4)
        for state in ("waiting-file", "pending", "running", "done"):
            self.assertIn(state, output.getvalue())
        self.assertIn("batch-test", output.getvalue())
        self.assertIn("60", output.getvalue())

    def test_timeout_includes_last_cloud_state_and_elapsed_time(self) -> None:
        """防止超时只报告任务号而无法区分排队与解析中的等待。"""
        clock = {"now": 0.0}
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            clock["now"] += 31
            return httpx.Response(200, json={"code": 0, "data": {"extract_result": [{
                "state": "running", "err_msg": "",
            }]}})

        parser = self._create_parser(handler)
        self.addCleanup(parser.close)
        with (
            patch("parsers.cloud_mineru.time.time", side_effect=lambda: clock["now"]),
            patch("parsers.cloud_mineru.time.sleep"),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(TimeoutError) as raised:
                parser.poll_until_done("batch-test", timeout_seconds=60)
        self.assertIn("batch-test", str(raised.exception))
        self.assertIn("running", str(raised.exception))
        self.assertIn("62", str(raised.exception))
        self.assertEqual(len(requests), 2)


class CloudMinerUReviewOutputTests(unittest.TestCase):
    review = (
        'The Ground Truth image displays a solid horizontal line. According to Rule 2 '
        '(UNDERSCORE & LINE RULES), a decorative line should be ignored. The provided OCR content '
        'was "____". Hence, the OCR result is inconsistent with the Ground Truth.'
    )

    def test_batch_removes_review_blocks_and_preserves_valid_text(self) -> None:
        from core.models import MinerUTaskStatus
        from parsers.cloud_mineru import CloudMineruParser

        ordinary = (
            'The Ground Truth image shows the road. According to Rule 2, labels use the visible boundaries. '
            'The OCR result does not match the Ground Truth.'
        )
        items = [
            {'type': 'text', 'page_idx': 0, 'text': self.review},
            {'type': 'text', 'page_idx': 1, 'content': self.review},
            {'type': 'text', 'page_idx': 2, 'content': ordinary},
            {'type': 'text', 'page_idx': 3, 'text': f'设备管理办法。 {self.review}\n\n第一条 应按流程办理。'},
            {'type': 'table', 'page_idx': 4, 'table_body': '<table><tr><td>有效表格</td></tr></table>'},
        ]
        archive = io.BytesIO()
        with ZipFile(archive, 'w') as package:
            package.writestr('report.md', '')
            package.writestr('report_content_list.json', json.dumps(items))
        url = 'https://mineru.test/report.zip'
        status = MinerUTaskStatus(task_id='test', status='done', zip_url=url)
        parser = CloudMineruParser(mode='v4')
        response = httpx.Response(200, content=archive.getvalue(), request=httpx.Request('GET', url))
        with (
            patch.object(parser, 'submit', return_value='test'),
            patch.object(parser, 'poll_until_done', return_value=status),
            patch('parsers.cloud_mineru.httpx.get', return_value=response),
        ):
            blocks = parser.parse('report.pdf')

        self.assertEqual([block.page_num for block in blocks], [2, 3, 4])
        self.assertEqual(blocks[0].content, ordinary)
        self.assertEqual([line for line in blocks[1].content.splitlines() if line], ['设备管理办法。', '第一条 应按流程办理。'])
        self.assertEqual(blocks[1].raw['text'], blocks[1].content)
        self.assertEqual(blocks[2].content, items[4]['table_body'])

    def test_agent_removes_review_paragraph_without_losing_the_document(self) -> None:
        from core.models import MinerUTaskStatus
        from parsers.cloud_mineru import CloudMineruParser

        parser = CloudMineruParser(mode='agent')
        url = 'https://mineru.test/result.md'
        status = MinerUTaskStatus(task_id='test', status='done', markdown_url=url)
        markdown = f'{self.review}\n\nTherefore, the corrected OCR output is:\n\n[Empty String]\n\n# 设备借用须知'
        response = httpx.Response(200, text=markdown, request=httpx.Request('GET', url))
        with (
            patch.object(parser, 'submit', return_value='test'),
            patch.object(parser, 'poll_until_done', return_value=status),
            patch('parsers.cloud_mineru.httpx.get', return_value=response),
        ):
            blocks = parser.parse('report.pdf')

        self.assertEqual([block.content for block in blocks], ['# 设备借用须知'])


class MinerUParserTests(unittest.TestCase):
    """验证本地 MinerU 的 PDF 图像请求和结果转换。"""

    def _parse_markdown_pages(self, pages, pages_per_request=1):
        responses = iter(pages)

        def handler(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": next(responses)}}]})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.pdf'
            self._create_pdf(path, len(pages) * pages_per_request)
            parser = self._create_parser(handler)
            self.addCleanup(parser.client.close)
            parser.config.pages_per_request = pages_per_request
            return parser.parse(str(path))

    def test_page_footers_are_removed_before_cross_page_clause_assembly(self):
        from policy.pipeline import build_policy_clauses

        first = '（1） 评审结果有1个“不合格”、4个“优秀”，经本人申请、'
        second = '导师和学院审批同意后可提交研究生院进行复评；'
        blocks = self._parse_markdown_pages([first + '\n\n1\n', second + '\n2'])
        self.assertEqual([block.content for block in blocks], [first, second])
        self.assertEqual([block.page_num for block in blocks], [0, 1])
        self.assertEqual([(block.raw['page_start'], block.raw['page_end']) for block in blocks], [(0, 0), (1, 1)])
        clauses = build_policy_clauses('p', blocks)
        self.assertEqual(clauses[0].raw_text, first + '\n' + second)
        self.assertEqual((clauses[0].page_start, clauses[0].page_end), (0, 1))

    def test_consecutive_page_headers_are_removed(self):
        blocks = self._parse_markdown_pages(['1\n第一条 正文。', '2\n第二条 正文。'])
        self.assertEqual([block.content for block in blocks], ['第一条 正文。', '第二条 正文。'])

    def test_explicit_page_label_is_removed_on_a_single_page(self):
        for footer in ('第1页', '第 1 页 共 1 页', '- 1 -', '— 1 —'):
            with self.subTest(footer=footer):
                blocks = self._parse_markdown_pages(['第一条 正文。\n' + footer])
                self.assertEqual(blocks[0].content, '第一条 正文。')

    def test_body_numbers_clause_markers_and_table_values_survive_cleanup(self):
        body = '第一条 2024年度评审。\n1\n1、提交材料。\n（1）有4个优秀。\n| 数量 |\n| --- |\n| 1 |'
        blocks = self._parse_markdown_pages([body + '\n1', '第二条 正文。\n2'])
        self.assertEqual(blocks[0].content, body)

    def test_unconfirmed_numeric_values_at_page_edges_are_kept(self):
        for pages in (['数量\n1'], ['2024\n第一条 正文。', '2024\n第二条 正文。'],
                      ['总数：\n1', '总数：\n2'], ['第一条 正文。\n1', '第二条 正文。\n3']):
            with self.subTest(pages=pages):
                self.assertEqual([block.content for block in self._parse_markdown_pages(pages)], pages)

    def test_multi_page_batch_keeps_numbers_without_internal_page_boundaries(self):
        text = '第一页正文\n1\n第二页正文\n2'
        blocks = self._parse_markdown_pages([text], pages_per_request=2)
        self.assertEqual(blocks[0].content, text)

    def test_isolated_last_page_number_after_confirmed_signature_is_removed(self):
        text = ('五、 此规定的解释权为学院学位评定委员会。\n武汉大学电气与自动化学院\n'
                '2024年12月9日\n武汉大学电气与自动化学院党政办公室 2024年12月17日印发')
        blocks = self._parse_markdown_pages(['第一条 正文。', '第二条 正文。', '第三条 正文。', text + '\n4'])
        self.assertEqual(blocks[-1].content, text)
        self.assertEqual(blocks[-1].page_num, 3)

    @staticmethod
    def _create_pdf(path: Path, page_count: int) -> None:
        document = fitz.open()
        for page_number in range(page_count):
            page = document.new_page()
            page.insert_text((72, 72), f"第 {page_number + 1} 页")
        document.save(path)
        document.close()

    @staticmethod
    def _create_parser(handler):
        from core.config import MinerUConfig
        from parsers.mineru import MinerUParser

        config = MinerUConfig(
            api_url="http://mineru.test/v1/chat/completions",
            api_key="test-key",
            model="mineru2.5-1.2b",
            dpi=72,
            pages_per_request=1,
            timeout_seconds=12.0,
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return MinerUParser(config=config, client=client)

    def test_parse_sends_rendered_pages_to_mineru_and_returns_markdown_block(self) -> None:
        """防止解析请求漏传认证、图片页或 MinerU 指令，导致服务无法正确解析。"""
        captured_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request["headers"] = dict(request.headers)
            captured_request["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "# 报销管理办法\n\n第一条"}}]},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "policy.pdf"
            self._create_pdf(pdf_path, page_count=1)
            parser = self._create_parser(handler)
            try:
                blocks = parser.parse(str(pdf_path))
            finally:
                parser.close()

        payload = captured_request["payload"]
        self.assertEqual(captured_request["headers"]["authorization"], "Bearer test-key")
        self.assertEqual(payload["model"], "mineru2.5-1.2b")
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(len(payload["messages"][0]["content"]), 2)
        self.assertTrue(payload["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"))
        prompt = payload["messages"][0]["content"][1]["text"]
        self.assertTrue(prompt.startswith("\nText Recognition:"))
        self.assertIn("忽略页眉、页脚中用于标记页次的页码", prompt)
        self.assertIn("保留正文中的所有数字和条款编号", prompt)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].content, "# 报销管理办法\n\n第一条")
        self.assertEqual(blocks[0].page_num, 0)

    def test_request_page_count_batches_the_entire_pdf_without_losing_the_tail(self) -> None:
        """防止每批页数被当作全文上限，或最后不足一批的页面被丢弃。"""
        for batch_size, expected_sizes, expected_starts in (
            (1, [1, 1, 1, 1, 1], [0, 1, 2, 3, 4]),
            (2, [2, 2, 1], [0, 2, 4]),
            (10, [5], [0]),
        ):
            with self.subTest(batch_size=batch_size), tempfile.TemporaryDirectory() as directory:
                payloads = []

                def handler(request: httpx.Request) -> httpx.Response:
                    payloads.append(json.loads(request.content))
                    return httpx.Response(200, json={"choices": [{"message": {
                        "content": f"第{len(payloads)}批正文",
                    }}]})

                path = Path(directory) / "policy.pdf"
                self._create_pdf(path, page_count=5)
                parser = self._create_parser(handler)
                self.addCleanup(parser.client.close)
                parser.config.pages_per_request = batch_size
                blocks = parser.parse(str(path))

                images = [[part["image_url"]["url"] for part in payload["messages"][0]["content"]
                           if part["type"] == "image_url"] for payload in payloads]
                self.assertEqual([len(items) for items in images], expected_sizes)
                self.assertEqual(len({image for items in images for image in items}), 5)
                self.assertEqual([block.page_num for block in blocks], expected_starts)
                self.assertEqual((blocks[-1].raw or {}).get("page_end"), 4)
                self.assertEqual(blocks[-1].content, f"第{len(expected_sizes)}批正文")

    def test_environment_batch_size_always_parses_the_entire_pdf(self) -> None:
        """环境配置只控制每次发送几页，不改变全文处理范围。"""
        from core.config import MinerUConfig

        for value, expected in (("1", [1] * 5), ("2", [2, 2, 1]), ("10", [5])):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                sizes = []

                def handler(request: httpx.Request) -> httpx.Response:
                    content = json.loads(request.content)["messages"][0]["content"]
                    sizes.append(sum(part["type"] == "image_url" for part in content))
                    return httpx.Response(200, json={"choices": [{"message": {"content": "正文"}}]})

                path = Path(directory) / "policy.pdf"
                self._create_pdf(path, page_count=5)
                parser = self._create_parser(handler)
                self.addCleanup(parser.client.close)
                with patch.dict(os.environ, {"MINERU_PAGES_PER_REQUEST": value}):
                    parser.config = MinerUConfig(api_url="http://mineru.test/v1/chat/completions",
                                                api_key="test-key", dpi=72)
                parser.parse(str(path))
                self.assertEqual(sizes, expected)

    def test_failed_batch_reports_the_page_range_and_stops_before_the_remaining_pages(self) -> None:
        """防止多页请求失败时报告错误页码范围或继续返回部分成功。"""
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 2:
                return httpx.Response(500, json={"error": {"message": "Internal error"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "正文"}}]})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pdf"
            self._create_pdf(path, page_count=5)
            parser = self._create_parser(handler)
            self.addCleanup(parser.client.close)
            parser.config.pages_per_request = 2
            with self.assertRaisesRegex(RuntimeError, "第 3-4 页.*500"):
                parser.parse(str(path))
        self.assertEqual(len(requests), 2)

    def test_parse_rejects_success_response_without_mineru_content(self) -> None:
        """防止服务返回缺少正文的成功 JSON 时把空内容当成解析完成。"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {}}]})

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "policy.pdf"
            self._create_pdf(pdf_path, page_count=1)
            parser = self._create_parser(handler)
            try:
                with self.assertRaisesRegex(RuntimeError, "缺少解析正文"):
                    parser.parse(str(pdf_path))
            finally:
                parser.close()

    def test_progress_shows_effective_settings_and_pages_without_exposing_credentials(self) -> None:
        """防止诊断输出漏报实际配置、页进度或泄露接口凭据。"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "本页正文"}}]})

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pdf"
            self._create_pdf(path, page_count=2)
            parser = self._create_parser(handler)
            self.addCleanup(parser.client.close)
            parser.config.api_url = (
                "http://diagnostic-user:diagnostic-password@mineru.test/v1/chat/completions"
                "?token=diagnostic-token#diagnostic-fragment"
            )
            parser.config.api_key = "diagnostic-api-key"
            parser.config.dpi = 60
            parser.config.pages_per_request = 1
            with redirect_stdout(output):
                blocks = parser.parse(str(path))

        text = output.getvalue()
        self.assertIn("backend=mineru", text)
        self.assertIn("http://mineru.test/v1/chat/completions", text)
        self.assertIn("mineru2.5-1.2b", text)
        self.assertIn("DPI=60", text)
        self.assertIn("每次请求最多 1 页", text)
        self.assertIn("总页数=2，本次解析=2 页", text)
        self.assertIn("第 1/2 页", text)
        self.assertIn("第 2/2 页", text)
        self.assertIn("496x702", text)
        self.assertIn("4 个字符", text)
        self.assertEqual(len(blocks), 2)
        for secret in ("diagnostic-user", "diagnostic-password", "diagnostic-token",
                       "diagnostic-fragment", "diagnostic-api-key", "data:image"):
            self.assertNotIn(secret, text)

    def test_local_backend_parses_all_pages_separately_for_the_text_pipeline(self) -> None:
        """防止本地后端集中发送大图、漏掉长文档尾页或丢失文本处理所需页码。"""
        from core.config import MinerUConfig
        from core.models import BlockType
        from parsers.dispatcher import PDFParser
        from processing.pipeline import build_document_classification_text

        payloads = []

        def handler(request: httpx.Request) -> httpx.Response:
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop",
                "message": {"content": f"第{len(payloads)}页正文"},
            }]})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long-policy.pdf"
            self._create_pdf(path, page_count=21)
            with patch.dict(os.environ):
                os.environ.pop("MINERU_DPI", None)
                os.environ.pop("MINERU_PAGES_PER_REQUEST", None)
                config = MinerUConfig(api_url="http://mineru.test/v1/chat/completions", api_key="test-key")
            with (
                httpx.Client(transport=httpx.MockTransport(handler)) as client,
                patch("parsers.mineru.app_config.mineru", config),
                patch("parsers.mineru.httpx.Client", return_value=client),
                patch("parsers.dispatcher.CloudMineruParser", side_effect=AssertionError("本地解析不应调用云端解析器")),
            ):
                parser = PDFParser(backend="mineru")
                try:
                    blocks = parser.parse(str(path))
                finally:
                    parser.close()

        self.assertEqual(len(blocks), 21)
        self.assertEqual([block.page_num for block in blocks], list(range(21)))
        self.assertTrue(all(block.type == BlockType.TEXT for block in blocks))
        self.assertEqual(len({block.block_id for block in blocks}), 21)
        self.assertEqual(blocks[-1].content, "第21页正文")
        self.assertEqual(build_document_classification_text(blocks),
                         "\n".join(f"第{i}页正文" for i in range(1, 22)))
        images = [[part["image_url"]["url"] for part in payload["messages"][0]["content"]
                   if part["type"] == "image_url"] for payload in payloads]
        self.assertEqual([len(items) for items in images], [1] * 21)
        self.assertEqual(len({items[0] for items in images}), 21)
        pixmap = fitz.Pixmap(base64.b64decode(images[0][0].split(",", 1)[1]))
        self.assertEqual((pixmap.width, pixmap.height), (595, 842))

    def test_local_backend_stops_when_truncation_recovery_is_exhausted(self) -> None:
        """分区恢复仍截断时必须有界失败，不能将半页正文入库或请求后续页。"""
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop" if len(requests) == 1 else "length",
                "message": {"content": "正文"},
            }]})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pdf"
            self._create_pdf(path, page_count=3)
            parser = self._create_parser(handler)
            self.addCleanup(parser.client.close)
            with self.assertRaisesRegex(RuntimeError, "第 2 页.*截断"):
                parser.parse(str(path))
        # 第一页成功、第二页截断、半页与四分之一页均截断后停止。
        self.assertEqual(len(requests), 4)

    def test_truncation_reports_token_usage_without_returning_partial_text(self) -> None:
        """截断时保留服务端用量证据，避免将重复生成误判为图片过大。"""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "length", "message": {"content": "不完整正文"}}],
                "usage": {"prompt_tokens": 1792, "completion_tokens": 6400, "total_tokens": 8192},
            })

        parser = self._create_parser(handler)
        self.addCleanup(parser.client.close)
        with self.assertRaises(RuntimeError) as raised:
            parser._request_mineru(["test-image"])
        message = str(raised.exception)
        for evidence in ("finish_reason=length", "prompt_tokens=1792", "completion_tokens=6400", "total_tokens=8192"):
            self.assertIn(evidence, message)
        self.assertNotIn("不完整正文", message)

    def test_local_backend_continues_after_a_normally_completed_blank_page(self) -> None:
        """防止正常返回空文本的中间页阻断后续正文解析。"""
        contents = iter(["第一页正文", "", "第三页正文"])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop", "message": {"content": next(contents)},
            }]})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pdf"
            self._create_pdf(path, page_count=3)
            parser = self._create_parser(handler)
            self.addCleanup(parser.client.close)
            blocks = parser.parse(str(path))
        self.assertEqual([block.content for block in blocks], ["第一页正文", "", "第三页正文"])
        self.assertEqual([block.page_num for block in blocks], [0, 1, 2])

    def test_local_backend_reports_the_page_with_an_http_error(self) -> None:
        """防止失败页面被跳过后仍将部分文档交给后续入库。"""
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 2:
                return httpx.Response(500, json={"error": {"message": "Internal server error"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "正文"}}]})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pdf"
            self._create_pdf(path, page_count=3)
            parser = self._create_parser(handler)
            self.addCleanup(parser.client.close)
            with self.assertRaisesRegex(RuntimeError, "第 2 页.*500") as raised:
                parser.parse(str(path))
        self.assertIsInstance(raised.exception.__cause__, httpx.HTTPStatusError)
        self.assertEqual(len(requests), 2)

    def test_default_dispatcher_backend_is_cloudmineru(self) -> None:
        """防止默认配置误路由到本地 MinerU，绕过 CloudMinerU。"""
        from parsers.dispatcher import PDFParser
        from parsers.cloud_mineru import CloudMineruParser

        parser = PDFParser()
        self.assertEqual(parser.backend, "cloudmineru")
        self.assertIsInstance(parser.strategy, CloudMineruParser)


if __name__ == "__main__":
    unittest.main()
