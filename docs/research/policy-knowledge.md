# 制度知识研究方案与操作

本文记录并列保留的研究链路，不指定最终技术路线。文件处理与制度问答的主线见 [README](../../README.md)，旧设计与实施记录见 [历史索引](policy-knowledge-history.md)。

“已有实现”表示代码和入口存在；“尚待验证”表示仍需真实制度数据、人工复核和质量评估；“仅有设计”表示历史文档中的目标尚无对应入口。单元测试验证程序行为，不证明抽取准确率、图谱完整性或流程适用性。

## 共同前置条件与共享能力

各方案读取已入库的制度文档和条款，不重新解析源文件。先执行 `python main.py --process-dir "D:\policies"` 并记录 `batch_id`。基础结构化在 `policy/pipeline.py`，共享存储在 `policy/storage.py`，质量评估在 `policy/quality.py`；模型客户端在 `policy/llm.py`。研究模型使用 `LLM_*` 配置，主线问答使用独立的 `ANSWER_LLM_*` 配置。

运行 ID 各有用途：文件导入为 `batch_id`，实体关系抽取为 `policy_run_id`，流程分流为 `policy_process_id`，V2 为 `knowledge_v2_run_id`，辅助分类为 `classification_run_id`。使用命令实际返回的 ID，不按示例前缀自行生成。命令全集见 `python main.py --help-all`。

## 通用实体关系抽取与人工审核

**目的与状态：已有实现，真实数据质量尚待验证。** 从实质性条款抽取实体和关系，保存原文证据及候选审核状态。入口为 `policy/graph/extraction.py` 和 `policy/graph/reviewer.py`。

链路是批次条款 → 规则或模型候选 → 类型、端点与证据验证 → 持久化候选 → 人工标注 → 抽检导出。输入为文件批次和现有条款；输出为实体、关系、审核项、人工标注及 CSV。运行状态和版本标识沿用原实现。

目录批处理识别为规章制度的 PDF 后，会自动写入制度文档和章/节/条/款/项层级的条款记录。条款结构化完成后，再手动启动实体关系抽取：

```powershell
# 为已完成的 PDF 批次创建一个新的抽取版本并执行
python main.py --extract-policy-batch batch_xxxxxxxxxxxxxxxx

# 先只抽取前 10 条实质性条款，验证结果和模型消耗
python main.py --extract-policy-batch batch_xxxxxxxxxxxxxxxx --limit 10

# 实体关系抽取中断后恢复
python main.py --resume-policy-extraction policy_run_xxxxxxxxxxxxxxxx

# 查看实体关系抽取状态
python main.py --policy-extraction-status policy_run_xxxxxxxxxxxxxxxx

# 在终端逐项审核 Qwen 候选；每次最多显示 20 条
python main.py --review-policy-run policy_run_xxxxxxxxxxxxxxxx --reviewer 张三 --review-limit 20
```



关联方案：流程分流链路复用此抽取器，但限制来源条款；V2 使用独立断言结构，两者可在同批数据上比较。已知局限：候选验证不能证明事实覆盖完整，也不能代替业务人员判定适用性；LLM 候选待人工审核，规则模式能力受模式边界限制。不得据此直接推断真实办事流程。

未配置 LLM 时使用规则抽取；配置后只采用模型候选。LLM 候选默认进入人工审核：`a` 通过、`r` 拒绝、`c` 修正、`n` 补充、`s` 跳过、`q` 结束。原始候选不覆盖，人工结论写入 `policy_manual_annotations`，保存证据字符位置，可用于后续训练标注。

## 流程分流图谱与事项域配置

**目的与状态：已有实现，规则边界和跨领域质量尚待验证。** 原“报销、差旅、采购流程图谱（首期试运行）”是这条链路的早期范围；现在事项域来自可扩展配置，不代表已完成这些领域的质量验收。

链路是批次条款 → `process/non_process/pending` 分流 → 符合条件的流程条款 → 复用实体关系抽取与人工审核 → 已确认结果的流程投影。输入为结构化批次、事项域选择和抽取运行；输出为分流记录、抽检 CSV、可溯源的节点/边 JSON。

