"use client";

import { type FC, useContext, useState, useEffect, useCallback, useRef } from "react";
import {
  ActionBarPrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useAui,
} from "@assistant-ui/react";
import "@assistant-ui/react-markdown/styles/dot.css";

import { cn } from "@/lib/utils";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import {
  ComposerAddAttachment,
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/assistant-ui/attachment";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  LoaderIcon,
  PencilIcon,
  RefreshCwIcon,
  SquareIcon,
  SparklesIcon,
} from "lucide-react";
import { ThinkingContext, type ThinkingState } from "@/lib/assistant-ui/thinking-context";
import {
  EvidenceContextProvider,
  useEvidenceContext,
} from "@/lib/assistant-ui/evidence-context";
import { useDebugMode } from "@/lib/hooks/use-debug-mode";
import { isLegacyUnauditableAuditDrilldownReply } from "@/lib/assistant-ui/annual-audit-reply-safety";

interface ChatThreadProps {
  suggestions?: string[];
  hasInitialMessages?: boolean;
  initialComposerValue?: string;
  attachmentDisabled?: boolean;
  attachmentDisabledReason?: string;
}

function ScrollFadeController({
  onScrollChange,
}: {
  onScrollChange: (atTop: boolean, atBottom: boolean) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const viewport = el.parentElement;
    if (!viewport) return;

    const update = () => {
      const { scrollTop, scrollHeight, clientHeight } = viewport;
      onScrollChange(scrollTop < 16, scrollTop >= scrollHeight - clientHeight - 16);
    };

    update();
    viewport.addEventListener("scroll", update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(viewport);
    return () => {
      viewport.removeEventListener("scroll", update);
      ro.disconnect();
    };
  }, [onScrollChange]);

  return <div ref={ref} className="sr-only" aria-hidden />;
}

