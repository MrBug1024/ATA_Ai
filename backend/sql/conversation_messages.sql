-- Unified conversation message table (decoupled from LangGraph checkpointer internals)
-- This table stores the display-friendly conversation history independently from
-- LangGraph's checkpoint blobs, making queries fast and schema-stable.
CREATE TABLE IF NOT EXISTS conversation_messages (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    turn_id     TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    intent      TEXT,
    case_id     INT  DEFAULT 0,
    final_report_ref TEXT DEFAULT '',
    uploaded_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    graph_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    version     INT DEFAULT 1,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ
);

-- 兼容已部署库：表已存在时补列（幂等，可反复执行）。
ALTER TABLE conversation_messages
    ADD COLUMN IF NOT EXISTS graph_context JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON TABLE conversation_messages IS
'统一对话消息存储表。与 LangGraph checkpointer 解耦，专供历史消息查询使用。';

COMMENT ON COLUMN conversation_messages.id IS '自增主键';
COMMENT ON COLUMN conversation_messages.thread_id IS '会话线程 ID，对应 LangGraph 的 thread_id';
COMMENT ON COLUMN conversation_messages.turn_id IS '轮次 ID，由 persist_conversation_memory 生成，格式为 {hash}_user / {hash}_assistant';
COMMENT ON COLUMN conversation_messages.role IS '消息角色：user、assistant、system';
COMMENT ON COLUMN conversation_messages.content IS '消息完整内容；assistant 为最终展示给用户的答复正文';
COMMENT ON COLUMN conversation_messages.intent IS '本轮对话的图流程意图：full_audit、drilldown、re_audit、ingest 等';
COMMENT ON COLUMN conversation_messages.case_id IS '关联案件 ID';
COMMENT ON COLUMN conversation_messages.final_report_ref IS '若本轮生成了最终报告，此处存放报告的 heavy-payload 引用 ID';
COMMENT ON COLUMN conversation_messages.uploaded_files IS 'user 消息携带的附件 FileItem 列表(由 POST /chat/invoke 传入);assistant 消息存空数组。前端刷新对话历史时据此回显附件';
COMMENT ON COLUMN conversation_messages.graph_context IS 'assistant 消息的图谱关联快照(JSONB),结构 {trace_items, citation_coverage, unresolved_relations, unresolved_claims}。落库本轮 /chat/invoke 当时的值,使刷新历史会话时角标证据预览/覆盖率警告条/待补件 badge 不丢失;user 消息存空对象 {}';
COMMENT ON COLUMN conversation_messages.version IS 'assistant 版本号，1=首次生成，2+=重新生成';
COMMENT ON COLUMN conversation_messages.created_at IS '入库时间';
COMMENT ON COLUMN conversation_messages.deleted_at IS '软删除时间；与 checkpoints 的软删除保持一致';

CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_msg_user_unique
    ON conversation_messages(thread_id, turn_id)
    WHERE role = 'user' AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_conv_msg_thread_created
    ON conversation_messages(thread_id, created_at)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_conv_msg_case_id
    ON conversation_messages(case_id)
    WHERE deleted_at IS NULL;
