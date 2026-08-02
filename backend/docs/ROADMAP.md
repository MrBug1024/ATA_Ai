# AI Hunter 工程路线图（对齐基线）

> 本文档是 2026-06-11 客户项目沟通会（见《不良资产AI审计系统项目沟通会议纪要-2026.06.11》）之后，
> 双方确认的**工程化决策与优先级基线**。仅覆盖**本代码库（AI Hunter LangGraph 编排服务）**能落地的部分；
> 机房/算力/满血模型部署、人员组织与考核、数据采集合规等业务/硬件事项不在本文范畴。
>
> 状态：决策已对齐，**每一项的详细技术/设计方案后续单独产出**。本文只定方向、边界、优先级与待确认项。

---

## 1. 当前系统基线（事实）

| 能力 | 现状 | 关键位置 |
|---|---|---|
| 八段式报告 | ✅ **已重构为 8 段专家子 agent**：`fetch_full_context → compute_metrics → 8 段并行扇出 → reconcile`。每段使用独立 prompt 与数据切片，支持分段 SSE 事件、有界并发、provider 失败回退；一致性 critic 仍后置 | [full_audit_graph.py](../ai_hunter/app/subgraphs/full_audit_graph.py) / [generate_sections.py](../ai_hunter/app/graph/nodes/generate_sections.py) / [report_s1.txt](../ai_hunter/app/prompts/report_s1.txt) |
| 报告链路 | ✅ `fetch_full_context → compute_metrics → generate_section_1..8 → reconcile_report_and_extract_tasks`。`report_part_a/b` 旧节点和 prompt 仍保留作兼容/测试，不再是主图报告生成路径 | [full_audit_graph.py](../ai_hunter/app/subgraphs/full_audit_graph.py) / [compute_metrics.py](../ai_hunter/app/graph/nodes/compute_metrics.py) / [reconcile_report.py](../ai_hunter/app/graph/nodes/reconcile_report.py) |
| 实时修正（上传新材料） | ✅ 写库：ingest→`reconcile_graph_delta` 把旧 claim `mark_claims_superseded`、插入新 claim/entity/relation + 对账台账。**权威、跨会话生效** | [reconcile_graph_delta.py](../ai_hunter/app/graph/nodes/reconcile_graph_delta.py) |
| 实时修正（文字指令） | ✅ 已升级为**权威订正 + 可追溯**：`extract_correction` 写入 `case_correction`，`fetch_full_context` 加载期应用，跨会话/跨人生效；支持同标的自动 supersede 与 list/add/revoke 管理接口 | [corrections.py](../ai_hunter/app/graph/nodes/corrections.py) / [correction_service.py](../ai_hunter/app/services/correction_service.py) / [routes_corrections.py](../ai_hunter/app/api/routes_corrections.py) |
| 估值/NPV/回收率 | ✅ 已有确定性数值引擎：本息口径回收率、去毒总账、NPV/T1-T3、归零、数据质量和交叉校验均由代码计算；业务参数通过 `METRICS_*` 配置读取并回显到 `computed_metrics.params` | [metrics_engine.py](../ai_hunter/app/graph/metrics_engine.py) / [compute_metrics.py](../ai_hunter/app/graph/nodes/compute_metrics.py) |
| 知识图谱 / 证据回源 | ✅ 实体/关系/子图/证据抽屉/演进等接口已完善（issues #1~#10 已修复关闭） | [kg_service.py](../ai_hunter/app/services/kg_service.py) / [routes_graph.py](../ai_hunter/app/api/routes_graph.py) |
| 资金流 / 白手套 / 关系穿透 | ✅ 工具已注册（18 个工具） | [tools/registry.py](../ai_hunter/app/tools/registry.py) |
| 裁判文书数据 | ✅ `query_wenshu_knowledge` 直连 `cpwsdata` | — |
| SOP 督办任务 | ✅ 第 7 段文本作为任务抽取来源，结构化任务走 `extracted_tasks` → `create_tasks`；新八段链路不再把 tasks JSON 泄漏进用户报告。外部任务 API 失败时仍会返回 `pending_integration`，用于离线/联调保护 | [reconcile_report.py](../ai_hunter/app/graph/nodes/reconcile_report.py) / [create_tasks.py](../ai_hunter/app/graph/nodes/create_tasks.py) |
| 回款 / 进度 / 复盘 | ✅ Phase 1 + Phase 2-A 已落地：3 表数据模型、看板接口、预期回款种子化、催收/利润提醒、AI 回款复盘。⬜ Phase 2-B 规则迭代学习回路未做 | [progress_service.py](../ai_hunter/app/services/progress_service.py) / [routes_progress.py](../ai_hunter/app/api/routes_progress.py) / [review_graph.py](../ai_hunter/app/subgraphs/review_graph.py) |
| 分层意图与业务线路由 | ✅ Phase 1-2、2.5.0-2.5.4 已完成实现、隔离真实冒烟、生产 legacy 模式部署、正式强制鉴权、数据库 DSN 日志脱敏及上下游服务 token 验收；`case.create / task.write / material.upload` 均已通过真实写入验收。🟡 `business_line` 灰度切流和观察窗口待完成 | [12-分层意图识别与业务线路由方案.md](design/12-分层意图识别与业务线路由方案.md) |
| 账号 / 角色 / 权限 | ✅ v2-A 已完成并同步真实库：私有化本地登录、本地用户/公司/角色、JWT 不写 roles、`app_user_role` 加载项目角色、`/me`/`/users`/`/roles` 管理接口、审计报告 8 段 `section_code` 权限矩阵、seed 初始化和审计日志。✅ v2-A.1 已完成：现有 `/files`、`/chat/upload-files`、`/chat/threads*`、`/chat/invoke` 已补身份与模块门禁，私有化生产旧 roles 回退默认关闭。✅ v2-B 已完成：共享 DDL、NpaDemo 案件租户/成员接口、ai_hunter tenancy 服务、thread metadata、案件路由强制校验和存量 159 个 thread 安全迁移均已落地。⬜ v2-C/D/E 未做：RLS、license key、平台用户中心适配 | [identity.py](../ai_hunter/app/auth/identity.py) / [permissions.py](../ai_hunter/app/auth/permissions.py) / [tenancy.py](../ai_hunter/app/auth/tenancy.py) / [routes_auth.py](../ai_hunter/app/api/routes_auth.py) |
| 资产包拆分→案件独立追踪 | 🟡 已有拿包前筛选 DDL 与设计文档，但尚无 service/router/subgraph 接线；当前核心审计仍以 `case_id` 为单位 | [screening_tables.sql](../sql/screening_tables.sql) / [拿包前业务线-资产包筛选与投决.md](business/拿包前业务线-资产包筛选与投决.md) |
| 报告导出 / 水印 / 移动端 | ❌ 后端仍只产报告文本、引用链和结构化接口；Word/PDF 导出、账号水印/暗记、移动端折叠尚未实现 | — |

