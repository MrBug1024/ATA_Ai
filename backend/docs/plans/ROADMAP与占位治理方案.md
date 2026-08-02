# ROADMAP 与占位治理方案

## 背景

当前 `docs/ROADMAP.md` 第 1 节仍保留早期基线描述，已经与代码现状不一致。静态核对后，八段式报告、确定性数值引擎、权威订正、回款看板、AI 复盘、权限网关 v1 等能力已经落地，但文档里仍有旧表述，容易误导后续排期。

同时，代码中仍存在几类“占位 / fallback / 待联调”路径。其中一部分是为了本地测试和缺远程依赖时不中断流程，另一部分属于业务参数或上游接口尚未最终对齐。

## 目标

1. 更新 `ROADMAP.md` 第 1 节，使其准确反映当前代码基线。
2. 将确定性数值引擎和回款提醒的业务参数读取统一收口到 `settings.py` / `.env`，避免在业务计算模块内散落硬编码默认值。
3. 梳理并说明以下占位路径当初为什么存在，后续是否应保留或收紧：
   - 上游 full_context / parseDocument / task 创建失败时的 fallback。
   - LLM 无 key 或 provider 不可用时的报告、复盘、下钻占位。
   - 文档分类 mock 服务。

## 范围

本次只处理文档基线和配置读取收口，不改变外部 API 行为，不删除 fallback，不修改数据库结构，不执行数据库数据修改。

涉及文件：

- `docs/ROADMAP.md`
- `.env.example`
- `.env`
- `ai_hunter/app/settings.py`
- `ai_hunter/app/graph/metrics_engine.py`
- `ai_hunter/app/services/progress_service.py`
- `tests/test_metrics_engine.py`

## 关键决策

1. `metrics_engine.py` 不再持有业务默认参数字典；业务参数由 `Settings` 暴露并从 `.env` 覆盖。
2. JSON 型参数仍使用 JSON 字符串配置，保持现有 `.env.example` 写法兼容。
3. 非法 JSON 配置继续回退到 `Settings` 默认值并记录 warning，避免生产因单个参数格式错误直接中断。
4. fallback 路径本次先保留，只在文档中解释原因；是否改为生产严格失败，需要后续单独确认方案。

## 占位路径原因说明

### 1. 上游接口 fallback

`fetch_full_context`、`parse_document_and_ingest`、`create_tasks` 在上游不可达或返回异常时保留 fallback，主要原因是：

- 本地开发和 pytest 不依赖远程 `10.0.10.2:8080` 服务。
- LangGraph 主流程在缺远程依赖时仍能跑通，便于验证路由、状态合并、报告拼接和持久化链路。
- 上传 / 任务创建这种外部副作用失败时，不让报告主链路直接崩掉。

风险：

- 生产若误用 fallback，会出现“看似成功、实际未入库 / 未建任务”的假完成。

后续建议：

- 增加生产严格模式，例如 `APP_ENV=prod` 或 `STRICT_UPSTREAM_INTEGRATION=true` 时上游失败直接报错。

### 2. LLM 占位

报告段、复盘段和下钻 agent 在无 API key 时输出占位，主要原因是：

- 测试环境和离线开发不能依赖真实模型。
- 八段报告采用并行子 agent 后，单段 provider 异常不应拖垮整份报告。
- 便于在未配置模型时仍能检查图编排和 SSE 分段事件。

风险：

- 生产若 key 缺失，会产出占位文本而非真实报告。

后续建议：

- 在生产环境对核心 LLM key 做启动期或请求期强校验。
- fallback 仅在 `APP_ENV=dev/test` 生效。

### 3. 文档分类 mock

文档分类 mock 是在 `fastserver_api` 类别接口未完整联调前保留的稳定替身，原因是：

- 上传摄入链需要类别目录、案件类别状态和类别校验三类响应。
- 前端和 LangGraph 可先按契约开发，不被上游接口进度阻塞。

风险：

- mock 返回“全部未上传 / 预校验成功”等稳定假数据，不代表真实案件材料状态。

后续建议：

- 真实上游接口稳定后，生产环境强制 `ENABLE_DOC_CATEGORY_API_MOCK=false`。
- 若开启 mock，应在响应或日志中明确标记 mock 来源。

## 验收标准

1. `ROADMAP.md` 第 1 节不再出现已过期的“八段式仍是 A/B 两段硬扛”“文字修正不写库”“回款/权限缺失”等表述。
2. 数值引擎参数通过 `Settings` 读取，测试仍可用 `monkeypatch.setenv` 覆盖。
3. 回款提醒阈值通过 `Settings` 读取。
4. 现有相关单测通过。