入口：`policy/graph/process.py`（规则）、`process_runner.py`（运行/恢复）、`workflow_graph.py`（投影）、`domain_catalog.py` 与同目录 `domain_catalog.json`（事项域配置）。同目录 JSON 随包迁移，加载仍按模块位置定位。

这条路径先区分流程与非流程条款，再抽取实体关系。每个当前条款保留为 `process`、`non_process` 或 `pending`；只有满足事项域配置、明确办事动作及证据条件的 `process` 条款进入后续抽取。采用规则判定，模糊条款保留为 `pending`；准确率需要人工样本验证。

```powershell
# 1. 对一个已完成的制度批次创建流程条款分流运行；报销试点时显式收窄范围
python main.py --classify-policy-process-batch batch_xxxxxxxxxxxxxxxx --policy-domains reimbursement

# 2. 查看统计，或在中断后恢复失败条款
python main.py --policy-process-status policy_process_xxxxxxxxxxxxxxxx
python main.py --resume-policy-process policy_process_xxxxxxxxxxxxxxxx

# 3. 导出流程分流抽检表，在 Excel 回填“分流正确、正确判定、错分原因、备注”
python main.py --export-policy-process-review policy_process_xxxxxxxxxxxxxxxx --quality-output "D:\policy_quality"

# 4. 只从已确认的流程条款抽取实体和关系；先限制 20 条做小样本验证
python main.py --extract-policy-process-run policy_process_xxxxxxxxxxxxxxxx --limit 20

# 5. 导出只包含流程来源候选的图谱抽检表
python main.py --export-policy-process-graph-review policy_run_xxxxxxxxxxxxxxxx --quality-output "D:\policy_quality"

# 6. 审核完成后导出可被前端或问答服务消费的办事流程图谱 JSON
python main.py --export-policy-workflow-graph policy_run_xxxxxxxxxxxxxxxx --workflow-graph-output "D:\policy_quality\workflow_graph.json"

# 7. 回填后生成报告；报告会包括流程分流正确/错误/待确认数和错分原因
python main.py --report-policy-quality "D:\policy_quality"
```

导出目录中的 `流程条款抽检.csv` 用于判断“这条是否应该进入办事图谱”；`流程图谱抽检.csv` 用于判断“已入图的实体和关系是否有原文证据、是否遗漏”。办事流程图谱不是另一套事实库：它仅投影已通过的实体、关系和人工标注，每个节点和边都包含制度、条款、页码及连续原文证据；也可通过 `GET /policy-workflow-graph/{policy_run_id}` 获取同一份 JSON。总则、目的、解释权、施行日期和一般执行要求会留有 `non_process` 判定记录，不会被删除，也不会进入图谱。`pending` 条款默认不入图，待你在抽检中确认规则边界后再调整。

关联方案：通用抽取不经过此分流；V2 不以 `process/non_process` 为入口。已知局限：明确动作和事项域规则可能漏掉隐含流程，`pending` 默认不入图；已批准候选的投影不等于完整流程推理。`GET /policy-workflow-graph/{policy_run_id}` 已实现 JSON 接口，历史设计中的在线图谱展示页 `/policy-workflow-view/{run_id}` 目前仅有设计，不能当成可用入口。

## V2 断言、事项与派生视图

**目的与状态：已有实现，抽取质量、事项聚合与检索收益尚待验证。** 从全部实质性条款提取带连续原文证据的断言，依照明确的章节或父条款结构聚合事项，再派生流程视图。

链路是实质性条款/样本清单 → 批量模型请求或明确列表规则 → 断言校验与持久化 → 事项聚合及视图 → 抽样审核 → 断言索引同步 → 条款检索增强。输入为批次、条款上下文、模型配置及可选样本 ID；输出为断言记录、事项/流程/公文种类 JSON、复核 CSV 和索引。