---

## 2. 已确认的工程决策

### 决策一：报告生成重构 —— 方案 A（全 8 段专家子 agent）

把"主 agent 一次扛 4 段"改为**每段一个专家子 agent**，治注意力衰减。架构三要素：

1. **8 段专家子 agent**：每个只拿**自己段落的 system prompt + 切片后的数据**，不再灌全量 JSON。
   - 数据切片示例：第 2 段（资产清单去毒重估）只喂不动产/矿权/担保/债权；第 3 段（资金流）只喂资金流工具输出+图谱资金/代持/担保关系；第 5 段（重整）只喂第 2 段产出的 V_net + 处置数据。
2. **确定性数值引擎**（见决策二）：硬数字代码算死，专家 agent 只负责把既定数字写成表格/结论，保证跨段数字一致。
3. **并行扇出 + join**：第 1-4 段基本独立 → LangGraph 并行；第 5-8 段依赖前段产物（尤其第 2 段数字）→ 第二批跑；末尾 join 节点拼装，沿用 `reconcile_report` 做自动挂角标+覆盖率。
   - 可选：末段加**一致性 critic**，校验跨段数字/结论不冲突。

> 注：方案 A 会显著增加单次报告的 LLM 调用数。当前算力（仅支持 ~5 项目并行、量化模型）下需关注成本/并发；机房+满血模型到位后此约束缓解。实现时按段拆 prompt（沿用 `prompts/*.txt` 不内联），并在 `full_audit_graph` 重接线，状态字段按段拆（`report_section_N_ref`）。

**附带必修：报告输出通道分离（修上表 SOP 的 JSON 泄漏 bug）**
- 第 7 段的 `tasks` JSON 是**机器数据通道**（喂 `create_tasks`），必须与**用户展示通道**（报告正文）分离。
- 重构后：专家 agent 产出展示正文；任务结构化数据走独立字段，**不拼进 `final_report`**。即使不等报告重构，这个剥离也应尽快单独修。

### 决策二：确定性数值引擎（代码算死，口径固化）

