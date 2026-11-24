"""从当前制度原文和既有审核记录投影文件关系，不改变制度效力。"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict


_QUOTED = re.compile(r"《(?P<title>[^《》\n]{2,120})》")
_ADJACENT_NUMBER = re.compile(r"^\s*(?P<number>(?:[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z \t]{0,35})?[〔\[［【（(]\s*(?:19|20)\d{2}\s*[〕\]］】）)]\s*第?\s*\d{1,8}\s*号)")
_CITE = re.compile(r"依据|根据|按照|遵照|参照|依照|执行|遵守|适用|落实")
_BOUNDARY = re.compile(r"[。！？!?\n]")
WARNINGS = [
    "图谱表示有原文依据的文件关联；多跳路径不代表废止、效力或适用范围可以传递。",
    "机器识别的引用和待审核废止不替代人工确认；普通提及不等于正式依据。",
    "未解析节点可能是未入库文件或版本不明确，不能据此认定文件不存在。",
]


def _title(value):
    return re.sub(r"\s+", "", str(value or ""))


def _number(value):
    from metadata.document_number import normalize_document_number

    normalized = normalize_document_number(str(value or ""))
    return normalize_document_number(re.sub(r"(\])第(?=\d)", r"\1", normalized))


def _id(prefix, *values):
    return prefix + hashlib.sha256("\x1f".join(str(v) for v in values).encode()).hexdigest()[:24]


def _sentence(text, start, end):
    boundaries = list(_BOUNDARY.finditer(text, 0, start))
    left = boundaries[-1].end() if boundaries else 0
    following = _BOUNDARY.search(text, end)
    right = following.end() if following else len(text)
    return text[left:right].strip(), text[left:start]


def _parenthetical_end(text, start):
    position = start
    while position < len(text) and text[position].isspace():
        position += 1
    if position >= len(text) or text[position] not in "（(":
        return None
    depth = 0
    for index in range(position, min(len(text), position + 160)):
        if text[index] in "（(":
            depth += 1
        elif text[index] in "）)":
            depth -= 1
            if depth == 0:
                return position, index + 1
    return None


def _adjacent_number(text, quoted):
    block = _parenthetical_end(text, quoted.end())
    if block:
        content = text[block[0] + 1:block[1] - 1].strip()
        # 疑似文号即使格式陌生也保留，绝不因解析失败而退回同名版本。
        if "号" in content:
            return content[:content.index("号") + 1]
        return ""
    match = _ADJACENT_NUMBER.match(text[quoted.end():quoted.end() + 120])
    return match.group("number") if match else ""


def _quoted_reference_end(text, quoted):
    block = _parenthetical_end(text, quoted.end())
    if block:
        if re.search(r"第[^。]{0,20}[条款项]", text[block[0]:block[1]]):
            return quoted.end()
        return block[1]
    number = _adjacent_number(text, quoted)
    if number:
        return text.find(number, quoted.end()) + len(number)
    return quoted.end()


def _abolition_occurrences(text, quotes):
    """定位直接连接废止触发词的书名组，避免屏蔽同句其他引用。"""
    result = set()
    for index, quoted in enumerate(quotes):
        end = _quoted_reference_end(text, quoted)
        for following in quotes[index + 1:]:
            gap = text[end:following.start()]
            if not re.fullmatch(r"\s*(?:(?:、|和|及|以及|与)\s*)?(?:原\s*)?", gap):
                break
            end = _quoted_reference_end(text, following)
        if re.match(r"^[\s，,、；;:：]*(?:(?:即|同时|予以|一并)\s*)*(?:废止|作废)", text[end:]):
            result.add(quoted.start())
        prefix = re.split(r"[。！？!?\n]", text[:quoted.start()])[-1]
        if re.search(r"(?:废止|作废)\s*$", prefix):
            result.add(quoted.start())
    return result


def _reference_kind(prefix, title):
    """触发词须直接支配书名或并列书名，不能跨越填写等其他动作。"""
    local = re.split(r"[，,；;：:\n]", prefix)[-1]
    local = _QUOTED.sub("", local)
    local = re.sub(r"[（(][^）)]*[）)]", "", local)
    triggers = list(_CITE.finditer(local))
    if not triggers:
        return "mentions"
    trigger = triggers[-1]
    if re.search(r"(?:不得|不应|不再|无需|禁止|不)\s*$", local[:trigger.start()]):
        return "mentions"
    tail = local[trigger.end():]
    if not re.fullmatch(r"(?:\s|、|和|及|与|以及|等|的|有关|相关|规定|要求)*", tail):
        return "mentions"
    return "mentions" if re.search(r"(?:申请表|备案表|回告单|处理单|协议|申请书)$", title) else "cites"


def build_document_graph(documents, clauses, abolition_relations):
    """准确保留版本歧义、未入库目标及废止审核状态的纯投影。"""
    from .abolition import (
        abolition_target_doc_number, document_publication_year, extract_abolition_candidates, target_publication_year,
    )

    by_id = {str(d["policy_id"]): d for d in documents}
    by_title = defaultdict(list)
    nodes, edges = {}, {}
    for pid, document in by_id.items():
        by_title[_title(document.get("title"))].append(document)
        nodes[pid] = {"id": pid, "policy_id": pid, "title": document.get("title") or document.get("file_name") or pid,
                      "doc_number": document.get("doc_number") or "", "resolution": "resolved",
                      "validity_status": document.get("validity_status") or "unknown",
                      **{k: str(document.get(k) or "") for k in ("effective_date", "expiry_date", "issue_date", "file_id", "file_name")}}
    active = {str(c["clause_id"]): c for c in clauses if str(c.get("policy_id")) in by_id
              and c.get("is_active", True) and c.get("structure_version", "") == by_id[str(c["policy_id"])].get("structure_version", "")}
    reviewed = {}
    for relation in abolition_relations:
        key = (
            str(relation.get("source_policy_id")), str(relation.get("evidence_clause_id")),
            _title(relation.get("target_title")), _number(abolition_target_doc_number(relation.get("target_doc_number"))),
        )
        if key not in reviewed or reviewed[key].get("review_status") == "pending":
            reviewed[key] = relation
    reviewed_by_clause = defaultdict(list)
    for key, relation in reviewed.items():
        reviewed_by_clause[key[:2]].append((key, relation))

    def resolve(title, number, source, explicit_id=None, year=None):
        if explicit_id in nodes and explicit_id != source:
            return explicit_id
        matches = [d for d in by_title[_title(title)] if str(d["policy_id"]) != source]
        if number:
            matches = [d for d in matches if _number(d.get("doc_number")) == _number(number)]
        if year is not None:
            matches = [d for d in matches if document_publication_year(d) == year]
        if len(matches) == 1:
            return str(matches[0]["policy_id"])
        external_id = _id("external_", _title(title), _number(number), year or "")
        nodes[external_id] = {"id": external_id, "policy_id": None, "title": title, "doc_number": number,
                              "resolution": "ambiguous" if len(matches) > 1 else "not_in_corpus",
                              "candidate_policy_ids": sorted(str(d["policy_id"]) for d in matches), "issue_year_hint": year, "validity_status": "unknown"}
        return external_id

    def add(source, title, number, kind, clause, evidence, status, relation=None):
        if not evidence or evidence not in str(clause.get("raw_text") or ""):
            return
        target = resolve(title, number, source, str((relation or {}).get("target_policy_id") or ""), target_publication_year(evidence, title))
        eid = _id("document_edge_", source, target, kind, status)
        citation = {"policy_id": source, "clause_id": clause["clause_id"], "evidence_text": evidence,
                    "raw_text": clause["raw_text"], "structure_version": clause.get("structure_version", ""),
                    "page_start": int(clause.get("page_start") or 0), "page_end": int(clause.get("page_end") or clause.get("page_start") or 0)}
        if relation:
            citation.update(relation_id=relation.get("relation_id"), effective_date=str(relation.get("effective_date") or ""))
        edge = edges.setdefault(eid, {"id": eid, "source": source, "target": target, "type": kind, "review_status": status, "citations": []})
        if citation not in edge["citations"]:
            edge["citations"].append(citation)

    for cid, clause in active.items():
        source = str(clause["policy_id"])
        text = str(clause.get("raw_text") or "")
        abolished_occurrences = set()
        quoted_matches = list(_QUOTED.finditer(text))
        direct_abolition_positions = _abolition_occurrences(text, quoted_matches)

        def mark_abolition(evidence, title, number):
            if not evidence:
                return
            offset = text.find(evidence)
            while offset >= 0:
                abolished_occurrences.update(q.start() for q in quoted_matches if q.start() in direct_abolition_positions
                                            and _title(q.group("title")) == _title(title)
                                            and _number(_adjacent_number(text, q)) == _number(number)
                                            and offset <= q.start() and q.end() <= offset + len(evidence))
                offset = text.find(evidence, offset + 1)

        normalized_text = re.sub(r"[（(](\s*(?:19|20)\d{2}\s*)[）)]", lambda m: "〔" + m[1] + "〕", text)
        for candidate in extract_abolition_candidates({**clause, "raw_text": normalized_text}):
            normalized_evidence = candidate["evidence_text"]
            offset = normalized_text.find(normalized_evidence)
            if offset < 0:
                continue
            candidate["evidence_text"] = text[offset:offset + len(normalized_evidence)]
            old_key = (source, cid, _title(candidate["target_title"]), _number(candidate["target_doc_number"]))
            # 复用既有废止语句定位，但完整读取含圆括号年份的文号。
            evidence_quotes = list(_QUOTED.finditer(candidate["evidence_text"]))
            numbers = {_adjacent_number(candidate["evidence_text"], q) for q in evidence_quotes if _title(q.group("title")) == _title(candidate["target_title"])} - {""}
            if len(numbers) == 1:
                candidate["target_doc_number"] = next(iter(numbers))
            key = (source, cid, _title(candidate["target_title"]), _number(candidate["target_doc_number"]))
            relation = reviewed.get(key) or reviewed.get(old_key)
            if relation and relation.get("review_status") == "rejected":
                continue
            mark_abolition(candidate["evidence_text"], candidate["target_title"], candidate["target_doc_number"])
            add(source, candidate["target_title"], candidate["target_doc_number"], "abolishes", clause,
                (relation or {}).get("evidence_text") or candidate["evidence_text"],
                "approved" if relation and relation.get("review_status") == "approved" else "pending", relation)
        # 已审核关系可包含人工修正的目标；仍必须属于当前条款且具有连续原文依据。
        for _, relation in reviewed_by_clause[(source, cid)]:
            if relation.get("review_status") == "approved":
                number = abolition_target_doc_number(relation.get("target_doc_number"))
                add(source, relation.get("target_title") or "", number, "abolishes", clause,
                    relation.get("evidence_text") or "", "approved", relation)
                mark_abolition(relation.get("evidence_text") or "", relation.get("target_title") or "", number)
        for quoted in quoted_matches:
            title = _title(quoted.group("title"))
            number = _adjacent_number(text, quoted)
            if quoted.start() in abolished_occurrences:
                continue
            if title == _title(by_id[source].get("title")) and (not number or _number(number) == _number(by_id[source].get("doc_number"))):
                continue
            # 表单、协议等引用仍可作为普通提及，不冒充正式制度依据。
            evidence, prefix = _sentence(text, quoted.start(), quoted.end())
            kind = _reference_kind(prefix, title)
            add(source, title, number, kind, clause, evidence, "machine_extracted")
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": sorted(edges.values(), key=lambda e: e["id"]),
            "stats": {"documents": len(by_id), "unresolved_targets": len(nodes) - len(by_id), "edges": len(edges),
                      "relations": dict(Counter(e["type"] for e in edges.values())),
                      "review_status": dict(Counter(e["review_status"] for e in edges.values()))}, "warnings": WARNINGS}


def graph_neighborhood(graph, policy_id, depth=1, direction="both", limit=100):
    """有界遍历原始边，不生成传递关系，也不推导失效。"""
    if depth not in (1, 2, 3) or direction not in {"both", "incoming", "outgoing"} or not 1 <= limit <= 200:
        raise ValueError("depth 须为 1 到 3，direction 须为 both/incoming/outgoing，limit 须为 1 到 200")
    nodes = {n["id"]: n for n in graph["nodes"]}
    if policy_id not in nodes:
        raise KeyError(policy_id)
    frontier, visited, picked, truncated = {policy_id}, {policy_id}, {}, False
    for _ in range(depth):
        next_frontier = set()
        for edge in graph["edges"]:
            source, target = edge["source"], edge["target"]
            adjacent = (direction != "incoming" and source in frontier) or (direction != "outgoing" and target in frontier)
            if not adjacent or edge["id"] in picked:
                continue
            if len(picked) >= limit:
                truncated = True
                continue
            picked[edge["id"]] = edge
            next_frontier.update({source, target} - visited)
            visited.update((source, target))
        frontier = next_frontier
        if not frontier:
            break
    return {"policy_id": policy_id, "depth": depth, "direction": direction, "nodes": [nodes[n] for n in sorted(visited)],
            "edges": list(picked.values()), "truncated": truncated, "warnings": graph.get("warnings", WARNINGS)}


def load_document_graph():
    """只读加载当前数据，明确拒绝超量截断，不创建或修改事实表。"""
    from storage.adapters import storage

    documents = storage.relational.query("policy_documents", limit=100001)
    clauses = storage.relational.query("policy_clauses", '"is_active" = TRUE', limit=200001)
    relations = storage.relational.query("policy_document_relations", limit=100001)
    if len(documents) > 100000 or len(clauses) > 200000 or len(relations) > 100000:
        raise RuntimeError("当前图谱数据超过单次加载上限，请按范围分批处理")
    return build_document_graph(documents, clauses, relations)


def query_document_graph(policy_id, depth=1, direction="both", limit=100):
    return graph_neighborhood(load_document_graph(), policy_id, depth, direction, limit)
