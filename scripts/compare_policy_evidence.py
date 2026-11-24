"""先验证补齐事项原文是否改善问答，不建设结构化办事卡。"""
import argparse
import copy
import json
import random
import time
from datetime import date
from pathlib import Path

from scripts.compare_policy_answers import DEFAULT_CASES, _save, write_report


def append_evidence(baseline, complete):
    """保留基础证据，已在关联原文中的条款也视为覆盖。"""
    result = copy.deepcopy(baseline)
    seen = {e.get("clause_id") for e in result}
    seen.update(c.get("clause_id") for e in result for c in e.get("related_clauses", []))
    for evidence in complete:
        if evidence["clause_id"] in seen:
            continue
        result.append({**copy.deepcopy(evidence), "evidence_id": f"E{len(result) + 1}"})
        seen.add(evidence["clause_id"])
    return result


def target_clauses(case_id, clauses):
    """只使用已人工核实的条款范围，不用模型生成答案作为依据。"""
    if case_id == "q08":
        return [c for c in clauses if c.get("level") == "article" and c.get("article_no") in {"九", "十四", "十五", "十七"}]
    selected = {c["clause_id"] for c in clauses if str(c.get("raw_text", "")).startswith(("三、", "六、"))}
    if len(selected) != 2:
        raise ValueError("福利费第三、六部分定位失败，停止试验")
    for _ in range(len(clauses)):
        children = {c["clause_id"] for c in clauses if c.get("parent_clause_id") in selected}
        if children.issubset(selected):
            break
        selected.update(children)
    return [c for c in clauses if c["clause_id"] in selected]


def prepare(case, as_of):
    from policy.answering import select_answer_evidence
    from policy.retrieval import search_indexed_policy_clauses, build_clause_metadata
    from policy.storage import get_policy_clauses
    from policy.temporal import classify_temporal_status
    from storage.adapters import storage

    title = case["references"][0]["title"]
    documents = storage.relational.query("policy_documents", "title = %s", 10, (title,))
    if len(documents) != 1:
        raise ValueError("目标制度缺失或版本不唯一")
    document = documents[0]
    status = classify_temporal_status(document, as_of)
    if status == "inapplicable":
        raise ValueError("目标制度在查询日期不适用")
    clauses = get_policy_clauses(document["policy_id"])
    targets = target_clauses(case["id"], clauses)
    if not targets or (case["id"] == "q08" and len(targets) != 4):
        raise ValueError("补全条款定位不完整")
    baseline = select_answer_evidence(search_indexed_policy_clauses(case["question"], top_k=20, as_of=as_of))
    if not baseline:
        raise ValueError("基础检索没有证据，不能将服务异常当作效果差异")
    complete = select_answer_evidence([
        {"id": c["clause_id"], "metadata": build_clause_metadata(c, document), "policy_document": document,
         "temporal_status": status, "score": 1.0} for c in targets
    ], max_evidence=len(targets), max_per_document=len(targets), max_documents=1)
    return {"baseline": baseline, "completed": append_evidence(baseline, complete),
            "required_ids": [c["clause_id"] for c in targets]}


def main():
    from policy.answering import call_answer_llm, validate_model_answer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/evidence-completion"))
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    date.fromisoformat(args.as_of)
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [c for c in json.loads(DEFAULT_CASES.read_text(encoding="utf-8")) if c["id"] in {"q04", "q08"}]
    path = args.output / "results.private.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"experiment": "evidence_completion", "as_of": args.as_of, "rows": []}
    if state.get("experiment") != "evidence_completion" or state["as_of"] != args.as_of:
        raise ValueError("输出目录已有其他试验，请换目录")
    for case in cases:
        row = next((r for r in state["rows"] if r["case"]["id"] == case["id"]), None)
        if row is None:
            print(f"准备 {case['id']} 的基础检索与原文补全", flush=True)
            evidence = prepare(case, args.as_of)
            row = {"case": case, "left_is_completed": bool(random.SystemRandom().randrange(2)), "evidence": evidence, "results": {}}
            state["rows"].append(row)
            _save(path, state)
        evidence = row["evidence"]
        added = len(evidence["completed"]) - len(evidence["baseline"])
        print(f"{case['id']}：基础证据 {len(evidence['baseline'])} 条，补入 {added} 条", flush=True)
        for mode in ("baseline", "completed"):
            if mode in row["results"]:
                continue
            started = time.perf_counter()
            try:
                if mode == "completed" and added == 0:
                    entry = copy.deepcopy(row["results"]["baseline"])
                    if "result" in entry:
                        entry["result"]["retrieval_mode"] = "clause_plus_evidence"
                    entry["reused_identical_input"] = True
                else:
                    print(f"生成 {case['id']} 回答", flush=True)
                    result = validate_model_answer(call_answer_llm(case["question"], args.as_of, evidence[mode]), evidence[mode])
                    entry = {"result": {**result, "question": case["question"], "as_of": args.as_of,
                                        "retrieval_mode": "clause_plus_evidence" if mode == "completed" else "clause_only"}}
                entry["seconds"] = round(time.perf_counter() - started, 3)
            except Exception as exc:
                entry = {"error": str(exc), "error_type": type(exc).__name__}
            row["results"][mode] = entry
            _save(path, state)
    print(write_report(state["rows"], args.output, experiment="evidence_completion").resolve())


if __name__ == "__main__":
    main()