把核心数字从 LLM 手里收回到代码：
- 计算：逐项去毒净值、总账、NPV `V_rec = Σ Pn·Wn/(1+r)^tn`、`V_net`、回收率、T1/T2/T3 三层回款预测。
- **口径固化**（同时解决会议"估值口径"要求）：
  - 金额统一**万元**为单位、保留小数（**会议要求 4 位小数、取消千分位**；当前 prompt 写的是 2 位 → 以会议口径为准，实现时统一）。
  - 回收率**只算法院终审本金+利息**，不计罚息、复利、后续利息（劣后债权清算/重整估值默认 0，仅作谈判筹码）。
  - 查封、案外异议等高风险标注；**极端情况资产估值直接归零**。
- 引擎输出结构化 `computed_metrics`，喂给相关段落专家 agent；专家不得重算核心数字。
- **待客户拍板的参数**：折现率 r（当前 prompt 默认 12%）、三层时间窗（T1 0-3 月 / T2 6-15 月 / T3 12-24+ 月）。

**金额单位按输出场景差异化（重要）**：同一份数据，渲染口径随产物类型不同——
- **审计报告**：以**万元**为单位、保留小数（会议口径 4 位）、**取消千分位**。
- **法律文书 / 函件**（如诉讼文书、催告函等）：金额以**元**为单位，并**加分节号（千分位分隔）**。
- 数值引擎应输出原始数值 + 提供按场景格式化的能力，由报告 / 文书生成分别套用各自口径，不在 prompt 里硬写单一格式。（法律文书生成本身是后续能力，见路线图。）

### 决策三：文字修正升级为「权威订正 + 可追溯」

- 现状文字修正只在会话内叠加、不写库、无时间。升级目标：
  - **落到权威订正表**（写库），在 `fetch_full_context` 加载阶段应用，**跨会话/跨人生效**，成为案件数据的一部分（与上传新材料的 supersede 机制对齐理念）。
  - **追溯能力**：记录每条修正的**时间、操作人、标的、指令、来源 query、生效范围**，可查"什么时候、谁、改了什么"。
- 与上传材料 supersede 的关系：两条权威更新路径并存（材料=证据驱动，文字=人工订正驱动），都应被复盘/审计可见。

### 决策四：回款闭环（隶属"进度看板"独立模块）

会议定义的进度看板独立模块：**展示项目阶段、风险提示、实际收款、预期回款，实时提醒款项催收与利润分配**。这是项目核心 KPI（"能拿回多少钱"），不是只出报告。要补的闭环：

```
出全量报告 → 执行(SOP任务) → 回款&进度跟踪 → 归档 → AI复盘审计 → 经验总结→规则迭代
```

后端要补：
1. **回款/进度数据模型**：每案件的阶段、风险提示、实际收款、预期回款、时间线，并与处置策略/SOP 任务关联。
2. **进度看板接口**：聚合上述数据给前端；含催收/利润分配的实时提醒触发。
3. **AI 复盘审计**（会议四.7）：项目终结后，以"当初报告预测 vs 实际回款/处置结果"做对账复盘报告（复用报告生成框架）。
4. **经验→规则迭代**：复盘结论沉淀为可被下次审计引用的规则/提示（学习回路）。

---

## 3. 优先级路线图

按依赖关系 + 影响面 + 是否被外部卡住排。**本仓库（后端编排）为主战场**，前端/硬件已标注。

### 当前开发主线：分层路由 Phase 2.5

Phase 1-2 已完成“精准分类 + capability 工具约束”，但尚未完成“精准分类后进入独立业务线工作流”。下一轮按 [design/12](design/12-分层意图识别与业务线路由方案.md) 依次推进：

1. **2.5.0 注册表与一致性检查**：✅ 已完成。`BusinessLineSpec / CapabilitySpec` 已成为 Schema、提示目录、权限、工具和 Agent 分支的单一来源，legacy 执行不变。
2. **2.5.1 业务线子图骨架与 shadow**：✅ 已完成。四个子图覆盖全部 capability；shadow 只记录 legacy/业务线目标，写操作不执行。
3. **2.5.2 迁移只读能力**：✅ 已完成。七个只读 capability 使用确定性参数和统一结果契约；`evidence.resolve` 只查本案卷宗，`caselaw.search` 只提供外部类案参考；模块/租户门禁保持在读取前。
4. **2.5.3 迁移专用图与领域 Agent**：✅ 已完成实现和隔离 HTTP 冒烟。审计、重审、复盘进入专用图，审计下钻和图谱查询使用固定 capability 领域 Agent。
5. **2.5.4 迁移写操作并切换**：✅ 代码迁移、模拟回归、`case.create / task.write / material.upload` 隔离真实写入验收、生产 legacy 模式部署、正式强制鉴权、数据库 DSN 日志脱敏和上下游服务 token 验收已完成；🟡 下一步评审灰度切流和观察窗口。

