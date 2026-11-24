import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import fitz
from core.policy_titles import (
    is_direct_policy_title, is_policy_issuance_notice_title, is_regulatory_title, normalize_policy_title, policy_title_subject,
)


@dataclass
class Signal:
    category: str  # 目标类别
    weight: float  # 权重
    description: str  # 原因
    is_strong: bool = False  # True=强信号，直接裁决


# 强信号冲突时的优先级（学术最优先，因其特征最独特）
CATEGORY_PRIORITY = {
    "academic_paper": 1,
    "other": 2,
    "policy_regulation": 3,
    "admin_form": 4,
    "contract": 5,
}


def classify_document(
    file_path: str,
    filename: str,
    parsed_text: Optional[str] = None,
    source_metadata: Optional[dict] = None,
) -> dict:
    """
    文档类型分类主入口

    返回: {
        "doc_type": str,       # academic_paper | policy_regulation | admin_form | contract | other
        "confidence": float,    # 0.0 ~ 1.0
        "reason": str,          # 分类原因简述
        "signals": list         # 命中的所有信号（调优/审计用）
    }
    """
    # 1. 提取文本：前3页 + 末1页（用于捕捉参考文献、落款等）
    # 主解析流程已经取得 CloudMinerU 文本时直接复用，避免扫描件被
    # PyMuPDF 的空文字层误判；只有独立调用时才保留旧回退路径。
    if parsed_text is None:
        print("!!!!未传入parsed_text")
    preview_text = (
        str(parsed_text)[:6000]
        if parsed_text is not None
        else _extract_text(file_path, head_pages=3, tail_pages=1)
    )


    total_pages = _get_page_count(file_path)
    metadata = _extract_metadata(file_path)
    if source_metadata:
        metadata["source_doc_number"] = str(source_metadata.get("doc_number") or "")
        metadata["source_title"] = str(source_metadata.get("title") or "")

    # 2. 规则引擎
    doc_type, confidence, reason, signals = _rule_based_classify(
        preview_text, filename, total_pages, metadata
    )

    # 3. 兜底
    if doc_type is None:
        doc_type = "other"
        confidence = 0.0

    return {
        "doc_type": doc_type,
        "confidence": round(confidence, 3),
        "reason": reason,
        "signals": [f"{'[强信号]' if s.is_strong else ''}{s.description}" for s in signals]
    }


# ==================== 文本/元数据提取 ====================

def _extract_text(file_path: str, head_pages: int = 3, tail_pages: int = 1, max_chars: int = 6000) -> str:
    """提取文档头部和尾部文本（尾部用于检测参考文献、公文落款等）"""
    try:
        doc = fitz.open(file_path)
        text = ""

        # 头部
        for i in range(min(head_pages, len(doc))):
            text += doc[i].get_text()

        # 尾部（避免与头部重复提取）
        if len(doc) > head_pages:
            start = max(head_pages, len(doc) - tail_pages)
            for i in range(start, len(doc)):
                text += doc[i].get_text()

        doc.close()
        return text[:max_chars]
    except Exception:
        return ""


def _extract_metadata(file_path: str) -> dict:
    try:
        doc = fitz.open(file_path)
        meta = doc.metadata or {}
        doc.close()
        return {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "creator": meta.get("creator", ""),
        }
    except Exception:
        return {}


