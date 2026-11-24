"""命令行参数定义、使用指南与参数校验。"""

import argparse


_COMMAND_ARGUMENTS = (
    "rebuild_file_text",
    "normalize_applicable_units",
    "migrate_text_chunks",
    "sample_policy_knowledge_v2",
    "process",
    "process_dir",
    "resume_batch",
    "batch_status",
    "reset_file",
    "reset_folder",
    "extract_policy_batch",
    "extract_policy_knowledge_v2",
    "resume_policy_knowledge_v2",
    "policy_knowledge_v2_status",
    "export_policy_knowledge_v2_review",
    "import_policy_knowledge_v2_review",
    "export_policy_knowledge_v2_view",
    "classify_policy_process_batch",
    "classify_policy_clauses",
    "resume_policy_clause_classification",
    "policy_clause_classification_status",
    "resume_policy_process",
    "policy_process_status",
    "extract_policy_process_run",
    "resume_policy_extraction",
    "policy_extraction_status",
    "rebuild_policy_clause_index",
    "resume_policy_clause_index",
    "policy_clause_index_status",
    "review_policy_run",
    "extract_policy_abolition_relations",
    "policy_abolition_relation_status",
    "backfill_policy_governance",
    "policy_governance_status",
    "review_policy_families",
    "review_policy_abolition_relations",
    "export_policy_clause_review",
    "export_policy_graph_review",
    "export_policy_process_review",
    "export_policy_process_graph_review",
    "export_policy_workflow_graph",
    "report_policy_quality",
    "export_policy_classification_review",
    "import_policy_classification_review",
)


def print_core_help() -> None:
    """打印文件处理、条款索引与制度问答的主线指南。"""
    print(
        """
文件处理与制度问答：三步上手

目标：导入制度文件，准备可回查原文的条款索引，再使用制度问答。

第 1 步：导入 PDF/DOC/DOCX（命令结束后记下输出的 batch_id）
  python main.py --process-dir "D:\\policies"

  制度条款结构化后自动同步索引，正常导入无需手动重建。

第 2 步：启动服务
  python main.py

第 3 步：打开制度问答页面
  http://127.0.0.1:12700/policy-qa

补充：处理单个 PDF 可用 --process "D:\\policies\\示例.pdf"。
索引失败不影响结构化结果；历史数据补建或失败修复见 README 的维护操作。
状态恢复、维护操作和研究命令请查看完整帮助；图谱方案见 docs/research/policy-knowledge.md：
  python main.py --help-all
        """.strip()
    )


