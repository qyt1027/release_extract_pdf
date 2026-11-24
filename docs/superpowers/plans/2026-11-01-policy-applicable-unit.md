# 制度适用单位实施计划

> **For agentic workers:** 内联执行以下步骤；按 test-driven-development 和 verification-before-completion 验证。当前工作目录不含 Git 元数据，不执行提交。

**Goal:** 用一个 `applicable_unit` 字符串区分全校、具体学院和未知，并接入制度检索。

**Architecture:** 按用户于 2026-11-02 确认的简化规则，标题或文件名含具体学院名称时直接采用；没有“学院”但包含“大学”时判为全校，标题无法判断时才参考正文明确范围。每个附件独立判定；关系表保存该字段，BM25 和向量索引携带制度名称及适用单位，查询具体学院时保留该学院和全校制度。

**Tech Stack:** Python、现有 PostgreSQL 适配器、BM25、现有向量检索、unittest。

**Spec:** 本聊天已确认的单字段方案：`全校`、具体学院名称、空字符串；不新增归属单位或发文部门字段。

## 全局约束

- 交流与新增代码注释使用中文。
- 不把发文部门或正文偶然提到的学院当作适用单位。
- 无明确证据、多学院或相互冲突的范围均留空，不默认全校。
- 优先复用现有入口，兼容旧调用；不调用模型，不改实际业务数据。

### 任务一：识别及保存适用单位

**Files:** 新增 `metadata/policy_scope.py`、`tests/test_policy_applicable_unit.py`；修改 `metadata/policy.py`、`metadata/__init__.py`、`processing/pipeline.py`、`policy/document_parts.py`、`core/models.py`、`policy/storage.py`、`processing/reset.py`。

**Interfaces:** 元数据与 `PolicyDocument` 增加 `applicable_unit: str`，默认空字符串；提取入口增加可选 `file_name` 参数。明确的学院标题直接决定分类，正文仅作补充。

- [x] 先写回归测试：计算机学院及其他学院标题、文件名回退、明确全校范围、标题优先、正文补充、引用或否定不误判、多个附件互不污染。
- [x] 执行 `python -X utf8 -m unittest discover -s tests -p test_policy_applicable_unit.py -v`，确认新增行为缺失。
- [x] 实现确定性识别函数，通过附件拆分统一赋值；在数据库迁移与 upsert 中增加该列，清理时清空。
- [x] 使用 SQLite 内存库执行 upsert SQL 的等价适配，验证保存及重复导入覆盖，不连接实际 PostgreSQL。

### 任务二：索引、检索和展示

**Files:** 修改 `policy/retrieval.py`、`policy/knowledge_v2/retrieval.py`、`policy/answering.py`、`policy/web_catalog.py`、`policy/web_ui/answer.js`；在 `tests/test_policy_applicable_unit.py` 增加检索测试。

**Interfaces:** `build_clause_index_text(clause, document=None)` 保持旧调用可用；索引 metadata 与查询、问答证据增加 `applicable_unit`。

- [x] 先写测试：学院和标题进入真实索引文本、BM25 标题命中、学院查询保留全校并排除其他学院、无学院查询保持跨单位检索、问答 V2 增强后仍遵守单位范围。
- [x] 运行上述测试，确认缺失行为导致失败。
- [x] 实现正文不变的索引上下文与候选筛选；多学院查询保留所有明确提到的学院和全校，不根据用户所属学院猜测。
- [x] 列表、详情、搜索结果和回答证据透出适用单位，网页在已有元数据区域显示。

### 任务三：验证与交付

- [x] 执行新增测试及元数据、附件拆分、默认效力、条款检索、语义重排、问答、V2、Web API、文件重置相关回归。
- [x] 对改动的 Python 文件执行编译检查，对网页脚本执行语法检查。
- [x] 按 requesting-code-review 技能请只读审查，处理有依据的问题并重跑受影响测试。
- [x] 报告实际测试结果，说明已有文件需要重新处理并重建索引。

## 验证结果（2026-11-02）

- 相关回归共 224 项：222 项通过，2 项因未配置独立 PostgreSQL/pgvector 测试库而跳过。
- 新增适用单位测试 27 项，全部通过；Python 编译及网页脚本语法检查通过。
- 独立审查发现的短名称、职责句、跨行范围、未知学院查询、引号及字段边界问题已复现并修正。
- MHTML 文号旧测试与既有规范化格式对齐，同时断言原始文号仍保留；未更改文号生产逻辑。
- Windows 沙箱阻止 asyncio 创建本机套接字，最终本地回归已通过授权在沙箱外执行；未操作业务库。
