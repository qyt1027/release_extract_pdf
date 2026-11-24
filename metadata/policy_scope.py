"""从制度自身的范围表述和标题中保守识别适用单位。"""
from __future__ import annotations

import re
from core.policy_signatures import SIGNATURE_DATE_PATTERN, SIGNATURE_PREFIX_GUARD
from core.policy_titles import compact_title_text, policy_title_subject
from core.unit_aliases import (
    normalize_applicable_unit, normalize_unit_query, registered_applicable_units, registered_unit_spans,
)


_POLICY_KIND = r"(?:办法|规定|制度|细则|条例|规则|章程|规程|意见|方案|通知|标准|措施)"
_SCOPE_RE = re.compile(
    rf"(?:本(?:管理|实施|工作|操作|试行|暂行|补充){{0,2}}{_POLICY_KIND}"
    r"(?:的?适用范围(?:为|是|[：:])|(?:仅|只)?适用(?:于|(?!于|范围|单位|对象|条件|情形|性|的)))|"
    r"适用(?:范围|单位)[：:])\s*([^。；;\n]{1,150})"
)
_TITLE_RE = re.compile(rf"[^《》。；：:]{{4,100}}{_POLICY_KIND}(?:[（(][^）)]{{1,20}}[）)])?$")
_BODY_START_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百千万零〇\d]+[编章节条]|[一二三四五六七八九十]+、|"
    r"[（(][一二三四五六七八九十\d]+[）)]|\d+[.．、])"
)
_ACCESS_SCOPE_RE = re.compile(r"[\u4e00-\u9fff]{0,40}开放对象(?:为|是|[：:])([^。；;]+)")
_UNIT_SEPARATOR_RE = re.compile(r"(?:[、，,]|以及|和|及|与)(?:武汉大学)?")
_SCHOOL_RECIPIENT_RE = re.compile(
    r"(?:主送[：:])?(?:全校|本校|我校|武汉大学|校内)"
    r"各(?:部门|单位|学院|院系)(?:[、，,及和]各?(?:部门|单位|学院|院系))*[：:]"
)
_SCHOOL_SCOPE_RE = re.compile(r"^(?:全校|(?:本校|我校|武汉大学)(?:各单位|各学院|各部门|全体|所有))")
_SCHOOL_TITLE_RE = re.compile(r"^(?:关于(?:印发|发布)[《〈])?武汉大学(?!生|与|和|及|、)")
_RESTRICTED_SCOPE_RE = re.compile(r"除外|不含|不包括|部分|若干|个别")
_ORGANIZATIONAL_SCOPE_RE = re.compile(
    r"学校|大学|全校|本校|我校|校内|学院|院系|本院|我院|该院|部门|单位|机构|实验室|中心|"
    r"人员|师生|教职工|教师|学生|职工|团队"
)
_GENERIC_COLLEGES = {"学院", "各学院", "本学院", "我学院", "该学院", "所有学院", "有关学院",
                     "相关学院", "其他学院", "部分学院", "二级学院", "所属学院", "全体学院"}