| 模块入口 | 职责 |
|---|---|
| `policy/knowledge_v2/logic.py` | 上下文、提示词、断言校验、事项与派生视图 |
| `policy/knowledge_v2/runner.py` | 模型调用、批量回退、运行与恢复 |
| `policy/knowledge_v2/review.py` | 复核导出/导入、人工结论与视图导出 |
| `policy/knowledge_v2/retrieval.py` | 断言索引同步与条款候选增强 |
| `policy/knowledge_v2/sampling.py` | 代表性条款抽样、样本清单读取 |

```powershell
# 创建并执行 V2 抽取，输出 knowledge_v2_run_id
python main.py --extract-policy-knowledge-v2 batch_xxxxxxxxxxxxxxxx

# 查看状态或恢复失败条款
python main.py --policy-knowledge-v2-status knowledge_v2_run_xxxxxxxxxxxxxxxx
python main.py --resume-policy-knowledge-v2 knowledge_v2_run_xxxxxxxxxxxxxxxx

# 导出、回填并导入断言抽样复核表
python main.py --export-policy-knowledge-v2-review knowledge_v2_run_xxxxxxxxxxxxxxxx --knowledge-v2-output "D:\policy_quality\V2断言复核.csv"
python main.py --import-policy-knowledge-v2-review "D:\policy_quality\V2断言复核.csv" --knowledge-v2-reviewer 张三

# 导出事项与流程视图
python main.py --export-policy-knowledge-v2-view knowledge_v2_run_xxxxxxxxxxxxxxxx --knowledge-v2-output "D:\policy_quality\V2事项流程.json"
```

V2 默认将同一制度的 4 条目标条款合并为一次模型请求，并在批量响应失败时自动回退为逐条抽取。可在 `.env` 中通过 `KNOWLEDGE_V2_BATCH_SIZE=4` 调整批大小；本地 7B 模型建议使用 2～6，过大会增加 JSON 截断概率。`KNOWLEDGE_V2_MAX_TOKENS=2400` 控制每次批量响应上限。`KNOWLEDGE_V2_CONTEXT_ANCESTOR_DEPTH=1` 控制提供给模型的上级条款层数：0 不提供，1 仅直接父条款，2 再包含祖父条款；层数越高，提示词越长。新运行创建时会固定该值，修改配置不会影响已有运行的断点续跑。运行期间会持续输出完成数、平均耗时和预计剩余时间。

对“学校公文种类包括：”下的“（一）决议。适用于……”等明确列表，V2 逐项生成用途断言，并保留父条款中的“学校公文种类”及其条款 ID；复核 CSV 会显示“所属类别”和“类别来源条款ID”。这类列表项不调用模型，避免把用途说明误当成办事动作。导出的事项流程 JSON 另含 `document_type_graph`：同一父条款的“学校公文种类 → 包含 → [决议、决定、请示……]”合并为一条关系，每个成员附原文条款证据；“请示 → 适用于 → 向上级单位请求指示、批准”等用途关系仍逐项保留。该汇聚视图从已保存的断言派生，旧运行无需重新抽取即可重新导出。

模型结果只有通过类型、端点、证据条款、连续原文及字符位置校验后才会以 `machine_extracted` 状态参与检索增强；`rejected`、`invalid` 结果不会参与。问答仍以条款向量召回为主，并且最终引用只包含原始条款。V2 断言索引不存在或服务失败时会自动退回原有条款检索。

抽样入口（不调用模型）：

```powershell
python main.py --sample-policy-knowledge-v2 batch_xxxxxxxxxxxxxxxx --knowledge-v2-sample-count 20 --knowledge-v2-output "D:\policy_quality\V2样本.csv"
python main.py --extract-policy-knowledge-v2 batch_xxxxxxxxxxxxxxxx --knowledge-v2-sample-file "D:\policy_quality\V2样本.csv"
```

运行器和审核导入沿用现有索引同步逻辑，人工否决或无效断言不参与增强；`sync_assertion_index_v2` 是内部同步入口，没有新增 CLI 命令。问答最终引用仍来自原始条款，增强失败回退到条款检索。

