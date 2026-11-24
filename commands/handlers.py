"""命令行任务执行与终端结果展示。"""

import datetime
from pathlib import Path
from typing import Sequence


def run_api():
    """启动 FastAPI 服务"""
    import uvicorn
    from web.api import app
    print("=" * 60)
    print("PDF 多模态提取入仓服务")
    print("=" * 60)
    print("启动 FastAPI 服务于 http://127.0.0.1:12700")
    print("API 文档: http://127.0.0.1:12700/docs")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=12700)


def prompt_folder_applicable_unit(file_path: str, title: str, college: str) -> bool:
    """明确确认后才采用父目录的学院名。"""
    print(f"\n文件：{file_path}")
    print(f"《{title}》的适用范围为院级，具体学院未能识别。")
    while True:
        try:
            answer = input(f"是否采用上级文件夹的「{college}」作为适用单位？[y]采用 [n]留空（默认）：").strip().lower()
        except (EOFError, OSError):
            return False
        if answer == "y":
            print(f"适用单位已确认为「{college}」。")
            return True
        if answer in {"", "n"}:
            return False
        print("请输入 y 或 n。")


def prompt_file_overwrite(record: dict) -> bool | None:
    """只有明确输入 y 才覆盖相同内容的已完成文件。"""
    print("\n检测到相同内容的已导入文件")
    print(f"当前文件：{record.get('source_file_name') or record.get('file_name')}")
    print(f"已有文件：{record.get('file_name')}")
    print(f"文件 ID：{record.get('file_id')}")
    while True:
        try:
            answer = input("是否重新解析并覆盖已有数据？[y]覆盖 [n]跳过（默认）：").strip().lower()
        except (EOFError, OSError):
            print("无法读取覆盖选择，本次未执行覆盖。")
            return None
        if answer == "y":
            return True
        if answer in {"", "n"}:
            return False
        print("请输入 y 或 n。")


def run_process(pdf_path: str, backend: str = None):
    """命令行处理单个文档。"""
    # 如果指定了 backend，修改全局 config
    if backend:
        from core.config import app_config
        app_config.parser.parser_backend = backend
        print(f"使用解析后端: {backend}")

    from processing.pipeline import process_pdf
    from policy.abolition import prompt_abolition_relation_insertion

    print(f"{datetime.datetime.now()} 正在处理: {pdf_path}")

    if Path(pdf_path).suffix.lower() == ".pdf":
        import fitz

        with fitz.open(pdf_path) as doc:
            page_count = len(doc)
        print(f"共有: {page_count}页")
    else:
        # Word 与网页归档没有可靠的 PDF 页数，解析器会按正文块处理。
        page_count = 0
        print("页数: 不适用（按文档正文块处理）")

    abolition_prompt = prompt_abolition_relation_insertion()
    from policy.duplicates import prompt_duplicate_import
    result = process_pdf(
        pdf_path,
        page_count,
        abolition_confirmation=abolition_prompt,
        abolition_approval_confirmation=abolition_prompt.confirm_approval,
        duplicate_confirmation=prompt_duplicate_import,
        folder_unit_confirmation=prompt_folder_applicable_unit,
        file_overwrite_confirmation=prompt_file_overwrite,
    )

    print(f"\n处理结果:")
    print(f"  文件 ID:    {result.file_id}")
    print(f"  状态:       {result.status.value}")
    print(f"  总块数:     {result.total_blocks}")
    print(f"  文本块:     {result.text_chunks_stored}")
    print(f"  图片:       {result.images_stored}")
    print(f"  数据表:     {result.data_tables_stored}")
    print(f"  表单:       {result.forms_stored}")
    print(f"  待审核表:   {result.uncertain_tables}")
    print(f"  废止候选:   {result.abolition_candidates}")
    print(f"  已插入关系: {result.abolition_relations_inserted}")
    print(f"  已跳过关系: {result.abolition_relations_skipped}")
    print(f"  已批准历史关系: {result.abolition_relations_approved}")
    print(f"  耗时:       {result.duration_seconds}s")
    if result.message:
        print(f"  说明:       {result.message}")
    if result.errors:
        print(f"  错误:")
        for e in result.errors:
            print(f"    - {e}")
    if result.status.value in {"done", "succeeded"} and result.file_id:
        from policy.clause_export import export_file_clause_structure
        source = Path(pdf_path).resolve()
        output_path = source.with_name(f"{source.stem}_条款重组结果.json")
        exported_path = export_file_clause_structure(result.file_id, output_path)
        print(f"已导出条款重组结果: {exported_path}")