def _get_page_count(file_path: str) -> int:
    try:
        doc = fitz.open(file_path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


# ==================== 信号检测引擎 ====================

_POLICY_SELF_REFERENCE = (
    r'本(?:管理|实施|工作|操作|试行|暂行|补充){0,2}(?:办法|规定|制度|细则|条例|规则|章程|规程|标准|意见|方案)'
)
_LIMITED_SCOPE = r'(?:本次|此次|当次|该次|本届|本学期|本学年|本年度)'
_DOCUMENT_NUMBER_PATTERN = (
    r'[\u4e00-\u9fa5]{2,12}[ \t]*[〔\[［﹝【][ \t]*(?:19|20)\d{2}[ \t]*[〕\]］﹞】]'
    r'[ \t]*\d+[ \t]*号'
)
# 依据只接受被替换的书名和紧随其后的文号，避免跳过正文中的转述或拟议措辞。
_POLICY_CITATION = (
    rf'《》(?:[ \t]*(?:[（(][ \t]*{_DOCUMENT_NUMBER_PATTERN}[ \t]*[）)]|{_DOCUMENT_NUMBER_PATTERN}))?'
)
_POLICY_ADOPTION_RE = re.compile(
    r'(?:^|[，,。；;\n])[ \t]*'
    rf'(?:(?:根据|依据|按照)\s*{_POLICY_CITATION}'
    rf'(?:\s*(?:[、，,]|以及|及|和)\s*{_POLICY_CITATION})*\s*|'
    r'(?:为|经)[^，,。；;：:\n]*(?=特|现))?'
    # “方案”须结合本文件制定表述和多项执行要求，不能仅凭文件名裁决。
    rf'(?:特|现|据此)?(?:制定|制订|修订|印发|发布)[ \t]*'
    rf'(?:{_POLICY_SELF_REFERENCE}|(?:以下|如下)(?:实施|工作)?(?:意见|方案))'
    r'[ \t]*(?=[。；;：:\n]|$)'
)
# 兼容“为规范……，学院制定了有关……规定”的叙述式制定表述。
# 从段首核对本单位和可选的制定目的，避免把转述、拟议或学习要求当成制定行为。
_POLICY_NARRATIVE_ADOPTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:为[^。；;：:\n]{1,200}[，,][ \t]*)?'
    r'(?:本校|本院|学校|学院|本单位)(?:现|特|已)?(?:制定|制订|修订)了?[ \t]*'
    r'(?:有关|关于)[^，,。；;：:\n《》〈〉“”]{1,80}'
    r'(?:办法|规定|制度|细则|条例|规则|章程|规程|标准)[ \t]*(?=[，,。；;：:\n]|$)'
)
# 研究决定也可直接设定管理规则；须明确按一般情形处理，不能只凭“决定”二字。
_POLICY_DECISION_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:为[^。；;：:\n]{1,200}[，,][ \t]*)?'
    r'经(?:本校|本院|学校|学院|本单位)?(?:研究|讨论|审议)决定[，,][ \t]*'
    r'对[^，,。；;：:\n]{0,60}(?:以下|下列)(?:情况|情形)[^，,。；;：:\n]{0,60}'
    r'(?=[，,。；;：:\n]|$)'
)
_POLICY_SECTION_RE = re.compile(
    r'(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*)?'
    r'(?:[一二三四五六七八九十百\d]+[、.．]|[（(][一二三四五六七八九十百\d]+[）)]|'
    r'第[一二三四五六七八九十百\d]+条)'
)
_POLICY_REQUIREMENT_RE = re.compile(
    r'应当|不得|不允许|必须|须|严禁|方可|要求为|'
    r'应(?:积极|在|于|按|由|向|提交|提供|履行|承担|符合|根据|及时)|'
    r'需(?:要|经|由|根据|提交|提供|填写|在|于)'
)
_CHAPTER_ARTICLE_HEADING_RE = re.compile(
    r'(?m)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?[ \t]*第[ \t]*'
    r'(?P<number>[零〇一二三四五六七八九十百千万\d][零〇一二三四五六七八九十百千万\d \t]*)'
    r'(?P<kind>[章条])(?:\*\*)?'
)


def _count_body_chapters_and_articles(text: str) -> tuple[int, int]:
    """按独立标题统计正文章条，排除引文、目录和重复编号。"""
    main_text = re.sub(r'《[^》]*》|〈[^〉]*〉|“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', '', text)
    main_text = re.sub(r'(?m)^[ \t]*>[^\n]*', '', main_text)
    headings = list(_CHAPTER_ARTICLE_HEADING_RE.finditer(main_text))
    chapters, articles = set(), set()
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(main_text)
        body = main_text[heading.end():end]
        first_line = body.partition('\n')[0]
        if re.search(r'[.．·…⋯]{2,}[ \t]*\d*[ \t]*$', first_line):
            continue
        number = ''.join(heading['number'].split())
        if heading['kind'] == '章' and body.strip():
            chapters.add(number)
        elif heading['kind'] == '条' and re.search(r'[。；;！？!?]', body):
            # 条款须有实际句子，不能把空编号或只有目录标题的条目算成正文。
            articles.add(number)
    return len(chapters), len(articles)