function ComposerInitializer({ value }: { value: string }) {
  const aui = useAui();
  useEffect(() => {
    aui.composer().setText(value);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function ChatThread({
  suggestions,
  hasInitialMessages,
  initialComposerValue,
  attachmentDisabled,
  attachmentDisabledReason,
}: ChatThreadProps) {
  const [atTop, setAtTop] = useState(true);
  const [atBottom, setAtBottom] = useState(false);

  const handleScrollChange = useCallback((top: boolean, bottom: boolean) => {
    setAtTop(top);
    setAtBottom(bottom);
  }, []);

  return (
    <ThreadPrimitive.Root
      className="flex h-full flex-col bg-background text-sm"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--accent-color" as string]: "#0ea5e9",
        ["--accent-foreground" as string]: "#ffffff",
      }}
    >
      {initialComposerValue && <ComposerInitializer value={initialComposerValue} />}
      <ThreadPrimitive.Viewport
        autoScroll
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth px-4 pt-4"
      >
        <ScrollFadeController onScrollChange={handleScrollChange} />

        <div
          className="pointer-events-none absolute inset-x-0 top-0 z-10 h-12 bg-gradient-to-b from-background to-transparent transition-opacity duration-200"
          style={{ opacity: atTop ? 0 : 1 }}
        />

        <AuiIf condition={(s) => !hasInitialMessages && s.thread.isEmpty}>
          <ThreadWelcome suggestions={suggestions} />
        </AuiIf>

        <ThreadPrimitive.Messages>{() => <ThreadMessage />}</ThreadPrimitive.Messages>

        <ThreadPrimitive.ViewportFooter className="relative sticky bottom-0 mx-auto mt-auto flex w-full max-w-[var(--thread-max-width)] flex-col gap-3 overflow-visible rounded-t-3xl bg-background pb-4">
          <div
            className="pointer-events-none absolute inset-x-0 -top-12 h-12 bg-gradient-to-b from-transparent to-background transition-opacity duration-200"
            style={{ opacity: atBottom ? 0 : 1 }}
          />
          <ScrollToBottomButton />
          <Composer
            attachmentDisabled={attachmentDisabled}
            attachmentDisabledReason={attachmentDisabledReason}
          />
          <p className="text-center text-[10px] text-muted-foreground/40">
            AI 可能出错，请核实重要信息
          </p>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

const ThreadWelcome: FC<{ suggestions?: string[] }> = ({ suggestions }) => (
  <div className="mx-auto my-auto flex w-full max-w-[var(--thread-max-width)] flex-grow flex-col">
    <div className="flex w-full flex-grow flex-col items-center justify-center">
      <div className="flex size-full flex-col justify-center px-8">
        <div className="text-2xl font-semibold">有什么可以帮助您？</div>
        <div className="text-2xl text-muted-foreground/65">
          上传文档或直接提问，AI 将为您分析
        </div>
      </div>
    </div>
    {suggestions && suggestions.length > 0 && (
      <div className="grid w-full gap-2 pb-4 md:grid-cols-2">
        {suggestions.map((s, i) => (
          <ThreadPrimitive.Suggestion key={i} prompt={s} asChild>
            <Button
              variant="ghost"
              className="h-auto w-full flex-col items-start justify-start gap-1 rounded-2xl border px-5 py-4 text-left text-sm"
            >
              <span className="font-medium">{s}</span>
            </Button>
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    )}
  </div>
);

const ScrollToBottomButton: FC = () => (
  <ThreadPrimitive.ScrollToBottom asChild>
    <TooltipIconButton
      tooltip="滚动到底部"
      variant="outline"
      className="-top-12 absolute z-10 self-center rounded-full p-4 disabled:invisible"
    >
      <ArrowDownIcon />
    </TooltipIconButton>
  </ThreadPrimitive.ScrollToBottom>
);

const ComposerSendButton: FC = () => {
  const isUploading = useAuiState((s) => {
    const attachments = (s.composer as unknown as {
      attachments?: Array<{ status: { type: string } }>;
    }).attachments;
    return attachments?.some((a) => a.status.type === "running") ?? false;
  });
  const isEmpty = useAuiState((s) => !(s.composer as unknown as { text?: string }).text?.trim());
  const disabled = isUploading || isEmpty;

  return (
    <ComposerPrimitive.Send asChild>
      <TooltipIconButton
        tooltip={isUploading ? "文件上传中，请稍候" : "发送消息"}
        side="bottom"
        variant="default"
        size="icon"
        disabled={disabled}
        className="size-8 rounded-full disabled:opacity-25"
        style={{
          backgroundColor: "var(--accent-color)",
          color: "var(--accent-foreground)",
        }}
        aria-label="发送消息"
      >
        <ArrowUpIcon className="size-4" />
      </TooltipIconButton>
    </ComposerPrimitive.Send>
  );
};

const Composer: FC<{
  attachmentDisabled?: boolean;
  attachmentDisabledReason?: string;
}> = ({ attachmentDisabled, attachmentDisabledReason }) => (
  <ComposerPrimitive.Root className="relative flex w-full flex-col">
    <ComposerPrimitive.AttachmentDropzone asChild>
      <div className="flex w-full flex-col rounded-2xl border border-input bg-background px-1 pt-2 outline-none transition-shadow has-[textarea:focus-visible]:border-ring has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring/20 data-[dragging=true]:border-ring data-[dragging=true]:border-dashed data-[dragging=true]:bg-accent/50">
        <ComposerAttachments />
        <ComposerPrimitive.Input
          placeholder="发送消息..."
          className="mb-1 max-h-32 min-h-14 w-full resize-none bg-transparent px-4 pt-2 pb-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-0"
          rows={1}
          aria-label="消息输入"
        />
        <ComposerAction
          attachmentDisabled={attachmentDisabled}
          attachmentDisabledReason={attachmentDisabledReason}
        />
      </div>
    </ComposerPrimitive.AttachmentDropzone>
  </ComposerPrimitive.Root>
);

const ComposerAction: FC<{
  attachmentDisabled?: boolean;
  attachmentDisabledReason?: string;
}> = ({ attachmentDisabled, attachmentDisabledReason }) => (
  <div className="relative mx-2 mb-2 flex items-center justify-between">
    <ComposerAddAttachment
      disabled={attachmentDisabled}
      disabledReason={attachmentDisabledReason}
    />

    <AuiIf condition={(s) => !s.thread.isRunning}>
      <ComposerSendButton />
    </AuiIf>

    <AuiIf condition={(s) => s.thread.isRunning}>
      <ComposerPrimitive.Cancel asChild>
        <Button
          type="button"
          variant="default"
          size="icon"
          className="size-8 rounded-full"
          style={{
            backgroundColor: "var(--accent-color)",
            color: "var(--accent-foreground)",
          }}
          aria-label="停止生成"
        >
          <SquareIcon className="size-3 fill-current" />
        </Button>
      </ComposerPrimitive.Cancel>
    </AuiIf>
  </div>
);

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);
  const isEditing = useAuiState((s) => s.message.composer.isEditing);
  if (isEditing) return <EditComposer />;
  if (role === "user") return <UserMessage />;
  return <AssistantMessage />;
};

const UserMessage: FC = () => (
  <MessagePrimitive.Root
    data-role="user"
    className="animate-in fade-in slide-in-from-bottom-1 mx-auto grid w-full max-w-[var(--thread-max-width)] auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 py-2 duration-150"
  >
    <div className="col-start-2 flex flex-wrap justify-end gap-2 empty:hidden">
      <UserMessageAttachments />
    </div>

    <div className="relative col-start-2 min-w-0">
      <div className="wrap-break-word rounded-2xl bg-muted px-4 py-2.5 text-foreground">
        <MessagePrimitive.Parts />
      </div>
      <div className="-translate-y-1/2 -translate-x-full absolute top-1/2 left-0 pr-2">
        <UserActionBar />
      </div>
    </div>

    <BranchPicker className="col-span-full col-start-1 row-start-3 -mr-1 justify-end" />
  </MessagePrimitive.Root>
);

const UserActionBar: FC = () => (
  <ActionBarPrimitive.Root
    hideWhenRunning
    autohide="not-last"
    className="flex flex-col items-end"
  >
    <ActionBarPrimitive.Edit asChild>
      <TooltipIconButton tooltip="编辑" className="p-2">
        <PencilIcon />
      </TooltipIconButton>
    </ActionBarPrimitive.Edit>
  </ActionBarPrimitive.Root>
);

const EditComposer: FC = () => (
  <MessagePrimitive.Root className="mx-auto flex w-full max-w-[var(--thread-max-width)] flex-col px-2 py-3">
    <ComposerPrimitive.Root className="ml-auto flex w-full max-w-[85%] flex-col rounded-2xl bg-muted">
      <ComposerPrimitive.Input
        autoFocus
        className="min-h-14 w-full resize-none bg-transparent p-4 text-sm text-foreground outline-none"
      />
      <div className="mx-3 mb-3 flex items-center gap-2 self-end">
        <ComposerPrimitive.Cancel asChild>
          <Button variant="ghost" size="sm">取消</Button>
        </ComposerPrimitive.Cancel>
        <ComposerPrimitive.Send asChild>
          <Button size="sm">更新</Button>
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  </MessagePrimitive.Root>
);

const ReasoningText: FC<{ text: string }> = ({ text }) => {
  if (!text.trim()) return null;

  return (
    <details className="my-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        思考
      </summary>
      <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap break-words font-sans leading-relaxed">{text}</pre>
    </details>
  );
};

const AssistantMessage: FC = () => {
  const thinkingMap = useContext(ThinkingContext);
  const evidenceContext = useEvidenceContext();
  const messageId = useAuiState((s) => s.message.id);
  const isRunning = useAuiState((s) => s.message.status?.type === "running");
  const isLegacyUnauditableAuditReply = useAuiState((s) => {
    const custom = s.message.metadata.custom;
    return isLegacyUnauditableAuditDrilldownReply(custom);
  });
  const messageReportRef = useAuiState((s) => {
    const custom = s.message.metadata.custom as
      | { finalReportRef?: unknown }
      | undefined;
    const value = custom?.finalReportRef;
    return typeof value === "string" && value.trim().length > 0 ? value : null;
  });
  const thinking = messageId
    ? thinkingMap.get(messageId) ?? (isRunning ? [...thinkingMap.values()].find((t) => !t.isComplete) : undefined)
    : undefined;
  const [debugMode] = useDebugMode();

  return (
    <MessagePrimitive.Root
      data-role="assistant"
      className="animate-in fade-in slide-in-from-bottom-1 relative mx-auto w-full max-w-[var(--thread-max-width)] py-2 duration-150"
    >
      <div className="wrap-break-word px-2 leading-relaxed text-foreground">
        {debugMode && thinking && <NodeTracePanel thinking={thinking} />}
        {!isRunning && isLegacyUnauditableAuditReply && (
          <div
            role="alert"
            className="mb-3 rounded-md border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200"
          >
            此历史回复未建立可审计证据链，不能作为审计结论或底稿。
          </div>
        )}
        <EvidenceContextProvider
          caseId={evidenceContext.caseId}
          reportRef={messageReportRef}
        >
          <MessagePrimitive.Parts components={{ Text: MarkdownText, Reasoning: ReasoningText }} />
        </EvidenceContextProvider>
        <MessageError />
        <AuiIf condition={(s) => s.thread.isRunning && s.message.content.length === 0}>
          <div className="flex items-center gap-2 text-muted-foreground">
            <LoaderIcon className="size-4 animate-spin" />
          </div>
        </AuiIf>
      </div>

      <div className="mt-1 ml-2 flex min-h-6 items-center">
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
};

const MessageError: FC = () => (
  <MessagePrimitive.Error>
    <ErrorPrimitive.Root className="mt-2 rounded-md border border-destructive bg-destructive/10 p-3 text-destructive text-sm dark:bg-destructive/5 dark:text-red-200">
      <ErrorPrimitive.Message className="line-clamp-2" />
    </ErrorPrimitive.Root>
  </MessagePrimitive.Error>
);

const AssistantActionBar: FC = () => (
  <ActionBarPrimitive.Root
    hideWhenRunning
    autohide="not-last"
    className="-ml-1 flex gap-1 text-muted-foreground"
  >
    <ActionBarPrimitive.Copy asChild>
      <TooltipIconButton tooltip="复制">
        <AuiIf condition={(s) => s.message.isCopied}>
          <CheckIcon />
        </AuiIf>
        <AuiIf condition={(s) => !s.message.isCopied}>
          <CopyIcon />
        </AuiIf>
      </TooltipIconButton>
    </ActionBarPrimitive.Copy>
    <ActionBarPrimitive.ExportMarkdown asChild>
      <TooltipIconButton tooltip="导出 Markdown">
        <DownloadIcon />
      </TooltipIconButton>
    </ActionBarPrimitive.ExportMarkdown>
    <AuiIf condition={(s) => s.message.metadata.custom?.canReload === true}>
      <ActionBarPrimitive.Reload asChild>
        <TooltipIconButton tooltip="重新生成">
          <RefreshCwIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Reload>
    </AuiIf>
  </ActionBarPrimitive.Root>
);

const BranchPicker: FC<React.ComponentPropsWithoutRef<typeof BranchPickerPrimitive.Root>> = ({
  className,
  ...rest
}) => (
  <BranchPickerPrimitive.Root
    hideWhenSingleBranch
    className={cn("-ml-2 mr-2 inline-flex items-center text-muted-foreground text-xs", className)}
    {...rest}
  >
    <BranchPickerPrimitive.Previous asChild>
      <TooltipIconButton tooltip="上一版本">
        <ChevronLeftIcon />
      </TooltipIconButton>
    </BranchPickerPrimitive.Previous>
    <span className="font-medium">
      <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
    </span>
    <BranchPickerPrimitive.Next asChild>
      <TooltipIconButton tooltip="下一版本">
        <ChevronRightIcon />
      </TooltipIconButton>
    </BranchPickerPrimitive.Next>
  </BranchPickerPrimitive.Root>
);

// ── 节点跟踪面板（debug 开启时才渲染）──────────────────

const NodeTracePanel: FC<{ thinking: ThinkingState }> = ({ thinking }) => {
  const { steps, isComplete, startedAt, completedAt } = thinking;
  const [expanded, setExpanded] = useState(true);

  const hasContent = steps.length > 0;
  const elapsedSeconds = isComplete && completedAt ? Math.round((completedAt - startedAt) / 1000) : null;

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-border/40 bg-muted/20">
      <button
        type="button"
        onClick={hasContent ? () => setExpanded((v) => !v) : undefined}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground/70 transition-colors",
          hasContent && "hover:text-muted-foreground"
        )}
      >
        {isComplete ? (
          <SparklesIcon className="size-3 shrink-0 text-muted-foreground/50" />
        ) : (
          <span className="size-2 shrink-0 animate-pulse rounded-full" style={{ backgroundColor: "var(--accent-color)" }} />
        )}
        <span className="font-medium">
          {isComplete
            ? elapsedSeconds != null && elapsedSeconds > 0
              ? `节点跟踪（${steps.length} 步，${elapsedSeconds}s）`
              : `节点跟踪（${steps.length} 步）`
            : `节点跟踪（${steps.length} 步，运行中…）`}
        </span>
        {hasContent && (
          <ChevronDownIcon className={cn("ml-auto size-3 shrink-0 transition-transform duration-200", expanded && "rotate-180")} />
        )}
      </button>

      {hasContent && expanded && (
        <div className="flex max-h-80 flex-col gap-1 overflow-y-auto border-t border-border/30 px-3 py-2">
          {steps.map((step, i) => (
            <NodeTraceItem key={i} step={step} />
          ))}
        </div>
      )}
    </div>
  );
};

const NodeTraceItem: FC<{ step: { title: string; nodeType: string; payload?: Record<string, unknown> } }> = ({ step }) => {
  const [open, setOpen] = useState(false);
  const hasPayload = !!step.payload && Object.keys(step.payload).length > 0;
  return (
    <div className="rounded-md border border-border/30 bg-background/40">
      <button
        type="button"
        onClick={hasPayload ? () => setOpen((v) => !v) : undefined}
        className={cn(
          "flex w-full items-start gap-2 px-2 py-1.5 text-left text-xs text-muted-foreground/80",
          hasPayload && "hover:text-foreground"
        )}
      >
        <span className="mt-0.5 shrink-0 rounded bg-muted px-1 py-0 font-mono text-[10px] text-muted-foreground/70">
          {step.nodeType || "node"}
        </span>
        <span className="min-w-0 flex-1 break-words leading-relaxed">{step.title}</span>
        {hasPayload && (
          <ChevronDownIcon className={cn("mt-0.5 size-3 shrink-0 transition-transform", open && "rotate-180")} />
        )}
      </button>
      {hasPayload && open && (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words border-t border-border/30 px-2 py-1.5 text-[11px] text-muted-foreground/70">
{JSON.stringify(step.payload, null, 2)}
        </pre>
      )}
    </div>
  );
};