def _print_batch_summary(status: dict) -> None:
    """打印批次和文件任务统计。"""
    batch = status["batch"]
    print(f"\n批次 ID: {batch['batch_id']}")
    print(f"批次状态: {batch.get('status')}")
    print(f"总文件数: {batch.get('total_count', 0)}")
    print(f"成功: {batch.get('succeeded_count', 0)}")
    print(f"跳过: {batch.get('skipped_count', 0)}")
    print(f"待重试: {batch.get('retryable_failed_count', 0)}")
    print(f"永久失败: {batch.get('permanent_failed_count', 0)}")
    items = status.get("items", [])
    waiting = [item for item in items if item.get("status") in {"pending", "retry_wait", "running", "pending_confirmation"}
               or (item.get("status") == "failed" and item.get("error_kind") == "transient")]
    for item in waiting:
        file_name = item.get("file_name") or item.get("file_path") or item.get("item_id") or "未知文件"
        print(f"  {file_name}: {item.get('status')}，{item.get('last_error') or '尚未完成'}")
    if waiting and not any(item.get("status") == "running" for item in waiting):
        print(f"未完成文件不会在后台自动重试。续跑：python main.py --resume-batch {batch['batch_id']}")


def run_process_dir(source_dir: str, backend: str = None) -> None:
    """创建并运行目录批次。"""
    if backend:
        from core.config import app_config
        app_config.parser.parser_backend = backend
        print(f"使用解析后端: {backend}")

    from processing.batch import create_batch_job, run_batch
    from policy.clause_export import export_batch_clause_structure
    from policy.abolition import prompt_abolition_relation_insertion

    batch_id = create_batch_job(source_dir)
    print(f"已创建批次: {batch_id}")
    abolition_prompt = prompt_abolition_relation_insertion()
    from policy.duplicates import prompt_duplicate_import
    status = run_batch(
        batch_id,
        abolition_confirmation=abolition_prompt,
        abolition_approval_confirmation=abolition_prompt.confirm_approval,
        duplicate_confirmation=prompt_duplicate_import,
        folder_unit_confirmation=prompt_folder_applicable_unit,
    )
    _print_batch_summary(status)
    output_path = Path(source_dir).resolve() / f"{batch_id}_条款重组结果.json"
    exported_path = export_batch_clause_structure(batch_id, output_path)
    print(f"已导出条款重组结果: {exported_path}")


def run_resume_batch(batch_id: str) -> None:
    """恢复指定批次。"""
    from processing.batch import run_batch
    from policy.duplicates import prompt_duplicate_import

    status = run_batch(
        batch_id, resume=True, duplicate_confirmation=prompt_duplicate_import,
        folder_unit_confirmation=prompt_folder_applicable_unit,
    )
    _print_batch_summary(status)


def run_batch_status(batch_id: str) -> None:
    """只查看批次状态，不执行文件。"""
    from processing.batch import get_batch_status

    _print_batch_summary(get_batch_status(batch_id))


def run_reset_file(file_id: str) -> None:
    """清理单个 PDF 的数据库自动产物，使其能够重新进入批处理。"""
    from processing.reset import reset_file_database_artifacts

    try:
        summary = reset_file_database_artifacts(file_id)
    except ValueError as error:
        raise SystemExit(f"文件重置未执行：{error}") from None
    print(f"已重置文件自动产物: {file_id}")
    print(
        "已清理："
        f"文本向量 {summary['text_vectors']}，"
        f"数据表 {summary['data_tables']}，"
        f"表单 {summary['forms']}，"
        f"表格目录 {summary['table_catalog_records']}，"
        f"块溯源 {summary['block_records']}，"
        f"制度条款 {summary['policy_clauses']}"
    )


