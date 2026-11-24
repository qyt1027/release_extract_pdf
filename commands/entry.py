"""解析命令行，校验参数并分发到终端任务。"""

import os
from typing import Sequence

from dotenv import load_dotenv

from core.paths import ENV_FILE, PROJECT_ROOT
from .arguments import build_parser, print_core_help, validate_args
from .handlers import (
    run_api,
    run_batch_status,
    run_classify_policy_clauses,
    run_classify_policy_process_batch,
    run_export_policy_classification_review,
    run_export_policy_clause_review,
    run_export_policy_graph_review,
    run_export_policy_knowledge_v2_review,
    run_export_policy_knowledge_v2_view,
    run_export_policy_process_graph_review,
    run_export_policy_process_review,
    run_export_policy_workflow_graph,
    run_extract_policy_abolition_relations,
    run_extract_policy_batch,
    run_extract_policy_knowledge_v2,
    run_extract_policy_process_run,
    run_import_policy_classification_review,
    run_import_policy_knowledge_v2_review,
    run_policy_abolition_relation_status,
    run_policy_abolition_review,
    run_policy_clause_classification_status,
    run_policy_clause_index_status,
    run_policy_extraction_status,
    run_policy_family_review,
    run_policy_governance_backfill,
    run_policy_governance_status,
    run_policy_knowledge_v2_status,
    run_policy_process_status,
    run_policy_review,
    run_process,
    run_process_dir,
    run_rebuild_policy_clause_index,
    run_report_policy_quality,
    run_reset_file,
    run_reset_folder,
    run_resume_batch,
    run_resume_policy_clause_classification,
    run_resume_policy_clause_index,
    run_resume_policy_extraction,
    run_resume_policy_knowledge_v2,
    run_resume_policy_process,
)


def main(argv: Sequence[str] | None = None) -> None:
    """解析命令行并执行对应任务；省略参数时读取系统命令行。"""
    load_dotenv(ENV_FILE)
    # 保留原启动入口以项目根目录为工作目录的行为。
    os.chdir(PROJECT_ROOT)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.help:
        print_core_help()
        return

    selected_domains = validate_args(parser, args)

    if args.process_dir:
        run_process_dir(args.process_dir, backend=args.backend)
    elif args.reset_file:
        run_reset_file(args.reset_file)
    elif args.reset_folder:
        run_reset_folder(args.reset_folder, confirm=args.confirm_reset_folder, allow_shared=args.allow_shared_reset,
                         release_stale=args.release_stale_reset, purge=args.purge_imported_data,
                         force=args.force_reset_folder)
    elif args.resume_batch:
        run_resume_batch(args.resume_batch)
    elif args.batch_status:
        run_batch_status(args.batch_status)
    elif args.extract_policy_batch:
        run_extract_policy_batch(args.extract_policy_batch, limit=args.limit)
    elif args.extract_policy_knowledge_v2:
        run_extract_policy_knowledge_v2(args.extract_policy_knowledge_v2, args.knowledge_v2_sample_file)
    elif args.sample_policy_knowledge_v2:
        from policy.knowledge_v2.sampling import export_samples

        print(export_samples(args.sample_policy_knowledge_v2, args.knowledge_v2_output, args.knowledge_v2_sample_count))
    elif args.resume_policy_knowledge_v2:
        run_resume_policy_knowledge_v2(args.resume_policy_knowledge_v2)
    elif args.policy_knowledge_v2_status:
        run_policy_knowledge_v2_status(args.policy_knowledge_v2_status)
    elif args.export_policy_knowledge_v2_review:
        run_export_policy_knowledge_v2_review(args.export_policy_knowledge_v2_review, args.knowledge_v2_output)
    elif args.import_policy_knowledge_v2_review:
        run_import_policy_knowledge_v2_review(args.import_policy_knowledge_v2_review, args.knowledge_v2_reviewer)
    elif args.export_policy_knowledge_v2_view:
        run_export_policy_knowledge_v2_view(args.export_policy_knowledge_v2_view, args.knowledge_v2_output)
    elif args.classify_policy_process_batch:
        run_classify_policy_process_batch(
            args.classify_policy_process_batch,
            selected_domains=selected_domains,
        )
    elif args.classify_policy_clauses:
        run_classify_policy_clauses(args.classify_policy_clauses)
    elif args.resume_policy_clause_classification:
        run_resume_policy_clause_classification(args.resume_policy_clause_classification)
    elif args.policy_clause_classification_status:
        run_policy_clause_classification_status(args.policy_clause_classification_status)
    elif args.resume_policy_process:
        run_resume_policy_process(args.resume_policy_process)
    elif args.policy_process_status:
        run_policy_process_status(args.policy_process_status)
    elif args.extract_policy_process_run:
        run_extract_policy_process_run(args.extract_policy_process_run, limit=args.limit)
    elif args.resume_policy_extraction:
        run_resume_policy_extraction(args.resume_policy_extraction)
    elif args.policy_extraction_status:
        run_policy_extraction_status(args.policy_extraction_status)
    elif args.rebuild_policy_clause_index:
        run_rebuild_policy_clause_index(args.rebuild_policy_clause_index)
    elif args.resume_policy_clause_index:
        run_resume_policy_clause_index(args.resume_policy_clause_index)
    elif args.policy_clause_index_status:
        run_policy_clause_index_status(args.policy_clause_index_status)
    elif args.review_policy_run:
        run_policy_review(args.review_policy_run, args.reviewer, args.review_limit)
    elif args.extract_policy_abolition_relations:
        run_extract_policy_abolition_relations(args.extract_policy_abolition_relations)
    elif args.policy_abolition_relation_status:
        run_policy_abolition_relation_status(args.policy_abolition_relation_status)
    elif args.backfill_policy_governance:
        run_policy_governance_backfill(args.backfill_policy_governance)
    elif args.policy_governance_status:
        run_policy_governance_status(args.policy_governance_status)
    elif args.review_policy_families:
        run_policy_family_review(args.review_policy_families, args.family_reviewer, args.family_review_limit or 20)
    elif args.review_policy_abolition_relations:
        run_policy_abolition_review(
            args.review_policy_abolition_relations,
            args.abolition_reviewer,
            args.abolition_review_limit or 20,
        )
    elif args.export_policy_clause_review:
        run_export_policy_clause_review(
            args.export_policy_clause_review,
            args.quality_output,
            args.clauses_per_policy,
        )
    elif args.export_policy_graph_review:
        run_export_policy_graph_review(
            args.export_policy_graph_review,
            args.quality_output,
        )
    elif args.export_policy_process_review:
        run_export_policy_process_review(
            args.export_policy_process_review,
            args.quality_output,
        )
    elif args.export_policy_process_graph_review:
        run_export_policy_process_graph_review(
            args.export_policy_process_graph_review,
            args.quality_output,
        )
    elif args.export_policy_classification_review:
        run_export_policy_classification_review(
            args.export_policy_classification_review,
            args.quality_output,
        )
    elif args.import_policy_classification_review:
        run_import_policy_classification_review(
            args.import_policy_classification_review,
            args.classification_reviewer,
        )
    elif args.export_policy_workflow_graph:
        run_export_policy_workflow_graph(
            args.export_policy_workflow_graph,
            args.workflow_graph_output,
        )
    elif args.report_policy_quality:
        run_report_policy_quality(args.report_policy_quality)
    elif args.process:
        run_process(args.process, backend=args.backend)
    else:
        run_api()