def _establishes_numbered_rules(text: str, title: str) -> bool:
    """识别本文件制定、决策或正文标题确认的多条执行规则。"""
    # 保留引用依据的位置，去掉被引用的内容，避免把转述当成本文件的规则。
    main_text = re.sub(r'《[^》]*》|〈[^〉]*〉', '《》', text)
    main_text = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', '', main_text)
    main_text = re.split(
        r'(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:附件|附表)[ \t]*'
        r'[一二三四五六七八九十\d]*[ \t]*(?:[：:]|$)',
        main_text,
        maxsplit=1,
    )[0]
    opening, *sections = _POLICY_SECTION_RE.split(main_text)
    has_own_adoption = (
        _POLICY_ADOPTION_RE.search(opening) is not None
        or _POLICY_NARRATIVE_ADOPTION_RE.search(opening) is not None
    )
    # 单次活动中的分类处理仍然只是临时安排，不作为一般管理规则的制定依据。
    has_general_decision = (
        _POLICY_DECISION_RE.search(opening) is not None
        and re.search(_LIMITED_SCOPE, opening) is None
    )
    subject = policy_title_subject(title)
    confirms_title = is_regulatory_title(title) and any(
        policy_title_subject(line) == subject for line in opening.splitlines()[:12]
    )
    return (
        (has_own_adoption or has_general_decision or confirms_title)
        and not re.search(
            rf'(?:本通知|本意见|{_POLICY_SELF_REFERENCE})\s*(?:仅|只)?适用于\s*{_LIMITED_SCOPE}',
            main_text,
        )
        and sum(_POLICY_REQUIREMENT_RE.search(section) is not None for section in sections) >= 2
    )