def run_reset_folder(
    folder: str, *, confirm: bool = False, allow_shared: bool = False, release_stale: bool = False,
    purge: bool = False, force: bool = False,
) -> None:
    """预览或批量重置指定目录内已导入文件的数据库产物。"""
    from processing.reset import reset_folder_database_artifacts

    try:
        plan = reset_folder_database_artifacts(folder, confirm=confirm, allow_shared=allow_shared,
                                               release_stale=release_stale, purge=purge, force=force)
    except ValueError as error:
        raise SystemExit(f"目录重置未执行：{error}") from None
    print(f"目标目录: {plan['folder']}")
    print(f"当前源文件: {plan['source_file_count']}，匹配已导入文件 ID: {len(plan['file_ids'])}")
    for file_id in plan["file_ids"]:
        print(f"  {file_id}")
    if plan["shared_file_ids"]:
        print(f"目录外批次共用文件 ID: {', '.join(plan['shared_file_ids'])}")
    if plan["running_file_ids"]:
        print(f"处理占用或遗留占用的文件 ID: {', '.join(plan['running_file_ids'])}")
    if plan.get("stale_file_ids"):
        print(f"已过期的占用 ID（需确认旧进程已退出）: {', '.join(plan['stale_file_ids'])}")
    if plan.get("released_stale_file_ids"):
        print(f"已释放过期占用: {', '.join(plan['released_stale_file_ids'])}")
    if plan.get("released_stale_policy_run_ids"):
        print(f"已释放过期条款运行: {', '.join(sorted(set(plan['released_stale_policy_run_ids'])))}")
    if purge:
        print("彻底清理模式：同时清除旧制度元数据、入向与出向废止关系、无剩余任务的运行记录；保留源文件与稳定 ID。")
    if plan.get("force", force or purge):
        print("强制重置模式：忽略文件及条款任务状态和时间，不会终止操作系统进程；关联共享条款运行将中止。")
    print(f"清理来源废止关系: {plan.get('abolition_relation_count', 0)} 条")
    if plan.get("affected_policy_ids"):
        print(f"需重算效力的目标制度: {', '.join(plan['affected_policy_ids'])}")
    if confirm:
        print(f"已重置 {len(plan['reset_file_ids'])} 个文件的数据库产物；原始文件未删除。")
    else:
        print("以上仅为预览，未修改数据库。重置会清除对应条款、向量及人工复核记录。")
        print("确认执行请追加 --confirm-reset-folder；允许共享结果同步失效请追加 --allow-shared-reset。")
        if not plan.get("force", force or purge):
            print("常规重置可追加 --release-stale-reset 释放过期占用；--purge-imported-data 会强制清除旧入库数据，不受任务状态限制。")


def _print_policy_extraction_summary(status: dict) -> None:
    """打印制度实体关系抽取运行统计。"""
    run = status["run"]
    print(f"\n抽取运行 ID: {run['run_id']}")
    print(f"抽取状态: {run.get('status')}")
    print(f"总条款数: {run.get('total_count', 0)}")
    print(f"成功: {run.get('succeeded_count', 0)}")
    print(f"失败: {run.get('failed_count', 0)}")
    print(f"当前版本: {'是' if run.get('is_current') else '否'}")


def run_extract_policy_batch(batch_id: str, limit: int | None = None) -> None:
    """创建一个新的制度实体关系抽取版本并执行。"""
    from policy.graph.extraction import create_and_run_policy_extraction
    print(f"{datetime.datetime.now()} 开始抽取关系")

    _print_policy_extraction_summary(
        create_and_run_policy_extraction(batch_id, limit=limit)
    )
    print(f"{datetime.datetime.now()} 结束抽取")


def _print_policy_knowledge_v2_summary(run: dict) -> None:
    print(f"\nV2 抽取运行 ID: {run.get('run_id', '')}")
    print(f"状态: {run.get('status', '')}")
    print(f"总条款数: {run.get('total_count', 0)}")
    print(f"成功: {run.get('succeeded_count', 0)}")
    print(f"失败: {run.get('failed_count', 0)}")


def run_extract_policy_knowledge_v2(batch_id: str, sample_path: str | None = None) -> None:
    from policy.knowledge_v2.runner import create_and_run_knowledge_extraction_v2

    _print_policy_knowledge_v2_summary(create_and_run_knowledge_extraction_v2(batch_id, sample_path=sample_path))


def run_resume_policy_knowledge_v2(run_id: str) -> None:
    from policy.knowledge_v2.runner import run_knowledge_extraction_v2

    _print_policy_knowledge_v2_summary(run_knowledge_extraction_v2(run_id, resume=True))


