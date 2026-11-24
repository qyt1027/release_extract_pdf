# 文件处理与制度问答

将 PDF、DOC、DOCX 文件解析、分类并存储，识别制度文档后按章、节、条、款、项保留原文结构。问答基于制度条款索引检索证据，返回可回查的制度名称、条款号、页码和原文；回答是初步判断，需要结合适用性和人工审核使用。

## 环境与配置

- Python 3.10+
- PostgreSQL 14+（需安装 pgvector 扩展）
- MinIO

### 安装运行依赖

```powershell
cd ./release_extract_pdf
.\.venv\Scripts\activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

配置从项目根目录 `.env` 读取，已设置的进程环境变量优先。解析、数据库和存储配置与问答模型分别配置；请将示例值替换为可用服务。

### 服务配置

设置以下环境变量连接真实服务：

```powershell
# cloudmineru API
$env:CLOUDMINERU_API_URL = "https://your-host/api/v1"
$env:CLOUDMINERU_API_KEY = "your-key"

# 文件分类及研究抽取 LLM（OpenAI 兼容接口，模型按部署填写）
$env:LLM_API_URL = "https://api.openai.com/v1"
$env:LLM_API_KEY = "sk-xxx"
$env:LLM_MODEL = "gpt-4o"

# 制度问答 LLM（DeepSeek 官方 OpenAI 兼容接口）
$env:ANSWER_LLM_API_URL = "https://api.deepseek.com"
$env:ANSWER_LLM_API_KEY = "your-deepseek-key"
$env:ANSWER_LLM_MODEL = "deepseek-flash"
$env:ANSWER_LLM_THINKING = "false"

# PostgreSQL
$env:PG_HOST = "127.0.0.1"
$env:PG_PORT = "5432"
$env:PG_USER = "postgres"
$env:PG_PASSWORD = "your-password"
$env:PG_DATABASE = "pdf_warehouse"

# MinIO
$env:MINIO_ENDPOINT = "127.0.0.1:9000"
$env:MINIO_ACCESS_KEY = "replace-with-your-minio-credential"
$env:MINIO_SECRET_KEY = "replace-with-your-minio-credential"
$env:MINIO_BUCKET_PDF = "pdfs"
$env:MINIO_BUCKET_IMAGES = "images"

```

PostgreSQL 初始化：
```sql
CREATE DATABASE pdf_warehouse;
\c pdf_warehouse
CREATE EXTENSION vector;
```

嵌入模型通过 `EMBEDDING_MODEL` 配置（默认 `BAAI/bge-m3`），运行设备由 `EMBEDDING_DEVICE` 指定（默认 `cpu`）。首次加载需要已有模型缓存或能够下载模型；数据库需要 pgvector 扩展。解析接口、分类模型与问答模型是不同配置项，详细默认值见 [配置定义](core/config.py)。

## 主线快速开始

### 1. 批量导入文件

```powershell
python main.py --process-dir "D:\policies"
```

制度识别、条款结构化和条款索引同步随文件处理自动执行。数据库和嵌入模型正常时，无需再手动创建索引。记下输出的 `batch_id`，供后续维护使用。

### 2. 启动服务

```powershell
python main.py
# 也可使用既有 ASGI 入口
uvicorn api:app --host 127.0.0.1 --port 8000
```

### 3. 打开制度问答

打开 `http://127.0.0.1:8000/policy-qa` 提问，查看回答引用的原文。API 文档位于 `http://127.0.0.1:8000/docs`。默认 `python main.py --help` 显示这条主线，全部命令通过 `python main.py --help-all` 查看。

索引同步失败时，结构化结果仍会保留，文件处理成功不代表索引一定成功。遇到索引未建立提示或历史数据缺少索引时，按本文最后的维护操作补建。

## 文件处理与制度问答说明

### 单文件与结构化输出

```powershell
python main.py --process "C:\path\to\your.pdf"
```

目录批处理和上传接口支持 `.pdf`、`.doc`、`.docx`。DOCX 使用本地解析器；真正的二进制 DOC 文件交给 CloudMinerU，需使用 `cloudmineru` 后端。部分学校网站下载的 `.doc` 实际是 MIME 封装的 HTML 网页归档，系统会按文件内容识别并在本地提取正文，无需 CloudMinerU；此类文件的章、条、项按提取后的段落解析。

