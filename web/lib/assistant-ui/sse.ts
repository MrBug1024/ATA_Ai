import type { ThinkingUpdate } from "./thinking-context";
import type { DbMessageContentParts } from "./types";
import { chatInvoke, type ChatInvokeRequest } from "@/lib/backend/langgraph";
import {
  isAttachmentJobRef,
  type AttachmentJobRef,
} from "@/lib/backend/generated-artifacts";

/**
 * LangGraph SSE 事件契约(discriminated union)。
 * 与 CLAUDE.md 「SSE 事件格式」一节一一对应;未知事件归入 `unknown`。
 */
export type LangGraphSseEvent =
  | {
      type: "start";
      threadId?: string;
      query?: string;
      currentCaseId?: number;
      uploadedFileCount?: number;
    }
  | { type: "node"; node: string; summary?: string; payload?: Record<string, unknown> }
  | { type: "text_chunk"; text: string }
  | { type: "reasoning_chunk"; text: string }
  | { type: "section_start"; sectionId: string; title: string; audience?: string }
  | { type: "section_chunk"; sectionId: string; text: string }
  | { type: "section_reasoning_chunk"; sectionId: string; text: string }
  | { type: "section_done"; sectionId: string }
  | {
      type: "final";
      finalReportRef?: string;
      finalReport?: string;
      metadata?: FinalResponseMetadata;
    }
  | { type: "done"; threadId?: string }
  | { type: "error"; threadId?: string; message: string }
  | { type: "unknown"; event: string; data: Record<string, unknown> };

export interface StreamContentSnapshot {
  text: string;
  parts?: DbMessageContentParts;
}

/**
 * Response-scoped graph/evidence snapshot carried by the terminal SSE event.
 * All values are retained on the assistant message that produced them, rather
 * than being resolved from mutable thread-wide state after another turn runs.
 */
export interface FinalResponseMetadata {
  assistantMessageId?: string;
  routeDecision?: Record<string, unknown> | null;
  traceItems?: Record<string, unknown>[];
  citationCoverage?: Record<string, unknown>;
  responseAnalysisRuns?: Record<string, unknown>[];
  unresolvedRelations?: Record<string, unknown>[];
  unresolvedClaims?: Record<string, unknown>[];
  attachmentJob?: AttachmentJobRef | null;
}

type StreamContentPart = DbMessageContentParts[number];

interface StreamSection {
  sectionId: string;
  title: string;
  audience?: string;
  text: string;
  reasoning: string;
  done: boolean;
  order: number;
}

const DEFAULT_SECTION_TITLES: Record<string, string> = {
  "1": "数据洗脱",
  "2": "资产清单",
  "3": "资金流(白手套)",
  "4": "时效看板",
  "5": "重整盘活",
  "6": "博弈策略",
  "7": "督办SOP",
  "8": "增量回款+下钻",
  R1: "对账总览",
  R2: "差异归因",
  R3: "经验与规则建议",
};

function stringField(data: Record<string, unknown>, key: string): string | undefined {
  const value = data[key];
  return typeof value === "string" ? value : undefined;
}