def run_policy_knowledge_v2_status(run_id: str) -> None:
    from policy.storage import get_policy_knowledge_run_v2

    run = get_policy_knowledge_run_v2(run_id)
    if not run:
        raise ValueError(f"V2 抽取运行不存在: {run_id}")
    _print_policy_knowledge_v2_summary(run)


def run_export_policy_knowledge_v2_review(run_id: str, output_path: str) -> None:
    from policy.knowledge_v2.review import export_assertion_review_v2

    print(f"已导出 V2 断言复核表：{export_assertion_review_v2(run_id, output_path)}")


def run_import_policy_knowledge_v2_review(csv_path: str, reviewer: str) -> None:
    from policy.knowledge_v2.review import import_assertion_review_v2

    print(f"已导入 V2 复核结果：{import_assertion_review_v2(csv_path, reviewer)}")


def run_export_policy_knowledge_v2_view(run_id: str, output_path: str) -> None:
    from policy.knowledge_v2.review import export_knowledge_view_v2

    print(f"已导出 V2 事项与流程视图：{export_knowledge_view_v2(run_id, output_path)}")


def run_resume_policy_extraction(run_id: str) -> None:
    """恢复指定的制度实体关系抽取运行。"""
    from policy.graph.extraction import run_policy_extraction

    _print_policy_extraction_summary(run_policy_extraction(run_id, resume=True))


def run_policy_extraction_status(run_id: str) -> None:
    """查看制度实体关系抽取状态，不执行抽取。"""
    from policy.graph.extraction import get_policy_extraction_status

    _print_policy_extraction_summary(get_policy_extraction_status(run_id))


def _print_policy_clause_index_summary(status: dict) -> None:
    """打印跨制度条款索引运行统计和失败原因。"""
    run = status.get("run", status)
    print(f"\n条款索引运行 ID: {run['run_id']}")
    print(f"索引状态: {run.get('status')}")
    print(f"总制度数: {run.get('total_count', 0)}")
    print(f"成功: {run.get('succeeded_count', 0)}")
    print(f"跳过: {run.get('skipped_count', 0)}")
    print(f"失败: {run.get('failed_count', 0)}")
    for item in status.get("items", []):
        if item.get("status") == "failed":
            print(f"  失败制度 {item.get('policy_id')}: {item.get('last_error')}")


def run_rebuild_policy_clause_index(batch_id: str) -> None:
    """为一个已结构化批次创建并执行全局条款索引重建。"""
    from policy.retrieval import create_and_run_policy_clause_index

    _print_policy_clause_index_summary(create_and_run_policy_clause_index(batch_id))


def run_resume_policy_clause_index(run_id: str) -> None:
    """只恢复失败的制度条款索引任务。"""
    from policy.retrieval import run_policy_clause_index

    _print_policy_clause_index_summary(run_policy_clause_index(run_id, resume=True))


def run_policy_clause_index_status(run_id: str) -> None:
    """查看条款索引重建进度和逐制度失败原因。"""
    from policy.retrieval import get_policy_clause_index_status

    _print_policy_clause_index_summary(get_policy_clause_index_status(run_id))


def run_policy_review(run_id: str, reviewer: str, limit: int) -> None:
    """在终端逐项人工审核制度实体和关系候选。"""
    from policy.graph.reviewer import run_interactive_policy_review

    summary = run_interactive_policy_review(run_id, reviewer=reviewer, limit=limit)
    print("\n本次人工审核统计:")
    print(f"通过: {summary['approved']}")
    print(f"拒绝: {summary['rejected']}")
    print(f"修正: {summary['corrected']}")
    print(f"补充: {summary['added']}")
    print(f"跳过: {summary['skipped']}")


def run_extract_policy_abolition_relations(batch_id: str) -> None:
    """抽取一个批次中需要人工确认的制度废止关系。"""
    from policy.abolition import extract_batch_abolition_relations

    summary = extract_batch_abolition_relations(batch_id)
    print("\n废止关系抽取统计:")
    for key, label in (("policies", "制度"), ("clauses", "条款"), ("candidates", "候选"), ("resolved", "已解析"), ("unresolved", "待解析")):
        print(f"{label}: {summary[key]}")


