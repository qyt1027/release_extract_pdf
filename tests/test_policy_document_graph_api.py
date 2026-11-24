"""文件图谱 API 与 MCP 参数传递测试，不访问数据库。"""
import unittest
from unittest.mock import patch

import httpx
from mcp.client import Client


class DocumentGraphAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_route_maps_bounds_and_unknown_document(self):
        from web.api import app

        with patch("policy.document_graph.query_document_graph", return_value={"nodes": [], "edges": []}) as query:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/policies/policy_a/relations?depth=2&direction=incoming&limit=20")
                self.assertEqual((await client.get("/api/policies/policy_a/relations?depth=4")).status_code, 422)
            self.assertEqual(response.status_code, 200)
            query.assert_called_once_with("policy_a", 2, "incoming", 20)
        with patch("policy.document_graph.query_document_graph", side_effect=KeyError("missing")):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.get("/api/policies/missing/relations")).status_code, 404)


class DocumentGraphMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_maps_graph_query_and_rejects_invalid_parameters(self):
        from policy_mcp.server import create_server

        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"nodes": [], "edges": [], "truncated": False})
        async with Client(create_server(api_transport=httpx.MockTransport(handler))) as client:
            result = await client.call_tool("get_policy_relations", {"policy_id": "policy_a", "depth": 2, "direction": "incoming", "limit": 20})
            self.assertFalse(result.is_error)
            self.assertEqual(requests[0].url.path, "/api/policies/policy_a/relations")
            self.assertEqual(dict(requests[0].url.params), {"depth": "2", "direction": "incoming", "limit": "20"})
            for params in ({"policy_id": "../x"}, {"policy_id": "a", "depth": 4}, {"policy_id": "a", "direction": "bad"}):
                self.assertTrue((await client.call_tool("get_policy_relations", params)).is_error)


if __name__ == "__main__":
    unittest.main()
