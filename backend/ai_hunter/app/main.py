import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .api.routes_chat import router as chat_router
from .api.routes_files import router as files_router
from .api.routes_graph import router as graph_router
from .api.routes_corrections import router as corrections_router
from .api.routes_auth import router as auth_router
from .api.routes_users import router as users_router
from .api.routes_artifacts import router as artifacts_router
from .api.routes_templates import router as templates_router
from .graph.checkpointer import close_async_checkpointer
from .logging_utils import configure_logging
from .middleware import RequestLoggingMiddleware
from .settings import get_settings
from ..annual_audit.api import router as annual_audit_router


configure_logging()
LOGGER = logging.getLogger(__name__)

DOCS_URL = "/docs"
REDOC_URL = "/redoc"
OPENAPI_URL = "/openapi.json"

OPENAPI_TAGS = [
    {
        "name": "docs",
        "description": "接口文档目录与文档入口信息。",
    },
    {
        "name": "chat",
        "description": "前端主对话入口，包括普通 JSON 调用与 SSE 流式返回。",
    },
    {
        "name": "files",
        "description": "文件上传、卷宗批次详情、案件上传历史等接口。",
    },
    {
        "name": "graph",
        "description": "证据回源、关系证据链、页锚点、实体子图等图谱能力接口。",
    },
]

APP_DESCRIPTION = """
AI 会计师年度审计智能体对前端暴露的统一 API 服务，包含 AI 编排、证据图谱、底稿与报告生成。

多租户说明：

- 前端认证、会话、案件、文档、审计、任务与治理接口均由本服务提供。
- AI 工具通过统一服务内部地址调用领域路由，并携带当前 identity 的 company_id / user_id / 管理员标记。
- company_id 用于公司级隔离；普通用户仅可访问 owner 或案件成员范围内的数据。
- is_company_admin / is_super_admin 只由 AI 编排层透传给领域引擎，仍使用 AUDIT_API_TOKEN 防止外部伪造服务身份。

可直接访问的接口文档入口：

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`
- ReDoc: `/redoc`
- 前端接口目录: `/docs-index`

推荐前端接入顺序：

1. 文件上传与批次回查：`/files/*`
2. 对话与报告生成：`/chat/*`
3. 图谱证据回源与子图能力：`/graph/*`、`/evidence/*`
"""


class DocsLinkItem(BaseModel):
    name: str
    method: str
    path: str
    summary: str


class DocsSectionItem(BaseModel):
    tag: str
    description: str
    endpoints: list[DocsLinkItem] = Field(default_factory=list)