def run_policy_abolition_relation_status(batch_id: str) -> None:
    """显示一个批次的废止关系审核和解析状态。"""
    from policy.abolition import get_batch_abolition_relation_status

    summary = get_batch_abolition_relation_status(batch_id)
    print("\n废止关系状态:")
    for key, label in (("total", "总数"), ("pending", "待审核"), ("approved", "已通过"), ("rejected", "已拒绝"), ("resolved", "已解析"), ("unresolved", "待解析")):
        print(f"{label}: {summary[key]}")


def run_policy_abolition_review(batch_id: str, reviewer: str, limit: int) -> None:
    """在终端审核一个批次中待处理的制度废止候选。"""
    from policy.abolition import run_interactive_abolition_review

    summary = run_interactive_abolition_review(batch_id, reviewer, limit)
    print("\n本次废止关系审核统计:")
    print(f"通过: {summary['approved']}")
    print(f"拒绝: {summary['rejected']}")
    print(f"跳过: {summary['skipped']}")


def run_policy_governance_backfill(batch_id: str) -> None:
    """回填批次的生效日期并生成制度族候选。"""
    from policy.governance import backfill_policy_governance
    summary = backfill_policy_governance(batch_id)
    print("\n制度版本治理回填统计:")
    for key, label in (("documents", "制度"), ("dated", "已有生效日期"),
                       ("date_unknown", "日期未知"), ("date_conflicts", "日期冲突"),
                       ("family_assigned", "已归族"), ("family_pending", "待确认归族"),
                       ("family_overlaps", "版本区间重叠")):
        print(f"{label}: {summary[key]}")


def run_policy_governance_status(batch_id: str) -> None:
    """显示批次的文档级版本治理状态。"""
    from policy.governance import get_policy_governance_status
    print(get_policy_governance_status(batch_id))


def run_policy_family_review(batch_id: str, reviewer: str, limit: int) -> None:
    """在终端审核制度族候选。"""
    from policy.governance import run_interactive_family_review
    summary = run_interactive_family_review(batch_id, reviewer, limit)
    print(f"\n归族审核统计: 通过 {summary['approved']}，拒绝 {summary['rejected']}，跳过 {summary['skipped']}")


def _print_quality_outputs(title: str, paths: dict[str, Path]) -> None:
    """输出质检工具生成的文件路径。"""
    print(f"\n{title}")
    for name, path in paths.items():
        print(f"  {name}: {path}")


def run_export_policy_clause_review(
    batch_id: str,
    output_dir: str,
    clauses_per_policy: int,
) -> None:
    """导出一个批次的条款人工抽检表。"""
    from policy.quality import export_clause_review

    _print_quality_outputs(
        "已导出条款抽检表：",
        export_clause_review(batch_id, output_dir, clauses_per_policy),
    )


def _print_policy_process_summary(status: dict) -> None:
    """打印流程条款分流运行统计。"""
    run = status.get("run", status)
    print(f"\n流程判定运行 ID: {run['run_id']}")
    print(f"运行状态: {run.get('status')}")
    print(f"总条款数: {run.get('total_count', 0)}")
    print(f"流程条款: {run.get('process_count', 0)}")
    print(f"非流程条款: {run.get('non_process_count', 0)}")
    print(f"待人工确认: {run.get('pending_count', 0)}")
    print(f"失败: {run.get('failed_count', 0)}")


def run_classify_policy_process_batch(
    batch_id: str,
    selected_domains: Sequence[str] | None = None,
) -> None:
    """创建并运行一个制度批次的流程条款分流。"""
    from policy.graph.process_runner import create_and_run_policy_process_classification

    _print_policy_process_summary(
        create_and_run_policy_process_classification(batch_id, selected_domains=selected_domains)
    )


def run_resume_policy_process(run_id: str) -> None:
    """恢复指定流程判定运行中的失败条款。"""
    from policy.graph.process_runner import run_policy_process_classification

    _print_policy_process_summary(run_policy_process_classification(run_id, resume=True))


def run_policy_process_status(run_id: str) -> None:
    """查看流程判定运行状态，不执行分流。"""
    from policy.graph.process_runner import get_policy_process_status

    _print_policy_process_summary(get_policy_process_status(run_id))


def _print_policy_classification_summary(status: dict) -> None:
    """打印条款规范类型分类统计。"""
    run = status.get("run", status)
    print(f"\n条款分类运行 ID: {run['run_id']}")
    print(f"运行状态: {run.get('status')}")
    print(f"总条款数: {run.get('total_count', 0)}")
    print(f"成功: {run.get('succeeded_count', 0)}")
    print(f"失败: {run.get('failed_count', 0)}")


