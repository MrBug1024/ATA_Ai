# ATA_AI 年审业务实现与验收说明

版本：2026-08-04  
项目：`E:\实验室\ATA_AI`  
业务域：`annual_audit`

## 1. 交付结论

ATA_AI 已完成一次真实的年审闭环验收，原不良资产项目目录未修改，年审运行时不会读取原项目的会话、文件、知识图谱或业务数据。

本次验收实际跑通：

```text
上传 Excel
  -> MinIO 原始文件
  -> PostgreSQL source_file/source_page/source_chunk
  -> 年审 MySQL 结构化导入
  -> 证据锚点绑定
  -> 年审分析与发现
  -> 知识图谱摘要
  -> 下钻结果与引用
  -> 底稿、年度审计报告
  -> MinIO 产物
  -> 自动复核任务
```

当前自动化测试结果：`140 passed, 5 warnings`。警告来自 LangGraph `create_react_agent` 的上游弃用提示和 Starlette/httpx 兼容提示，不影响本次年审验收。

## 2. 已实现的公共能力

公共能力已经以项目无关的方式补入 ATA_AI，年审只通过业务适配层使用：

| 能力 | 当前实现 | 隔离要求 |
|---|---|---|
| 运行时业务域、项目上下文 | `backend/ai_hunter/platform_core.py` | 所有 Redis、MinIO、向量检索调用携带 `annual_audit` 和项目范围 |
| LangGraph 编排、checkpoint、降级 | `backend/ai_hunter/app/graph/` | thread、heavy payload 使用年审域 namespace |
| 文件和证据链 | `source_file/source_page/source_chunk` + 年审源定位字段 | 结构化行绑定真实源文件、页面/表格定位和 chunk，不再生成 `annual:*` 假 chunk ID |
| Excel 证据定位 | `locator_kind=sheet_row`、sheet、row、cell 信息 | 前端按表格证据展示行号/单元格，不再把 Excel 伪装成文本页 |
| 知识图谱 | `build_knowledge_graph_graph.py`、`kg_service.py` | 图谱摘要和实体关系只从当前年审项目数据生成 |
| 关键词/向量检索 | `backend/ai_hunter/app/services/vector_search.py` | PostgreSQL 检索强制按当前 project_id 过滤；embedding 维度校验由公共层负责 |
| 下钻工具注册 | `backend/ai_hunter/annual_audit/tools.py`、`app/graph/capabilities.py` | 只注册年审工具，不能看到不良资产工具和数据 |
| 底稿与报告产物 | `backend/ai_hunter/annual_audit/artifact_service.py` | 生成 Markdown、DOCX、XLSX 报告和 XLSX 底稿，产物写入年审 MinIO bucket |
| 任务和审计痕迹 | `annual_task`、trace、citation coverage | 报告生成后自动创建待复核任务，引用覆盖率可验收 |

公共架构边界详见：[公共基础架构说明](../platform/public-foundation-architecture.md)。

## 3. 数据与运行时隔离

当前 ATA_AI 年审使用以下专属目标：

```text
MySQL          ata_ai
PostgreSQL     ata_agent_platform（当前本地平台库）
Redis          年审 namespace：ata:<environment>:annual_audit:...
MinIO raw      ata-annual-raw
MinIO derived  ata-annual-derived
MinIO artifact ata-annual-artifacts
```

隔离规则已经落实：

1. `Settings` 只加载 ATA_AI 当前 `backend/.env`，不会回退读取原不良资产 `.env`。
2. MySQL 拒绝 `ata_agent`、`ai_hunter`、`npa`、`npa_lang`、`cpwsdata`、`bad_assets` 等旧业务库名。
3. PostgreSQL 年审平台契约不创建旧业务 `public.cases` 表；当前平台库只承载公共会话、checkpoint、文件、证据和图谱能力。
4. Redis key、MinIO object key、向量检索均携带业务域和项目范围。
5. 年审前端图谱分类和证据展示不显示 NPA 业务实体标签。
6. 原不良资产项目只作为能力参考，未被 ATA_AI 运行时导入或复用其业务数据。

## 4. 真实端到端验收结果

验收脚本：[`run_acceptance_flow.py`](../../backend/ai_hunter/annual_audit/scripts/run_acceptance_flow.py)

最近一次真实验收生成了独立年审项目 `case_id=9`，结果如下：