def build_parser() -> argparse.ArgumentParser:
    """创建参数解析器，保留现有命令、分组和默认值。"""
    parser = argparse.ArgumentParser(
        description="PDF 多模态提取入仓工具（运行 --help 查看核心操作）",
        add_help=False,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="显示文件处理、条款索引和制度问答的三步指南",
    )
    parser.add_argument(
        "--help-all",
        action="help",
        help="显示全部命令和进阶功能",
    )

    pdf_group = parser.add_argument_group("PDF 导入")
    entity_graph_group = parser.add_argument_group("实体和关系抽取")
    workflow_group = parser.add_argument_group("办事流程图谱（研究）")
    recovery_group = parser.add_argument_group("状态、恢复与条款检索（进阶）")
    quality_group = parser.add_argument_group("抽检与质量报告（进阶）")
    classification_group = parser.add_argument_group("条款义务、许可、禁止分类（研究）")
    knowledge_v2_group = parser.add_argument_group("制度知识抽取 V2（研究）")

    recovery_group.add_argument("--migrate-text-chunks", action="store_true", help="将旧文本向量迁移到共享表，保留源表")
    recovery_group.add_argument("--rebuild-file-text", help="仅重建指定文件的共享文本向量，保留旧表及制度审核数据")
    recovery_group.add_argument("--text-source", help="文本重建使用的原文件路径，须与原记录SHA256一致")
    recovery_group.add_argument("--normalize-applicable-units", action="store_true", help="按学院别名表统一历史制度适用单位")
    recovery_group.add_argument("--unit-normalization-dry-run", action="store_true", help="仅预览适用单位统一结果，不修改数据")
    recovery_group.add_argument("--text-migration-dry-run", action="store_true", help="仅预检查文本迁移，不写入数据")
    recovery_group.add_argument("--legacy-embedding-model", help="为缺少模型记录的旧文件明确声明原嵌入模型")

    pdf_group.add_argument(
        "--process",
        type=str,
        help="处理单个 PDF 文件的路径"
    )
    pdf_group.add_argument(
        "--backend",
        type=str,
        choices=["cloudmineru", "mineru", "pymupdf"],
        default=None,
        help="指定解析后端：cloudmineru、mineru（本地 MinerU）或 pymupdf，默认从 config 读取"
    )
    pdf_group.add_argument(
        "--process-dir",
        type=str,
        help="递归创建并处理目录中的全部 PDF"
    )
    recovery_group.add_argument(
        "--resume-batch",
        type=str,
        help="恢复指定批次，只处理未完成或到期重试的文件"
    )
    recovery_group.add_argument(
        "--batch-status",
        type=str,
        help="查看指定批次状态，不执行文件"
    )
    recovery_group.add_argument(
        "--reset-file",
        type=str,
        help="删除指定文件的数据库自动产物并置为待处理，供重新解析使用",
    )
    recovery_group.add_argument(
        "--reset-folder",
        type=str,
        help="预览指定目录（含子目录）中所有已导入文件的整体重置范围",
    )
    recovery_group.add_argument(
        "--force-reset-folder",
        action="store_true",
        help="与 --reset-folder 配合，忽略文件和条款任务状态及时间强制重置；不会终止后台进程",
    )
    recovery_group.add_argument(
        "--purge-imported-data",
        action="store_true",
        help="与 --reset-folder 配合，忽略任务状态强制清除旧制度元数据、所有相关废止关系及无剩余任务的运行记录；保留原始文件和稳定 ID",
    )
    recovery_group.add_argument(
        "--release-stale-reset",
        action="store_true",
        help="与 --reset-folder 配合，确认旧进程已退出后释放过期文件及条款任务；仍保护近期活动和无法核实过期的任务",
    )
    recovery_group.add_argument(
        "--allow-shared-reset",
        action="store_true",
        help="与 --reset-folder 配合，允许清理其他目录批次共用的文件结果；仍禁止重置正在处理的文件",
    )
    recovery_group.add_argument(
        "--confirm-reset-folder",
        action="store_true",
        help="与 --reset-folder 一起使用，确认清理该目录全部已导入文件的数据库产物",
    )
    entity_graph_group.add_argument(
        "--extract-policy-batch",
        type=str,
        help="为指定 PDF 批次创建并执行制度实体关系抽取"
    )
    entity_graph_group.add_argument(
        "--limit",
        type=int,
        help="仅抽取前 N 条实质性条款；可与两种实体关系抽取命令一起使用"
    )
    recovery_group.add_argument(
        "--resume-policy-extraction",
        type=str,
        help="恢复指定的制度实体关系抽取运行"
    )
    recovery_group.add_argument(
        "--policy-extraction-status",
        type=str,
        help="查看指定制度实体关系抽取运行状态"
    )
    recovery_group.add_argument(
        "--rebuild-policy-clause-index",
        type=str,
        help="为指定已结构化 PDF 批次建立跨制度条款索引",
    )
    recovery_group.add_argument(
        "--resume-policy-clause-index",
        type=str,
        help="恢复指定条款索引运行中的失败制度",
    )
    recovery_group.add_argument(
        "--policy-clause-index-status",
        type=str,
        help="查看指定跨制度条款索引运行状态",
    )
    entity_graph_group.add_argument(
        "--review-policy-run",
        type=str,
        help="在终端逐项人工审核指定抽取运行的实体和关系候选"
    )
    entity_graph_group.add_argument(
        "--extract-policy-abolition-relations",
        type=str,
        help="从指定已结构化 PDF 批次抽取待审核的制度废止关系",
    )
    recovery_group.add_argument(
        "--policy-abolition-relation-status",
        type=str,
        help="查看指定批次的制度废止关系审核状态",
    )
    knowledge_v2_group.add_argument(
        "--extract-policy-knowledge-v2", type=str,
        help="为指定已结构化批次创建并执行制度断言与明确结构事项抽取",
    )
    knowledge_v2_group.add_argument(
        "--resume-policy-knowledge-v2", type=str,
        help="恢复指定 V2 知识抽取运行中的失败条款",
    )
    knowledge_v2_group.add_argument(
        "--policy-knowledge-v2-status", type=str,
        help="查看指定 V2 知识抽取运行状态",
    )
    knowledge_v2_group.add_argument("--export-policy-knowledge-v2-review", type=str, help="导出指定 V2 运行的断言复核 CSV")
    knowledge_v2_group.add_argument("--import-policy-knowledge-v2-review", type=str, help="导入 V2 断言复核 CSV")
    knowledge_v2_group.add_argument("--knowledge-v2-reviewer", type=str, help="导入 V2 复核表时使用的审核人")
    knowledge_v2_group.add_argument("--export-policy-knowledge-v2-view", type=str, help="导出指定 V2 运行的事项与流程视图 JSON")
    knowledge_v2_group.add_argument("--knowledge-v2-output", type=str, help="V2 复核 CSV 或事项流程 JSON 输出路径")
    knowledge_v2_group.add_argument("--sample-policy-knowledge-v2", type=str, help="为批次导出代表性条款清单，不调用模型")
    knowledge_v2_group.add_argument("--knowledge-v2-sample-count", type=int, default=20, help="样本条款数，默认20")
    knowledge_v2_group.add_argument("--knowledge-v2-sample-file", type=str, help="只抽取指定清单中选用的条款")
    recovery_group.add_argument("--backfill-policy-governance", type=str, help="回填指定批次的制度生效日期并生成归族候选")
    recovery_group.add_argument("--policy-governance-status", type=str, help="查看指定批次的制度版本治理状态")
    entity_graph_group.add_argument("--review-policy-families", type=str, help="审核指定批次的制度族候选")
    entity_graph_group.add_argument("--family-reviewer", type=str, help="制度族审核人；只可与 --review-policy-families 一起使用")
    entity_graph_group.add_argument("--family-review-limit", type=int, default=None, help="制度族审核上限，默认 20")
    entity_graph_group.add_argument(
        "--review-policy-abolition-relations",
        type=str,
        help="在终端审核指定批次的制度废止关系候选",
    )
    entity_graph_group.add_argument(
        "--abolition-reviewer",
        type=str,
        help="废止关系审核人的姓名或账号；只可与 --review-policy-abolition-relations 一起使用",
    )
    entity_graph_group.add_argument(
        "--abolition-review-limit",
        type=int,
        default=None,
        help="本次最多显示多少条待审核废止关系，默认 20；只可与 --review-policy-abolition-relations 一起使用",
    )
    entity_graph_group.add_argument(
        "--reviewer",
        type=str,
        help="人工审核人的姓名或账号；只可与 --review-policy-run 一起使用"
    )
    entity_graph_group.add_argument(
        "--review-limit",
        type=int,
        default=20,
        help="本次最多显示多少条待审核候选，默认 20；只可与 --review-policy-run 一起使用"
    )
    workflow_group.add_argument(
        "--classify-policy-process-batch",
        type=str,
        help="为指定 PDF 批次创建并执行流程条款分流",
    )
    classification_group.add_argument(
        "--classify-policy-clauses",
        type=str,
        help="为指定已结构化批次创建并执行条款义务、许可、禁止分类",
    )
    classification_group.add_argument(
        "--resume-policy-clause-classification",
        type=str,
        help="恢复指定条款分类运行中的失败任务",
    )
    classification_group.add_argument(
        "--policy-clause-classification-status",
        type=str,
        help="查看指定条款分类运行状态",
    )
    workflow_group.add_argument(
        "--policy-domains",
        type=str,
        help="流程分流的事项域代码，逗号分隔；省略则使用目录中全部启用事项域",
    )
    workflow_group.add_argument(
        "--resume-policy-process",
        type=str,
        help="恢复指定流程条款分流运行中的失败条款",
    )
    workflow_group.add_argument(
        "--policy-process-status",
        type=str,
        help="查看指定流程条款分流运行状态",
    )
    workflow_group.add_argument(
        "--extract-policy-process-run",
        type=str,
        help="只从指定流程判定运行的已确认条款抽取实体和关系",
    )
    quality_group.add_argument(
        "--export-policy-clause-review",
        type=str,
        help="导出指定批次的制度条款人工抽检 CSV"
    )
    entity_graph_group.add_argument(
        "--export-policy-graph-review",
        type=str,
        help="导出指定抽取运行的实体关系人工抽检 CSV"
    )
    workflow_group.add_argument(
        "--export-policy-process-review",
        type=str,
        help="导出指定流程判定运行的流程条款人工抽检 CSV",
    )
    workflow_group.add_argument(
        "--export-policy-process-graph-review",
        type=str,
        help="导出指定流程图谱抽取运行的实体关系人工抽检 CSV",
    )
    workflow_group.add_argument(
        "--export-policy-workflow-graph",
        type=str,
        help="导出指定流程抽取运行的已审核办事流程图谱 JSON",
    )
    workflow_group.add_argument(
        "--workflow-graph-output",
        type=str,
        help="办事流程图谱 JSON 的输出文件；只可与 --export-policy-workflow-graph 一起使用",
    )
    quality_group.add_argument(
        "--report-policy-quality",
        type=str,
        help="读取指定目录中回填的抽检 CSV，生成质量报告"
    )
    classification_group.add_argument(
        "--export-policy-classification-review",
        type=str,
        help="导出指定条款分类运行的人工复核 CSV",
    )
    classification_group.add_argument(
        "--import-policy-classification-review",
        type=str,
        help="导入人工回填的条款分类复核 CSV",
    )
    classification_group.add_argument(
        "--classification-reviewer",
        type=str,
        help="条款分类 CSV 导入审核人；只可与导入命令一起使用",
    )
    quality_group.add_argument(
        "--quality-output",
        type=str,
        help="条款或图谱抽检 CSV 的输出目录"
    )
    quality_group.add_argument(
        "--clauses-per-policy",
        type=int,
        default=10,
        help="每份制度均匀抽取的条款数，默认 10；只可与 --export-policy-clause-review 一起使用"
    )
    return parser