def run_classify_policy_clauses(batch_id: str) -> None:
    from policy.clause_classification.runner import create_and_run_policy_clause_classification
    _print_policy_classification_summary(create_and_run_policy_clause_classification(batch_id))


def run_resume_policy_clause_classification(run_id: str) -> None:
    from policy.clause_classification.runner import run_policy_clause_classification
    _print_policy_classification_summary(run_policy_clause_classification(run_id, resume=True))


def run_policy_clause_classification_status(run_id: str) -> None:
    from policy.clause_classification.runner import get_policy_clause_classification_status
    _print_policy_classification_summary(get_policy_clause_classification_status(run_id))


def run_export_policy_classification_review(run_id: str, output_dir: str) -> None:
    from policy.clause_classification.review import export_classification_review
    print(f"已导出条款分类复核表：{export_classification_review(run_id, output_dir)}")


def run_import_policy_classification_review(csv_path: str, reviewer: str) -> None:
    from policy.clause_classification.review import import_classification_review
    result = import_classification_review(csv_path, reviewer)
    print(f"已导入 {result['reviewed_count']} 条人工复核结果")
    print(f"多标签完全一致率: {result['exact_match_rate']:.2%}")
    print(f"质量报告: {result['report_path']}")


def run_extract_policy_process_run(process_run_id: str, limit: int | None = None) -> None:
    """只从流程判定运行中已确认的条款执行实体关系抽取。"""
    from policy.graph.extraction import create_and_run_process_policy_extraction

    _print_policy_extraction_summary(
        create_and_run_process_policy_extraction(process_run_id, limit=limit)
    )


def run_export_policy_graph_review(run_id: str, output_dir: str) -> None:
    """导出一次抽取运行的图谱候选人工抽检表。"""
    from policy.quality import export_graph_review

    _print_quality_outputs(
        "已导出图谱抽检表：",
        export_graph_review(run_id, output_dir),
    )


def run_export_policy_process_review(process_run_id: str, output_dir: str) -> None:
    """导出流程条款分流的人工审核表。"""
    from policy.quality import export_process_review

    _print_quality_outputs(
        "已导出流程条款抽检表：",
        export_process_review(process_run_id, output_dir),
    )


def run_export_policy_process_graph_review(run_id: str, output_dir: str) -> None:
    """导出仅限流程条款来源的图谱人工审核表。"""
    from policy.quality import export_process_graph_review

    _print_quality_outputs(
        "已导出流程图谱抽检表：",
        export_process_graph_review(run_id, output_dir),
    )


def run_export_policy_workflow_graph(run_id: str, output_path: str) -> None:
    """导出指定流程抽取运行的已审核办事流程图谱 JSON。"""
    from policy.graph.workflow_graph import export_policy_workflow_graph

    path = export_policy_workflow_graph(run_id, output_path)
    print(f"已导出办事流程图谱：{path}")


def run_report_policy_quality(output_dir: str) -> None:
    """读取已回填的审核表并生成质量报告。"""
    from policy.quality import write_quality_report

    _print_quality_outputs(
        "已生成质量报告：",
        write_quality_report(output_dir),
    )



def run_migrate_text_chunks(*, dry_run=False, legacy_model=None):
    """输出逐文件迁移报告；存在失败项时返回非零退出码。"""
    import json
    from storage.text_migration import migrate_text_chunks
    report = migrate_text_chunks(dry_run=dry_run, legacy_model=legacy_model)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise SystemExit(1)


def run_normalize_applicable_units(*, dry_run=False):
    """由操作者显式预览或执行已有适用单位的统一。"""
    import json
    from policy.unit_normalization import normalize_stored_applicable_units
    print(json.dumps(normalize_stored_applicable_units(dry_run=dry_run), ensure_ascii=False, indent=2))


def run_rebuild_file_text(file_id: str, *, source_path=None):
    """为单个冲突文件重新生成文本向量，不运行文件重置。"""
    import json
    from processing.text_rebuild import rebuild_file_text
    try:
        report=rebuild_file_text(file_id,source_path)
    except ValueError as exc:
        raise SystemExit(f'文本重建未执行或未完成：{exc}') from None
    print(json.dumps(report,ensure_ascii=False,indent=2))
