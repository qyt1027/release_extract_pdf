# 一个人做制度问答对比

样本已录入 `examples/policy_evaluation_questions.json`，共 14 题、13 组。第 1 和第 11 题是同义问法，归为一组；没有原文定位的问题保持待核实，不算错误答案。原有问题不做身份补写，便于检查系统是否识别歧义。

## 运行

在项目根目录使用已配置数据库、条款索引和问答模型的 Python 环境执行：

```powershell
# 只检查题目，不连接数据库或模型
python -m scripts.compare_policy_answers --output evaluation_results/first --prepare-only

# 先试两题，最多调用问答模型四次
python -m scripts.compare_policy_answers --output evaluation_results/pilot --limit 2 --as-of 2026-10-26

# 完整运行，最多调用问答模型二十八次
python -m scripts.compare_policy_answers --output evaluation_results/full --as-of 2026-10-26
```

请按实际需要修改查询日期。该日期表示询问哪一天适用的制度，不会自动把旧材料判定为当前有效。

基础条款索引须已建立。要评估 V2，还需已经完成 V2 抽取与断言索引同步；脚本不会自动抽取或发布索引。V2 缺失或静默回退时，终端会显示增强模式数量，报告也会标记未形成有效对比，不应据此判定 V2 无用。

每次调用后保存结果；相同命令可接着跑，已经保存的结果（包括失败）不会重复请求。样本、数量或日期变化时请换输出目录。修复服务后要重跑失败结果，也应换目录。不要同时向同一目录运行两个进程；续跑前也不要改变数据、索引或模型配置，否则两次结果可能不可比。

## 评价

打开输出目录的 `report.html`。每题左右顺序随机，有差异的题默认展开，内容相同的题默认折叠。参考文件和条号仅作为人工定位提示，不自动断言命中正确，更不据此计算准确率。

只需选择“左边更好 / 右边更好 / 差不多 / 无法判断”，无需填写原因或标准答案。比较结论、条件和原文依据，不能只比较语言流畅度。页面尽量将评价保存在当前浏览器中，完成后点击“导出评价”，保存下载的 `评价.json`。

先评价，再查看 `results.private.json`。它包含每题的 `left_is_v2` 对照、全部原始响应、耗时及错误详情；可结合评价文件分析哪种方案更好。它包含制度原文，应与本地业务数据一样保管。

两侧使用相同问题、日期和当前配置，分别调用现有问答流程。生成可能有波动，文本不同不等于质量提高；耗时包含首次模型加载影响，不能据此进行严谨性能比较。本轮不计算自动总分，未核实题、失败题、发生降级或 V2 未增强的题不用于效果结论。同义题需按组观察，避免重复统计。

## 住宿制度隔离试验

`scripts/pilot_dormitory_knowledge.py` 只处理《武汉大学学生住宿管理办法》第六条的分配调整职责项、第九条、第十条、第十一条。首次运行生成样本清单和独立运行，已有运行可恢复。抽取结果会写入正常 V2 记录表，但不会发布到正式断言索引。

```powershell
python -m scripts.pilot_dormitory_knowledge extract
# 检查 assertions.json / assertions.csv 后，可针对第十条反馈重抽一次
python -m scripts.pilot_dormitory_knowledge repair
# 核实可用候选后，发布到独立 policy_assertion_pilot_* 表
python -m scripts.pilot_dormitory_knowledge publish
python -m scripts.pilot_dormitory_knowledge compare
```

默认产物在 `evaluation_results/dormitory-pilot`。首轮数据保存在 `assertions.initial.json`，反馈重抽结果在 `assertions.json` 和 `assertions.csv`。盲评报告在 `comparison-exact/report.html`，包含 q01 和 q11 两种问法。正式 MCP 默认不使用这张试验表；只有本地试验问答显式传入 `knowledge_index_name`。

本次运行发现：四条原文首轮生成七条候选，只有两条通过结构和证据校验；第十条反馈重抽后新增一条通过校验的候选。共发布三条机器候选，并未标记为人工审核通过。金额、期限、条件和语义覆盖仍不能据此认定完整。反馈重抽只是明确模型输出格式，未放宽校验，也未手工编造断言。

另外，空表先建立 IVFFlat 加速索引、再插入三条向量时，试验中出现近似搜索零命中、精确搜索三命中的差异。因此该脚本仅移除独立试验表上的 IVFFlat 加速索引，保留向量表和主键，使用精确检索。没有修改正式向量表的加速策略。

问答成功响应中的 `knowledge_status` 可区分 `matched`、`no_matches`、`failed`；失败还记录 `knowledge_error_type`，不向用户输出数据库等异常正文。增强失败仍降级为条款检索。
