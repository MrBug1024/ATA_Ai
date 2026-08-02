# AI Hunter LangGraph 部署文档（Ubuntu / 10.0.10.2）

本文面向 Ubuntu 服务器，给出两种部署方式：

1. 前台启动：适合首次联调、排障、临时运行
2. `systemd` 托管：适合长期稳定运行

默认按以下假设编写：

- 服务器 IP：`10.0.10.2`
- 项目部署目录：`/opt/ai-hunter-langgraph`
- 服务监听端口：`8081`
- Python 版本：`3.11+`
- 启动入口：`ai_hunter.app.main:app`

如果你的实际目录、用户、端口不同，替换成自己的值即可。

## 1. 部署前准备

### 1.1 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

建议顺手确认版本：

```bash
python3 --version
pip3 --version
```

本项目要求 Python `>= 3.11`。

### 1.2 创建部署目录

```bash
sudo mkdir -p /opt/ai-hunter-langgraph
sudo chown -R $USER:$USER /opt/ai-hunter-langgraph
```

### 1.3 拉取代码

如果服务器可以直接拉仓库：

```bash
cd /opt
git clone <你的仓库地址> ai-hunter-langgraph
cd /opt/ai-hunter-langgraph
```

如果你已经把代码传上去，直接进入项目目录即可：

```bash
cd /opt/ai-hunter-langgraph
```

## 2. Python 环境安装

### 2.1 创建虚拟环境

```bash
cd /opt/ai-hunter-langgraph
python3 -m venv .venv
source .venv/bin/activate
```

### 2.2 安装依赖

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

如果你只跑服务，不需要测试，也可以用：

```bash
python -m pip install -e .
```

## 3. 环境变量配置

项目通过 `.env` 读取配置，模板文件在 `.env.example`。

### 3.1 复制配置模板

```bash
cd /opt/ai-hunter-langgraph
cp .env.example .env
```

### 3.2 至少确认这些关键配置

下面这些值最值得先核对：

```env
APP_ENV=prod
APP_HOST=0.0.0.0
APP_PORT=8081
LOG_LEVEL=INFO

LLM_DEFAULT_PROVIDER=minimax

POSTGRES_DSN=postgresql+psycopg://user:password@127.0.0.1:5432/ai_hunter
LANGGRAPH_CHECKPOINTER=postgres
LANGGRAPH_CHECKPOINTER_AUTO_SETUP=false

REDIS_URL=redis://127.0.0.1:6379/0

UNIFIED_API_BASE_URL=http://127.0.0.1:8081
AUDIT_API_TOKEN=替换为内部领域路由使用的独立随机密钥

OCR_BASE_URL=https://ocr.rhzy.ai
OCR_API_KEY=你的 OCR Key

MINIMAX_API_KEY=你的 MiniMax Key
```

`AUDIT_API_TOKEN` 是 AI 编排层调用内置领域路由时使用的 Bearer token，不是用户登录 JWT。只在统一后端的 `.env` 配置，并将文件权限收紧为 `0600`：

```text
/opt/ai-hunter-langgraph/.env
```

更新 token 后重启统一后端。验收至少覆盖：无 token `401`、错误 token `401`、正确 token 可读取有权案件、跨公司身份无法读取案件。

如果你不用 `minimax`，改成实际厂商并补全对应 key：

- `openai`
- `kimi`
- `faker`
- `minimax`

### 3.3 如果前端单独部署

建议把跨域来源改成明确地址，不要长期用 `*`：

```env
CORS_ALLOW_ORIGINS=http://10.0.10.2:3000,http://10.0.10.2:5173
```

如果浏览器会带 cookie 或鉴权头：

```env
CORS_ALLOW_CREDENTIALS=true
```

## 4. 数据库初始化

如果你启用了 PostgreSQL 持久化，建议在首次启动前先手工执行 SQL。

### 4.1 LangGraph checkpoint 表

```bash
psql "postgresql://user:password@127.0.0.1:5432/ai_hunter" -f sql/langgraph_checkpointer.sql
```

### 4.2 heavy payload 表

```bash
psql "postgresql://user:password@127.0.0.1:5432/ai_hunter" -f sql/heavy_payload_store.sql
```

### 4.3 上传批次与文档分类相关表

```bash
psql "postgresql://user:password@127.0.0.1:5432/ai_hunter" -f sql/sql_doc_category_tables.sql
```

### 4.4 材料事件表

```bash
psql "postgresql://user:password@127.0.0.1:5432/ai_hunter" -f sql/material_events.sql
```

### 4.5 未决图谱项表

```bash
psql "postgresql://user:password@127.0.0.1:5432/ai_hunter" -f sql/kg_unresolved_items.sql
```

如果数据库不在本机，把 `127.0.0.1`、用户名、密码、库名替换成实际值。

## 5. 前台启动方式

这种方式适合首次部署验证。

### 5.1 启动命令

```bash
cd /opt/ai-hunter-langgraph
source .venv/bin/activate
uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8081
```

说明：

- 前台启动后，终端不能关闭
- 看到类似 `Uvicorn running on http://0.0.0.0:8081` 说明服务已起来

