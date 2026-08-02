# Docs Index

本目录按“全局入口留根目录、专题文档进分类目录”整理。

## 当前开发基线

- 分层意图识别 Phase 1-2 已完成：已具备稳定路由契约、业务线与 capability 分类、澄清分支、能力级权限和工具约束。
- Phase 2.5.0 已完成：业务线/capability 单一注册表、一致性校验和 `ROUTER_EXECUTION_MODE` 配置契约已落地。
- Phase 2.5.1 已完成：四个业务线子图骨架可独立编译，legacy/business-line shadow 只记录目标差异，禁止执行业务工具。
- Phase 2.5.2 已完成：案件画像、材料状态/校验、本案证据、外部类案、任务查询和时效查询七个只读能力可按配置进入确定性业务线节点；本案证据与 CPWS 类案已物理分离。
- Phase 2.5.3 已完成实现和隔离 HTTP 冒烟：完整审计、修正重审、回款复盘进入专用图，`audit.drilldown / graph.query` 使用固定 capability 的独立领域 Agent；四条业务线写入轻量 context 命名空间；前三项缺案件上下文时统一澄清，不执行专用图。
- Phase 2.5.4 代码迁移已完成：`case.create / material.upload / task.write` 已接入确定性写命令节点，支持 `write_command` 结构化槽位、服务端身份注入、建案会话回绑、任务归属校验和上传单次摄入。
- Phase 2.5.4 隔离真实写入已验收：`case.create / task.write / material.upload` 已覆盖真实 HTTP、数据库一致性、MinIO、OCR/parse-document、KG 证据链、幂等重放和权限/归属拒绝。
- 案件参与方治理已进入落地：正式 `case_party` 模型、案件 116 角色修正和债务人强主数据解析见 [design/13-案件参与方角色模型与债务人解析治理.md](design/13-案件参与方角色模型与债务人解析治理.md)。
- 真实卷宗 OCR 分段实现已完成；晨光 61 页和正华 19 页 PDF 已通过整卷 OCR 隔离真实 HTTP 验收。`OCR_PDF_SPLIT_ENABLED=false` 全程未改，主动分段真实 HTTP 验收仍待执行，见 [design/14-PDF主动分段OCR与超时恢复方案.md](design/14-PDF主动分段OCR与超时恢复方案.md)。
- Phase 2.5.4 已以 `legacy` 模式部署到正式 ai_hunter，正式幂等上传与 JSON/SSE 缓存冒烟通过；2026-07-30 已启用 `AUTH_ENABLED=true`、关闭开发信任头，并完成数据库 DSN 日志脱敏、上下游代码/环境对齐和 `AUDIT_API_TOKEN` 服务间鉴权冒烟。`business_line` 灰度切流和观察窗口仍待执行。
- 默认仍为 `ROUTER_EXECUTION_MODE=legacy`；详细边界、迁移顺序和回滚方案见 [design/12-分层意图识别与业务线路由方案.md](design/12-分层意图识别与业务线路由方案.md)。

## 根目录

- [ROADMAP.md](ROADMAP.md)：项目路线图、当前基线、优先级和待确认事项。
- [开发规范.md](开发规范.md)：协作开发规范。
- [AI猎手整体方向与双线建设报告.md](AI猎手整体方向与双线建设报告.md)：项目总体方向和双线建设说明。

## 分类目录

- [business/](business/)：客户进度、业务框架、拿包前业务线和运营材料。
- [design/](design/)：功能级设计方案；权限 v2 / 多租户落地见 [design/07-权限网关v2与多租户落地.md](design/07-权限网关v2与多租户落地.md)，LangGraph 升级见 [design/08-LangGraph依赖升级与Agent API迁移.md](design/08-LangGraph依赖升级与Agent API迁移.md)，审计报告段落权限见 [design/09-审计报告段落权限矩阵与配置化方案.md](design/09-审计报告段落权限矩阵与配置化方案.md)，v2-B 案件与会话隔离见 [design/10-权限网关v2-B案件与会话隔离方案.md](design/10-权限网关v2-B案件与会话隔离方案.md)，环境配置统一接入见 [design/11-环境配置统一接入Settings审计方案.md](design/11-环境配置统一接入Settings审计方案.md)，分层意图与业务线路由见 [design/12-分层意图识别与业务线路由方案.md](design/12-分层意图识别与业务线路由方案.md)，案件参与方与债务人解析治理见 [design/13-案件参与方角色模型与债务人解析治理.md](design/13-案件参与方角色模型与债务人解析治理.md)，PDF 主动分段 OCR 见 [design/14-PDF主动分段OCR与超时恢复方案.md](design/14-PDF主动分段OCR与超时恢复方案.md)。
- [architecture/](architecture/)：系统架构、LangGraph、SSE、会话消息架构；当前部署拓扑见 [architecture/统一后端架构.md](architecture/统一后端架构.md)。
- [integration/](integration/)：前端联调、上游 NpaDemo 对齐。
- [deployment/](deployment/)：部署和运维。
- [domain-engine/](domain-engine/)：合并后的 NPA 确定性领域引擎说明与排障资料。
- [reference/npa-domain/](reference/npa-domain/)：原领域模型、提示词和数据库参考资料。
- [knowledge-graph/](knowledge-graph/)：数据追溯、知识图谱、证据链专项。
- [plans/](plans/)：专项治理、改造计划、缺口台账。
- [prompts/](prompts/)：提示词和模型输出规范资料。