function numberField(data: Record<string, unknown>, key: string): number | undefined {
  const value = data[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function recordField(data: Record<string, unknown>, key: string): Record<string, unknown> | undefined {
  const value = data[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function recordArrayField(data: Record<string, unknown>, key: string): Record<string, unknown>[] | undefined {
  const value = data[key];
  if (!Array.isArray(value)) return undefined;
  return value.filter(
    (item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null && !Array.isArray(item)
  );
}

function normalizeHeading(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function sectionSortKey(section: StreamSection): number {
  if (/^\d+$/.test(section.sectionId)) return Number(section.sectionId);
  const review = /^R(\d+)$/i.exec(section.sectionId);
  if (review) return 100 + Number(review[1]);
  return 1000 + section.order;
}

function sectionHeading(section: StreamSection): string {
  const title = normalizeHeading(section.title) || DEFAULT_SECTION_TITLES[section.sectionId] || "报告分段";
  return `## ${section.sectionId}. ${title}`;
}

function sectionBlock(section: StreamSection): string {
  const body = section.text;
  const loading = section.done ? "" : body ? "\n\n_生成中..._" : "_生成中..._";
  return `${sectionHeading(section)}\n\n${body}${loading}`.trimEnd();
}

class SectionStreamAccumulator {
  private defaultText = "";
  private defaultReasoning = "";
  private readonly sections = new Map<string, StreamSection>();
  private order = 0;

  get usesSnapshots(): boolean {
    return this.sections.size > 0 || this.defaultReasoning.length > 0;
  }

  get hasTextContent(): boolean {
    if (this.defaultText.length > 0) return true;
    return Array.from(this.sections.values()).some((section) => section.text.length > 0);
  }

  appendDefaultText(text: string): void {
    this.defaultText += text;
  }

  appendDefaultReasoning(text: string): void {
    this.defaultReasoning += text;
  }

  startSection(sectionId: string, title: string, audience?: string): void {
    const section = this.ensureSection(sectionId);
    section.title = title || section.title;
    section.audience = audience ?? section.audience;
  }

  appendSectionText(sectionId: string, text: string): void {
    this.ensureSection(sectionId).text += text;
  }

  appendSectionReasoning(sectionId: string, text: string): void {
    this.ensureSection(sectionId).reasoning += text;
  }

  completeSection(sectionId: string): void {
    this.ensureSection(sectionId).done = true;
  }

  snapshot(): StreamContentSnapshot {
    const blocks: string[] = [];
    const parts: StreamContentPart[] = [];

    if (this.defaultText) {
      blocks.push(this.defaultText);
      parts.push({ type: "text", text: this.defaultText });
    }
    if (this.defaultReasoning) {
      parts.push({ type: "reasoning", text: this.defaultReasoning });
    }

    const sections = Array.from(this.sections.values()).sort((a, b) => {
      const byKey = sectionSortKey(a) - sectionSortKey(b);
      return byKey || a.order - b.order;
    });

    for (const section of sections) {
      const parentId = `section-${section.sectionId}`;
      const block = sectionBlock(section);
      blocks.push(block);
      parts.push({ type: "text", text: block, parentId });
      if (section.reasoning) {
        parts.push({ type: "reasoning", text: section.reasoning, parentId });
      }
    }

    return { text: blocks.join("\n\n"), parts };
  }

  private ensureSection(sectionId: string): StreamSection {
    const existing = this.sections.get(sectionId);
    if (existing) return existing;

    const section: StreamSection = {
      sectionId,
      title: DEFAULT_SECTION_TITLES[sectionId] ?? "",
      text: "",
      reasoning: "",
      done: false,
      order: this.order++,
    };
    this.sections.set(sectionId, section);
    return section;
  }
}

export function toLangGraphEvent(
  event: string,
  data: Record<string, unknown>
): LangGraphSseEvent {
  switch (event) {
    case "start": {
      const start: Extract<LangGraphSseEvent, { type: "start" }> = { type: "start" };
      const threadId = stringField(data, "thread_id");
      const query = stringField(data, "query");
      const currentCaseId = numberField(data, "current_case_id");
      const uploadedFileCount = numberField(data, "uploaded_file_count");
      if (threadId) start.threadId = threadId;
      if (query) start.query = query;
      if (currentCaseId !== undefined) start.currentCaseId = currentCaseId;
      if (uploadedFileCount !== undefined) start.uploadedFileCount = uploadedFileCount;
      return start;
    }
    case "node":
      return {
        type: "node",
        node: typeof data.node === "string" ? data.node : "",
        summary: typeof data.summary === "string" ? data.summary : undefined,
        payload:
          typeof data.payload === "object" && data.payload !== null
            ? (data.payload as Record<string, unknown>)
            : undefined,
      };
    case "text_chunk":
      return { type: "text_chunk", text: typeof data.text === "string" ? data.text : "" };
    case "reasoning_chunk":
      return { type: "reasoning_chunk", text: typeof data.text === "string" ? data.text : "" };
    case "section_start":
      return {
        type: "section_start",
        sectionId: stringField(data, "section_id") ?? "",
        title: stringField(data, "title") ?? "",
        audience: stringField(data, "audience"),
      };
    case "section_chunk":
      return {
        type: "section_chunk",
        sectionId: stringField(data, "section_id") ?? "",
        text: stringField(data, "text") ?? "",
      };
    case "section_reasoning_chunk":
      return {
        type: "section_reasoning_chunk",
        sectionId: stringField(data, "section_id") ?? "",
        text: stringField(data, "text") ?? "",
      };
    case "section_done":
      return { type: "section_done", sectionId: stringField(data, "section_id") ?? "" };
    case "final":
      {
        const final: Extract<LangGraphSseEvent, { type: "final" }> = {
        type: "final",
        finalReportRef:
          typeof data.final_report_ref === "string" && data.final_report_ref
            ? data.final_report_ref
            : undefined,
        finalReport: typeof data.final_report === "string" ? data.final_report : undefined,
        };
        const metadata: FinalResponseMetadata = {};
        const assistantMessageId = stringField(data, "assistant_message_id");
        const routeDecision = recordField(data, "route_decision");
        const traceItems = recordArrayField(data, "trace_items");
        const citationCoverage = recordField(data, "citation_coverage");
        const responseAnalysisRuns = recordArrayField(data, "response_analysis_runs");
        const unresolvedRelations = recordArrayField(data, "unresolved_relations");
        const unresolvedClaims = recordArrayField(data, "unresolved_claims");
        const attachmentJobCandidate = data.attachment_job;
        const attachmentJob = isAttachmentJobRef(attachmentJobCandidate) &&
          (!assistantMessageId ||
            !attachmentJobCandidate.assistant_turn_id ||
            attachmentJobCandidate.assistant_turn_id === assistantMessageId)
          ? attachmentJobCandidate
          : attachmentJobCandidate === null
            ? null
            : undefined;
        if (assistantMessageId) metadata.assistantMessageId = assistantMessageId;
        if (routeDecision) metadata.routeDecision = routeDecision;
        if (traceItems !== undefined) metadata.traceItems = traceItems;
        if (citationCoverage) metadata.citationCoverage = citationCoverage;
        if (responseAnalysisRuns !== undefined) metadata.responseAnalysisRuns = responseAnalysisRuns;
        if (unresolvedRelations !== undefined) metadata.unresolvedRelations = unresolvedRelations;
        if (unresolvedClaims !== undefined) metadata.unresolvedClaims = unresolvedClaims;
        if (attachmentJob !== undefined) metadata.attachmentJob = attachmentJob;
        if (Object.keys(metadata).length > 0) final.metadata = metadata;
        return final;
      }
    case "done": {
      const done: Extract<LangGraphSseEvent, { type: "done" }> = { type: "done" };
      const threadId = stringField(data, "thread_id");
      if (threadId) done.threadId = threadId;
      return done;
    }
    case "error": {
      const err: Extract<LangGraphSseEvent, { type: "error" }> = {
        type: "error",
        message: typeof data.message === "string" && data.message ? data.message : "Stream error",
      };
      const threadId = stringField(data, "thread_id");
      if (threadId) err.threadId = threadId;
      return err;
    }
    default:
      return { type: "unknown", event, data };
  }
}

export type RunStreamRequest = ChatInvokeRequest;

export interface StreamCallbacks {
  onChunk: (content: string) => void;
  onReplace?: (snapshot: StreamContentSnapshot) => void;
  onAbortRef: (cancel: () => void) => void;
  onThinking?: (update: ThinkingUpdate) => void;
  onFinal?: (
    finalReportRef: string,
    finalReport?: string,
    metadata?: FinalResponseMetadata
  ) => void;
}

export async function* parseSseStream(
  response: Response,
  signal?: AbortSignal
): AsyncGenerator<LangGraphSseEvent> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const onAbort = () => reader.cancel();
  signal?.addEventListener("abort", onAbort);

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    let currentEvent = "";
    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          const dataStr = line.slice(5).trim();
          if (!dataStr) continue;

          let parsed: Record<string, unknown> | null = null;
          try {
            parsed = JSON.parse(dataStr);
          } catch {
            continue;
          }
          if (parsed) {
            yield toLangGraphEvent(currentEvent || "message", parsed);
            currentEvent = "";
          }
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
    reader.releaseLock();
  }
}

export async function runStream(
  request: RunStreamRequest,
  callbacks: StreamCallbacks,
  scheduleFlush: (fn: () => void) => void,
  _cancelFlush: () => void,
  flushNow: () => void
): Promise<void> {
  const abortController = new AbortController();

  const response = await chatInvoke(request, abortController.signal);

  callbacks.onAbortRef(() => abortController.abort());
  const accumulator = new SectionStreamAccumulator();
  const emitSnapshot = () => {
    callbacks.onReplace?.(accumulator.snapshot());
    scheduleFlush(flushNow);
  };

  try {
    for await (const ev of parseSseStream(response, abortController.signal)) {
      switch (ev.type) {
        case "node":
          if (ev.summary || ev.node) {
            callbacks.onThinking?.({
              type: "node",
              title: ev.summary || ev.node,
              nodeType: ev.node,
              payload: ev.payload,
            });
          }
          break;
        case "text_chunk":
          if (ev.text) {
            accumulator.appendDefaultText(ev.text);
            if (accumulator.usesSnapshots) {
              emitSnapshot();
            } else {
              callbacks.onChunk(ev.text);
              scheduleFlush(flushNow);
            }
          }
          break;
        case "reasoning_chunk":
          if (ev.text) {
            accumulator.appendDefaultReasoning(ev.text);
            emitSnapshot();
          }
          break;
        case "section_start":
          if (ev.sectionId) {
            accumulator.startSection(ev.sectionId, ev.title, ev.audience);
            emitSnapshot();
          }
          break;
        case "section_chunk":
          if (ev.sectionId && ev.text) {
            accumulator.appendSectionText(ev.sectionId, ev.text);
            emitSnapshot();
          }
          break;
        case "section_reasoning_chunk":
          if (ev.sectionId && ev.text) {
            accumulator.appendSectionReasoning(ev.sectionId, ev.text);
            emitSnapshot();
          }
          break;
        case "section_done":
          if (ev.sectionId) {
            accumulator.completeSection(ev.sectionId);
            emitSnapshot();
          }
          break;
        case "final":
          // 故意不把 final_report 写回消息内容：
          // text_chunk 累加的内容已经是流式可见结果，final_report 是后端清理过的另一版本，
          // 替换会让 smooth 揭示动画从头重放一遍。这里只在没有流式正文时兜底使用 final_report。
          if (!accumulator.hasTextContent && ev.finalReport) {
            callbacks.onReplace?.({ text: ev.finalReport });
            scheduleFlush(flushNow);
          }
          flushNow();
          // The final payload is the persisted, authoritative reply. It can
          // include citations that are not present in token chunks, so forward
          // it even if a report reference is absent.
          if (ev.finalReportRef || ev.finalReport || ev.metadata) {
            callbacks.onFinal?.(ev.finalReportRef ?? "", ev.finalReport, ev.metadata);
          }
          break;
        case "error":
          throw new Error(ev.message);
      }
    }
  } catch (err) {
    if (abortController.signal.aborted) return;
    throw err;
  }
}