### 5.2 后台临时跑法

如果你只是想临时挂后台，不想立刻配 `systemd`，可以先用：

```bash
cd /opt/ai-hunter-langgraph
source .venv/bin/activate
nohup .venv/bin/uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8081 > logs/console.out 2>&1 &
```

查看进程：

```bash
ps -ef | grep uvicorn
```

停止进程：

```bash
pkill -f "uvicorn ai_hunter.app.main:app"
```

## 6. systemd 托管方式

这是正式环境推荐方式。

### 6.1 创建运行用户

如果你想单独建服务账号：

```bash
sudo useradd -r -s /bin/bash -d /opt/ai-hunter-langgraph aihunter
sudo chown -R aihunter:aihunter /opt/ai-hunter-langgraph
```

如果你暂时不想新建用户，也可以先用现有账号，但正式环境更推荐专用用户。

### 6.2 创建 systemd 服务文件

创建文件：

```bash
sudo vi /etc/systemd/system/ai-hunter-langgraph.service
```

写入以下内容：

```ini
[Unit]
Description=AI Hunter LangGraph FastAPI Service
After=network.target

[Service]
Type=simple
User=aihunter
Group=aihunter
WorkingDirectory=/opt/ai-hunter-langgraph
EnvironmentFile=/opt/ai-hunter-langgraph/.env
ExecStart=/opt/ai-hunter-langgraph/.venv/bin/uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8081
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

如果你没有创建 `aihunter` 用户，请把 `User` 和 `Group` 改成实际运行账号。

### 6.3 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-hunter-langgraph
sudo systemctl start ai-hunter-langgraph
```

### 6.4 查看状态

```bash
sudo systemctl status ai-hunter-langgraph
```

### 6.5 查看日志

```bash
sudo journalctl -u ai-hunter-langgraph -f
```

项目本身还会把日志写到：

```text
/opt/ai-hunter-langgraph/logs/
```

默认文件名：

- `logs/app.log`
- `logs/access.log`

### 6.6 重启与停止

重启：

```bash
sudo systemctl restart ai-hunter-langgraph
```

停止：

```bash
sudo systemctl stop ai-hunter-langgraph
```

禁用开机自启：

```bash
sudo systemctl disable ai-hunter-langgraph
```

## 7. 部署后验证

### 7.1 健康检查

在服务器本机执行：

```bash
curl -sS http://127.0.0.1:8081/files/health
```

预期返回：

```json
{"status":"ok"}
```

### 7.2 Swagger 检查

浏览器访问：

- `http://10.0.10.2:8081/docs`
- `http://10.0.10.2:8081/openapi.json`
- `http://10.0.10.2:8081/docs-index`

### 7.3 端口检查

```bash
ss -lntp | grep 8081
```

## 8. 升级发布流程

如果后续拉了新代码，推荐流程：

```bash
cd /opt/ai-hunter-langgraph
git pull
source .venv/bin/activate
python -m pip install -e .
```

如果有新的 SQL 脚本，先执行对应 `psql -f ...`。

前台启动方式：

1. 先停止旧进程
2. 再重新执行 `uvicorn ...`

`systemd` 方式：

```bash
sudo systemctl restart ai-hunter-langgraph
```

## 9. 常见问题

### 9.1 服务启动了，但接口超时

优先检查：

- `.env` 里的 LLM key 是否正确
- OCR 服务是否可达
- `127.0.0.1:8081/api/*` 领域路由是否由统一进程提供
- PostgreSQL / Redis 是否可达

### 9.2 启动时提示数据库连不上

检查：

- `POSTGRES_DSN` 是否正确
- 数据库防火墙是否放通
- PostgreSQL 是否允许目标 IP 连接
- 相关表是否已经初始化

### 9.3 `systemd` 启动失败

先看日志：

```bash
sudo journalctl -u ai-hunter-langgraph -n 200 --no-pager
```

常见原因：

- `ExecStart` 路径写错
- `.venv` 没创建
- `.env` 文件不存在
- 运行用户对项目目录没有权限

### 9.4 日志目录权限问题

如果日志写不进去：

```bash
sudo chown -R aihunter:aihunter /opt/ai-hunter-langgraph
sudo chmod -R 755 /opt/ai-hunter-langgraph/logs
```

## 10. 推荐的正式环境做法

如果这是长期运行环境，建议至少做到这几件事：

1. 使用专用 Linux 用户运行服务
2. 使用 `systemd` 托管，而不是 `nohup`
3. `.env` 中填真实内网地址和密钥，不要保留示例值
4. 先手工执行 SQL 初始化，不依赖自动建表
5. 用固定端口 `8081`，并确认没有和其他服务冲突
6. 发布后先跑 `/files/health`、`/docs`、`/openapi.json` 三个检查点

## 11. 一套可直接执行的最短命令清单

如果你已经有代码，只想快速在 `10.0.10.2` 跑起来，可以按这个顺序：

```bash
cd /opt/ai-hunter-langgraph
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
vi .env
mkdir -p logs
uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8081
```

然后验证：

```bash
curl -sS http://127.0.0.1:8081/files/health
```