该阶段不涉及 DDL；灰度期间保留旧 `intent` 和 legacy 分支，可通过 `ROUTER_EXECUTION_MODE=legacy` 回滚。

### 🔴 Tier 1 —— 核心主线（先做）
1. ~~**确定性数值引擎**（决策二）~~ ✅ **已完成**（ai_hunter `1610f47`，见 [design/01](design/01-确定性数值引擎.md)）：本息回收率 + NPV + 去毒总账 + 归零 + 数据质量/交叉校验，参数化，已接入 full_audit_graph、报告 §2.5 消费。另下游 1.1/1.2 上游对齐亦已完成。
2. ~~**报告生成重构 方案 A**（决策一）~~ ✅ **已完成**（ai_hunter `0b3c407`，见 [design/02](design/02-报告八段式子agent重构.md)）：8 段专家子 agent 并行扇出 + reconcile 聚合 + 分段 SSE 事件 + SOP-JSON 泄漏修复 + audience 前向兼容。一致性 critic 后置。
3. **回款闭环 / 进度看板**（决策四）：定义"项目成功"本身。**Phase 1 ✅ 已完成**（见 [design/03](design/03-回款闭环与进度看板.md)）：3 表（case_progress/recovery_record/recovery_forecast）+ `routes_progress.py` 看板/收款/预期接口 + 报告 NPV 预期种子化 + 催收/利润提醒（阈值 env 可配，现 60 天/85%）。**Phase 2-A ✅ 已完成**：AI 复盘审计（预期 vs 实际三视角对账 + 差异归因 + 经验规则建议，`intent=review` + `review_graph` + `POST /cases/{id}/review`）。**Phase 2-B ⬜**：规则迭代学习回路（复盘结论沉淀成规则、下次审计自动引用，需先定规则存储/注入方式）。

### 🟡 Tier 2 —— 数据与订正增强
4. ~~**文字修正→权威订正+追溯**（决策三）~~ ✅ **已完成**（见 [design/04](design/04-文字修正权威订正与追溯.md)）：新表 `case_correction`（写库、可追溯）+ `extract_correction` 写库 + `fetch_full_context` 加载期应用（跨会话/跨人生效）+ 同标的自动 supersede + `routes_corrections.py`（list/add/revoke）。操作人记 `operator_id`/`operator_name`，`operator_meta` 预留账号体系角色/标签。
5. ~~**司法时效看板**~~ ✅ **已完成**（见 [design/05](design/05-司法时效看板.md)）：确定性引擎 `deadline_board.py`（归一 + 倒计时 + 红黄绿四级重算，阈值 env 可配 30/90）+ `GET /cases/{id}/deadline-board` 结构化接口；报告第 4 段保持叙述、进度看板 risk_alerts 改用同一引擎口径统一。
6. **外部接口**：执行信息网（待接）、企查查（按需开关，会议称临时关停）；新增 provider/工具注册到 `tools/registry.py`。