输出示例：
```
正在处理: C:\path\to\your.pdf

处理结果:
  文件 ID:    pdf_abc123def456...
  状态:       done
  总块数:     4
  文本块:     1
  图片:       1
  数据表:     1
  表单:       1
  待审核表:   0
  耗时:       0.85s
```

一份印发通知包含多个《制度名称》，且正文中能确认各制度独立标题及章节起点时，会自动拆成多份制度记录，共享源文件和通知文号。条款层级、效力识别、检索索引及废止关系分别归属各制度；单文件/批次导出和文件重置覆盖全部制度。第一份制度沿用原制度 ID，其余按源文件 ID 和制度标题生成 ID，重复处理相同文件不会新增重复制度。无法确认完整正文边界时保留单制度处理，不按引用书名猜测附件。

已确认多份制度时，提取的源文件 metadata 通过 `policies` 数组返回各制度的 `title`、通知文号和来源页码，通知名称保存为 `notice_title`，源文件层不再用通知名充当制度 `title`。单制度文件仍使用原来的 `title` 字段。

问答服务启动时会预热本地向量模型（含一次编码）和 BM25 索引，预热结束后开始接受请求，避免首个问题承担初始化耗时。预热不调用 DeepSeek，不消耗问答接口 token；某阶段失败会记录警告，后续检索仍可重试。入库、重置后的索引刷新和缓存失效逻辑保持有效；每个服务进程分别预热，启动耗时会相应增加。

批处理按文件 SHA256 去重，临时错误最多自动重试 3 次；状态、错误及解析器和模型版本保存在 PostgreSQL 中。

目录批处理完成后，输入目录会自动生成 `batch_xxx_条款重组结果.json`，保留条款顺序、父条款 ID、章节路径、页码和原文，便于核查。

### 上传与状态查询

**上传 PDF：**
```powershell
curl -X POST http://127.0.0.1:8000/upload -F "file=@C:\path\to\your.pdf"
```

上传成功立即返回 HTTP `202`，而不是等待解析完成：

```json
{"file_id":"pdf_xxx","status":"pending","status_url":"/status/pdf_xxx"}
```

前端应轮询 `status_url` 或 `GET /status/{file_id}` 获取处理进度和最终结果。跨域前端默认可访问；生产环境建议以逗号分隔的域名列表设置 `CORS_ALLOW_ORIGINS`，例如 `https://app.example.com`。

**查询状态：**
```powershell
curl http://127.0.0.1:8000/status/{file_id}
```

### 跨制度条款检索

每条结果包含制度名称、文件名、具体条款号、章节路径、页码和原文证据；问答在这些可回查的条款上生成初步回答。

新完成结构化的制度会自动尝试同步条款索引；已有制度需按批次重建。索引只纳入原文非空的条、款、项，编、章、节标题不作为检索结果。重建按制度记录状态，失败不会改写源条款。

```http
GET /policy-search?q=出差报销需要什么材料&top_k=5
GET /policy-search?q=差旅住宿标准&top_k=10&as_of=2020-06-01
```

若索引尚未建立或没有可检索条款，`/policy-search` 返回 HTTP 409 和中文提示；问题为空返回 422；真实嵌入或数据库不可用返回 503。原有 `/search` 仍是按 `file_id` 检索通用文本块，不能替代此接口。

完成首批索引后，从报销、差旅、采购等真实办事问题中准备至少 20 题，在 [检索验收模板](docs/policy-search-evaluation-template.csv) 中逐题填写期望条款 ID、Top-3/Top-5 是否命中和实际首位结果。模板不包含虚构制度或模拟检索结果；没有达到预期命中率前，不进入基于条款的办事流程或图谱推理阶段。

### 基于制度证据的初步问答

跨制度检索先合并向量和 BM25 候选，再复用问答模型对融合排名靠前的候选进行语义评分，默认最多 30 条，通过 `POLICY_SEMANTIC_RERANK_CANDIDATES` 可调整为 1 至 100 条。评分发生在最终结果截断和证据名额分配之前，不针对特定问法扩展关键词。效力未知的相关条款仍可引用并解释原文，同时提示待核实；明确不适用的条款继续排除。

语义重排默认启用，可通过 `POLICY_SEMANTIC_RERANK_ENABLED=false` 关闭；`POLICY_SEMANTIC_RERANK_TIMEOUT_SECONDS` 默认 45 秒。缓存未命中时增加一次问答模型请求；模型不可用或评分不合法时保留混合召回排序并返回降级警告。只引用适用性待核实条款的回答不能给出确定结论。

