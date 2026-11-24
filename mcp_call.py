"""通过真实 MCP 服务调用制度工具，不属于自动回归测试。"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx2
from dotenv import load_dotenv
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='MCP 地址，默认读取项目 .env')
    tools = parser.add_subparsers(dest='tool', required=True)

    catalog = tools.add_parser('list_policies', help='查询制度目录')
    catalog.add_argument('--query', default='')
    catalog.add_argument('--status', choices=['', 'current', 'invalid', 'unknown'], default='')
    catalog.add_argument('--limit', type=int, choices=range(1, 101), default=10, metavar='1-100')
    catalog.add_argument('--offset', type=int, default=0)

    detail = tools.add_parser('get_policy_detail', help='读取制度全文')
    detail.add_argument('--policy-id', required=True)

    relations = tools.add_parser('get_policy_relations', help='查询制度引用、提及和废止关联')
    relations.add_argument('--policy-id', required=True)
    relations.add_argument('--depth', type=int, choices=[1, 2, 3], default=1)
    relations.add_argument('--direction', choices=['both', 'incoming', 'outgoing'], default='both')
    relations.add_argument('--limit', type=int, choices=range(1, 201), default=100, metavar='1-200')

    answer = tools.add_parser('answer_policy_question', help='真实问答，会调用业务模型并产生相应费用')
    answer.add_argument('--question', required=True)
    answer.add_argument('--as-of')

    search = tools.add_parser('search_policy_clauses', help='检索制度原文')
    search.add_argument('--query', required=True)
    search.add_argument('--top-k', type=int, choices=range(1, 21), default=5, metavar='1-20')
    search.add_argument('--as-of')
    args = parser.parse_args(argv)
    if args.tool == 'list_policies' and args.offset < 0:
        parser.error('--offset 不能为负数')
    return args


async def call(args):
    # 使用脚本所在目录定位配置，不依赖终端的当前目录。
    load_dotenv(Path(__file__).resolve().parent / '.env')
    token = os.getenv('POLICY_MCP_TOKEN', '')
    if not token:
        raise ValueError('缺少 POLICY_MCP_TOKEN，请在项目 .env 中配置与服务端相同的凭证')
    url = args.url or os.getenv('POLICY_MCP_URL') or (
        'http://127.0.0.1:' + os.getenv('POLICY_MCP_PORT', '8001') + '/mcp'
    )
    arguments = {
        key: value for key, value in vars(args).items()
        if key not in {'url', 'tool'} and value is not None
    }
    print(f'MCP 地址：{url}')
    print(f'调用工具：{args.tool}')
    print('参数：' + json.dumps(arguments, ensure_ascii=False))
    if args.tool == 'answer_policy_question':
        print('提示：本次问答会实际调用业务服务配置的大模型。')
    async with httpx2.AsyncClient(
        headers={'Authorization': f'Bearer {token}'},
        timeout=httpx2.Timeout(200.0, connect=5.0),
        trust_env=False,
    ) as http:
        transport = streamable_http_client(url, http_client=http)
        async with Client(transport, read_timeout_seconds=200.0) as client:
            result = await client.call_tool(args.tool, arguments)
    # 输出完整协议结果，保留结构化数据、文本和错误标记。
    print(json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2))
    print('调用失败' if result.is_error else '调用成功，请结合原文、引用和警告判断业务结论。')
    return 1 if result.is_error else 0


def main():
    # 保证 Windows CMD 中的中文输出使用 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parse_args()
    try:
        return asyncio.run(call(args))
    except Exception as exc:
        print(f'调用失败：{exc}', file=sys.stderr)
        print('请检查 MCP 地址、凭证、服务状态及服务端日志。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
