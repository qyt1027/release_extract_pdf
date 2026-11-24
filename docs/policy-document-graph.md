# 文件级制度关系图谱

文件作为节点，当前活动结构版本的原文书名引用以及已有废止审核记录作为关系来源。不调用大模型，不建设新的图数据库，不修改文件效力。

## 关系含义

| 类型 | 含义 | 状态 |
| --- | --- | --- |
| cites | 依据、按照、参照等明确引入的书名 | 机器识别，仍须核对 |
| mentions | 原文出现书名，但不足以认定为引用依据 | 普通提及，不用于效力推导 |
| abolishes | 原文明示整份文件废止 | 保留既有审核结论；新识别的候选为 pending |

部分条款废止不会表示成整份文件废止。拒绝废止关系后，书名在原文出现这一事实仍可保留为普通提及。引用提取是保守规则法，不保证识别所有表达，也不推断隐含引用、修订或冲突。

每条边保存来源制度 ID、当前结构版本、条款 ID、连续原文证据和页码。相同来源/目标/类型/审核状态的边合并多个原文出处。

## 版本与未解析目标

有明确文号时按标题和文号匹配；明确提及印发年份时进一步限制目标版本。缺少文号且有多个同名文件时不自动选版本。未匹配目标和歧义目标都保留独立节点，展示是否未入库或存在多个候选。

本功能仅投影数据，不回写已有废止审核与效力字段。A 引用 B、B 废止 C，只表示两条关联，不得推导 A 废止 C，也不得推导 A 随 B 自动失效。

## 导出与浏览

```powershell
# 从当前数据库只读生成全库 JSON 和离线页面
python -m scripts.export_document_graph

# 可指定目录，或仅导出某份制度的有界邻域
python -m scripts.export_document_graph --output outputs/selected-graph --policy-id policy_xxx --depth 2
```

默认页面为 `outputs/document-graph/index.html`，数据为相邻的 `graph.json`。可搜索文件、切换普通提及和待审核废止、点击关联文件继续浏览、点击边或关系列表查看原文。图中最多展示八条直接关系以保持可读，完整直接关系保留在下方列表。离线文件是导出时快照，数据更新后需重新导出。

## API 与 MCP

新增业务 API：

```text
GET /api/policies/{policy_id}/relations?depth=1&direction=both&limit=100
```

`depth` 为 1—3；`direction` 为 `both`、`incoming`、`outgoing`；`limit` 为最多返回的关系数，范围 1—200。超出边数上限会返回 `truncated=true`。无关系的文件返回本节点和空边，不冒充缺失文件。实际数据超过当前加载上限时明确报服务不可用，不静默漏掉数据。

新增只读 MCP 工具 `get_policy_relations`，参数同上。先通过目录或检索获得 `policy_id`。工具只提供关联证据，不自动更改正式问答的候选排序或生成提示。重启业务 API 和 MCP 后生效。

## 测试

```powershell
python -m unittest tests.test_policy_document_graph tests.test_policy_document_graph_api tests.test_policy_mcp tests.test_policy_abolition_versions tests.test_policy_temporal tests.test_policy_answering tests.test_project_layout
```

首版覆盖文号与印发年份、版本歧义、未入库目标、否定引用、表单提及、部分废止、审核状态、旧结构排除、边界遍历、HTML 转义、API/MCP 参数及错误处理。代码审查发现的错误版本绑定和跨分句引用误判均纳入反例测试。