### 🔵 Tier 3 —— 跨栈/前端为主（后端配合给数据）
7. **账号/角色/权限网关**：v1 ✅ 已合入（认证信任用户中心 JWT + 角色→audience/模块分权 + 人员标签五维 + `GET /me`/`/roles` 可配，默认 `AUTH_ENABLED=false` 灰度）。**v2-A ✅ 已完成并同步真实库**（见 [design/07](design/07-权限网关v2与多租户落地.md)、[design/09](design/09-审计报告段落权限矩阵与配置化方案.md)）：私有化本地用户 / 公司 / 角色 / 本地登录、JWT 去 roles、本地 `app_user_role` 加载项目角色、角色模块权限、审计报告 8 段 `section_code` 权限矩阵、初始化脚本和审计日志。**v2-A.1 ✅ 已完成**：现有外露业务接口已补身份 / 模块门禁，私有化生产旧 roles 回退默认关闭。**v2-B ✅ 已完成**（见 [design/10](design/10-权限网关v2-B案件与会话隔离方案.md)）：共享 DDL、NpaDemo 案件租户/成员接口、ai_hunter tenancy 服务、thread metadata 全链路、案件路由强制校验及存量 159 个 thread 安全迁移均已完成。**v2-C/D/E ⬜**：RLS、私有化 license key、平台用户中心适配。
   - **用户/人员标签体系（权限组扩展信息，均可多选，用于分权与人岗匹配）**：
     - **一、项目角色**：项目经理(`project_manager`)、投资专员(`investment_specialist`)、法务专员(`legal_specialist`)、财审专员(`finance_specialist`)、项目助理(`project_assistant`)、律所律师(`lawyer`)、尽调专员(`due_diligence_specialist`)、法辅专员(`legal_assistant`)
     - **二、专业职称**：律师、会计师、审计师、税务师、金融分析师、不动产评估师、矿产评估师、拍卖师、破产管理人、不良资产经营师
     - **三、专业专长**（分组）：
       1. 通用综合：政策研究、行业分析、产业研判、宏观经济、AMC 全业务运营、重组重整
       2. 法律司法：经济庭实务、破产重整/清算、债权纠纷、强制执行、资产查封、案外异议处理、刑事线索梳理
       3. 风控侦查：全面风控、经济侦查、反贪稽查、资产转移识别、"白手套"排查、税务稽查
     - **四、常住地域**：省-市-县（区）
     - **五、所属公司名**
   - 设计要点：标签是**人员画像维度**（多选），与**访问权限**（按报告段落/模块分权）是两层——前者用于人岗匹配/任务派发/绩效，后者用于数据可见性管控；数据模型上分开但关联。
8. **资产包拆分 → 案件独立追踪 + 拿包前后数据隔离**：数据模型基础改造，影响面广，建议与权限体系一起设计。
9. **报告导出 Word/PDF + 账号水印/暗记 + 移动端折叠**：前端为主，后端给导出数据+水印元数据；依赖账号体系（水印=账号）。

### ⚪ 不在本代码库范畴（会议有，但非软件开发）
机房建设/算力扩容/满血版模型部署、人员组织与考核、专家评审流程、数据采集合规、阿里/京东拍卖数据爬取建库。

---

## 4. 待客户确认事项

> 说明：下表分两类——「仅待赋值」机制已实现，客户给值后改 env / 配置即可，不卡开发；「卡实现」需求本身未落地，依赖客户输入才能动手。

### 4.1 仅待赋值（机制已就绪，env 可配）

| # | 事项 | 配置入口 | 现默认值 |
|---|---|---|---|
| 1 | 数值引擎折现率 r | `METRICS_DISCOUNT_RATE` | 0.12 |
| 1 | 三层时间窗 T1/T2/T3（年化期数） | `METRICS_TRANCHE_YEARS` | `{"T1":0.125,"T2":0.875,"T3":1.5}` |
| 1 | 三档分配比例 / 概率权重 | `METRICS_TRANCHE_ALLOCATION` / `METRICS_TRANCHE_WEIGHT` | 见 [.env.example](../.env.example) |
| 2 | 金额小数位 | `METRICS_AMOUNT_DECIMALS` | 4（会议口径，已定） |
| 4 | 催收逾期宽限 / 利润提醒阈值 | `RECOVERY_OVERDUE_DAYS` / `PROFIT_DISTRIBUTION_THRESHOLD_PCT` | 60 天 / 85% |

### 4.2 卡实现（需求未落地，依赖客户输入）

| # | 事项 | 影响 |
|---|---|---|
| 4 | 利润分配**计算规则**（怎么算可分配/已分配；阈值已配，规则未知） | 决策四看板逻辑 |

> 原 #3「文字订正操作人来源」已不卡开发：决策三落地后记 `operator_id`/`operator_name`（调用方传入，可空），`operator_meta` 预留账号体系角色/标签，待 Tier 3 账号体系上线回填即可。

---

## 5. 下一步

当前不再重复产出已完成的数值引擎、八段报告和回款闭环 Phase 1/2-A 方案。分层路由 Phase 2.5.0-2.5.4 已完成实现、隔离真实冒烟、生产 legacy 模式部署、正式强制鉴权、数据库 DSN 日志脱敏和上下游服务 token 验收；下一步在保留 `ROUTER_EXECUTION_MODE=legacy` 回滚点的前提下评审 `business_line` 灰度切流和观察窗口。

Phase 2.5 完成后，再结合真实匿名问句标注集和混淆矩阵进入 Phase 3 数据驱动优化；方案三的业务线独立 Agent 保留为工具规模和多步流程复杂度增长后的后期升级项。