重排评分使用有容量上限的进程内缓存：`POLICY_SEMANTIC_RERANK_CACHE_TTL_SECONDS` 默认 600 秒，`POLICY_SEMANTIC_RERANK_CACHE_MAX_ENTRIES` 默认 256，任一设为 0 可禁用缓存。相同问题、日期、模型及有序候选内容复用评分，并合并相同的并发评分请求。缓存只保存评分，不保存回答或制度效力；条款、标题或结构版本变化会产生新缓存键，本进程入库更新、索引重建和重置也会清空缓存。重启后缓存为空，多进程各自缓存，其他进程的数据变更依靠候选内容变化识别。命中缓存仍会召回候选并实时判断效力，最终回答生成仍调用问答模型。

`POST /policy-answer` 会从最多三份制度中选择最多八条相关条款，再使用独立的 `ANSWER_LLM_API_URL`、`ANSWER_LLM_API_KEY` 和 `ANSWER_LLM_MODEL` 配置生成带引用的初步回答。默认接入 DeepSeek 官方 API，不会改变制度抽取和表格分类继续使用的本地 Qwen：

启动 API 服务后，可直接打开 `http://127.0.0.1:8000/policy-qa`。页面提供制度问答、条款检索、制度库与完整结构化条款、服务端历史会话和回答反馈。历史会话依赖当前浏览器的 HttpOnly Cookie；清除 Cookie 后不能恢复旧会话。制度效力为 `unknown` 时，页面显示“待核实”。

面向页面的新接口包括 `GET /api/policies`（`q`、`status`、`limit`、`offset`）、`GET /api/policies/{policy_id}`、`POST/GET /api/conversations`、`GET/PATCH/DELETE /api/conversations/{conversation_id}`、`POST /api/conversations/{conversation_id}/messages` 和 `POST /api/messages/{message_id}/feedback`。问答消息接口使用 JSON 请求 `{ "question": "...", "as_of": "YYYY-MM-DD" }`，反馈使用 `{ "rating": "helpful" }` 或 `unhelpful`。完整设计取舍见 [前端实施说明](docs/policy-frontend-implementation.md)。

```http
POST /policy-answer
Content-Type: application/json

{
  "question": "差旅住宿标准是否适用于校外专家？",
  "as_of": "2026-09-16"
}
```

未提供 `as_of` 时，系统只自动识别问题中的完整日期；模糊历史时间会要求补充具体日期，完全没有时间表达则按请求当天检索。模型只能引用服务端提供的证据编号，响应中的制度原文、条款编号和页码由服务端回填。

该接口提供的是基于现有制度库的初步判断，不是正式审批或最终合规裁决。明确的符合、不符合和有条件符合结论都会标记 `requires_human_review=true`。没有明确适用证据、模型未配置、模型超时或输出无法校验时，接口返回 `undetermined` 和已检索原文，不会编造结论。

### 时间检索与回答边界

制度默认有效（`current`），缺失生效日期不补造；已确认废止标为 `invalid`，未解决的日期或效力冲突保留 `unknown`。未来生效或废止按查询日期判断；已确认废止但日期未知时，当前问答排除，历史查询保留待核实。

归族候选来自已批准的废止关系和规范标题匹配，但废止关系本身不等于版本继承，必须人工确认。条款不单独保存有效期，而是继承所属 `policy_documents` 的 `effective_date` 与 `expiry_date`。

普通检索保持原行为；只有提供 `as_of` 时才应用左闭右开的有效区间过滤。日期未知的制度不会被丢弃，但排在可证明适用的制度之后：

```http
GET /policy-search?q=差旅住宿标准&top_k=10
GET /policy-search?q=差旅住宿标准&top_k=10&as_of=2020-06-01
```

时间检索实时读取 PostgreSQL 中的文档治理字段，无需因日期或制度族调整而重建向量索引。同一制度族在指定日期存在多个适用版本时，接口保留全部结果并返回重叠警告。

## 其他接口与扩展

### 通用文本与表格查询

**语义检索：**
```powershell
curl "http://127.0.0.1:8000/search?q=学生成绩&file_id={file_id}&top_k=5"
```

