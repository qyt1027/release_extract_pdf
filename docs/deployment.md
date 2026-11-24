# 新环境部署

本部署文件夹包含当前工作区的源代码、网页资源、事项域 JSON、文档、测试、依赖声明和配置模板。它是代码部署包：不包含原环境的 `.env`、虚拟环境、数据库数据、对象存储原件、模型权重或业务导出文件。完整业务使用说明见 [README](../README.md)。

## 1. 准备基础环境

- 安装 Python 3.10 或更新版本。本次代码验证环境为 Windows / Python 3.14；新环境仍需完成依赖安装和验证。
- 准备 PostgreSQL 14 或更新版本，并安装与该数据库版本匹配的 pgvector 扩展。
- 默认配置使用 CPU 嵌入模型。首次下载 `BAAI/bge-m3` 需要网络和足够磁盘空间；离线环境须另行准备完整模型目录，并将 `EMBEDDING_MODEL` 指向它。
- 准备 CloudMinerU、文件分类模型和问答模型的可用接口及凭据。DOCX 和 MIME/HTML 网页归档 DOC 可以本地解析；默认 PDF 和二进制 DOC 使用 CloudMinerU。
- 如需保存原件和图片，准备 MinIO 并将 `MINIO_ENABLED` 改为 `true`。关闭 MinIO 时仍需保留模板中的 MinIO 配置项。

包中不自动安装数据库，也不会操作原环境数据库。下面的数据库初始化命令只应在准备的新数据库中执行。

## 2. 创建虚拟环境并安装依赖

先进入本部署文件夹。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-tested.txt
Copy-Item .env.example .env
```

Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-tested.txt
cp .env.example .env
```

`requirements-tested.txt` 固定本次打包时已安装的直接运行依赖版本，保留 `uvicorn[standard]` 的可选依赖；`requirements.txt` 则保留项目原有版本约束。固定文件并非包含所有传递依赖和操作系统依赖的离线锁文件。需要 GPU 时，按目标设备选择匹配的 PyTorch 安装方式。

需执行开发测试或手动工具时，再安装：

```bash
python -m pip install -r requirements-dev.txt
```

以上开发命令中的 `python` 指虚拟环境解释器；Windows 可替换为 `.venv\Scripts\python.exe`，Linux 可替换为 `.venv/bin/python`。

## 3. 填写配置并初始化新数据库

编辑刚复制的 `.env`，填写 `PG_*`、`CLOUDMINERU_API_KEY`、`LLM_*`、`ANSWER_LLM_*`，需要对象存储时填写 MinIO 的真实配置。不要将配置模板中的示例密码用于正式环境。已有进程环境变量优先于 `.env`，修改后需重新启动服务。

使用 PostgreSQL 的 `psql` 工具连接新数据库服务器。默认数据库名的示例：

```sql
CREATE DATABASE pdf_warehouse;
\connect pdf_warehouse
CREATE EXTENSION IF NOT EXISTS vector;
```

如果数据库已由管理员创建，只在该库启用 pgvector 即可。运行应用的数据库用户需具有当前 schema 的建表、读写和索引权限；应用按需创建业务表。不要直接把旧 `.venv` 复制到另一台机器。

## 4. 验证配置和启动入口

在虚拟环境中执行：

```bash
python -m pip check
python main.py --help
python -m policy_mcp --help
python -c "from core.config import app_config; print('配置加载成功')"
```

这些命令不会处理文件或调用模型。它们验证依赖、配置加载和入口，不代表数据库、模型及解析服务已通过全链路验收。

## 5. 导入文件并使用制度问答

```bash
python main.py --process-dir "你的制度文件目录"
python main.py
```

制度识别、条款结构化和条款索引自动同步。打开 `http://127.0.0.1:8000/policy-qa`，检查答案及原文引用。默认页面初次启动会加载嵌入模型；首次启动可能比之后慢。

跨机器访问时，可使用既有 ASGI 入口并指定监听地址：

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

通过浏览器访问部署机器的实际地址，例如 `http://部署机器IP:8000/policy-qa`。按实际部署设置访问控制、反向代理和 `CORS_ALLOW_ORIGINS`。重建索引、失败恢复和文件重置见 README 最后的维护操作。

需要 MCP 时，设置 `.env` 中的 `POLICY_MCP_TOKEN`，在另一个终端运行 `python -m policy_mcp`。详细地址、认证与 Host 配置见 [MCP 说明](../policy_mcp/README.md)。

## 6. 测试与打包记录

安装开发依赖后执行 `python -B -m unittest discover -s tests`。当前源代码完整回归为 450 项，原有文号括号格式测试仍失败，两个 PostgreSQL/pgvector 测试因未配置隔离测试库而跳过。真实数据库测试只使用 `POLICY_RETRIEVAL_TEST_DATABASE` 指向隔离测试库。

`MANIFEST.json` 保存文件路径和 SHA-256，可检查复制是否完整；`build-info.json` 保存打包时间、Python 版本及运行依赖版本，不包含本机凭据。部署包未迁移已有制度库：如需延续旧数据，需另外准备数据库备份、MinIO 对象及模型缓存，并制定数据迁移步骤。
