"""运行制度问答开关对比，生成可离线评价的盲评报告。"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import time
from datetime import date
from pathlib import Path


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "examples" / "policy_evaluation_questions.json"


def _save(path, value):
    """逐次保存，避免中断后重复消耗模型调用。"""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_comparison(cases, output_dir, as_of, *, answer_fn=None):
    """固定问题与日期，分别执行两种模式；相同目录支持断点续跑。"""
    if answer_fn is None:
        from policy.answering import answer_policy_question

        answer_fn = answer_policy_question
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps([cases, as_of], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path = output_dir / "results.private.json"
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["signature"] != signature:
            raise ValueError("该目录已有其他问题或日期的结果，请使用新的输出目录。")
    else:
        state = {"signature": signature, "as_of": as_of, "rows": []}
    by_id = {row["case"]["id"]: row for row in state["rows"]}
    for case in cases:
        row = by_id.get(case["id"])
        if row is None:
            row = {"case": case, "left_is_v2": bool(random.SystemRandom().randrange(2)), "results": {}}
            state["rows"].append(row)
        # 调用顺序也随机，避免始终由某种方案承担首次加载成本。
        for enabled in (row["left_is_v2"], not row["left_is_v2"]):
            key = "v2" if enabled else "baseline"
            if key in row["results"]:
                continue
            print(f"正在处理 {case['id']}：{case['question']}（本题第 {len(row['results']) + 1}/2 次）", flush=True)
            started = time.perf_counter()
            try:
                result = answer_fn(case["question"], requested_as_of=as_of, use_knowledge_v2=enabled)
                entry = {"result": result}
            except Exception as exc:
                entry = {"error": str(exc), "error_type": type(exc).__name__}
            entry["seconds"] = round(time.perf_counter() - started, 3)
            row["results"][key] = entry
            _save(path, state)
    return state["rows"]


def _escape(value):
    return html.escape(str(value or ""), quote=True)


def _visible(entry):
    """仅保留评审内容，不让方案名、匹配断言和排序分数泄漏分组。"""
    if "error" in entry:
        return {"执行失败": entry.get("error_type", "Error")}
    result = entry["result"]
    return {
        "结论": result.get("conclusion"), "回答": result.get("answer"),
        "条件": result.get("conditions", []), "警告": result.get("warnings", []),
        "降级": result.get("degraded", False),
        "引用": [{key: citation.get(key) for key in (
            "policy_id", "clause_id", "title", "clause_no", "page_start", "page_end",
            "raw_text", "related_clauses", "temporal_status",
        )} for citation in result.get("citations", [])],
    }


def _panel(entry):
    visible = _visible(entry)
    if "执行失败" in visible:
        return "<p>执行失败，本侧不能作为问答质量结果。</p>"
    result = entry["result"]
    parts = [f"<p>{_escape(visible['回答'])}</p>", f"<p>结论：{_escape(visible['结论'])}</p>"]
    for label in ("条件", "警告"):
        if visible[label]:
            parts.append(f"<p>{label}：{_escape('；'.join(visible[label]))}</p>")
    if result.get("degraded"):
        parts.append("<p>本次回答发生降级，请选择无法判断并核查运行记录。</p>")
    for citation in visible["引用"]:
        parts.append(f"<details open><summary>{_escape(citation['title'])} · {_escape(citation['clause_no'])} · 第 {_escape(citation['page_start'])} 页</summary><p>{_escape(citation['raw_text'])}</p>")
        for related in citation.get("related_clauses") or []:
            parts.append(f"<p>关联原文：{_escape(related.get('raw_text'))}</p>")
        parts.append("</details>")
    if not visible["引用"]:
        parts.append("<p>没有引用原文。</p>")
    return "".join(parts)


def write_report(rows, output_dir, *, experiment="v2"):
    """生成静态双栏报告，浏览器本地保存评价并支持导出。"""
    output_dir = Path(output_dir)
    sections = []
    enhanced_key = "completed" if experiment == "evidence_completion" else "v2"
    left_flag = "left_is_completed" if experiment == "evidence_completion" else "left_is_v2"
    enhanced_mode = "clause_plus_evidence" if experiment == "evidence_completion" else "clause_plus_knowledge"
    for row in rows:
        case = row["case"]
        left_key, right_key = (enhanced_key, "baseline") if row[left_flag] else ("baseline", enhanced_key)
        left, right = (row["results"][key] for key in (left_key, right_key))
        same = _visible(left) == _visible(right)
        enhanced = row["results"][enhanced_key].get("result", {})
        valid = all("error" not in value and not value.get("result", {}).get("degraded") for value in (left, right)) and enhanced.get("retrieval_mode") == enhanced_mode
        label = "展示内容相同" if same else "展示内容有差异（不代表质量有差异）"
        references = "；".join(f"{item['title']}：{'、'.join(item.get('locators', []))}" for item in case.get("references", [])) or "待核实，暂不计算正确率"
        options = "".join(f'<option value="{value}">{text}</option>' for value, text in (
            ("", "尚未评价"), ("left", "左边更好"), ("right", "右边更好"), ("tie", "差不多"), ("unknown", "无法判断")))
        sections.append(f'''<section><h2>{_escape(case['id'])} · {_escape(case['question'])}</h2>
<p>分组：{_escape(case.get('group', case['id']))}　参考定位：{_escape(references)}</p>
<p>{label}。{'本题未形成有效增强对比，请先核查运行记录。' if not valid else ''}</p>
<label>评价：<select data-id="{_escape(case['id'])}">{options}</select></label>
<details {'open' if not same else ''}><summary>查看两侧回答及原文</summary><div class="columns"><article><h3>左边</h3>{_panel(left)}</article><article><h3>右边</h3>{_panel(right)}</article></div></details></section>''')
    namespace = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>制度问答对比</title>
<style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:24px auto;padding:0 20px;color:#202b35;background:#f5f7fa}section{background:white;padding:20px;margin:20px 0;border:1px solid #d9e0e7;border-radius:8px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{min-width:0}p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65}summary{cursor:pointer}select,button{padding:8px}h2{font-size:20px}@media(max-width:800px){.columns{grid-template-columns:1fr}}</style>
<h1>制度问答盲评</h1><p>每题左右顺序随机。先看有差异的题，只需选择哪边更好；同义题属于同一组。引用定位来自你提供的信息，尚未经自动核实。文本差异也可能来自模型生成波动，不能直接归因为检索收益。</p>
<p>两侧使用相同配置和日期，分别检索、生成；首次加载可能影响耗时。判定质量应回看引用原文，不能仅凭回答措辞。</p>
<button id="export">导出评价</button><span id="status"></span>''' + "".join(sections) + '''
<script>
const storageKey = 'policy-review-NAMESPACE';
let ratings = {};
try { ratings = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) {}
document.querySelectorAll('select[data-id]').forEach(select => {
  select.value = ratings[select.dataset.id] || '';
  select.addEventListener('change', () => {
    ratings[select.dataset.id] = select.value;
    try { localStorage.setItem(storageKey, JSON.stringify(ratings)); }
    catch (_) { document.getElementById('status').textContent = '本地保存不可用，请及时导出评价。'; }
  });
});
document.getElementById('export').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({report: storageKey, ratings}, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = '评价.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
</script></html>'''.replace("NAMESPACE", namespace)
    if experiment == "evidence_completion":
        document = document.replace("<h1>制度问答盲评</h1>", "<h1>制度问答盲评</h1><p>本次试验比较当前条款检索与人工核实的原文补全；不使用 V2 或办事卡。补全组保留原证据，仅加入缺失条款。它衡量补齐证据的潜在收益，不证明自动归集能力。没有新增证据时两侧复用同一回答。</p>")
        document = document.replace("两侧使用相同配置和日期，分别检索、生成", "两侧使用相同配置和日期，共用一次基础检索；原文补全后再生成")
    path = output_dir / "report.html"
    path.write_text(document, encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=None, help="先运行前几题，减少模型调用")
    parser.add_argument("--prepare-only", action="store_true", help="仅检查样本，不连接数据库或模型")
    args = parser.parse_args()
    date.fromisoformat(args.as_of)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        parser.error("样本必须是非空数组")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
        parser.error("每题必须有不重复的字符串 id")
    if any(not isinstance(case.get("question"), str) or not case["question"].strip() for case in cases):
        parser.error("每题必须有非空 question")
    if args.limit is not None:
        if args.limit < 1:
            parser.error("limit 必须大于零")
        cases = cases[:args.limit]
    if args.prepare_only:
        print(f"样本检查通过：{len(cases)} 题，{len({case.get('group', case['id']) for case in cases})} 组；日期 {args.as_of}。未调用模型。")
        return
    rows = run_comparison(cases, args.output, args.as_of)
    report = write_report(rows, args.output)
    effective = sum(row["results"]["v2"].get("result", {}).get("retrieval_mode") == "clause_plus_knowledge" for row in rows)
    print(f"报告：{report.resolve()}\nV2 返回增强模式：{effective}/{len(rows)}；这不代表效果提升。")
    print("先评阅 report.html；results.private.json 含方案映射和错误详情，请在评价后查看。")


if __name__ == "__main__":
    main()
