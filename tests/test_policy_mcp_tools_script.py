"""验证手动联调脚本的错误诊断，不依赖已启动的服务。"""
import asyncio
import contextlib
import io
import os
import socket
import unittest
from unittest.mock import patch

import httpx
import httpx2
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from policy_mcp.api_client import PolicyAPIClient
from policy_mcp.server import create_http_app, create_server
from tests.test_policy_mcp_tools import MCPConnectionError, main, probe_endpoint


class PolicyMCPScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_error_is_not_wrapped_in_exception_group(self):
        app = create_http_app(token="test-token", server=create_server(
            api_transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        ))
        async with app.router.lifespan_context(app):
            http = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                headers={"Authorization": "Bearer test-token"},
            )
            with patch.dict(os.environ, {"POLICY_MCP_TOKEN": "test-token"}), \
                 patch("tests.test_policy_mcp_tools.load_dotenv"), \
                 patch("tests.test_policy_mcp_tools.httpx2.AsyncClient", return_value=http), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(MCPConnectionError, "检索工具失败"):
                    await main()

    async def test_internal_api_does_not_use_global_proxy(self):
        async def search(request):
            return JSONResponse({"results": []})
        app = Starlette(routes=[Route("/policy-search", search)])
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            address = f"http://127.0.0.1:{listener.getsockname()[1]}"
            server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        if task.done():
                            await task
                            self.fail("测试业务服务未启动")
                        await asyncio.sleep(0.01)
                # 故意配置不可用的全局代理，确认内部请求仍直连本机业务服务。
                with patch.dict(os.environ, {
                    "HTTP_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": "",
                }):
                    async with httpx.AsyncClient(trust_env=True, timeout=2) as proxied:
                        with self.assertRaises(httpx.RequestError):
                            await proxied.get(address + "/policy-search")
                    async with PolicyAPIClient(address) as api:
                        self.assertEqual(await api.search_clauses("测试"), {"results": []})
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, timeout=5)

    async def test_host_rejection_reports_restart_instead_of_protocol_failure(self):
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(
            lambda r: httpx2.Response(421, text="Invalid Host header")
        )) as http:
            with self.assertRaisesRegex(MCPConnectionError, "Host.*重启"):
                await probe_endpoint(http, "http://127.0.0.1:8001/mcp")

    async def test_authentication_and_missing_route_are_distinct(self):
        for status, message in [(401, "凭证"), (403, "Origin"), (404, "地址")]:
            with self.subTest(status=status):
                async with httpx2.AsyncClient(transport=httpx2.MockTransport(
                    lambda r: httpx2.Response(status)
                )) as http:
                    with self.assertRaisesRegex(MCPConnectionError, message):
                        await probe_endpoint(http, "http://127.0.0.1:8001/mcp")

    async def test_unreachable_service_has_startup_hint(self):
        def handler(request):
            raise httpx2.ConnectError("connection refused")
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            with self.assertRaisesRegex(MCPConnectionError, "启动 MCP"):
                await probe_endpoint(http, "http://127.0.0.1:8001/mcp")

    async def test_legacy_discovery_error_does_not_prevent_handshake(self):
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(
            lambda r: httpx2.Response(200, json={
                "jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"},
            })
        )) as http:
            await probe_endpoint(http, "http://127.0.0.1:8001/mcp")


if __name__ == "__main__":
    unittest.main()