class DocsIndexResponse(BaseModel):
    service: str
    version: str
    swagger_url: str
    redoc_url: str
    openapi_url: str
    sections: list[DocsSectionItem] = Field(default_factory=list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.require_runtime_storage()
    LOGGER.info(
        "app_started env=%s host=%s port=%s log_level=%s",
        settings.app_env,
        settings.app_host,
        settings.app_port,
        settings.log_level,
    )
    LOGGER.info(
        "app_docs_ready swagger_url=%s redoc_url=%s openapi_url=%s docs_index_url=/docs-index",
        DOCS_URL,
        REDOC_URL,
        OPENAPI_URL,
    )
    yield
    await close_async_checkpointer()
    LOGGER.info("app_shutdown async resources released")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI 会计师年度审计智能体 API",
        version="0.1.0",
        description=APP_DESCRIPTION,
        debug=settings.app_env == "dev",
        lifespan=lifespan,
        docs_url=DOCS_URL,
        redoc_url=REDOC_URL,
        openapi_url=OPENAPI_URL,
        openapi_tags=OPENAPI_TAGS,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list or ["*"],
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods_list or ["*"],
        allow_headers=settings.cors_allow_headers_list or ["*"],
        expose_headers=[
            "Accept-Ranges",
            "Content-Range",
            "Content-Length",
            "Content-Disposition",
            "X-Request-ID",
        ],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(chat_router)
    app.include_router(files_router)
    app.include_router(graph_router)
    app.include_router(corrections_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(artifacts_router)
    app.include_router(templates_router)
    app.include_router(annual_audit_router)

    @app.get(
        "/docs-index",
        summary="前端接口文档目录",
        description="按业务分组返回当前对前端暴露的 API 文档目录，便于前端快速定位 Swagger 路径。",
        response_model=DocsIndexResponse,
        tags=["docs"],
    )
    async def docs_index() -> DocsIndexResponse:
        return DocsIndexResponse(
            service="AI 会计师年度审计智能体 API",
            version="0.1.0",
            swagger_url=DOCS_URL,
            redoc_url=REDOC_URL,
            openapi_url=OPENAPI_URL,
            sections=[
                DocsSectionItem(
                    tag="files",
                    description="文件上传、批次详情、材料事件、结论演进与未决图谱项。",
                    endpoints=[
                        DocsLinkItem(
                            name="文件服务健康检查",
                            method="GET",
                            path="/files/health",
                            summary="确认文件上传路由是否已挂载",
                        ),
                        DocsLinkItem(
                            name="上传并异步摄入文件",
                            method="POST",
                            path="/files/upload-and-ingest",
                            summary="上传原始文件并立即返回受理结果，后台继续 OCR、解析与图谱摄入",
                        ),
                        DocsLinkItem(
                            name="查询上传批次详情",
                            method="GET",
                            path="/files/upload-batches/{upload_batch_id}",
                            summary="查看批次状态、文件列表和持久化校验结果",
                        ),
                        DocsLinkItem(
                            name="查询案件上传批次列表",
                            method="GET",
                            path="/files/cases/{case_id}/upload-batches",
                            summary="查看案件最近的上传历史",
                        ),
                        DocsLinkItem(
                            name="重试上传批次",
                            method="POST",
                            path="/files/upload-batches/{upload_batch_id}/retry",
                            summary="对失败的上传批次执行手动重试，支持 auto、parse、graph 三种阶段",
                        ),
                        DocsLinkItem(
                            name="查询材料事件详情",
                            method="GET",
                            path="/files/material-events/{material_event_id}",
                            summary="查看一次上传或补件事件的状态与变化摘要",
                        ),
                        DocsLinkItem(
                            name="查询案件材料事件列表",
                            method="GET",
                            path="/files/cases/{case_id}/material-events",
                            summary="查看案件最近的材料事件时间线",
                        ),
                        DocsLinkItem(
                            name="查询案件结论演进视图",
                            method="GET",
                            path="/files/cases/{case_id}/evolution-items",
                            summary="查看旧结论到新结论的演进与证据上下文",
                        ),
                        DocsLinkItem(
                            name="查询案件未决图谱项",
                            method="GET",
                            path="/files/cases/{case_id}/unresolved-items",
                            summary="查看待后续批次补齐的 relation 和 claim",
                        ),
                    ],
                ),
                DocsSectionItem(
                    tag="chat",
                    description=(
                        "主对话与报告生成。调用内置领域接口时会透传当前身份租户上下文；"
                        "公司管理员 / 全局超管标记依赖 AUDIT_API_TOKEN 服务间 token。"
                    ),
                    endpoints=[
                        DocsLinkItem(
                            name="主对话入口",
                            method="POST",
                            path="/chat/invoke",
                            summary="支持 JSON 返回和 SSE 流式返回",
                        ),
                        DocsLinkItem(
                            name="获取会话历史列表",
                            method="GET",
                            path="/chat/threads",
                            summary="返回会话线程列表，支持按案件 ID 过滤和分页",
                        ),
                        DocsLinkItem(
                            name="获取会话详情",
                            method="GET",
                            path="/chat/threads/{thread_id}",
                            summary="返回指定会话线程的详细信息",
                        ),
                        DocsLinkItem(
                            name="获取会话消息历史",
                            method="GET",
                            path="/chat/threads/{thread_id}/messages",
                            summary="返回指定会话线程的完整消息历史记录",
                        ),
                        DocsLinkItem(
                            name="删除会话",
                            method="DELETE",
                            path="/chat/threads/{thread_id}",
                            summary="删除指定会话线程及其所有检查点数据",
                        ),
                    ],
                ),
                DocsSectionItem(
                    tag="graph",
                    description="证据回源、页锚点、子图和关系证据链。",
                    endpoints=[
                        DocsLinkItem(
                            name="按 claim 解析证据",
                            method="POST",
                            path="/evidence/resolve",
                            summary="把报告引用解析成具体证据和页锚点",
                        ),
                        DocsLinkItem(
                            name="按 relation 获取证据链",
                            method="POST",
                            path="/graph/relation-evidence",
                            summary="查看关系对应的 claim 与证据链",
                        ),
                        DocsLinkItem(
                            name="校验标杆案件证据回源链路",
                            method="POST",
                            path="/graph/demo-case-trace/validate",
                            summary="验证 citation 到 evidence 的可回源性",
                        ),
                        DocsLinkItem(
                            name="获取实体周边子图",
                            method="POST",
                            path="/graph/subgraph",
                            summary="查看指定实体周围的轻量知识子图",
                        ),
                        DocsLinkItem(
                            name="获取页内证据锚点",
                            method="GET",
                            path="/files/page-anchors",
                            summary="给前端高亮渲染页内证据框",
                        ),
                    ],
                ),
            ],
        )
    return app


app = create_app()