**表格搜索与展示：**
```powershell
# 搜索表格目录：q 可匹配表格编号、表格名称或原始 PDF 文件名，并附带前 N 行预览
curl "http://127.0.0.1:8000/tables/search?q=X010102&row_limit=100"

# 单独读取一张表，返回 columns + rows + page，可直接渲染为表格
curl "http://127.0.0.1:8000/tables/{file_id}/{block_id}/data?limit=100&offset=0"

# 按列筛选：支持 contains、equals、gte、lte；filters 是 JSON 条件数组
curl.exe -G "http://127.0.0.1:8000/tables/{file_id}/{block_id}/data" `
  --data-urlencode 'filters=[{"column":"项目","operator":"contains","value":"Rcpy"}]'
```

`/search` 始终只返回文本检索结果，表格不会混入其中。新处理的表格会保存编号、名称、来源文件名、页码、列定义和存储位置。名称优先取 `table_caption`，为空时回退到同页相邻的标题文本（如 `X010102 经费数额`）。`/tables/{file_id}/{block_id}/data` 的响应固定包含 `columns`、`rows` 和 `page`，可直接渲染为独立表格；关系表内部行号和页码字段不会暴露。筛选列必须存在于该表目录，条件值使用参数化查询；历史表格需重新处理后才会进入搜索目录。

### MCP 接入

新增 `policy_mcp` 服务，通过现有 HTTP API 提供条款检索、制度目录、全文读取和带引用问答。默认使用 Streamable HTTP，地址为 `http://127.0.0.1:8001/mcp`，HTTP 模式要求配置 `POLICY_MCP_TOKEN`。业务服务和 MCP 服务分别启动，详细配置及客户端示例见 [制度 MCP 使用说明](policy_mcp/README.md)。

### 文档版本治理与废止审核

归族候选来自已批准的废止关系和规范标题匹配，但废止不等于版本继承，必须人工确认。条款继承所属制度的 `effective_date` 与 `expiry_date`，不单独保存有效期。

PDF 条款结构化完成后，系统会从整份文本识别明确生效日期；已有生效日期不会被自动结果覆盖。历史批次无需重新解析 PDF，可执行：

```powershell
python main.py --backfill-policy-governance batch_xxxxxxxxxxxxxxxx
python main.py --policy-governance-status batch_xxxxxxxxxxxxxxxx
python main.py --review-policy-families batch_xxxxxxxxxxxxxxxx --family-reviewer 张三
```

使用 `--process` 或 `--process-dir` 解析制度 PDF 时，条款结构化完成后会自动检查明确的废止措辞。只有识别到候选才会显示来源制度、目标制度、日期、页码和证据，并提示输入 `y` 插入、`n` 跳过或 `q` 结束本次命令的后续询问。插入的候选状态仍为 `pending`，不会自动改变旧制度状态。

如果被废止制度晚于来源制度入库，系统会在目标制度结构化后反向匹配历史未解析候选，并询问是否批准；确认后会回填 `target_policy_id`，同时把目标制度标记为 `invalid` 并写入已识别的失效日期。文号精确唯一匹配优先，标题规范化唯一匹配作为后备；歧义关系不会自动绑定。API 和批次恢复不会等待终端输入。

也可以单独为已有结构化批次补录制度级候选；该命令保持自动插入全部候选，不调用大模型：

```powershell
# 从已结构化批次中提取废止关系候选
python main.py --extract-policy-abolition-relations batch_xxxxxxxxxxxxxxxx

# 查看候选的审核和目标解析状态
python main.py --policy-abolition-relation-status batch_xxxxxxxxxxxxxxxx

# 在终端审核待处理候选；默认最多显示 20 条
python main.py --review-policy-abolition-relations batch_xxxxxxxxxxxxxxxx --abolition-reviewer 张三
```

只有同句中明确、直接连接“废止”谓词与 `《制度名》` 的表述才会产生候选；否定表述、跨句依据引用和“第…条/款/项”等局部废止不会被提取。未能唯一匹配旧制度、或未能识别废止日期的候选，都需要人工确认；终端审核可输入 `a` 通过、`r` 拒绝、`t` 指定目标制度并输入或保留日期后通过、`d` 指定日期并在目标未解析时输入目标制度后通过、`s` 跳过或 `q` 结束。只有审核通过，系统才会把已确认的目标制度标为失效并写入已确认的废止日期；已审核关系不能重复审核。

## 开发与文档导航

