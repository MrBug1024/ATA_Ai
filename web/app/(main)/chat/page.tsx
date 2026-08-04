"use client";

import {
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  Suspense,
  type KeyboardEvent,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SidebarTrigger } from "@/components/ui/sidebar";
import {
  AlertCircle,
  ArrowUpIcon,
  File as FileIcon,
  Loader2,
  Paperclip,
  Scale,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCases, type Case } from "@/lib/hooks/use-cases";
import type { FileItem } from "@/lib/types/chat-upload";
import {
  useChatComposerAttachments,
  type PendingAttachment,
} from "@/lib/hooks/use-chat-composer-attachments";
import { CommandPalette, CasePickerDropdown } from "@/components/chat/slash-picker";
import {
  pendingMessageKey,
  type PendingChatPayload,
} from "@/lib/utils/pending-chat-payload";
import {
  filterCommands,
  parseSlash,
  stripSlashLine,
  type SlashCommandDef,
} from "@/lib/utils/slash-commands";

const PICKER_MAX = 8;

const COMMANDS: readonly SlashCommandDef[] = [
  { key: "case", label: "/case", description: "选择要执行的年审项目" },
];

interface SelectedCase {
  case_id: number;
  case_name?: string;
  case_type?: string;
  entity_name?: string;
}

type PickerMode =
  | { kind: "none" }
  | { kind: "command"; matches: SlashCommandDef[] }
  | { kind: "case"; filter: string };

function ChatPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialCaseIdParam = searchParams.get("caseId");
  const initialCaseId = initialCaseIdParam ? Number(initialCaseIdParam) : null;

  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCase, setSelectedCase] = useState<SelectedCase | null>(
    initialCaseId != null && !Number.isNaN(initialCaseId) ? { case_id: initialCaseId } : null
  );
  const [highlightIdx, setHighlightIdx] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const slash = useMemo(() => parseSlash(query), [query]);
  const mode: PickerMode = useMemo(() => {
    if (!slash) return { kind: "none" };
    const matched = COMMANDS.find((c) => c.key === slash.command);
    if (matched) return { kind: "case", filter: slash.arg };
    return { kind: "command", matches: filterCommands(COMMANDS, slash.command) };
  }, [slash]);
  const pickerOpen = mode.kind !== "none";

  const { cases, isLoading: casesLoading, setKeyword } = useCases();

  useEffect(() => {
    if (mode.kind === "case") setKeyword(mode.filter);
  }, [mode, setKeyword]);

  useEffect(() => {
    if (!selectedCase || selectedCase.case_name) return;
    const found = cases.find((c) => c.case_id === selectedCase.case_id);
    if (found) {
      setSelectedCase({
        case_id: found.case_id,
        case_name: found.case_name,
        case_type: found.case_type,
        entity_name: found.entity_name,
      });
    }
  }, [cases, selectedCase]);

  const visibleCases = useMemo(() => cases.slice(0, PICKER_MAX), [cases]);

  const optionCount =
    mode.kind === "command"
      ? mode.matches.length
      : mode.kind === "case"
      ? visibleCases.length
      : 0;

  // Reset highlight when the picker contents change (mode switch or filter change).
  const modeSignature =
    mode.kind === "command"
      ? `cmd:${mode.matches.map((c) => c.key).join(",")}`
      : mode.kind === "case"
      ? `case:${mode.filter}`
      : "none";
  useEffect(() => {
    setHighlightIdx(0);
  }, [modeSignature]);

  const insertCommand = useCallback((cmd: SlashCommandDef) => {
    setQuery((prev) => {
      const m = parseSlash(prev);
      if (!m) return prev;
      // Replace just the slash-command portion of the first line with the
      // full trigger + a trailing space, preserving any text below.
      const rest = prev.slice(m.lineEnd);
      return `/${cmd.key} ${rest}`;
    });
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const selectCase = useCallback((c: Case) => {
    setSelectedCase({
      case_id: c.case_id,
      case_name: c.case_name,
      case_type: c.case_type,
      entity_name: c.entity_name,
    });
    setQuery((prev) => stripSlashLine(prev));
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  // 附件上传状态机抽到 hook(见 use-chat-composer-attachments)。
  const {
    attachments,
    isUploading,
    fileInputRef,
    removeAttachment,
    handleAttachClick,
    handleFileInputChange,
  } = useChatComposerAttachments(selectedCase?.case_id ?? null);

  const cancelSlash = useCallback(() => {
    setQuery((prev) => stripSlashLine(prev));
  }, []);

  const confirmHighlight = useCallback(() => {
    if (mode.kind === "command") {
      const cmd = mode.matches[highlightIdx];
      if (cmd) insertCommand(cmd);
    } else if (mode.kind === "case") {
      const c = visibleCases[highlightIdx];
      if (c) selectCase(c);
    }
  }, [mode, highlightIdx, visibleCases, insertCommand, selectCase]);

  const handleSubmit = useCallback(() => {
    if (pickerOpen || isUploading) return;
    const content = query.trim();
    if (!content || isLoading) return;

    setIsLoading(true);
    const threadId = crypto.randomUUID();
    const completed = attachments.filter(
      (a): a is PendingAttachment & { fileItem: FileItem } => a.status === "complete" && !!a.fileItem
    );
    const payload: PendingChatPayload = {
      content,
      attachments: completed.map((a) => ({
        id: a.id,
        type: "file",
        name: a.fileItem.name,
        contentType: a.fileItem.content_type,
        content: [],
        status: { type: "complete" },
      })),
      fileItemEntries: completed.map((a) => [a.id, a.fileItem]),
    };
    sessionStorage.setItem(pendingMessageKey(threadId), JSON.stringify(payload));
    const cid = selectedCase?.case_id;
    const qs = cid !== undefined ? `?caseId=${cid}` : "";
    router.push(`/chat/${threadId}${qs}`);
  }, [query, isLoading, router, selectedCase, pickerOpen, isUploading, attachments]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (pickerOpen) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setHighlightIdx((i) => (optionCount === 0 ? 0 : Math.min(i + 1, optionCount - 1)));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setHighlightIdx((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
          e.preventDefault();
          confirmHighlight();
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          cancelSlash();
          return;
        }
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [pickerOpen, optionCount, confirmHighlight, cancelSlash, handleSubmit]
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <SidebarTrigger className="size-9 shrink-0 text-muted-foreground hover:bg-accent hover:text-foreground" />
      </header>

      <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-4 pb-20">
        <h1 className="animate-in fade-in slide-in-from-bottom-1 fill-mode-both text-center font-semibold text-2xl duration-200">
          有什么可以帮助您？
        </h1>
        <p className="animate-in fade-in slide-in-from-bottom-1 fill-mode-both mt-2 text-center text-muted-foreground text-xl delay-75 duration-200">
          上传账套与审计资料，AI 将执行年审分析、证据追溯、图谱构建与报告生成
        </p>
        <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1">
          {COMMANDS.map((cmd) => (
            <span key={cmd.key} className="flex items-center gap-1.5 text-xs text-muted-foreground/55">
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{cmd.label}</code>
              {cmd.description}
            </span>
          ))}
        </div>

        <div className="animate-in fade-in slide-in-from-bottom-2 fill-mode-both relative mt-10 w-full max-w-2xl delay-150 duration-200">
          {mode.kind === "command" && (
            <CommandPalette
              matches={mode.matches}
              highlightIdx={highlightIdx}
              onHover={setHighlightIdx}
              onPick={insertCommand}
            />
          )}
          {mode.kind === "case" && (
            <CasePickerDropdown
              cases={visibleCases}
              isLoading={casesLoading}
              highlightIdx={highlightIdx}
              onHover={setHighlightIdx}
              onPick={selectCase}
            />
          )}

          <div className="flex w-full flex-col gap-2 rounded-3xl border bg-background p-3 transition-shadow focus-within:border-ring/75 focus-within:ring-2 focus-within:ring-ring/20">
            {selectedCase && (
              <SelectedCaseChip
                selected={selectedCase}
                onClear={() => setSelectedCase(null)}
              />
            )}

            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {attachments.map((a) => (
                  <AttachmentChip key={a.id} attachment={a} onRemove={removeAttachment} />
                ))}
              </div>
            )}

            <textarea
              ref={textareaRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={selectedCase ? "向年审项目提问或要求执行审计程序…" : "发送消息，或输入 / 选择年审项目"}
              rows={1}
              className="max-h-32 min-h-10 w-full resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/60"
            />

            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={handleFileInputChange}
            />

            <div className="flex items-center justify-between">
              <AttachmentButton
                hasCase={selectedCase != null}
                onClick={handleAttachClick}
              />
              <button
                type="button"
                disabled={isLoading || !query.trim() || pickerOpen || isUploading}
                onClick={handleSubmit}
                aria-label={
                  isLoading ? "创建中" : isUploading ? "上传中" : "发送消息"
                }
                title={isUploading ? "文件上传中，请稍候" : undefined}
                className={cn(
                  "flex size-8 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-80",
                  (isLoading || !query.trim() || pickerOpen || isUploading) &&
                    "cursor-not-allowed opacity-25"
                )}
              >
                {isLoading ? (
                  <span className="size-3.5 animate-spin rounded-full border-2 border-background border-t-transparent" />
                ) : (
                  <ArrowUpIcon className="size-4" />
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AttachmentButton({
  hasCase,
  onClick,
}: {
  hasCase: boolean;
  onClick: () => void;
}) {
  if (hasCase) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label="上传附件"
        title="上传附件"
        className="flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-accent hover:text-foreground"
      >
        <Paperclip className="size-4" />
      </button>
    );
  }
  const reason = "需要选择年审项目才能上传附件";
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-disabled="true"
            aria-label={reason}
            onClick={(e) => e.preventDefault()}
            className="flex size-8 shrink-0 cursor-not-allowed items-center justify-center rounded-full text-muted-foreground/40 hover:text-muted-foreground/60"
          >
            <Paperclip className="size-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top">{reason}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function AttachmentChip({
  attachment,
  onRemove,
}: {
  attachment: PendingAttachment;
  onRemove: (id: string) => void;
}) {
  const isUploading = attachment.status === "uploading";
  const isError = attachment.status === "error";
  const name = attachment.fileItem?.name ?? attachment.file.name;
  const preview = attachment.previewUrl;

  if (preview) {
    return (
      <div
        className={cn(
          "group relative size-16 shrink-0 overflow-hidden rounded-md border bg-muted",
          isError ? "border-destructive/60" : "border-border"
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={preview}
          alt={name}
          className={cn("size-full object-cover", (isUploading || isError) && "opacity-50")}
        />
        {isUploading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30">
            <Loader2 className="size-4 animate-spin text-white" />
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex items-center justify-center bg-destructive/20">
            <AlertCircle className="size-4 text-destructive" />
          </div>
        )}
        <span className="absolute bottom-0 left-0 right-0 truncate bg-black/60 px-1 py-0.5 text-[9px] leading-tight text-white">
          {name}
        </span>
        <button
          type="button"
          onClick={() => onRemove(attachment.id)}
          aria-label="删除附件"
          className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-black/70 text-white opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
        >
          <X className="size-2.5" />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex max-w-[180px] items-center gap-1.5 rounded-md px-2 py-1 text-xs",
        isError
          ? "border border-destructive/40 bg-destructive/8 text-destructive"
          : "bg-muted text-muted-foreground"
      )}
      title={isError ? attachment.errorReason : undefined}
    >
      {isUploading ? (
        <Loader2 className="size-3 shrink-0 animate-spin" />
      ) : isError ? (
        <AlertCircle className="size-3 shrink-0" />
      ) : (
        <FileIcon className="size-3 shrink-0 text-muted-foreground/70" />
      )}
      <span className="truncate">{name}</span>
      {isError && <span className="shrink-0 text-[10px]">上传失败</span>}
      <button
        type="button"
        onClick={() => onRemove(attachment.id)}
        aria-label="删除附件"
        className="ml-0.5 shrink-0 rounded-full text-current/60 hover:text-current"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}

function SelectedCaseChip({
  selected,
  onClear,
}: {
  selected: SelectedCase;
  onClear: () => void;
}) {
  return (
    <div className="flex items-center gap-2 self-start rounded-full border border-border/60 bg-muted/50 py-1 pl-2.5 pr-1 text-xs">
      <Scale className="size-3 text-muted-foreground/60" />
      <span className="max-w-[220px] truncate text-foreground/85">
        {selected.case_name ?? `年审项目 #${selected.case_id}`}
      </span>
      <span className="font-mono text-[10px] text-muted-foreground/50">#{selected.case_id}</span>
      <button
        type="button"
        onClick={onClear}
        className="ml-0.5 flex size-4 items-center justify-center rounded-full text-muted-foreground/60 hover:bg-accent hover:text-foreground"
        aria-label="移除已选年审项目"
      >
        <X className="size-2.5" />
      </button>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense>
      <ChatPageClient />
    </Suspense>
  );
}
