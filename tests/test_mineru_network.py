"""验证 MinerU 网络波动只重试当前请求，不丢页或无限重试。"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx

from tests import test_mineru


class MinerUNetworkTests(unittest.TestCase):
    @staticmethod
    def _response(text='完整正文', reason='stop'):
        return httpx.Response(200, json={
            'choices': [{'finish_reason': reason, 'message': {'content': text}}],
        })

    def test_connection_timeout_retries_current_page_and_continues_document(self):
        """第二页两次连接超时后恢复，应保留第一页且继续第三页。"""
        images = []

        def handler(request):
            payload = json.loads(request.content)
            images.append(payload['messages'][0]['content'][0]['image_url']['url'])
            if len(images) in (2, 3):
                raise httpx.ConnectTimeout('模拟连接超时', request=request)
            return self._response({1: '第一页正文', 4: '第二页正文', 5: '第三页正文'}[len(images)])

        parser = test_mineru.MinerUParserTests._create_parser(handler)
        parser.config.max_retries = 2
        self.addCleanup(parser.client.close)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch('time.sleep'),
            redirect_stdout(io.StringIO()) as output,
        ):
            path = Path(directory) / 'policy.pdf'
            test_mineru.MinerUParserTests._create_pdf(path, page_count=3)
            blocks = parser.parse(str(path))
        self.assertEqual([block.content for block in blocks], ['第一页正文', '第二页正文', '第三页正文'])
        self.assertEqual([block.page_num for block in blocks], [0, 1, 2])
        self.assertEqual(images[1:4], [images[1]] * 3)
        self.assertEqual(len(set(images)), 3)
        self.assertIn('重试', output.getvalue())

    def test_transient_transport_errors_can_recover(self):
        """连接、读取和协议连接中断均应允许当前请求恢复。"""
        for error_type in (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError,
                           httpx.ReadError, httpx.RemoteProtocolError):
            with self.subTest(error=error_type.__name__):
                attempts = []

                def handler(request):
                    attempts.append(request)
                    if len(attempts) == 1:
                        raise error_type('模拟临时故障', request=request)
                    return self._response()

                parser = test_mineru.MinerUParserTests._create_parser(handler)
                self.addCleanup(parser.client.close)
                with patch('time.sleep'), redirect_stdout(io.StringIO()):
                    self.assertEqual(parser._request_mineru(['page']), '完整正文')
                self.assertEqual(len(attempts), 2)

    def test_repeated_timeouts_stop_after_retry_budget_and_keep_page_context(self):
        """连续超时只能请求三次，不能跳过失败页或返回前面的半份文件。"""
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) > 1:
                raise httpx.ConnectTimeout('模拟持续超时', request=request)
            return self._response('第一页正文')

        parser = test_mineru.MinerUParserTests._create_parser(handler)
        parser.config.max_retries = 2
        self.addCleanup(parser.client.close)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch('time.sleep'),
            redirect_stdout(io.StringIO()) as output,
        ):
            path = Path(directory) / 'policy.pdf'
            test_mineru.MinerUParserTests._create_pdf(path, page_count=3)
            with self.assertRaisesRegex(RuntimeError, '第 2 页') as raised:
                parser.parse(str(path))
        self.assertEqual(len(requests), 4)
        self.assertIsInstance(raised.exception.__cause__, httpx.ConnectTimeout)
        self.assertIn('代理', output.getvalue())

    def test_http_failure_and_truncation_are_not_retried_as_network_errors(self):
        """鉴权失败和模型长度截断应沿用原有错误处理，避免重复请求完整图。"""
        for kind in ('authorization', 'truncation'):
            with self.subTest(kind=kind):
                requests = []

                def handler(request):
                    requests.append(request)
                    if kind == 'authorization':
                        return httpx.Response(401, json={'error': 'unauthorized'})
                    return self._response('不完整正文', 'length')

                parser = test_mineru.MinerUParserTests._create_parser(handler)
                self.addCleanup(parser.client.close)
                expected = httpx.HTTPStatusError if kind == 'authorization' else RuntimeError
                with patch('time.sleep'), self.assertRaises(expected):
                    parser._request_mineru(['page'])
                self.assertEqual(len(requests), 1)

    def test_retry_budget_can_be_disabled(self):
        """设置零次重试应保留一次请求即失败的行为。"""
        requests = []

        def handler(request):
            requests.append(request)
            raise httpx.ConnectTimeout('连接失败', request=request)

        parser = test_mineru.MinerUParserTests._create_parser(handler)
        parser.config.max_retries = 0
        self.addCleanup(parser.client.close)
        with patch('time.sleep'), redirect_stdout(io.StringIO()), self.assertRaises(httpx.ConnectTimeout):
            parser._request_mineru(['page'])
        self.assertEqual(len(requests), 1)

    def test_retry_budget_is_read_from_environment(self):
        """环境变量限制一次重试时，应在第二次失败后停止。"""
        requests = []

        def handler(request):
            requests.append(request)
            raise httpx.ConnectTimeout('连接失败', request=request)

        with patch.dict('os.environ', {'MINERU_MAX_RETRIES': '1'}):
            parser = test_mineru.MinerUParserTests._create_parser(handler)
        self.addCleanup(parser.client.close)
        with patch('time.sleep'), redirect_stdout(io.StringIO()), self.assertRaises(httpx.ConnectTimeout):
            parser._request_mineru(['page'])
        self.assertEqual(len(requests), 2)

    def test_negative_retry_budget_is_rejected_before_request(self):
        """负数不能造成请求循环直接跳过而使用未定义的响应。"""
        parser = test_mineru.MinerUParserTests._create_parser(lambda _: self._response())
        parser.config.max_retries = -1
        self.addCleanup(parser.client.close)
        with self.assertRaisesRegex(ValueError, 'MINERU_MAX_RETRIES'):
            parser._request_mineru(['page'])