| 目录或入口 | 职责 |
|------------|------|
| `main.py` | 命令行及服务启动入口 |
| `api.py` | ASGI 兼容入口，继续支持 `uvicorn api:app` |
| `core/` | 环境配置、共享 Pydantic 模型和项目资源路径 |
| `commands/` | 参数定义与校验、命令分发、终端执行与结果展示 |
| `web/` | FastAPI 应用与 HTTP 接口 |
| `processing/` | 文档主流程、批处理、文件重置、文本/图片/表格处理 |
| `classification/` | 文档分类与三级表格分类 |
| `storage/` | PostgreSQL/pgvector/JSONB、MinIO、文件溯源及表格目录查询 |
| `parsers/` | 解析策略、解析调度及 CloudMinerU 客户端 |
| `metadata/` | 学术文档、制度与表单的内容元数据抽取 |
| `policy/` | 基础条款、检索问答、效力治理、共享存储、质量评估与 `llm.py` 客户端 |
| `policy/graph/` | 实体关系抽取、人工审核、流程分流、投影及事项域资源 |
| `policy/knowledge_v2/` | V2 断言逻辑、运行、审核、检索增强与抽样 |
| `policy/clause_classification/` | 条款多标签分类逻辑、运行与复核 |
| `policy_mcp/` | 独立的制度 MCP 服务 |
| `scripts/` | 显式运行的 MinerU 手动联调工具 |
| `examples/` | 独立运行的图表分析示例 |
| `tests/` | unittest 自动回归测试及既有 MCP 手动联调脚本 |

各模块使用功能目录下的新导入路径，例如 `from processing.pipeline import process_pdf`。
旧根目录业务模块的 import 路径已迁移；三个既有启动方式保持不变。
项目配置统一定位根目录 `.env`；命令行入口继续以项目根目录作为工作目录，处理和导出位置沿用原有规则。

运行服务安装 `requirements.txt`；执行测试及手动工具安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

测试使用 unittest。真实 PostgreSQL/pgvector 集成测试需要显式配置 `POLICY_RETRIEVAL_TEST_DATABASE` 指向隔离测试库；未配置时跳过。

MinerU 手动工具读取根目录 `.env` 中的 `MINERU_API_URL`、`MINERU_API_KEY`、`MINERU_MODEL`。
图表示例读取 `CHART_API_URL`、`CHART_API_KEY`、`CHART_MODEL`。
凭据不写在源码中；这些模块在导入和查看帮助时不会请求外部服务。

```powershell
# 查看参数，无外部请求
python -m scripts.mineru_parse --help
python -m scripts.mineru_probe --help
python -m examples.chart_description --help

# 显式运行时会调用所配置的外部服务
python -m scripts.mineru_parse "D:\policies\sample.pdf"
python -m scripts.mineru_probe
python -m examples.chart_description "D:\images\chart.png" --context "图表说明"
```

研究方案与操作集中在 [制度知识研究说明](docs/research/policy-knowledge.md)，历次设计和实施计划见 [研究历史索引](docs/research/policy-knowledge-history.md)。各套方案保留用于比较，技术路线尚未确定；实现与单元测试不能代替真实制度数据的质量验收。

## 维护操作

### 批次与索引恢复

新导入制度自动尝试创建条款索引；历史数据缺少索引或自动同步失败时，先恢复数据库、嵌入模型等依赖，再使用文件批次 ID 补建：

```powershell
python main.py --rebuild-policy-clause-index batch_xxxxxxxxxxxxxxxx
```

该命令会重新计算并替换该批次制度的条款向量，不必在每次正常导入后重复执行。它返回独立的索引运行 ID；只有已经创建了索引运行，才使用下面的索引状态和恢复命令。

```powershell
python main.py --batch-status batch_xxxxxxxxxxxxxxxx
python main.py --resume-batch batch_xxxxxxxxxxxxxxxx
python main.py --policy-clause-index-status policy_index_xxxxxxxxxxxxxxxx
python main.py --resume-policy-clause-index policy_index_xxxxxxxxxxxxxxxx
```

批次恢复只处理未完成或到期重试文件；条款索引恢复只重试失败制度。索引运行 ID 由索引重建命令返回，不与文件批次 ID 混用。失败不会改写源条款。

### 清理目录内已入库文件并重新解析

批次状态 `running` 表示存在运行中的文件；`retry_wait` 表示尚有文件等待重试，当前命令可能已经返回。等待重试的文件不会在后台自动执行，使用 `python main.py --resume-batch BATCH_ID` 续跑；`--batch-status BATCH_ID` 会列出未完成文件及原因。遇到其他任务占用时会先等待，进程中断遗留的文件状态默认在 30 分钟保护期后可由续跑接管。

