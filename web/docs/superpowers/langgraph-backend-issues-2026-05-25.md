# LangGraph 后端接口问题清单（待修复）

> 测试日期：2026-05-25
> Base URL：`http://10.0.10.2:8081`
> 测试方式：以真实数据手动调用全部 19 个接口（全新 thread / case / file），以真实返回为准。
> 测试数据：thread `268540b6-afbd-4bbf-be4e-11d6077833ec`（3 轮，含重复现场）、单轮 thread `cfaeaea4-57ec-4823-aa66-20c9ae374faa`、case `124`、file `40`、upload_batch `local-87fbdcaa0e95`。

## 结论速览

- **正常（13 个）**：`/files/health`、`/docs-index`、`/files/upload-and-ingest`、`/files/upload-batches/{id}`、`/files/cases/{id}/upload-batches`、`/files/cases/{id}/material-events`、`/files/material-events/{id}`、`/files/cases/{id}/evolution-items`、`/files/cases/{id}/unresolved-items`、`/files/page-anchors`、`/evidence/resolve`、`/graph/subgraph`、`/graph/relation-evidence`、`/graph/demo-case-trace/validate`、`/chat/invoke`（功能正常，但有性能/记忆问题见下）、`/chat/threads`、`/chat/threads/{id}`、`/chat/threads/{id}`(DELETE)。
- **需修复（6 个问题）**：见下文。

> 说明：文中 `HTTP:000` 一律是 **curl `--max-time` 到点主动断开**（客户端放弃），不是服务器返回超时——此时服务器是"完全不响应"。

---

## 问题 1：`GET /chat/threads/{id}/messages` 多轮历史严重重复

**问题**：同一线程发 N 轮对话，历史接口返回的消息数远多于 2N，老轮次被重复多次且顺序错乱。

### 测试过程
在一个全新线程上顺序发 3 轮 `chat/invoke`（全 `stream:false`、`current_case_id:0`），再调历史接口。

### 测试数据
- thread_id：`268540b6-afbd-4bbf-be4e-11d6077833ec`
- 3 轮 query 及结果：
  1. `你好，简单介绍一下你能做什么` → 200 / 36.3s / final_report 354 字
  2. `你刚才提到的资金流向拓扑分析，需要我提供哪些材料？` → 200 / 31.5s / final_report **0 字（空）**
  3. `破产清算和破产重整有什么区别？` → 200 / 41.1s / final_report 650 字

### 调用命令
```bash
B=http://10.0.10.2:8081
TID=268540b6-afbd-4bbf-be4e-11d6077833ec
curl -s -X POST "$B/chat/invoke" -H 'Content-Type: application/json' \
  -d "{\"thread_id\":\"$TID\",\"query\":\"你好，简单介绍一下你能做什么\",\"current_case_id\":0,\"stream\":false}"
curl -s -X POST "$B/chat/invoke" -H 'Content-Type: application/json' \
  -d "{\"thread_id\":\"$TID\",\"query\":\"你刚才提到的资金流向拓扑分析，需要我提供哪些材料？\",\"current_case_id\":0,\"stream\":false}"
curl -s -X POST "$B/chat/invoke" -H 'Content-Type: application/json' \
  -d "{\"thread_id\":\"$TID\",\"query\":\"破产清算和破产重整有什么区别？\",\"current_case_id\":0,\"stream\":false}"
curl -s "$B/chat/threads/$TID/messages"
```

### 实际返回
`message_count: 14`（期望 6），排布如下：

| idx | role | 内容 | 长度 |
|---|---|---|---|
| 0 | user | 你好，简单介绍… | 14 |
| 1 | assistant | 轮1答案 | 354 |
| 2 | user | 你好（重复） | 14 |
| 3 | assistant | 轮1答案（重复） | 354 |
| 4 | user | 你刚才提到的资金流向… | 25 |
| 5 | assistant | `intent=drilldown \| case_id=0`（stub，见问题2） | 28 |
| 6 | user | 你好（重复） | 14 |
| 7 | assistant | 轮1答案（重复） | 354 |
| 8 | user | 你好（重复） | 14 |
| 9 | assistant | 轮1答案（重复） | 354 |
| 10 | user | 资金流向（重复） | 25 |
| 11 | assistant | stub（重复） | 28 |
| 12 | user | 破产清算和重整区别 | 15 |
| 13 | assistant | 轮3答案 | 650 |

