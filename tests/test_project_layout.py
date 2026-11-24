"""验证目录迁移后的启动入口、资源路径和工具导入边界。"""

import importlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core.paths import ENV_FILE, PROJECT_ROOT


class ProjectLayoutTests(unittest.TestCase):
    def test_project_paths_do_not_depend_on_working_directory(self):
        original_dir = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                from core import config

                self.assertEqual(PROJECT_ROOT, Path(__file__).resolve().parents[1])
                self.assertEqual(ENV_FILE, PROJECT_ROOT / ".env")
                self.assertEqual(config.env_path, ENV_FILE)
            finally:
                os.chdir(original_dir)

    def test_asgi_entry_exports_same_app(self):
        import api
        from web.api import app

        self.assertIs(api.app, app)
        self.assertEqual(api.__all__, ["app"])

    def test_cli_entry_exports_same_main(self):
        import main
        from commands.entry import main as command_main

        self.assertIs(main.main, command_main)

    def test_policy_assets_remain_available(self):
        from policy.answer_ui import render_policy_qa_page
        from policy.graph.domain_catalog import load_process_domain_catalog

        self.assertTrue(load_process_domain_catalog().enabled_domains)
        self.assertIn("<html", render_policy_qa_page().lower())

    def test_tool_imports_do_not_create_clients_or_request_services(self):
        """真实请求及模型客户端构造均作为禁止调用的边界。"""
        modules = ("scripts.mineru_parse", "scripts.mineru_probe", "examples.chart_description")
        with (
            patch("requests.get", side_effect=AssertionError("导入时不能请求外部服务")),
            patch("requests.post", side_effect=AssertionError("导入时不能请求外部服务")),
            patch("openai.OpenAI.__init__", side_effect=AssertionError("导入时不能创建模型客户端")),
        ):
            for name in modules:
                with self.subTest(module=name):
                    importlib.reload(importlib.import_module(name))

    def test_tool_help_does_not_request_services(self):
        modules = ("scripts.mineru_parse", "scripts.mineru_probe", "examples.chart_description")
        with (
            patch("requests.get", side_effect=AssertionError("帮助不能请求外部服务")),
            patch("requests.post", side_effect=AssertionError("帮助不能请求外部服务")),
            patch("openai.OpenAI.__init__", side_effect=AssertionError("帮助不能创建模型客户端")),
        ):
            for name in modules:
                with self.subTest(module=name), redirect_stdout(io.StringIO()) as output:
                    module = importlib.reload(importlib.import_module(name))
                    with self.assertRaises(SystemExit) as raised:
                        module.main(["--help"])
                    self.assertEqual(raised.exception.code, 0)
                    self.assertIn("usage:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
