# 设计方案 08 · LangGraph 依赖升级与 Agent API 迁移

> 状态：任务已立项，待执行。本文只做升级方案与验收设计，不直接升级依赖、不修改 Agent 行为。
> 关联：`ai_hunter/app/graph/nodes/run_drilldown_agent.py`、`pyproject.toml`、`uv.lock`。

## 1. 背景

当前全量测试通过，但存在 LangGraph 弃用提示：

```text
LangGraphDeprecatedSinceV10: create_react_agent has been moved to `langchain.agents`.
```

触发点在 `run_drilldown_agent.py`：

```python
from langgraph.prebuilt import create_react_agent
```

这不是运行错误，也不是权限 v2-A 引入的问题。根因是 LangGraph 1.x 已将 Agent 构建 API 从 `langgraph.prebuilt` 迁移到 `langchain.agents`，旧入口仍可用，但未来 LangGraph v2 可能移除。

## 2. 当前版本状态

本地 `.venv` 当前实际版本：

| 依赖 | 当前版本 | 说明 |
|---|---:|---|
| `langgraph` | `1.2.0` | 当前可运行；PyPI 最新已到 `1.2.8` |
| `langgraph-checkpoint-postgres` | `3.1.0` | Postgres checkpointer 插件 |
| `langchain-core` | `1.4.0` | 已安装 |
| `langchain` | 未安装 | 迁移到 `langchain.agents` 可能需要新增依赖 |

`pyproject.toml` 当前依赖范围偏宽：

```toml
langgraph>=0.2.0
langgraph-checkpoint-postgres>=2.0.0
```

风险：新环境安装时可能直接解析到更高版本，而代码仍依赖旧 Agent API，容易出现“本地能跑、重装后行为变化”的问题。

## 3. 目标

1. 将 LangGraph 相关依赖收紧到验证过的版本范围。
2. 消除 `create_react_agent` 旧入口弃用 warning。
3. 保持现有主图、SSE、同步 / 异步 checkpointer、下钻 Agent 工具调用行为稳定。
4. 明确升级后的回归测试和冒烟路径，避免 Agent 行为静默变化。

## 4. 非目标

- 不在本任务中重构主图节点顺序。
- 不改变 18 个下钻工具注册表。
- 不调整提示词业务口径。
- 不同时推进权限 v2 / 多租户 / RLS 相关改造。

## 5. 风险点

| 风险 | 严重度 | 说明 |
|---|---|---|
| Agent API 行为变化 | 高 | `langchain.agents` 新入口可能改变 prompt、state_schema、工具调用、返回 messages 结构。 |
| SSE 事件结构变化 | 高 | `/chat/invoke stream=true` 依赖内部 token / node 事件穿透，Agent 迁移可能影响前端流式展示。 |
| checkpointer 兼容性 | 中 | `langgraph`、`langgraph-checkpoint`、`langgraph-checkpoint-postgres` 版本必须匹配。 |
| 依赖范围过宽 | 中 | `>=` 无上界会让新环境安装未验证版本。 |
| 未安装完整 `langchain` | 中 | 迁移到 `langchain.agents` 可能需要新增 `langchain` 依赖，需确认包体积和版本约束。 |

## 6. 推荐实施步骤

### Phase 1：依赖锁定评审

建议先把依赖范围从宽松下限改为验证窗口，例如：

```toml
langchain-core>=1.4.0,<1.5.0
langchain-openai>=1.2.1,<1.3.0
langgraph>=1.2.0,<1.3.0
langgraph-checkpoint-postgres>=3.1.0,<3.2.0
```

是否新增完整 `langchain` 依赖需要在 Phase 2 验证后确认。

### Phase 2：Agent API 兼容试迁移

单独修改 `run_drilldown_agent.py`：

- 将旧入口 `langgraph.prebuilt.create_react_agent` 替换为新推荐入口。
- 验证新入口是否支持当前参数：
  - `llm`
  - `ALL_DRILLDOWN_TOOLS`
  - `prompt=_build_system_prompt`
  - `state_schema=AuditGraphState`
- 如果新入口返回结构不同，必须只在 `_extract_agent_output` 附近做兼容，不扩大改动面。

### Phase 3：回归验证

必须执行：

```bash
.venv/bin/pytest -q
```

重点补充 / 手动冒烟：

| 路径 | 验证点 |
|---|---|
| 非流式下钻 | Agent 能看到当前用户 query，不回退 generic 菜单 |
| SSE 流式下钻 | token / node / final / done 事件正常 |
| 工具调用 | 18 个工具仍能被 Agent 识别和调用 |
| Postgres checkpointer 同步图 | 普通 `/chat/invoke` 可恢复上下文 |
| Postgres checkpointer 异步图 | `stream=true` 可恢复上下文 |
| 无 API key / 离线 | 仍回退 `_fallback_agent_output` |

### Phase 4：上线策略

- 先在开发环境升级并锁定 `uv.lock`。
- 保留一轮回滚方案：如新 Agent API 行为不一致，先仅锁依赖，不迁移 API。
- 通过冒烟后再推送远程。

## 7. 验收标准

- 全量测试通过。
- 不再出现 `LangGraphDeprecatedSinceV10: create_react_agent has been moved to langchain.agents`。
- 下钻 Agent 对同一输入的最终输出结构仍为：

```python
{"agent_output": "..."}
```

- `/chat/invoke` 非流式与 SSE 流式均正常。
- `pyproject.toml` 不再使用 `langgraph>=0.2.0` 这种过宽依赖范围。

## 8. 需要确认

1. 是否允许本任务新增完整 `langchain` 依赖。
2. 是否本期只锁定依赖窗口，Agent API 迁移后置。
3. 是否需要对接真实活服务做下钻 Agent 冒烟。
4. 如果新 API 与当前 `state_schema` 不兼容，是适配新 API，还是短期继续固定旧入口版本。

## 9. 建议结论

建议先做“依赖锁定 + 小范围 Agent API 试迁移”，不与权限 v2、多租户、RLS 混合提交。若新 API 行为差异较大，优先锁定 LangGraph 1.2.x 版本窗口，避免未来重装环境出现不可控变更，再单独排期改 Agent 架构。