def _detect_signals(text: str, filename: str, page_count: int, metadata: dict) -> List[Signal]:
    """统一检测所有信号（强信号 + 软信号）"""
    signals = []
    filename_lower = filename.lower()
    text_lower = text.lower()

    # ==================== 学术论文 ====================
    # --- 强信号 ---
    if re.search(r'(?:https?://doi\.org/)?10\.\d{4,9}/[-._;()/:A-Z0-9]+', text, re.I):
        signals.append(Signal("academic_paper", 1.0, "检测到DOI", True))

    if re.search(r'arXiv\s*:\s*\d{4}\.\d{4,5}(?:v\d+)?', text, re.I):
        signals.append(Signal("academic_paper", 1.0, "检测到arXiv编号", True))

    if re.search(r'PMID\s*:\s*\d{7,8}|PMCID\s*:\s*PMC\d+', text, re.I):
        signals.append(Signal("academic_paper", 1.0, "检测到PubMed标识", True))

    # 学术引用格式块（PVLDB/ACM/IEEE Reference Format...）
    ACADEMIC_VENUES = (
        r'(?:PVLDB|VLDB|SIGMOD|ICDE|CIDR|EDBT|TKDE|TODS|TOIS|'
        r'NeurIPS|ICML|ICLR|AAAI|IJCAI|CVPR|ICCV|ECCV|'
        r'ACL|EMNLP|NAACL|COLING|KDD|WWW|CIKM|WSDM|RecSys|'
        r'OSDI|SOSP|NSDI|EuroSys|ASPLOS|ATC|FAST|'
        r'SIGCOMM|MobiCom|MobiSys|INFOCOM|'
        r'S&P|CCS|USENIX\s+Security|NDSS|Crypto|Eurocrypt|'
        r'PLDI|POPL|OOPSLA|ICSE|FSE|ASE|'
        r'STOC|FOCS|SODA|'
        r'Nature|Science|PNAS|IEEE|ACM|Springer|Elsevier)'
    )
    if re.search(rf'{ACADEMIC_VENUES}\s+Reference\s+Format\s*[：:]', text, re.I | re.M):
        signals.append(Signal("academic_paper", 1.0, "检测到学术引用格式块", True))


    # 审稿/出版日期三连（Received/Accepted/Published 或 收稿/修回/录用）
    if re.search(r'(?:Received|Revised|Accepted|Published).*?\d{4}|'
                 r'(?:收稿日期|修回日期|录用日期).*?\d{4}', text, re.I):
        signals.append(Signal("academic_paper", 1.0, "检测到论文审稿或出版日期", True))

    # 期刊卷期页格式
    if re.search(r'(?:Journal|Vol\.?|Volume)\s*\d+.*(?:No\.?|Issue)\s*\d+', text, re.I):
        signals.append(Signal("academic_paper", 1.0, "检测到期刊卷期格式", True))

    # --- 软信号 ---
    # 行首编号也用于制度附录和参考文献列表；行内编号只作为辅助证据。
    inline_citation_text = re.sub(r'(?m)^[^\S\n]*\[\d{1,2}\]', '', text)
    citation_count = len(re.findall(r'\[\d{1,2}\]', inline_citation_text))
    if citation_count >= 10:
        signals.append(Signal("academic_paper", 2.0, f"检测到{citation_count}处行内方括号编号"))

    academic_keywords = [
        "abstract", "introduction", "keywords", "references",
        "materials and methods", "results", "discussion","conclusion","experiments",
        "摘要", "关键词", "引言", "材料与方法", "结果", "讨论", "参考文献", "结论"
    ]
    matched = sum(1 for k in academic_keywords if k in text_lower)
    if matched >= 3:
        signals.append(Signal("academic_paper", 2.5, f"命中{matched}个论文章节关键词"))

    fig_table = len(re.findall(r'(?:Fig\.|Figure|Table|图\s*\d|表\s*\d)', text, re.I))
    if fig_table >= 3:
        signals.append(Signal("academic_paper", 2.0, f"检测到{fig_table}处图表引用"))

    # 参考文献列表（通常在末尾）
    if re.search(r'(?:References|参考文献)\s*\n\s*(?:\[\d+\]|\d+\.)', text, re.I):
        ref_items = len(re.findall(r'(?:\n\s*\[\d+\]|\n\s*\d+\.)', text[-2000:]))
        if ref_items >= 5:
            signals.append(Signal("academic_paper", 2.0, f"参考文献列表约{ref_items}条"))

    if 5 <= page_count <= 50:
        signals.append(Signal("academic_paper", 1.0, "页数符合论文范围(5-50页)"))

    if metadata.get("author") and len(metadata["author"]) > 3:
        signals.append(Signal("academic_paper", 0.5, "PDF元数据含作者信息"))

    if re.search(r'论文|学报|journal|thesis|dissertation|paper|review', filename, re.I):
        signals.append(Signal("academic_paper", 1.0, "文件名含学术关键词"))

    # ==================== 政策制度 ====================
    # --- 强信号 ---
    # 结合正文标题、专题和排期识别学习计划，文件名只能作为佐证。
    title = normalize_policy_title(filename)
    if (
        title.endswith("学习计划")
        and normalize_policy_title(text.lstrip().partition("\n")[0]) == title
        and re.search(r"(?m)^[ \t]*第[一二三四五六七八九十百\d]+专题\s*[：:]", text)
        and re.search(r"(?m)^[ \t]*时间安排[ \t]*[：:][ \t]*\d{4}\s*年\s*\d{1,2}\s*月", text)
    ):
        signals.append(Signal("other", 1.0, "学习计划正文列有学习专题和月份安排", True))

    # 制度印发通知的文件名在扫描件中仍然可靠，应作为明确制度信号。
    if is_policy_issuance_notice_title(title, regulatory_only=True):
        signals.append(Signal("policy_regulation", 1.0, "文件名为制度印发通知", True))

    # 完整的直接制度标题也可独立分类；整串匹配避免把解读、研究或调查表当成制度。
    if is_direct_policy_title(filename):
        signals.append(Signal("policy_regulation", 1.0, "文件名为直接制度标题", True))

    # 本地提取的标题还须与正文首行相符，不能只凭文件属性中的旧标题判定。
    source_title = metadata.get("source_title", "")
    opening_line = next((line for line in text.splitlines() if line.strip()), "")
    if (is_direct_policy_title(source_title)
            and normalize_policy_title(opening_line) == normalize_policy_title(source_title)):
        signals.append(Signal("policy_regulation", 1.0, "来源标题与正文首行的直接制度标题一致", True))

    # 通知、意见也可以载有反复执行的规则，核对其适用表述和正文要求。
    applicable_scope = re.search(
        rf'(?:本(?:通知|意见)|{_POLICY_SELF_REFERENCE})\s*(?:仅|只)?适用于\s*'
        rf'(?!{_LIMITED_SCOPE})\S',
        text,
    )
    if re.search(r'应当|不得|必须|须|严禁|方可', text):
        if applicable_scope:
            signals.append(Signal("policy_regulation", 1.0, "正文包含明确适用范围和约束性要求", True))
        # 用条款自身的生效表述辅助识别，排除句中转述和引号内的引用。
        elif re.search(
            r'(?m)^[ \t]*(?:第[一二三四五六七八九十百\d]+条|[一二三四五六七八九十百\d]+[、.．])?[ \t]*'
            r'本(?:制度|办法|规定|细则|条例|规则|章程)[^。；;“”「」]{0,100}'
            r'自(?:颁布|公布|发布|印发)之日起(?:施行|实施|执行|生效)',
            text,
        ):
            signals.append(Signal("policy_regulation", 1.0, "正文包含约束性要求和制度生效条款", True))

    if _establishes_numbered_rules(text, title):
        signals.append(Signal(
            "policy_regulation", 1.0, "正文标题或制定、决策表述与多项条款中的执行要求相互印证", True,
        ))

    chapters, articles = _count_body_chapters_and_articles(text)
    has_body_structure = (chapters >= 2 and articles >= 3) or articles >= 5
    if has_body_structure:
        # 章条结构本身可裁决，不再要求标题关键词、制定表述或特定义务用词。
        signals.append(Signal(
            "policy_regulation", 1.0, f"正文具有完整章条结构：{chapters}章、{articles}条", True,
        ))

    # 文号和其他公文格式保留在日志中，供审核溯源。
    if (
        re.search(_DOCUMENT_NUMBER_PATTERN, text)
        or re.fullmatch(_DOCUMENT_NUMBER_PATTERN, metadata.get("source_doc_number", ""))
    ):
        signals.append(Signal("official_document", 0.0, "检测到公文发文字号"))

    if "主送：" in text and "抄送：" in text:
        signals.append(Signal("official_document", 0.0, "检测到公文主送抄送格式"))

    if re.search(r'(?:国务院|中共中央|教育部|发改委|人民政府|办公厅).{0,15}印发', text):
        signals.append(Signal("official_document", 0.0, "检测到权威机关印发用语"))

    if re.search(r'现印发给你们|请认真贯彻执行|请遵照执行|特此通知|此令', text):
        signals.append(Signal("official_document", 0.0, "检测到公文套语"))

    # --- 软信号 ---
    chapter_struct = len(re.findall(r'第[一二三四五六七八九十百\d]+[章条]', text))
    if chapter_struct >= 3 and not has_body_structure:
        signals.append(Signal("policy_regulation", 2.5, f"检测到{chapter_struct}处章节条款"))

    policy_types = ["通知", "规定", "办法", "条例", "细则", "意见", "决定", "公告", "批复", "令"]
    type_matches = sum(1 for t in policy_types if t in text)
    if type_matches >= 2:
        signals.append(Signal("official_document", 0.0, f"命中{type_matches}个公文类型词"))

    if re.search(r'(?:自|于)\d{4}年\d{1,2}月\d{1,2}日(?:起?施行|实施|生效)', text):
        signals.append(Signal("policy_regulation", 1.5, "检测到施行日期"))

    if re.search(r'^\s*[\u4e00-\u9fa5]{2,12}(?:厅|局|委|办|部|署|会|院|校|政府)', text, re.M):
        signals.append(Signal("policy_regulation", 1.5, "检测到发文机关标志"))

    if re.search(r'办法|规定|条例|细则|制度', filename):
        signals.append(Signal("policy_regulation", 1.0, "文件名含制度关键词"))

    # ==================== 表单 ====================
    # --- 强信号 ---
    checkbox_count = len(re.findall(r'[□☑☐]', text))
    if checkbox_count >= 5:
        signals.append(Signal("admin_form", 1.0, f"检测到{checkbox_count}个复选框", True))

    if re.search(r'(申请|登记|审批|报名|调查|备案|统计|申报|测评|考核)[表册]', filename):
        signals.append(Signal("admin_form", 1.0, "文件名明确为表单类型", True))

    if "填表日期" in text and ("填表人" in text or "申请人" in text):
        signals.append(Signal("admin_form", 1.0, "检测到填表日期和填表人/申请人", True))

    underline_count = len(re.findall(r'[_]{3,}', text))
    if underline_count >= 10:
        signals.append(Signal("admin_form", 1.0, f"检测到{underline_count}处输入下划线", True))

    # --- 软信号 ---
    form_fields = [
        "姓名", "性别", "年龄", "出生年月", "身份证号", "联系电话",
        "电子邮箱", "通讯地址", "邮政编码", "学历", "学位", "职称", "工作单位"
    ]
    field_matches = sum(1 for f in form_fields if f in text)
    if field_matches >= 4:
        signals.append(Signal("admin_form", 2.5, f"命中{field_matches}个表单字段标签"))

    if 1 <= page_count <= 5:
        signals.append(Signal("admin_form", 1.5, "页数符合表单范围(1-5页)"))

    if re.search(r'(?:签名|签字)[：:]|(?:盖章|公章)[：:]|填表日期', text):
        signals.append(Signal("admin_form", 1.0, "检测到签名盖章或日期区域"))

    if re.search(r'表$|表格|form', filename, re.I):
        signals.append(Signal("admin_form", 0.5, "文件名含表单词"))

    # ==================== 合同（可选扩展类别） ====================
    if re.search(r'甲方[：:].*?乙方[：:]', text, re.S):
        signals.append(Signal("contract", 1.0, "检测到甲乙双方", True))

    if "本合同一式" in text or "（盖章）" in text:
        signals.append(Signal("contract", 0.8, "检测到合同套语"))

    return signals


