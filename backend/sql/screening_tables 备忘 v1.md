# screening_tables 变更备忘 v1（2026-06-10）

## 本次变更

新增拿包前业务线（快筛/投决）数据模型，DDL 见 `screening_tables.sql`，共 6 张表：

1. `packages` —— 资产包（商机）主表，与影子 case 1:1。
2. `screening_item_catalog` —— 评分项目录（《指引》评分表执行化，19 项 100 分，含种子数据）。
3. `screening_scorecards` —— 评分卡主表（一包多版本，draft/confirmed）。
4. `screening_scorecard_items` —— 评分明细（机器预填与人工确认分列、改分留痕）。
5. `pricing_params` —— 定价参数表（版本化只增不改；含**占位示例初值**，生效前必须由财务开新版本确认）。
6. `screening_economics` —— 回收与收益测算结果（参数快照可追溯）。

设计依据：`docs/business/拿包前业务线-资产包筛选与投决.md` §7（五项决策）/ §8.2 / §8.7。

## 与案件服务的协同约定（重要）

影子 case 路线复用 `cases` 表，约定如下，**需案件服务侧知悉并配合**：

- 建包时预建影子 case：`case_type='资产包'`（CHECK 约束既有枚举，原先未使用），
  `status='筛选中'`，`notes` 带 `{"biz_stage":"pre_acquisition","package_id":...}`。
- `cases.status` 新增两个约定值：`'筛选中'`、`'已放弃'`（该列无 CHECK 约束，纯约定）；
  拿包转化时翻回 `'进行中'`。
- **案件服务的案件列表查询及库内 5 个视图（v_investigation_progress / v_case_todo_list 等）
  目前对 cases 无任何过滤，影子 case 会混入列表**——需加
  `status NOT IN ('筛选中','已放弃')` 或按 notes 标记过滤。

## 未尽事项

- `pricing_params` 种子数值全部为占位示例（note 已标注），启用测算前由财务/投决开 version 2 确认。
- 快速变现折扣系数二期由司法拍卖历史数据校准。
- 评分项调整走 `screening_item_catalog.enabled` 停用，不删行，保历史评分卡可解释。