_TITLE_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}年(?:度)?")
_CONTEXTUAL_TITLE_UNITS = {"前沿交叉学科研究院": {"高等研究院": "武汉大学高等研究院"}}
_CYBERSECURITY_STUDENT_TITLE_RE = re.compile(r"^(?:武汉大学)?网络空间安全(?:专业|学科)?(?:来华)?(?:留学生|国际学生)")
_LOCAL_COLLEGE = r"(?:本学院|我学院|本院|我院)"
_LOCAL_PEOPLE = r"(?:的)?(?:全体|在编在岗|在编|在岗|离退休)?(?:教师|教职工|师生员工|师生|学生|人员)"
_LOCAL_GROUP = rf"(?:{_LOCAL_COLLEGE}|全院|(?<![学外])院内){_LOCAL_PEOPLE}"
_LOCAL_GROUP_RE = re.compile(_LOCAL_GROUP)
_LOCAL_SCOPE_RE = re.compile(
    rf"(?:{_LOCAL_COLLEGE}|{_LOCAL_GROUP}|学院{_LOCAL_PEOPLE}|"
    r"由(?:本学院|我学院|本院|我院|学院)[^、，,；;]*(?:开设|组织|管理)[^、，,；;]*)"
    r"(?:[，,]其他人员参照执行)?"
)
_FOLDER_SCOPE_REFERENCE_RE = re.compile(rf"(?:由?{_LOCAL_COLLEGE}|{_LOCAL_GROUP}|学院{_LOCAL_PEOPLE})")
_LOCAL_SUPPORT_RE = re.compile(
    rf"(?:本学院|本院|学院)(?:资助|鼓励|支持){_LOCAL_GROUP}(?:参加|进行|开展|申请|申报|赴|参会)"
)
_LOCAL_RETIREMENT_POLICY_RE = re.compile(
    r"^(?:本学院|我学院|本院|我院|学院)的?离退休(?:教职工|教师|职工|人员)"
    r"[^。！？；;]*[，,]经(?:本学院|我学院|本院|我院|学院)(?:研究)?决定[，,]?特?"
    r"(?:制定|制订|修订)本(?:措施|办法|规定)(?=[。；;，,]|$)"
)
_POLICY_ADOPTION_RE = re.compile(rf"(?:制定|制订|修订)本{_POLICY_KIND}")
_LOCAL_POLICY_ADOPTION_RE = re.compile(
    rf"(?:^|[，,。；;]|及|并)(?:结合|根据)?(?:{_LOCAL_COLLEGE}|学院)(?:的)?(?:实际|具体)(?:情况)?[，,]?"
    rf"(?:特|现)?(?:制定|制订|修订)(?:本{_POLICY_KIND}|如下[^。；;]*{_POLICY_KIND}|"
    rf"{_LOCAL_COLLEGE}[^。；;，,《》]{{1,60}}{_POLICY_KIND}(?=[。；;，,]|$))"
)
_LOCAL_GOVERNING_BODY = rf"(?:{_LOCAL_COLLEGE}|学院|院)党政(?:联席|办公)会(?:议)?"
_LOCAL_POLICY_INTERPRETATION_RE = re.compile(
    rf"(?:^|[，,。；;])本(?:暂行|管理|实施)?{_POLICY_KIND}由{_LOCAL_GOVERNING_BODY}(?:负责)?解释"
)
_LOCAL_GOVERNANCE_DECISION_RE = re.compile(rf"(?:由|经){_LOCAL_GOVERNING_BODY}(?:讨论)?(?:决定|批准|审定|确定)")
_QUOTED_TEXT_RE = re.compile(r"“([^”]*)”|「([^」]*)」")
_LOCAL_EXECUTION_RE = re.compile(
    r"(?:^|[。；;，,：:]|由|经|报)(?:本学院|我学院|本院|我院|学院)(?:统一|最终)?"
    r"(?:组织|审核|审批|审定|受理|聘任|考核|决定(?:建立|设立|实行)|划拨(?:专项)?经费)"
    r"(?!架构|结构|机构|体系|设置|流程|程序|制度|办法|方案|标准|结果|指标)|"
    r"(?:交|向|报送)(?:本学院|学院|本院|院)[\u4e00-\u9fff]{1,12}(?:办公室|工作室)"
)
_COLLEGE_SIGNATURE_RE = re.compile(
    rf"{SIGNATURE_PREFIX_GUARD}(?:中共)?(?:武汉大学)?(?P<college>[\u4e00-\u9fff（）()]{{2,60}}?)"
    rf"(?:委员会|党委)?(?:{SIGNATURE_DATE_PATTERN})?"
)


def _colleges_in_title(title: str) -> set[str]:
    """在标题任意位置提取学院名称，不要求固定后缀或制度句式。"""
    # 年份是标题的一部分，只在识别学院时把它当作名称边界。
    title = _TITLE_YEAR_RE.sub(" ", title)
    spans = registered_unit_spans(title)
    colleges = {canonical for _, _, canonical in spans}
    # 已识别全称整段移除，避免把联合学院、括号中的别名再次拆成另一个单位。
    for start, end, _ in reversed(spans):
        title = title[:start] + ' ' + title[end:]
    title = re.sub(r"学院(?:和|及|与|、|，|,)", "学院 ", title)
    for part in re.findall(r"[\u4e00-\u9fff]+?学院", title):
        # 去掉学校名称及常见引导语，不把它们算进学院名称。
        college = re.split(r"武汉大学|关于|印发|发布|开展|加强|规范|全校", part)[-1]
        if college.endswith("学院") and college not in _GENERIC_COLLEGES:
            colleges.add(normalize_applicable_unit(college))
    return colleges


def _unit_from_prefix(value: str) -> str:
    """只接受句首可定位的单一学院名称或明确的全校范围。"""
    value = normalize_unit_query("".join(value.split()))
    if re.search(r"学院(?:[、，,]|和|及|与).{0,30}学院", value):
        return ""
    if re.match(r"全校", value) and not re.search(r"除|不含|部分", value):
        return "全校"
    if re.match(r"(?:本校|我校)(?:各单位|各学院|全体|所有)", value):
        return "全校"
    value = re.sub(r"^关于", "", value)
    registered = registered_unit_spans(value)
    if registered and registered[0][0] == 0:
        return registered[0][2] if len(_colleges_in_title(value)) == 1 else ''
    value = re.sub(r"^(?:[\u4e00-\u9fff]{2,30}大学|本校|我校)", "", value)
    registered = registered_unit_spans(value)
    if registered and registered[0][0] == 0:
        return registered[0][2] if len(_colleges_in_title(value)) == 1 else ''
    match = re.match(r"([\u4e00-\u9fff]{1,30}?学院)", value)
    if not match:
        return ""
    unit = match.group(1)
    if re.match(r"(?:本学院|我学院|该学院|本院|我院|该院|各|所有|有关|相关|其他|部分|二级|所属|全校|全体|加强|规范|修订|印发|依据|参照)", unit):
        return ""
    return normalize_applicable_unit(unit)