def validate_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> list[str] | None:
    """校验命令组合，返回流程分流所选的事项域。"""
    if (args.text_migration_dry_run or args.legacy_embedding_model) and not args.migrate_text_chunks:
        parser.error("文本迁移选项只能与 --migrate-text-chunks 一起使用")
    if args.unit_normalization_dry_run and not args.normalize_applicable_units:
        parser.error("--unit-normalization-dry-run 只能与 --normalize-applicable-units 一起使用")
    if args.text_source and not args.rebuild_file_text:
        parser.error("--text-source 只能与 --rebuild-file-text 一起使用")
    if sum(bool(getattr(args, name)) for name in _COMMAND_ARGUMENTS) > 1:
        parser.error("处理、批次和制度抽取参数只能选择一个")
    if args.reset_file:
        from processing.reset import is_valid_file_id

        if not is_valid_file_id(args.reset_file):
            parser.error("文件 ID 格式非法")
    for option in (
        "confirm_reset_folder",
        "allow_shared_reset",
        "release_stale_reset",
        "purge_imported_data",
        "force_reset_folder",
    ):
        if getattr(args, option) and not args.reset_folder:
            parser.error(f"--{option.replace('_', '-')} 只能与 --reset-folder 一起使用")
    if args.limit is not None and not (args.extract_policy_batch or args.extract_policy_process_run):
        parser.error("--limit 只能与制度实体关系抽取参数一起使用")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须大于等于 1")
    if args.knowledge_v2_reviewer and not args.import_policy_knowledge_v2_review:
        parser.error("--knowledge-v2-reviewer 只能与 V2 复核导入一起使用")
    if args.import_policy_knowledge_v2_review and not str(args.knowledge_v2_reviewer or "").strip():
        parser.error("导入 V2 复核表必须提供 --knowledge-v2-reviewer")
    if (args.export_policy_knowledge_v2_review or args.export_policy_knowledge_v2_view) and not args.knowledge_v2_output:
        parser.error("导出 V2 产物必须提供 --knowledge-v2-output")
    if args.sample_policy_knowledge_v2 and (not args.knowledge_v2_output or args.knowledge_v2_sample_count < 1):
        parser.error("生成样本需要输出路径和正数样本数量")
    if args.knowledge_v2_sample_file and not args.extract_policy_knowledge_v2:
        parser.error("样本清单只能与 V2 抽取命令一起使用")
    if args.knowledge_v2_output and not (args.export_policy_knowledge_v2_review or args.export_policy_knowledge_v2_view or args.sample_policy_knowledge_v2):
        parser.error("--knowledge-v2-output 只能与 V2 导出命令一起使用")
    if args.policy_domains is not None and not args.classify_policy_process_batch:
        parser.error("--policy-domains 只能与 --classify-policy-process-batch 一起使用")
    selected_domains = None
    if args.policy_domains is not None:
        selected_domains = [item.strip() for item in args.policy_domains.split(",") if item.strip()]
        if not selected_domains:
            parser.error("--policy-domains 至少需要一个事项域代码")
    if args.workflow_graph_output and not args.export_policy_workflow_graph:
        parser.error("--workflow-graph-output 只能与 --export-policy-workflow-graph 一起使用")
    if args.export_policy_workflow_graph and not args.workflow_graph_output:
        parser.error("--export-policy-workflow-graph 必须提供 --workflow-graph-output")
    if args.reviewer and not args.review_policy_run:
        parser.error("--reviewer 只能与 --review-policy-run 一起使用")
    if args.review_policy_run and not args.reviewer:
        parser.error("--review-policy-run 必须提供 --reviewer")
    if args.abolition_reviewer and not args.review_policy_abolition_relations:
        parser.error("--abolition-reviewer 只能与 --review-policy-abolition-relations 一起使用")
    if args.review_policy_abolition_relations and not str(args.abolition_reviewer or "").strip():
        parser.error("--review-policy-abolition-relations 必须提供非空 --abolition-reviewer")
    if args.abolition_review_limit is not None:
        if args.abolition_review_limit < 1:
            parser.error("--abolition-review-limit 必须大于等于 1")
        if not args.review_policy_abolition_relations:
            parser.error("--abolition-review-limit 只能与 --review-policy-abolition-relations 一起使用")
    if args.family_reviewer and not args.review_policy_families:
        parser.error("--family-reviewer 只能与 --review-policy-families 一起使用")
    if args.review_policy_families and not str(args.family_reviewer or "").strip():
        parser.error("--review-policy-families 必须提供非空 --family-reviewer")
    if args.family_review_limit is not None and args.family_review_limit < 1:
        parser.error("--family-review-limit 必须大于等于 1")
    if args.family_review_limit is not None and not args.review_policy_families:
        parser.error("--family-review-limit 只能与 --review-policy-families 一起使用")
    if args.review_limit < 1:
        parser.error("--review-limit 必须大于等于 1")
    if args.classification_reviewer and not args.import_policy_classification_review:
        parser.error("--classification-reviewer 只能与 --import-policy-classification-review 一起使用")
    if args.import_policy_classification_review and not str(args.classification_reviewer or "").strip():
        parser.error("--import-policy-classification-review 必须提供 --classification-reviewer")
    if args.clauses_per_policy < 1:
        parser.error("--clauses-per-policy 必须大于等于 1")
    exporting_review = (
        args.export_policy_clause_review
        or args.export_policy_graph_review
        or args.export_policy_process_review
        or args.export_policy_process_graph_review
        or args.export_policy_classification_review
    )
    if args.quality_output and not exporting_review:
        parser.error("--quality-output 只能与质检表导出参数一起使用")
    if args.clauses_per_policy != 10 and not args.export_policy_clause_review:
        parser.error("--clauses-per-policy 只能与 --export-policy-clause-review 一起使用")
    if exporting_review and not args.quality_output:
        parser.error("导出质检表必须提供 --quality-output")
    return selected_domains
