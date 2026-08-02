# SSE 流式架构说明

> 当前实现依据：`ai_hunter/app/graph/checkpointer.py` 与
> `ai_hunter/app/api/routes_chat.py`。历史上使用单一 `MemorySaver` 的方案已经失效。

## 架构决策

`POST /chat/invoke` 同时支持两种响应模式：

- `stream=true` 或请求头包含 `Accept: text/event-stream`：使用 SSE，逐步返回节点、模型文本和最终结果。
- 其他请求：使用普通 JSON，等待本轮图执行完成后返回完整结果。

两条路径共享同一个顶层图定义和 `thread_id` 状态，但必须分别绑定同步与异步
checkpointer，不能把同步 `PostgresSaver` 直接用于 `astream_events()`。

## Checkpointer 选择

### 当前方案：双 Postgres checkpointer

当 `LANGGRAPH_CHECKPOINTER=postgres` 时：

| 请求路径 | Checkpointer | 初始化方式 | 图执行方式 |
|---|---|---|---|
| 普通 JSON | `PostgresSaver` | 同步 `ConnectionPool`，进程内缓存 | `graph.stream()` 在线程池执行 |
| SSE | `AsyncPostgresSaver` | 异步 `AsyncConnectionPool`，双检锁单例 | 独立编译图执行 `astream_events()` |

- 两个 saver 使用同一个规范化后的 PostgreSQL DSN，并读写同一组 LangGraph checkpoint 表。
- `/chat/invoke` 在图执行外使用 thread 级 PostgreSQL advisory lock，保证同一会话串行执行。
- SSE 图首次请求时延迟编译；FastAPI lifespan 关闭时释放异步连接池。
- `LANGGRAPH_CHECKPOINTER_AUTO_SETUP=false` 时不会自动建表，首次启动前需手工执行
  `sql/langgraph_checkpointer.sql`。

### MemorySaver 回退边界

以下情况会使用 `MemorySaver`：

- 显式配置 `LANGGRAPH_CHECKPOINTER=memory`；
- `postgres` 模式初始化同步或异步 saver 失败。

回退用于本地开发和测试，不是生产持久化方案。进程重启后 checkpoint 会丢失，多实例之间也不共享状态。
此外，`conversation_messages`、thread metadata 和部分业务写入仍依赖 PostgreSQL，因此“图回退内存”不代表完整服务已经离线可用。

## 验证方式

维护中的自动化测试只从 `tests/` 收集：

```bash
.venv/bin/pytest -q
```

自动化测试可以覆盖图编译、路由和 SSE 事件处理，但无法证明目标环境中的 PostgreSQL 持久化已经生效。
部署验收还应分别执行真实 JSON/SSE 请求，并在服务重启后确认同一 `thread_id` 可以恢复状态。

## 代码实现

### checkpointer.py
```python
@lru_cache(maxsize=1)
def get_checkpointer():
    # 普通 JSON 路径：PostgresSaver + 同步连接池；失败时回退 MemorySaver。
    ...

async def get_async_checkpointer():
    # SSE 路径：AsyncPostgresSaver + 异步连接池；失败时回退 MemorySaver。
    ...
```

### routes_chat.py
```python
async def _ensure_async_graph():
    async_cp = await get_async_checkpointer()
    return build_audit_orchestrator_graph(checkpointer=async_cp)

async for event in streaming_graph.astream_events(graph_input, config=config, version="v2"):
    ...
```

## SSE 事件契约

节点数量和顺序由本轮意图、上传分支及 `ROUTER_EXECUTION_MODE` 决定，客户端不能假设固定为 8 个节点。

| 事件 | 含义 |
|---|---|
| `start` | 请求开始，包含 thread、query 和上传数量等基础信息 |
| `node` | 一个图节点结束，包含节点名、摘要和脱水后的公开 payload |
| `text_chunk` / `reasoning_chunk` | 非分段模型节点的正文或推理增量 |
| `section_start` | 八段审计或三段复盘的某一段开始 |
| `section_chunk` / `section_reasoning_chunk` | 带 `section_id` 的分段正文或推理增量 |
| `section_done` | 某一报告段完成 |
| `final` | 与非流式 `ChatInvokeResponse` 对齐的最终结果 |
| `done` | 正常流结束 |
| `error` | 权限拒绝或执行异常；收到后本轮结束 |

报告段权限会同时过滤分段事件和 `final_report`。`business_line_result`、业务线 context
及其他内部大字段不会直接进入公开 SSE payload。

最小事件序列如下，实际执行可能在中间产生任意数量的节点和分段事件：

```text
start -> node/文本或分段事件... -> final -> done
                                  \-> error
```

## 前端集成

该接口是带 JSON body 的 `POST`，浏览器原生 `EventSource` 只能发起 GET，不能直接用于此接口。
前端应使用 `fetch()` 读取 `ReadableStream`，并按空行分隔完整 SSE frame；解析器必须保留跨 chunk 的残余 buffer。
完整请求字段、事件 payload 和报告段渲染约定见
[`docs/integration/前端调用手册-追溯与知识图谱.md`](../integration/前端调用手册-追溯与知识图谱.md)。

## 并发与资源生命周期

- JSON 和 SSE 都在图执行外获取同一个 `thread_id` 的 PostgreSQL advisory lock，防止多 worker 下同一会话乱序写入。
- 异步 saver 和 SSE 图均延迟初始化并在进程内复用，避免每次请求创建连接池和重复编译图。
- FastAPI shutdown 阶段调用 `close_async_checkpointer()` 关闭异步连接池。
- `client_turn_id` 命中已有助手消息时直接返回缓存结果，`regenerate=true` 才绕过缓存。

## 生产验收

1. 确认部署 `.env` 使用 `LANGGRAPH_CHECKPOINTER=postgres`，且 DSN 指向目标 PostgreSQL。
2. 若关闭自动建表，先经授权执行 `sql/langgraph_checkpointer.sql`。
3. 分别验证普通 JSON 与 SSE 请求；SSE 正常序列应以 `final -> done` 结束，而不是 `error`。
4. 重启服务后用同一 `thread_id` 继续对话，确认上下文可以恢复。
5. 核对启动日志确实选择 `PostgresSaver` / `AsyncPostgresSaver`，不得把回退警告当作正常持久化。
6. 另行核对 `conversation_messages` 和 thread metadata 落库；checkpoint 成功不等于消息层全部成功。

## 当前结论

- 普通 JSON 使用同步 `PostgresSaver`，SSE 使用独立的 `AsyncPostgresSaver`。
- 两条路径共享 PostgreSQL checkpoint 数据，但 saver 实例和图编译实例不可互换。
- `MemorySaver` 仅用于显式内存模式或 PostgreSQL 初始化失败后的降级，不是生产推荐方案。
- 单元测试通过不能替代真实 PostgreSQL、服务重启和 JSON/SSE 冒烟。

---

**最后更新**：2026-07-19
**架构状态**：双 Postgres checkpointer 已实现
