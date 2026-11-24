"""验证命令行入口的分发、参数传递和副作用边界。"""

import io
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch

from commands import entry as main


class MainCliTests(unittest.TestCase):
    def test_no_command_starts_api(self) -> None:
        with patch('commands.entry.run_api') as run_api:
            main.main([])
        run_api.assert_called_once_with()

    def test_omitted_arguments_read_system_command_line(self) -> None:
        with (
            patch("sys.argv", ["main.py", "--batch-status", "batch_1"]),
            patch('commands.entry.run_batch_status') as status,
        ):
            main.main()
        status.assert_called_once_with("batch_1")

    def test_commands_pass_parameters_to_expected_handler(self) -> None:
        """覆盖导入、重置、抽取、审核及导出的关键参数传递。"""
        cases = [
            (["--process", "sample.pdf", "--backend", "pymupdf"],
             "run_process", ("sample.pdf",), {"backend": "pymupdf"}),
            (["--process-dir", "samples"],
             "run_process_dir", ("samples",), {"backend": None}),
            (["--reset-folder", "samples", "--confirm-reset-folder", "--allow-shared-reset",
              "--release-stale-reset", "--purge-imported-data", "--force-reset-folder"],
             "run_reset_folder", ("samples",),
             {"confirm": True, "allow_shared": True, "release_stale": True, "purge": True, "force": True}),
            (["--reset-folder", "samples"],
             "run_reset_folder", ("samples",),
             {"confirm": False, "allow_shared": False, "release_stale": False, "purge": False, "force": False}),
            (["--extract-policy-batch", "batch_1", "--limit", "3"],
             "run_extract_policy_batch", ("batch_1",), {"limit": 3}),
            (["--extract-policy-knowledge-v2", "batch_1", "--knowledge-v2-sample-file", "sample.csv"],
             "run_extract_policy_knowledge_v2", ("batch_1", "sample.csv"), {}),
            (["--classify-policy-process-batch", "batch_1", "--policy-domains", " travel, , reimbursement "],
             "run_classify_policy_process_batch", ("batch_1",),
             {"selected_domains": ["travel", "reimbursement"]}),
            (["--classify-policy-process-batch", "batch_1"],
             "run_classify_policy_process_batch", ("batch_1",), {"selected_domains": None}),
            (["--review-policy-families", "batch_1", "--family-reviewer", "张三"],
             "run_policy_family_review", ("batch_1", "张三", 20), {}),
            (["--review-policy-abolition-relations", "batch_1", "--abolition-reviewer", "张三",
              "--abolition-review-limit", "5"],
             "run_policy_abolition_review", ("batch_1", "张三", 5), {}),
            (["--export-policy-clause-review", "batch_1", "--quality-output", "outputs",
              "--clauses-per-policy", "4"],
             "run_export_policy_clause_review", ("batch_1", "outputs", 4), {}),
            (["--export-policy-knowledge-v2-view", "run_1", "--knowledge-v2-output", "view.json"],
             "run_export_policy_knowledge_v2_view", ("run_1", "view.json"), {}),
        ]
        handlers = [name for name in vars(main) if name.startswith("run_")]
        for argv, expected_handler, positional, keywords in cases:
            with self.subTest(argv=argv), ExitStack() as stack:
                mocks = {name: stack.enter_context(patch(f'commands.entry.{name}')) for name in handlers}
                stack.enter_context(patch("sys.argv", ["main.py", "--unknown-option"]))
                main.main(argv)
                mocks[expected_handler].assert_called_once_with(*positional, **keywords)
                for name, handler in mocks.items():
                    if name != expected_handler:
                        handler.assert_not_called()

    def test_help_skips_validation_and_execution(self) -> None:
        with (
            patch('commands.entry.run_api') as run_api,
            patch('commands.entry.run_policy_review') as review,
            redirect_stdout(io.StringIO()) as output,
        ):
            main.main(["--help", "--review-policy-run", "run_1"])
        self.assertIn("三步上手", output.getvalue())
        run_api.assert_not_called()
        review.assert_not_called()

    def test_full_help_exits_successfully(self) -> None:
        with patch('commands.entry.run_api') as run_api, redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as raised:
                main.main(["--help-all"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--reset-folder", output.getvalue())
        self.assertIn("--extract-policy-knowledge-v2", output.getvalue())
        run_api.assert_not_called()

    def test_invalid_command_combinations_do_not_execute(self) -> None:
        cases = [
            (["--process", "sample.pdf", "--reset-folder", "samples"], "只能选择一个"),
            (["--confirm-reset-folder"], "只能与 --reset-folder"),
            (["--allow-shared-reset"], "只能与 --reset-folder"),
            (["--release-stale-reset"], "只能与 --reset-folder"),
            (["--purge-imported-data"], "只能与 --reset-folder"),
            (["--force-reset-folder"], "只能与 --reset-folder"),
            (["--classify-policy-process-batch", "batch_1", "--policy-domains", " , "], "至少需要一个"),
            (["--export-policy-clause-review", "batch_1"], "必须提供 --quality-output"),
            (["--quality-output", "outputs"], "只能与质检表导出"),
        ]
        handlers = [name for name in vars(main) if name.startswith("run_")]
        for argv, message in cases:
            with self.subTest(argv=argv), ExitStack() as stack:
                mocks = [stack.enter_context(patch(f'commands.entry.{name}')) for name in handlers]
                output = stack.enter_context(redirect_stderr(io.StringIO()))
                with self.assertRaises(SystemExit) as raised:
                    main.main(argv)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(message, output.getvalue())
                for handler in mocks:
                    handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
