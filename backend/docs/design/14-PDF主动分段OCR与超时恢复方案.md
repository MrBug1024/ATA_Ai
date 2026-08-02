# PDF 主动分段 OCR 与超时恢复方案

> 状态：分段实现已完成；两份真实 PDF 整卷 OCR 全链路已在隔离服务验收，主动分段真实 HTTP 验收和生产观察窗口待执行
> 日期：2026-07-15

## 1. 背景与问题

当前上传摄入会把整份 PDF 作为一个 `/api/parse/sync` 请求发送给远程 OCR。
真实 P0 验收暴露出该方式无法稳定处理生产卷宗：

- 晨光煤矿第一次债权人会议资料：61 页、约 37 MB，604.87 秒后触发本地 600 秒读取超时。
- 正华公司第一期现金清偿公告二：19 页、约 13 MB，远程返回 `HTTP 500` 和 `The operation timed out.`。
- 晨光第一页真实扫描页探针：541 KB，13.05 秒成功，证明远程服务和鉴权可用，问题集中在整卷处理容量。

因此不能仅调大本地超时。系统需要在请求远程 OCR 前主动识别大文件并分段，同时为阈值以下文件保留超时后安全降级分段的能力。

## 2. 目标与边界

目标：

- 根据 PDF 文件大小或页数主动分段，任一条件满足即进入分段路径。
- 每段同时受最大页数和序列化后字节数约束。
- 分段结果按原始页序稳定合并，恢复全卷 `page_idx`、页面和 bbox 引用关系。
- 单段失败仅重试该段；超过重试上限后整批安全失败，并在错误中保留页码范围。
- 全部远程 OCR 请求共享 `OCR_MAX_PARALLEL` 总并发上限。
- 保持现有上传、MinIO、parse-document、KG 和 Swagger 请求契约不变。

本阶段不修改远程 OCR 服务，不新增 DDL，不改变 `MAX_UPLOAD_FILE_MB` 上传拒绝语义。

## 3. Settings 契约

| 环境变量 | 默认值 | 语义 |
| --- | ---: | --- |
| `OCR_TABLE_ENABLE_PDF` | `true` | PDF OCR 是否启用表格结构识别 |
| `OCR_TABLE_ENABLE_IMAGE` | `false` | 单张图片 OCR 是否启用表格结构识别 |
| `OCR_AUTO_ROTATE_PDF` | `false` | PDF OCR 是否自动检测并纠正页面方向 |
| `OCR_AUTO_ROTATE_IMAGE` | `true` | 单张图片 OCR 是否自动检测并纠正页面方向 |
| `OCR_PDF_SPLIT_ENABLED` | `false` | 是否启用主动分段和超时降级分段；默认关闭，按环境显式开启 |
| `OCR_PDF_SPLIT_THRESHOLD_MB` | `10` | 文件达到该大小时主动分段 |
| `OCR_PDF_SPLIT_THRESHOLD_PAGES` | `10` | 文件达到该页数时主动分段 |
| `OCR_PDF_CHUNK_MAX_MB` | `8` | 单个远程 OCR 分段序列化后的最大体积 |
| `OCR_PDF_CHUNK_MAX_PAGES` | `1` | 单个远程 OCR 分段最大页数；真实 5 页和 2 页分段均触发 300 秒读取超时 |
| `OCR_PDF_CHUNK_CONCURRENCY` | `1` | 单份 PDF 内分段并发上限；默认串行以保护当前远端容量 |
| `OCR_PDF_CHUNK_TIMEOUT_SECONDS` | `300` | 单段远程请求超时 |
| `OCR_PDF_CHUNK_MAX_RETRIES` | `2` | 单段首次失败后的最大重试次数 |

`MAX_UPLOAD_FILE_MB=500` 继续表示单文件上传拒绝上限；它与 OCR 分段阈值相互独立。
恢复生产 P0 分段验收时，需在目标环境显式设置 `OCR_PDF_SPLIT_ENABLED=true` 并重启 ai_hunter。

## 4. 处理流程

```text
读取 PDF 字节和页数
  -> size >= threshold_mb OR pages >= threshold_pages
       -> 按 max_pages 组成候选段
       -> 序列化后再按 max_mb 收紧
       -> 有界并发调用远程 OCR
  -> 未达到阈值
       -> 整卷 OCR
       -> ReadTimeout / 远程 operation timed out
       -> 降级到相同分段流程一次
  -> 按原始 page_start 排序
  -> 合并 markdown/text、pages、blocks
  -> page_idx 加上分段起始页偏移
  -> 进入 parse-document 与 KG
```

单页本身超过 `OCR_PDF_CHUNK_MAX_MB` 时不得无限拆分，返回带文件名和原始页码的 `OCR_SINGLE_PAGE_TOO_LARGE`。

## 5. 合并契约

- 文本按分段起始页升序拼接，段间保留空行。
- `pages` 保持原始页顺序；若远程页对象包含 `page_idx`，统一偏移到全卷零基页码。
- `blocks[*].page_idx` 必须增加分段起始页偏移。
- `page_width/page_height` 保留首个有效页面尺寸，逐页尺寸仍以 `pages` 内字段为准。
- `raw_response` 只保留必要的分段摘要，不复制全部响应造成状态膨胀。
- 合并结果继续满足现有 `build_page_records_from_layout()` 和引用链契约。