| 验收项 | 结果 |
|---|---:|
| 识别数据集 | 4 类：科目余额表、序时账、应收账款明细、银行流水 |
| 结构化导入 | 10 行，跳过 0，错误 0 |
| 证据绑定 | 10/10 行绑定真实 source_file，10/10 行绑定 source_chunk |
| 分析发现 | 8 项 |
| 证据数 | 11 条 |
| 引用覆盖率 | 8/8，100% |
| 报告版本 | v1 |
| 底稿 | 3 份 XLSX |
| 报告产物 | Markdown、DOCX、XLSX 共 3 份 |
| 全部 MinIO 产物 | 6 份，状态 `published` |
| 自动复核任务 | 创建 8 项，跳过 0，失败 0 |

产物包含：

```text
annual-audit-9-v1.md
annual-audit-9-v1.docx
annual-audit-9-v1.xlsx
workpaper-C1-2-9-v1.xlsx
workpaper-C5-2-9-v1.xlsx
workpaper-F1-2-9-v1.xlsx
```

## 5. 如何重新验收

在 PowerShell 中执行：

```powershell
Set-Location E:\实验室\ATA_AI\backend
$py = 'D:\anaconda3\envs\npaLang_env\python.exe'

# 迁移年审 MySQL 和平台 PostgreSQL
& $py -B -m ai_hunter.annual_audit.storage.migrate

# 执行真实完整年审闭环，脚本会创建独立测试项目和测试文件
& $py -B -m ai_hunter.annual_audit.scripts.run_acceptance_flow

# 执行自动化测试
& $py -B -m pytest -q -p no:cacheprovider

# 启动 API
uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8080
```

验收脚本必须至少满足：

```text
intent=full_audit
annual_evidence_binding_summary.unbound_count=0
final_report_ref_scoped=true
artifact_status=published
citation_coverage.coverage_ratio=1.0
task_result.tasks_failed=0
```

## 6. 当前仍需补充的外部配置

### 6.1 Redis 认证密码

当前线上 Redis 认证配置已经生效，隔离检查 `redis=ok`。后续如果更换线上 Redis，只需要填写 ATA_AI 自己的 `ANNUAL_REDIS_PASSWORD` 或 `REDIS_PASSWORD`，不要复制原不良资产 Redis 密码；`verify_local_stack.py` 会在认证缺失时给出明确提示。

### 6.2 语义向量模型

当前 PostgreSQL 已启用 pgvector，关键词检索和已有 chunk 检索可用。若要启用真正的语义向量召回，需要在 ATA_AI `.env` 中填写独立的：

```text
ANNUAL_EMBEDDING_MODEL=
ANNUAL_EMBEDDING_DIMENSION=
ANNUAL_VECTOR_COLLECTION_PREFIX=
```

模型、维度和 collection 必须保持一致，不能使用原不良资产知识库的 collection 或 embedding 配置。

### 6.3 正式审计模板与知识库

当前报告产物链路已跑通，但正式生产前仍需由审计人员提供并审核：

- 年审报告 DOCX/PDF 模板及版本号；
- C1-C8 章节字段映射和必填项；
- 科目余额、序时账、应收、银行、凭证等材料清单；
- 会计准则、审计准则、审计程序和客户模板知识库；
- 每条规则的生效日期、适用范围、引用要求和人工复核责任人。

这些内容应进入年审自己的知识库和模板目录，不得接入原不良资产 CPWS、法律知识库或 NPA collection。

## 7. 最终验收标准

正式上线前，至少逐项通过：

1. 新用户、新项目、新会话中看不到原不良资产对话和文件。
2. 年审数据只能在 `ata_ai`、年审 PostgreSQL project scope、年审 Redis namespace 和年审 MinIO buckets 中读写。
3. PDF、图片、文本、Excel 的证据索引返回正确的预览类型和定位信息。
4. 图谱节点、关系、断言均能回溯到当前项目证据，不能只有无来源节点。
5. 完整年审、重新审计、下钻、证据查询、底稿生成、报告生成和复核任务均可执行。
6. 报告中的每个结论都有证据或明确标记为“需要人工补充”，不能把知识库规则当成客户事实。
7. 产物可从 MinIO 下载，版本号、项目号、报告号和引用清晰可追溯。
8. 更换线上环境或补齐 embedding 模型、正式模板和年审知识库后，再执行一次全量验收并留存结果。
