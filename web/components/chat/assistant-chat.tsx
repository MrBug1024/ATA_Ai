// components/chat/assistant-chat.tsx
"use client";

import type { AttachmentAdapter } from "@assistant-ui/react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { Network } from "lucide-react";
import { useLanggraphRuntime } from "@/lib/assistant-ui/use-langgraph-runtime";
import { ThinkingContext } from "@/lib/assistant-ui/thinking-context";
import { EvidenceContextProvider } from "@/lib/assistant-ui/evidence-context";
import type { DbMessage } from "@/lib/assistant-ui/types";
import { EvidenceDrawer } from "@/components/knowledge-graph/evidence-drawer";
import { PreviewProvider, PreviewSidePanel } from "@/components/shared/preview-host";
import { ChatThread } from "./chatgpt-thread";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { useGraphModalStore } from "@/lib/stores/graph-modal";
import { useAuth } from "@/lib/hooks/use-auth";
import { canAccessModule } from "@/lib/auth/authorization";

export interface SerializableMessage {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  metadata: Record<string, unknown> | null;
  createdAt: string;
  _attachments?: DbMessage["_attachments"];
}

interface AssistantChatProps {
  threadId: string;
  caseId?: number;
  initialMessages?: SerializableMessage[];
  initialReportRef?: string;
  title?: string;
  attachmentAdapter?: AttachmentAdapter;
  attachmentDisabled?: boolean;
  attachmentDisabledReason?: string;
}

export function AssistantChat({
  threadId,
  caseId,
  initialMessages,
  initialReportRef,
  title,
  attachmentAdapter,
  attachmentDisabled,
  attachmentDisabledReason,
}: AssistantChatProps) {
  const { runtime, thinkingMap, reportRef } = useLanggraphRuntime(
    threadId,
    caseId,
    initialMessages,
    attachmentAdapter,
    initialReportRef
  );
  const openGraph = useGraphModalStore((s) => s.openModal);
  const { user } = useAuth();
  const canUseGraph = caseId != null && canAccessModule(user, "graph");

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThinkingContext.Provider value={thinkingMap}>
        <EvidenceContextProvider
          caseId={canUseGraph && caseId != null ? caseId : null}
          reportRef={canUseGraph ? reportRef : null}
        >
        <div className="relative flex h-full flex-col">
          <div className="absolute inset-x-2 top-2 z-10 flex min-w-0 items-center gap-2">
            <SidebarTrigger className="size-8 text-muted-foreground/50 hover:bg-accent hover:text-foreground" />
            {canUseGraph && caseId != null && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5 px-2 text-xs text-muted-foreground/70 hover:text-foreground"
                onClick={() => openGraph({ caseId, reportRef })}
                title="查看知识图谱"
              >
                <Network className="h-3.5 w-3.5" />
                图谱
              </Button>
            )}
            {title && (
              <span className="min-w-0 flex-1 truncate text-sm text-foreground/60">
                {title}
              </span>
            )}
          </div>

          <PreviewProvider>
            <div className="flex min-h-0 flex-1">
              <div className="min-w-0 flex-1 overflow-hidden">
                <ChatThread
                  hasInitialMessages={!!initialMessages?.length}
                  attachmentDisabled={attachmentDisabled}
                  attachmentDisabledReason={attachmentDisabledReason}
                />
              </div>
              {/* 附件预览与证据抽屉均与对话并排：打开时对话区收缩左移 */}
              <PreviewSidePanel />
              {canUseGraph && <EvidenceDrawer variant="inline" />}
            </div>
          </PreviewProvider>
        </div>
        </EvidenceContextProvider>
      </ThinkingContext.Provider>
    </AssistantRuntimeProvider>
  );
}