即 **轮1 出现 4 次、轮2 出现 2 次、轮3 出现 1 次**。

### 分析
- 重数递减（4/2/1）+ 顺序错乱（`[t1,t1,t2,t1,t1,t2,t3]`）→ 疑似**每次 `invoke` 把累积的 `memory_context` 反序列化成消息又重新落库一遍**，越老的轮次被重复落库越多次。
- **对照**：单轮线程 `cfaeaea4-…` 调 `/messages` 正好返回 2 条，干净。重复只在多轮出现。

### 期望
3 轮 = 6 条（user/assistant 各 3），无重复、按时间正序。

---

## 问题 2：`/messages` 与 `memory_context` 存"助手摘要 stub"而非答案正文

**问题**：服务端记忆只保留用户原问 + 一行助手元数据（intent/case_id/字数），不存答案正文；某轮答案为空时，`/messages` 把这行 stub 当正文返回。

### 测试过程
观察问题1中**轮2**（空答案）的响应字段，以及它在 `/messages`、线程详情里的落库形态。

### 测试数据
- 同 thread `268540b6-…`，轮2 query：`你刚才提到的资金流向拓扑分析，需要我提供哪些材料？`

### 调用命令
```bash
curl -s -X POST "$B/chat/invoke" -H 'Content-Type: application/json' \
  -d "{\"thread_id\":\"$TID\",\"query\":\"你刚才提到的资金流向拓扑分析，需要我提供哪些材料？\",\"current_case_id\":0,\"stream\":false}"
curl -s "$B/chat/threads/$TID"   # 线程详情里也能看到 memory_context
```

### 实际返回
- 轮2 响应：`intent: "drilldown"`，但 `final_report: ""`（0 字，空答案）。
- `/messages` 里轮2 的 assistant 正文 = `intent=drilldown | case_id=0`（28 字）。
- `memory_context` 字段内容：
  ```
  [最近对话]
  user: 你好，简单介绍一下你能做什么
  assistant: intent=drilldown | case_id=0 | report_generated chars=354
  user: 你刚才提到的资金流向拓扑分析，需要我提供哪些材料？
  assistant: intent=drilldown | case_id=0
  ```

### 分析
- **2a 记忆只存摘要**：assistant 行只有 `intent | case_id | 字数`，无正文 → LLM 无法回忆自己上一轮具体说了什么，"你刚才说的第三点"类追问会失准。
- **2b 空答案落库成 stub**：前端会渲染出 `intent=drilldown | case_id=0` 这串内部字符串。
- **2c 路由疑点（附带）**：`current_case_id:0` 下的追问类问题被路由成 `drilldown` 却产出空 `final_report`；同样 case_id=0 的通用问题却能正常出答案。请确认是意图路由还是生成问题。

### 期望
`/messages` 与 `memory_context` 都保存**完整助手正文**；不应把内部 stub 当答案返回。

---

## 问题 3：chat 重活请求被客户端断连后不取消 → 拖死整个后端

**问题**：一个慢的 `chat/invoke` 被客户端放弃后，服务端不取消、继续占资源，随后连 `/files/health` 都返回不了，整个后端 wedge，必须重启。本次测试复现 **2 次**。

### 测试过程 / 两条触发路径
- **路径1（断连未取消累积）**：发一个绑定 case、注定 >150s 的分析，客户端 150s 断开 → 紧接着探活 `/health`。
- **路径2（单个顺序请求也触发）**：worker 空闲时（graph 接口刚 100ms 秒回），只发一个 `case_id:0` 的普通问题，它跑了 >120s，**之后** `/health`、`/messages` 全部 000，需重启。

### 测试数据
- 路径1：thread `cfaeaea4-57ec-4823-aa66-20c9ae374faa`，query `请分析本案的债权申报情况，列出债权人、债务人和申报金额`，`current_case_id:124`。
- 路径2：thread `b897d89b-70e9-451c-8156-0caa162d6552`，query `破产重整的法定程序有哪些步骤？`，`current_case_id:0`。

### 调用命令（最小复现，重启后跑）
```bash
B=http://10.0.10.2:8081
# 终端1：绑 case 的重活，故意 20s 断开模拟用户离开
curl -s --max-time 20 -X POST "$B/chat/invoke" -H 'Content-Type: application/json' \
  -d '{"thread_id":"wedge-test-001","query":"请分析本案的债权申报情况","current_case_id":124,"stream":false}'
# 终端2：断开后立刻反复探活
for i in 1 2 3 4 5; do curl -s --max-time 10 -o /dev/null -w "health=%{http_code} t=%{time_total}\n" "$B/files/health"; done
```