# ==================== 裁决逻辑 ====================

def _resolve_strong_signals(signals: List[Signal]) -> Optional[Tuple[str, str]]:
    """处理强信号冲突：按优先级返回最高优先级的强信号类别"""
    strong = [s for s in signals if s.is_strong]
    if not strong:
        return None

    # 按类别分组，取每类最强信号
    best_by_cat = {}
    for s in strong:
        if s.category not in best_by_cat or s.weight > best_by_cat[s.category][0]:
            best_by_cat[s.category] = (s.weight, s.description)

    # 按 CATEGORY_PRIORITY 排序，取优先级最高的
    sorted_cats = sorted(
        best_by_cat.items(),
        key=lambda x: CATEGORY_PRIORITY.get(x[0], 99)
    )
    winner_cat, (weight, reason) = sorted_cats[0]
    return winner_cat, reason


def _calculate_soft_scores(signals: List[Signal]) -> Dict[str, float]:
    """按类别累计软信号权重"""
    scores = {"academic_paper": 0, "policy_regulation": 0, "admin_form": 0, "contract": 0}
    for s in signals:
        if not s.is_strong and s.category in scores:
            scores[s.category] += s.weight
    return scores


def _normalize_confidence(top_score: float, second_score: float) -> float:
    """
    置信度归一化：基于绝对分数和相对差距，映射到 0.5~1.0
    """
    if top_score < 3.5:
        return 0.0

    # 基础分：分数越高，sigmoid 越接近 1
    base = 0.5 + 0.5 * (1 - math.exp(-top_score / 5))

    # 差距加成：与第二名拉得越开越确信
    gap = top_score - second_score
    bonus = 0.15 * (1 - math.exp(-gap / 3))

    return min(base + bonus, 1.0)


