"""住宿制度小样本试验：抽取、隔离发布和盲评，均保留可复查产物。"""
import argparse
import csv
import hashlib
import json
from functools import partial
from pathlib import Path

from scripts.compare_policy_answers import DEFAULT_CASES, run_comparison, write_report


def prepare_exact_search(index_name, relational):
    """小样本采用精确检索，只移除试验表上不适用的近似加速索引。"""
    if not index_name.startswith("policy_assertion_pilot_"):
        raise ValueError("不得修改正式向量表的索引")
    from psycopg2 import sql

    with relational.conn.cursor() as cursor:
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = %s AND indexdef LIKE %s",
            (index_name, "%USING ivfflat%"),
        )
        for (name,) in cursor.fetchall():
            cursor.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier(name)))


def run(stage, directory):
    from policy import storage as policies
    from storage.adapters import storage

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "pilot.json"
    if stage == "extract":
        from policy.knowledge_v2.runner import PROMPT_VERSION, RULE_VERSION, SCHEMA_VERSION, run_knowledge_extraction_v2
        from policy.knowledge_v2.sampling import FIELDS
        from processing.batch import current_processing_versions

        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            documents = storage.relational.query("policy_documents", "title = %s", 10, ("武汉大学学生住宿管理办法",))
            if len(documents) != 1:
                raise ValueError("住宿制度不存在或存在多个版本，请先核实目标制度")
            document = documents[0]
            batches = storage.relational.query("pdf_batch_items", "file_id = %s AND status = %s", 100, (document["file_id"], "succeeded"))
            if not batches:
                raise ValueError("没有找到来源成功批次")
            batch_id = batches[0]["batch_id"]
            clauses = policies.get_policy_clauses(document["policy_id"])
            selected = [c for c in clauses if (c.get("level") == "article" and c.get("article_no") in {"九", "十", "十一"}) or (c.get("level") == "item" and c.get("article_no") == "六" and "分配与调整" in c.get("raw_text", ""))]
            if len(selected) != 4:
                raise ValueError("目标条款数量不符合预期，请先核实结构")
            sample = directory / "sample.csv"
            with sample.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                for clause in selected:
                    writer.writerow({"选用": "是", "批次ID": batch_id, "条款ID": clause["clause_id"], "制度名称": document["title"], "原文": clause["raw_text"], "原文指纹": hashlib.sha256(clause["raw_text"].encode()).hexdigest()})
            run_id = policies.create_policy_knowledge_run_v2(batch_id, current_processing_versions(), PROMPT_VERSION, RULE_VERSION, SCHEMA_VERSION, sample_path=str(sample))
            state = {"run_id": run_id, "policy_id": document["policy_id"], "index_name": "policy_assertion_pilot_" + run_id.rsplit("_", 1)[-1]}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        result = run_knowledge_extraction_v2(state["run_id"], resume=True)
        from policy.knowledge_v2.review import export_assertion_review_v2

        export_assertion_review_v2(state["run_id"], directory / "assertions.csv")
        assertions = policies.get_policy_assertion_review_rows_v2(state["run_id"])
        (directory / "assertions.json").write_text(json.dumps(assertions, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"run_id": state["run_id"], "status": result.get("status"), "assertions": len(assertions), "usable": sum(a.get("status") in {"machine_extracted", "approved", "corrected"} for a in assertions)}, ensure_ascii=False))
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if stage == "repair":
        from policy.knowledge_v2.runner import retry_clause_assertions_with_feedback
        from policy.knowledge_v2.review import export_assertion_review_v2

        original = directory / "assertions.json"
        archive = directory / "assertions.initial.json"
        if original.exists() and not archive.exists():
            archive.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
        clauses = policies.get_policy_clauses(state["policy_id"])
        clause = next(c for c in clauses if c.get("level") == "article" and c.get("article_no") == "十")
        assertions = policies.get_policy_assertions_v2(state["run_id"])
        failed = [a for a in assertions if a.get("clause_id") == clause["clause_id"] and a.get("status") == "invalid"]
        document = policies.get_policy_document(policy_id=state["policy_id"])
        valid, invalid = retry_clause_assertions_with_feedback((clause, clauses, document), ([], failed))
        print(json.dumps({"valid": valid, "invalid": invalid}, ensure_ascii=False), flush=True)
        policies.replace_policy_assertions_v2(state["run_id"], clause["clause_id"], valid, invalid)
        updated = policies.get_policy_assertions_v2(state["run_id"])
        from policy.knowledge_v2.logic import build_explicit_matters

        policies.replace_policy_matters_v2(state["run_id"], state["policy_id"], build_explicit_matters(state["run_id"], state["policy_id"], clauses, updated))
        export_assertion_review_v2(state["run_id"], directory / "assertions.csv")
        original.write_text(json.dumps(policies.get_policy_assertion_review_rows_v2(state["run_id"]), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return
    if stage == "publish":
        from policy.knowledge_v2.logic import validate_assertion
        from policy.knowledge_v2.retrieval import assertion_index_text
        from policy.retrieval import _encode_policy_clause_texts

        run_info = policies.get_policy_knowledge_run_v2(state["run_id"])
        if not run_info or run_info.get("status") != "succeeded":
            raise ValueError("只发布已完成的小样本运行")
        assertions = policies.get_policy_assertions_v2(state["run_id"], usable_only=True)
        clauses = {c["clause_id"]: c for c in policies.get_policy_clauses(state["policy_id"])}
        if not assertions:
            raise ValueError("没有可发布断言")
        for assertion in assertions:
            validate_assertion(assertion, clauses)
        if not state["index_name"].startswith("policy_assertion_pilot_"):
            raise ValueError("仅允许写入独立试验索引")
        vectors = _encode_policy_clause_texts([assertion_index_text(a) for a in assertions])
        storage.vector.create_index(state["index_name"], len(vectors[0]))
        storage.vector.delete_vectors_by_metadata(state["index_name"], "run_id", state["run_id"])
        metadata = [{**{key: a.get(key) for key in ("assertion_id", "clause_id", "policy_id", "kind", "modality", "subject_text", "predicate_text", "object_text", "receiver_text")}, "run_id": state["run_id"]} for a in assertions]
        storage.vector.insert_vectors(state["index_name"], vectors, metadata)
        prepare_exact_search(state["index_name"], storage.relational)
        count = storage.vector.count_vectors(state["index_name"])
        print(json.dumps({"pilot_index": state["index_name"], "count": count}, ensure_ascii=False))
        return
    from policy.answering import answer_policy_question

    cases = [c for c in json.loads(DEFAULT_CASES.read_text(encoding="utf-8")) if c["id"] in {"q01", "q11"}]
    # 首轮近似索引未命中的记录留作诊断，修正后使用新的报告目录。
    comparison_dir = directory / "comparison-exact"
    rows = run_comparison(cases, comparison_dir, "2026-10-26", answer_fn=partial(answer_policy_question, knowledge_index_name=state["index_name"]))
    print(write_report(rows, comparison_dir).resolve())
    for row in rows:
        result = row["results"]["v2"].get("result", {})
        print(row["case"]["id"], result.get("retrieval_mode"), result.get("knowledge_status"), result.get("knowledge_error_type"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("extract", "repair", "publish", "compare"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/dormitory-pilot"))
    args = parser.parse_args()
    run(args.stage, args.output)