### 实际返回
- 断开后 `/files/health`、`/chat/threads/{id}/messages` 均 `HTTP:000`；专门跑的 150s 排空探测期间 `/health` 一直 000，重启后才恢复（恢复后 `/health` 200 / 88ms）。
- 佐证服务端没取消：路径1 那条客户端断了，但**服务端跑完并落库了**——事后用 `GET /chat/threads/cfaeaea4…/messages` 免费取回了完整 10,911 字报告。

### 分析（嫌疑根因，需后端日志确认）
**断连不触发任务取消 + 某个被独占的共享资源（单 worker / DB 连接 / LLM 客户端 / 全局锁）长期不释放**。一旦被一个重活占住，后续所有请求（含 `/health`）全堵死。可同时解释：①断连后还在跑；②连最轻的 `/health` 都不通；③同参数耗时能差 3 倍（排队）。路径2 证明不是并发独有。

### 请后端确认
1. 客户端断 TCP 后那条 `chat/invoke` 的 LLM 调用是否仍在跑？有无 request-cancel / `asyncio` 任务取消？
2. uvicorn/gunicorn worker 数？LLM 调用是真 `await` 还是阻塞事件循环？
3. DB 连接池大小？是否每个 chat 请求长期独占一条连接（>150s）导致 `/health` 拿不到连接？
4. 上游 LLM provider 是否有并发/速率限制导致排队？
5. 有无服务端请求总超时（目前看没有，任务能跑 >150s 不被掐）？

### 期望
①断连即取消服务端任务；②重活不阻塞 `/health` 等轻接口；③加并发/排队/超时保护，单请求异常不拖垮全局。

---

## 问题 4：绑定 case 的分析 `stream:false` 下 >150s，HTTP 必然超时

**问题**：`current_case_id` 绑到真实案件 + 分析类 query，生成稳定 >150s，`stream:false` 把整段憋到最后返回，前端 HTTP 必超时。

### 测试数据（实测耗时）
| query | current_case_id | 耗时 | 结果 |
|---|---|---|---|
| 你好，简单介绍一下你能做什么 | 0 | 36.3s | 200 |
| 你刚才提到的资金流向…需要哪些材料 | 0 | 31.5s | 200（空报告） |
| 破产清算和破产重整有什么区别 | 0 | 41.1s | 200 |
| 请分析本案的债权申报情况… | **124** | **>150s** | 客户端断；服务端落库 10,911 字 |

### 调用命令
```bash
curl -s --max-time 200 -X POST "$B/chat/invoke" -H 'Content-Type: application/json' \
  -d '{"thread_id":"<uuid>","query":"请分析本案的债权申报情况","current_case_id":124,"stream":false}'
```

### 分析
- `current_case_id≠0` 触发对已入库文档的检索 + 固定 8 段模板报告生成，输出量是通用问答的 20 倍以上。
- `stream:false` 不返回任何中间内容，客户端只能干等到全部生成完。

### 期望
长任务走 SSE（`stream:true`，事件 `start/node/final/done`），或提供异步任务 + 轮询。（好的一面：断连后结果仍落库，前端可用 `/messages` 兜底取回。）

---

## 问题 5：`doc_category` 必填但无枚举/校验端点

**问题**：上传必须带 `doc_category`，否则 400；但没有任何接口能列出合法取值，预校验显示"暂不可用"，前端只能硬编码经验值。

### 测试数据
- 文件：一份债权申报材料纯文本（`fresh_claim.txt`）
- `doc_category`：第一次不传；第二次传 `loan_contract`

### 调用命令
```bash
# 不带 doc_category → 400
curl -s -X POST "$B/files/upload-and-ingest" \
  -F "files=@fresh_claim.txt;type=text/plain" -F "current_case_id=0"
# 带合法值 → 202
curl -s -X POST "$B/files/upload-and-ingest" \
  -F "files=@fresh_claim.txt;type=text/plain" \
  -F "current_case_id=0" -F "doc_category=loan_contract" -F "batch_name=2026-05 测试批次"
```