def _rule_based_classify(text, filename, page_count, metadata):
    """分类主逻辑"""
    # 1. 检测所有信号
    signals = _detect_signals(text, filename, page_count, metadata)

    # 2. 强信号优先裁决（一旦命中，置信度 1.0，直接返回）
    strong_result = _resolve_strong_signals(signals)
    if strong_result:
        cat, reason = strong_result
        return cat, 1.0, reason, signals

    # 3. 软信号计分
    scores = _calculate_soft_scores(signals)
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_cat, top_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0

    # 4. 阈值判定（必须满足：绝对分够高 + 与第二名拉开差距）
    if top_score < 3.5 or (top_score - second_score) < 2.0:
        if not signals:
            return None, 0.0, "未触发任何有效分类信号", signals
        reason = (
            f"信号不足或类别差距过小：最高得分{top_score:.1f}（要求≥3.5），"
            f"领先第二名{top_score - second_score:.1f}分（要求≥2.0）"
        )
        return None, 0.0, reason, signals

    confidence = _normalize_confidence(top_score, second_score)

    # 生成人类可读的原因
    cat_signals = [s for s in signals if s.category == top_cat and not s.is_strong]
    reason = f"综合{len(cat_signals)}个软信号，累计得分{top_score:.1f}（领先第二名{top_score - second_score:.1f}分）"

    return top_cat, confidence, reason, signals