批处理按文件内容哈希复用已完成结果，复制文件或改名不会触发重跑。需要重新解析时，先预览再重置：

```powershell
# 预览目录及子目录中匹配的入库文件、共享文件和废止关系影响范围
python main.py --reset-folder "D:\policies\sample"

# 确认清理；若其他目录的历史批次也复用了同一文件，显式允许共享结果同步失效
python main.py --reset-folder "D:\policies\sample" --confirm-reset-folder --allow-shared-reset

# 创建新批次重新解析
python main.py --process-dir "D:\policies\sample"
```

如果重置被旧的 `processing/running` 占用阻止，先核实原处理进程已退出，再追加 `--release-stale-reset`。此参数只在确认重置时释放超过批处理保护期（默认 30 分钟）的旧占用，包括文件处理及条款分类、抽取、V2 知识抽取和索引任务。条款任务会锁定并检查整个共享运行的启动、结束和心跳时间；任一近期活动或无法核实时间的活动任务都会阻止释放。遗留运行标为失败，清理失败时释放状态与数据库清理一起回滚。预览不修改状态。目录扫描及历史批次匹配均忽略 Office `~$` 临时锁文件。

如果旧代码抽取不准，需要清除制度元数据后重新入库，追加 `--purge-imported-data`：除常规结果、真实条款问答索引和断言索引外，还清除标题、文号、日期、效力、归族与当前抽取指针，删除所有指向或源自目标制度的废止关系、归族候选，以及本次涉及且无剩余任务的运行。删除废止关系可能改变其他制度的效力，依据剩余关系重算。跨制度共享运行仍有任务时保留；源文件、MinIO 原件、文件/制度稳定 ID 占位和历史 PDF 批次、问答历史、已导出文件不删除。此模式清理入库抽取数据，不是删除历史备份。

```bash
python main.py --reset-folder "D:\policies\sample" --purge-imported-data
python main.py --reset-folder "D:\policies\sample" --confirm-reset-folder --allow-shared-reset --release-stale-reset --purge-imported-data
```

`--purge-imported-data` 已包含强制重置，在 Ctrl+C 后也不受旧任务状态或时间限制，无需另外添加参数：

```bash
python main.py --reset-folder "D:\policies\sample" --confirm-reset-folder --allow-shared-reset --purge-imported-data
```

彻底清理忽略文件处理、结构化及条款任务的活动状态，包括近期心跳和无法核实的时间；将关联 PDF 批任务释放为待处理，将关联共享条款运行及其活动任务标为失败，再清理目标文件产物。共享运行中目录外的原始条款不删除，但运行会中止。仍保留共享文件授权、目录范围、读取上限及事务回滚检查；不加 `--confirm-reset-folder` 仍仅预览。此操作不终止后台进程，执行前需停止旧处理进程，避免清理后继续写回。与 `--release-stale-reset` 同用时以强制模式为准。原有 `--force-reset-folder` 保留兼容，彻底清理不需要它。

重置会清理条款、向量、表格、分类、知识抽取及相关审核产物，保留源文件、MinIO 对象、文件和制度主记录，文件状态改为待处理。原批次保留为历史记录，不会自动重跑；已有导出的 JSON 文件也不会自动删除。

重置废止来源制度 A 时，会清理 A 发起的废止关系（含人工审核结论）及引用这些关系的归族候选。若目标制度 B 仍有其他已批准废止关系，则保留失效状态并按剩余关系更新日期；否则仅清除与删除关系相符的失效日期，没有其他失效日期或待处理冲突时恢复为默认有效。独立的人工失效日期继续保留，已确认的制度族归属保留。

重置被废止制度 B 时，保留其他制度发起的入向废止关系及 B 的效力状态。其他 PDF 的条款和向量不会因效力重算被删除。

单文件 `--reset-file FILE_ID` 使用常规关联清理和效力重算逻辑。近期 PDF 批任务占用、制度结构化以及近期或无法核实过期的条款任务禁止重置。目录内任一文件清理失败会回滚整个目录的数据库变更；`--allow-shared-reset`、`--release-stale-reset` 和 `--purge-imported-data` 仅允许与 `--reset-folder` 配合使用。

```powershell
# 单文件常规重置，然后按原路径重新处理
python main.py --reset-file pdf_xxxxxxxxxxxxxxxx
python main.py --process "D:\policies\sample.pdf"
```