## 6. 并发、重试与失败

- 单 PDF 并发取 `min(OCR_PDF_CHUNK_CONCURRENCY, OCR_MAX_PARALLEL, 分段数)`。
- 默认单并发按页顺序处理；任一页最终失败后立即停止，不继续提交后续页。
- 所有整卷和分段请求还需经过进程级远程 OCR 信号量，总并发不得超过 `OCR_MAX_PARALLEL`。
- 整卷 `ReadTimeout` 触发一次分段降级；单段 `ReadTimeout` 不立即自动重试，避免远端仍在执行时堆积重复任务。
- 连接级错误、远程 5xx 和包含 `operation timed out` 的明确失败结果允许按配置重试。
- 4xx 鉴权、参数错误和无效文件不重试。
- 单段最终失败时错误必须包含 `pages=<start>-<end>` 和尝试次数，上传批次保持 `failed/ocr_running`，可由现有 retry 接口重建 MinIO 文件后重试。

## 7. 验收

单元测试至少覆盖：

- 大小阈值和页数阈值任一命中即分段。
- 小文件正常走整卷路径；整卷超时后只降级分段一次。
- 单段同时满足最大页数和最大字节数。
- 并发结果乱序返回时仍按原始页序合并。
- `blocks.page_idx` 和 `pages.page_idx` 正确偏移。
- 单段可重试错误、不可重试错误和超大单页错误。
- 分段关闭时完全回到原整卷行为。

真实 HTTP 验收：

1. 案件 116 / 债务人 76 上传晨光 61 页 PDF。
2. 案件 118 / 债务人 78 上传正华 19 页 PDF。
3. 两批均达到 `completed`，且 MinIO、source file/page/chunk/category、parse-document 记录和 KG 持久化检查通过。
4. 错误债务人仍返回 `409`，不得进入 MinIO/OCR。

## 8. 回滚

将 `OCR_PDF_SPLIT_ENABLED=false` 并重启 ai_hunter，即恢复整卷 OCR 行为；无需回滚 DDL。已生成的 MinIO 原文件、source file/page/chunk 和 KG 数据不自动删除，任何数据清理必须单独评审和授权。

## 9. 2026-07-15 挂起记录

- 正华单页探针成功，返回 1 页、10 个 blocks，证明远程入口和鉴权可用。
- 正华 19 页真实 retry 串行完成前 10 页；第 4 页首次 500 后页内重试成功。
- 第 11 页连续 3 次收到远程 `HTTP 500 / Unable to connect`，批次安全失败在 `ocr_running`，未进入 parse-document。
- 晨光和正华批次均保留 MinIO 原文件及失败状态，不执行清理，后续可从 retry 接口恢复。
- 2026-07-15 用户决定挂起本项，先调整远程 OCR 服务；恢复条件是单页服务稳定后重新执行两批完整 HTTP 验收。

## 10. 2026-07-19 自动化收口记录

- OCR、上传路由、Settings、ingest 和 chunk 持久化聚焦回归：`40 passed`。
- 完整 pytest：`324 passed, 13 warnings`；warnings 均为既有 LangGraph `create_react_agent` 弃用提示。
- `py_compile`、`git diff --check` 通过；当前 `.env` 和 Settings 代码默认值均为 `OCR_PDF_SPLIT_ENABLED=false`。
- 本记录只代表实现与自动化回归完成。远程 OCR 未恢复探测，ai_hunter 未重启，晨光/正华生产 HTTP 上传验收仍保持挂起状态。

## 11. 2026-07-29 整卷 OCR 全链路验收

- 远程 OCR 单页探针在 `3.45s` 内成功，返回 1 页和 3 个 block，确认服务入口、鉴权和基本处理恢复。
- 晨光 61 页、约 37 MB PDF 使用批次 `phase254-pdf-case116-20260729-1`：OCR 约 `261s`，总耗时约 `361s`，最终 `completed`，持久化 61 页、625 个 chunk 和 11 条 parse-document 记录。
- 正华 19 页、约 13 MB PDF 使用批次 `phase254-pdf-case118-20260729-1`：OCR 约 `106s`，总耗时约 `130s`，最终 `completed`，持久化 19 页、36 个 chunk 和 4 条 parse-document 记录。
- 正华首轮 KG 模型输出了空 `evidence_chunk_ids`。增加证据质量门禁后，新批次 `phase254-pdf-case118-evidence-20260729-2` 生成 8 条 claim 和 12 条带 chunk、页码、原文的 `kg_evidence_link`。
- 本次全程保持 `OCR_PDF_SPLIT_ENABLED=false`，验证的是远程 OCR 调整后的整卷路径。主动分段路径仍只有自动化回归证据，上线前需在隔离进程显式开启后重跑真实 PDF，不得由本次结果推导为分段生产验收已通过。
- 正式 `.env`、正式 `8080/8081` 和生产 `legacy` 模式未修改或重启；未执行 DDL。生产部署时仍可保持 `OCR_PDF_SPLIT_ENABLED=false` 回滚到本次已验收的整卷路径。
