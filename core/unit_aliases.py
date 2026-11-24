"""适用单位的显式别名表，入库、查询与展示共用，不改写原文。"""
import json
import re
from functools import lru_cache
from pathlib import Path

_ALIAS_PREFIX_RE = re.compile(
    r'(?:^|[^\u4e00-\u9fffA-Za-z0-9_]|武汉大学|请问|请教|咨询|问问|问|查询|查询一下|查|找|看看|'
    r'关于|对于|针对|印发|发布|开展|加强|规范|来自|我在|我是|我们|本校|我校|想了解|了解|一下|在|是|对|和|与|及|或|由|到|去|向|让|给|为)$'
)

_UNIT_HIERARCHY = {
    "前沿交叉学科研究院": {
        "中国传统文化研究中心": (),
        "国家文化发展研究院": (),
        "质量发展战略研究院": (),
        "中国边界与海洋研究院": (),
        "国际问题研究院": (),
        "董辅礽经济社会发展研究院": ("董辅礽研究院", "董辅礽经济发展研究院", "董辅礽社会经济发展研究院"),
        "武汉大学高等研究院": (),
        "新型电力系统与国际标准研究院": ("新标院",),
        "湖北国家应用数学中心": ("湖北应用数学中心", "应数中心"),
        "前沿交叉学科研究院心理学系": ("心理学系",),
    },
}
_UNIT_PATHS = {
    unit: f"{parent}-{unit.removeprefix(parent)}"
    for parent, children in _UNIT_HIERARCHY.items()
    for unit in children
}
_CHILD_UNIT_ALIASES = {
    alias: unit
    for children in _UNIT_HIERARCHY.values()
    for unit, aliases in children.items()
    for alias in (unit, _UNIT_PATHS[unit], *aliases)
}


@lru_cache(maxsize=1)
def unit_aliases() -> dict[str, str]:
    groups = json.loads(Path(__file__).with_name('unit_aliases.json').read_text(encoding='utf-8'))
    aliases = {}
    if not isinstance(groups, dict):
        raise ValueError('学院别名配置必须是标准名到别名列表的对象')
    generic = {'全校', '学院', '本院', '本学院', '我院', '各学院', ''}
    for canonical, values in groups.items():
        if not isinstance(canonical, str) or not isinstance(values, list):
            raise ValueError('学院标准名须为字符串，别名须为列表')
        canonical = ''.join(canonical.split())
        if canonical in generic:
            raise ValueError('学院标准名不能是泛称')
        for alias in [canonical, *values]:
            if not isinstance(alias, str):
                raise ValueError('学院别名必须为字符串')
            alias = ''.join(alias.split())
            # 手工删掉某个简称后留下的空占位等同于未配置，不让整张规则表失效。
            if not alias:
                continue
            if alias in generic or (alias in aliases and aliases[alias] != canonical):
                raise ValueError(f'学院别名属于泛称或存在多个归属（标准名：{canonical}）：{alias}')
            aliases[alias] = canonical
    return aliases


def normalize_applicable_unit(value: str | None) -> str:
    unit = ''.join(str(value or '').split())
    return unit_aliases().get(unit, _CHILD_UNIT_ALIASES.get(unit, unit))


def normalize_applicable_units(values: list[str] | str | None) -> list[str]:
    """统一列表中的单位名称；旧条款向量中可能仍保存单个单位。"""
    if isinstance(values, str):
        values = [values]
    units = dict.fromkeys(normalize_applicable_unit(value) for value in (values or []))
    units.pop("", None)
    return ["全校"] if "全校" in units else list(units)


def registered_applicable_units(values: list[str] | str | None) -> list[str]:
    """新提取的适用范围只接受全校或已登记机构，拒绝不完整的单位组合。"""
    raw_units = [values] if isinstance(values, str) else (values or [])
    aliases = _CHILD_UNIT_ALIASES | unit_aliases()
    units = []
    for value in raw_units:
        unit = ''.join(str(value or '').split())
        if unit == '全校':
            units.append(unit)
        elif unit in aliases:
            units.append(aliases[unit])
        elif unit:
            return []
    return normalize_applicable_units(units)


def applicable_unit_paths(values: list[str] | str | None) -> list[str]:
    """从适用单位生成由归口单位到具体机构的展示路径。"""
    return [_UNIT_PATHS.get(unit, unit) for unit in normalize_applicable_units(values)]


def registered_unit_spans(text: str) -> list[tuple[int, int, str]]:
    """定位明确出现的登记单位，兼容研究院、学堂及带括号的官方全称。"""
    aliases = _CHILD_UNIT_ALIASES | unit_aliases()
    if not aliases:
        return []
    pattern = '|'.join(re.escape(name) for name in sorted(aliases, key=lambda name: (-len(name), name)))
    spans = []
    for match in re.finditer(pattern, text):
        name = match.group()
        canonical = aliases[name]
        if not _ALIAS_PREFIX_RE.search(text[:match.start()]):
            continue
        # “对外院校”“马院长”不是学院简称，不能据此限制制度范围。
        if name != canonical and len(name) <= 3 and text[match.end():match.end() + 1] in {'校', '系', '长', '士'}:
            continue
        spans.append((match.start(), match.end(), canonical))
    return spans


def normalize_unit_query(query: str) -> str:
    """一次展开已登记名称，不改写普通词内片段或重复展开生成的全称。"""
    pieces = []
    offset = 0
    for start, end, canonical in registered_unit_spans(query):
        pieces.extend([query[offset:start], canonical])
        offset = end
    pieces.append(query[offset:])
    return ''.join(pieces)


def applicable_unit_variants(unit: str) -> set[str]:
    canonical = normalize_applicable_unit(unit)
    aliases = _CHILD_UNIT_ALIASES | unit_aliases()
    return {canonical} | {alias for alias, name in aliases.items() if name == canonical}