关联方案：与旧实体关系和流程分流并列保留；不把结构聚合视为已确定的技术路线。已知局限：连续证据及字符位置校验能拒绝部分非法输出，但不能排除遗漏、语义误判和不完整事项；父条款边界会影响聚合，批量模型请求受上下文与输出长度限制。需以同批真实数据人工验收后比较收益。

## 条款分类与抽检复核

**目的与状态：已有实现，多标签质量和抽样代表性尚待验证。** 这是辅助分类链路，按义务、许可、禁止、其他标记实质性条款，不决定流程分流或图谱事实。

链路是条款 → 明确措辞规则 → 无法确定时模型分类 → 分类运行记录 → CSV 人工复核 → 独立人工标签与质量报告。输入为结构化批次与复核文件；输出为多标签记录、复核 CSV 和 JSON 质量报告。入口为 `policy/clause_classification/logic.py`、`runner.py`、`review.py`。

制度结构化完成后，可单独对正文非空的条、款、项执行多标签分类。明确的“应当、必须、可以、不得、严禁”等表述优先使用规则；规则无法确定时调用现有 `LLM_*` 配置的本地模型。模型不可用时任务会保留为失败状态，不会误标为“其他”。

```powershell
python main.py --classify-policy-clauses batch_xxxxxxxxxxxxxxxx
python main.py --policy-clause-classification-status classification_run_xxxxxxxxxxxxxxxx
python main.py --resume-policy-clause-classification classification_run_xxxxxxxxxxxxxxxx

python main.py --export-policy-classification-review classification_run_xxxxxxxxxxxxxxxx --quality-output "D:\policy_quality"
python main.py --import-policy-classification-review "D:\policy_quality\条款分类复核.csv" --classification-reviewer 张三
```

一条条款可同时属于义务、许可和禁止；“其他”不能与这三类同时出现。复核表最多导出 50 条，人工填写“是否正确”，错误时在“修正标签”中用顿号填写，例如 `义务、禁止`。导入后会生成 `条款分类质量报告.json`，统计多标签完全一致率以及三类标签各自的精确率和召回率。人工标签与系统原始结果分开保存，后续使用时人工结论优先。

关联方案：可作为分析和误差定位辅助，与图谱/V2 分别持久化。已知局限：同一条款可能多标签，关键词并不足以覆盖所有法律语义；最多 50 条复核样本的指标不能推及整个制度库。

### 公共条款与图谱抽检

工具只读取数据库并导出 UTF-8 CSV，不更新制度、条款、实体、关系或既有人工审核结论；人工回填后生成报告。

```powershell
# 1. 从已完成的制度 PDF 批次中，为每份制度均匀抽取 10 条，导出条款抽检表和错误字典
python main.py --export-policy-clause-review batch_xxxxxxxxxxxxxxxx --quality-output "D:\policy_quality"

# 可按需调整为每份制度抽检 5 条
python main.py --export-policy-clause-review batch_xxxxxxxxxxxxxxxx --quality-output "D:\policy_quality" --clauses-per-policy 5

# 2. 从已完成的实体关系抽取运行中导出图谱候选抽检表
python main.py --export-policy-graph-review policy_run_xxxxxxxxxxxxxxxx --quality-output "D:\policy_quality"

# 3. 在 Excel 中回填“对/错”、错误类型、缺失内容和备注后，生成 Markdown 与 JSON 报告
python main.py --report-policy-quality "D:\policy_quality"
```

导出目录会包含 `条款抽检.csv`、`图谱抽检.csv`、`错误字典.csv`；报告命令会新增 `质量报告.md` 与 `质量报告.json`。条款表核验边界、层级、文字和页码；图谱表核验实体/关系是否有原文证据。人工填写只保存在 CSV 中，系统原始结果不会被覆盖。

这些导出工具属于 `policy/quality.py`，继续服务多套方案；流程分流和图谱抽检命令见上文。CSV 人工填报只用于报告，不会自动批准数据库中的图谱候选；数据库审核与辅助分类/V2 复核导入是各自独立入口。报告反映已填样本，尚未填报的数据不构成质量验收证据。
