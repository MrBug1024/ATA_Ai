# AI Hunter

AI Hunter 原平台的规范化单仓工作区。当前整理只合并工程和运行入口，不改变不良资产处置业务能力。

## 目录

```text
backend/   统一 FastAPI 服务（AI 编排 + NPA 领域引擎）
web/       Next.js 前端
new_docs/  新项目客户原始资料（本轮不参与实现）
```

后端只启动一个进程、监听一个端口。原 8080 领域接口路径保持不变，并与原 8081 AI、认证、会话、文件、图谱和治理接口一起由 `ai_hunter.app.main:app` 提供。

## 本地启动

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m ai_hunter

cd ..\web
pnpm install
pnpm dev
```

前端只需配置：

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8081
```