### 实际返回
- 不带：`HTTP 400` `{"detail":"缺少 doc_category；当前约定同一批次只允许上传一种卷宗类别。"}`
- 带 `loan_contract`：`HTTP 202`，响应里 `doc_category_validation.message = "doc_category 预校验暂不可用"`。
- `/docs-index` 只是接口目录，不含类别枚举；openapi 里 `doc_category` 也只是普通 string，无 enum。
- 已知能用的值：`basic_info`、`loan_contract`。

### 分析
前端无法可靠拿到合法 `doc_category` 列表，只能硬编码，类别一变即出错；预校验未上线。

### 期望
提供"卷宗类别枚举"接口，或在 openapi 用 `enum` 约束 `doc_category`，并补上预校验。

---

## 问题 6：`retry` 对非失败批次返回 500 并泄露完整 traceback

**问题**：业务上只允许重试失败批次（正确），但实现用未捕获的 `ValueError` 拒绝 → 返回 500 + 把完整 Python traceback、文件路径、依赖版本泄露给客户端。

### 测试数据
- upload_batch_id：`local-87fbdcaa0e95`（已成功完成，status=completed）
- stage：`auto`

### 调用命令
```bash
curl -i -X POST "http://10.0.10.2:8081/files/upload-batches/local-87fbdcaa0e95/retry?stage=auto"
```

### 实际返回
`HTTP 500`，响应体是完整 traceback，根因：
```
File ".../ai_hunter/app/api/routes_files.py", line 424, in retry_upload_batch
    resolved_stage = _resolve_retry_stage(batch=batch, event=event, requested_stage=stage)
File ".../ai_hunter/app/api/routes_files.py", line 1277, in _resolve_retry_stage
    raise ValueError("仅支持对失败批次执行重试。")
ValueError: 仅支持对失败批次执行重试。
```

### 分析
- 业务逻辑对，但 `_resolve_retry_stage` 抛的 `ValueError` 没被捕获 → 500 + 暴露内部实现细节（路径、行号、框架版本），**安全 + 体验双重问题**。
- **正常路径未验证**：失败批次 → retry → 恢复，需要一个真正失败的批次（建议后端用故意失败的批次自测；前端侧造失败批次有再次拖死后端的风险）。

### 期望
- 捕获业务校验异常，返回 **4xx**（如 400/409）+ 干净 JSON：`{"detail":"仅支持对失败批次执行重试。"}`。
- 全局兜底：生产环境关闭 traceback 回显，未处理异常统一返回通用 500 JSON。

---

## 附：本次实测正常的接口（13 个，供参考）

| 接口 | 方法 | 备注 |
|---|---|---|
| `/files/health` | GET | 200，~88ms |
| `/docs-index` | GET | 200，接口目录（无类别枚举） |
| `/files/upload-and-ingest` | POST | 202（必须带 doc_category）；txt 直读 ~4s 完成；case_id=0 自动识别为 124，debtor=85 |
| `/files/upload-batches/{id}` | GET | 200，含 persistence_checks |
| `/files/cases/{id}/upload-batches` | GET | 200 |
| `/files/cases/{id}/material-events` | GET | 200 |
| `/files/material-events/{id}` | GET | 200，~4s 完成 |
| `/files/cases/{id}/evolution-items` | GET | 200（单批无演进→空） |
| `/files/cases/{id}/unresolved-items` | GET | 200（空） |
| `/files/page-anchors` | GET | 200（已修复）；txt 返回 quote_text+source_page_id，bbox/page_image 为空（仅 PDF/图片 OCR 有版面坐标） |
| `/evidence/resolve` | POST | 200（无 claim 优雅返回空） |
| `/graph/subgraph` | POST | 200（case 124 无关系落库→空 nodes/edges） |
| `/graph/relation-evidence` | POST | 200（空 trace_items） |
| `/graph/demo-case-trace/validate` | POST | 200（无 report_ref→`missing_case_id_or_report_ref`） |
| `/chat/invoke` | POST | 功能正常（见问题 1-4 的性能/记忆问题） |
| `/chat/threads` | GET | 200，带分页 `{threads,total,limit,offset}`；注意 `title`=最后一轮 query |
| `/chat/threads/{id}` | GET | 200，含 title/case_id/last_query/memory_context/step 等 |
| `/chat/threads/{id}` | DELETE | 200 `{"success":true}`，再 GET 返回 404 |