def _signed_college(lines: list[str]) -> str:
    """识别文末独立学院署名，兼容无日期、同行日期及跨行排版。"""
    for count in range(1, min(4, len(lines)) + 1):
        match = _COLLEGE_SIGNATURE_RE.fullmatch("".join(lines[-count:]))
        if match:
            units = registered_applicable_units(match["college"])
            if units:
                return units[0]
    return ""


def _units_from_scope(scope: str) -> list[str]:
    """识别范围开头完整的并列院系，避免把后文提及的学院纳入范围。"""
    if re.search(r"除外|不含|不包括", scope):
        return []
    if _SCHOOL_SCOPE_RE.match(scope) and not _RESTRICTED_SCOPE_RE.search(scope):
        return ["全校"]
    spans = registered_unit_spans(scope)
    if not spans:
        return []
    prefix = scope[:spans[0][0]]
    tail = scope[spans[-1][1]:]
    if prefix in {"由", "由武汉大学"}:
        if not re.match(r"[^、，,]*(?:开设|组织|管理)", tail):
            return []
    elif prefix not in {"", "武汉大学"}:
        return []
    if not all(_UNIT_SEPARATOR_RE.fullmatch(scope[left[1]:right[0]]) for left, right in zip(spans, spans[1:])):
        return []
    names = [name for _, _, name in spans]
    if _colleges_in_title(scope) != set(names) or re.search(r"[、，,及和与].*学院", tail):
        return []
    return registered_applicable_units(names)


def infer_applicable_unit(
    title: str = "", text: str = "", *, source_unit: str = "", college_fallback: str = "",
) -> list[str]:
    """推断适用单位；仅在范围确定为本院而具体学院未知时使用候选学院。"""
    title = normalize_unit_query(policy_title_subject(title))
    program_students = bool(_CYBERSECURITY_STUDENT_TITLE_RE.match(title))
    candidates = [title]
    # 正文只取首个标题候选，不向后扫描职责描述等普通段落。
    if not _TITLE_RE.fullmatch(title):
        for line in text.splitlines()[:12]:
            line = normalize_unit_query(policy_title_subject(line))
            if not line:
                continue
            if _BODY_START_RE.match(line):
                break
            if re.search(rf"负责(?:解释|实施|执行)|本{_POLICY_KIND}|应当|必须|不得", line) or re.match(
                r"^(?:发布机构|发文机关|印发单位)[：:]", line,
            ):
                break
            candidates.append(line)
            break
    title_units = []
    for candidate in candidates:
        # 同名机构简称只在有对应采集归口且标题明确写出时使用。
        for short_name, official_name in _CONTEXTUAL_TITLE_UNITS.get(source_unit, {}).items():
            if candidate.startswith(short_name):
                candidate = official_name + candidate[len(short_name):]
                break
        colleges = _colleges_in_title(candidate)
        if colleges:
            college_fallback = ""
            if len(colleges) == 1:
                title_units = registered_applicable_units(list(colleges))
            else:
                units = _units_from_scope(candidate)
                if set(units) == colleges:
                    title_units = units
            break
        if (candidate.startswith("全校") and not _RESTRICTED_SCOPE_RE.search(candidate)) or (
            not program_students and _SCHOOL_TITLE_RE.match(candidate) and "学院" not in candidate
        ):
            title_units = ["全校"]
            break

    def normalize_quotation(match: re.Match) -> str:
        quoted = match.group(1) or match.group(2) or ""
        # 引用中的完整范围句不用于本制度；单位名称上的引号只去掉符号。
        return "" if _SCOPE_RE.search("".join(quoted.split())) else quoted

    uncited_text = re.sub(r"《[^》]*》", "", text)
    scope_text = _QUOTED_TEXT_RE.sub(normalize_quotation, uncited_text)
    # 保留字段和条款行边界，范围触发词后的排版换行由正则单独兼容。
    scope_text = "\n".join(compact_title_text(line) for line in scope_text.splitlines())
    scopes = _SCOPE_RE.findall(scope_text)
    lines = [compact_title_text(line) for line in text.splitlines() if line.strip()]
    signed_college = _signed_college(lines)
    for line in lines:
        access = _ACCESS_SCOPE_RE.match(_BODY_START_RE.sub("", line, count=1))
        if access:
            scopes.append(access[1])
    if scopes:
        if all(_LOCAL_SCOPE_RE.fullmatch(scope) for scope in scopes):
            units = title_units or registered_applicable_units(signed_college)
            if not units and college_fallback and all(_FOLDER_SCOPE_REFERENCE_RE.match(scope) for scope in scopes):
                return [college_fallback]
            return units
        scopes_by_unit = [_units_from_scope(scope) for scope in scopes]
        if any(scopes_by_unit):
            first = scopes_by_unit[0]
            return first if all(set(units) == set(first) for units in scopes_by_unit) else []
        if any(_RESTRICTED_SCOPE_RE.search(scope) or _colleges_in_title(scope) for scope in scopes):
            return []
        if not title_units and any(_ORGANIZATIONAL_SCOPE_RE.search(scope) for scope in scopes):
            return []
    if title_units:
        return title_units

    # 正文可能仅限定业务类型。主送对象须在公文开头独立成行。
    for line in lines[:12]:
        if _BODY_START_RE.match(line) or re.search(r"[。！？；]$", line) or line.startswith("抄送"):
            break
        if _SCHOOL_RECIPIENT_RE.fullmatch(line):
            return ["全校"]
    # 明确的学院落款默认确定本院范围，不再依赖固定的本院适用或制定句式。
    # 正文范围、标题和全校主送对象已在前面处理，落款不会覆盖它们。
    if signed_college:
        return [signed_college]
    # 没有具名落款时，正文院级职责或制定说明只用于确认目录学院的候选范围。
    local_college = college_fallback
    if local_college:
        unquoted_lines = [
            _BODY_START_RE.sub("", compact_title_text(line), count=1)
            for line in _QUOTED_TEXT_RE.sub("", uncited_text).splitlines()
        ]
        execution_clauses = sum(_LOCAL_EXECUTION_RE.search(line) is not None for line in unquoted_lines)
        supports_local_staff = any(
            _LOCAL_SUPPORT_RE.match(_BODY_START_RE.sub("", line, count=1)) for line in lines
        )
        adopts_local_retirement_policy = any(
            _LOCAL_RETIREMENT_POLICY_RE.match(line) for line in unquoted_lines[:12]
        )
        if execution_clauses >= 2 or supports_local_staff or adopts_local_retirement_policy:
            return [local_college]
        # 序言中的本院人员和制定说明可分段出现，引用和全校适用范围已在前面处理。
        opening = "\n".join(unquoted_lines[:12])
        if _LOCAL_GROUP_RE.search(opening) and _POLICY_ADOPTION_RE.search(opening):
            return [local_college]
        # 具体办法名称可能被 PDF 排版拆行，合并序言换行后识别本院制定说明。
        if (any(_LOCAL_POLICY_ADOPTION_RE.search(line) for line in unquoted_lines[:12])
                or _LOCAL_POLICY_ADOPTION_RE.search(''.join(unquoted_lines[:12]))):
            return [local_college]
        if any(_LOCAL_POLICY_INTERPRETATION_RE.search(line) for line in unquoted_lines):
            return [local_college]
        if title.startswith("学院") and any(_LOCAL_GOVERNANCE_DECISION_RE.search(line) for line in unquoted_lines):
            return [local_college]
    # 学科可以由多个学院开设，须由采集来源和正文的专业培养、院级活动共同印证。
    if (program_students and source_unit == "国家网络安全学院"
            and any("网络空间安全专业" in line for line in lines)
            and any(re.match(r"学院(?:还)?(?:通过|负责|组织)", line) for line in lines)):
        return [source_unit]
    return []


def query_applicable_units(query: str, known_units: set[str]) -> set[str]:
    """将问题中的显式别名和已有单位归一化，不推测用户所属单位。"""
    query = normalize_unit_query("".join(query.split()))
    known_units = {normalize_applicable_unit(unit) for unit in known_units}
    matches = {unit for unit in known_units if unit and unit != "全校" and unit in query}
    if matches:
        # 名称包含时取较完整的一个，避免将较长学院名称的片段当作另一学院。
        return {unit for unit in matches if not any(unit != other and unit in other for other in matches)}
    # 尚未入库的学院也可能位于问题中段，不能因此放行其他学院的制度。
    units = set()
    for part in re.split(r"[，,。！？?：:]", query):
        prefix = re.sub(r"^(?:请问|我在|我是|我们是|对于|关于)", "", part)
        unit = _unit_from_prefix(prefix)
        if unit:
            units.add(unit)
    return units
