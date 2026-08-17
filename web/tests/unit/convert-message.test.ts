// tests/unit/convert-message.test.ts
import { describe, it, expect } from "vitest";
import { convertDbMessage } from "@/lib/assistant-ui/convert-message";
import type { DbMessage } from "@/lib/assistant-ui/types";

const baseMsg: DbMessage = {
  id: "msg-1",
  conversationId: "conv-1",
  role: "user",
  content: "Hello",
  metadata: null,
  createdAt: new Date("2024-01-01"),
};

describe("convertDbMessage", () => {
  it("用户消息原样返回内容", () => {
    const result = convertDbMessage(baseMsg);
    expect(result.role).toBe("user");
    expect(result.content).toBe("Hello");
    expect(result.id).toBe("msg-1");
  });

  it("助手消息去除 think 标签", () => {
    const msg: DbMessage = { ...baseMsg, role: "assistant", content: "<think>思考</think>答案" };
    const result = convertDbMessage(msg);
    expect(result.content).toBe("答案");
  });

  it("助手消息存在结构化 parts 时优先透传 parts", () => {
    const parts = [
      { type: "text", text: "正文", parentId: "section-1" },
      { type: "reasoning", text: "思考", parentId: "section-1" },
    ] as DbMessage["_contentParts"];
    const msg: DbMessage = {
      ...baseMsg,
      role: "assistant",
      content: "<think>思考</think>正文",
      _contentParts: parts,
    };
    const result = convertDbMessage(msg);
    expect(result.content).toBe(parts);
  });

  it("无附件时 attachments 为 undefined", () => {
    const result = convertDbMessage(baseMsg);
    expect(result.attachments).toBeUndefined();
  });

  it("_attachments 透传到 attachments", () => {
    const attachments = [
      {
        id: "att-1",
        type: "file",
        name: "a.pdf",
        contentType: "application/pdf",
        content: [],
        status: { type: "complete" },
      },
    ] as unknown as DbMessage["_attachments"];
    const msg: DbMessage = { ...baseMsg, _attachments: attachments };
    const result = convertDbMessage(msg);
    expect(result.attachments).toBe(attachments);
  });

  it("createdAt 转换为 Date 对象", () => {
    const result = convertDbMessage(baseMsg);
    expect(result.createdAt).toBeInstanceOf(Date);
  });

  it("_status 透传", () => {
    const msg: DbMessage = { ...baseMsg, _status: { type: "incomplete", reason: "error", error: "Oops" } };
    const result = convertDbMessage(msg);
    expect(result.status).toEqual({ type: "incomplete", reason: "error", error: "Oops" });
  });

  it("只把本地可重放标记暴露给操作栏", () => {
    expect(convertDbMessage(baseMsg).metadata?.custom?.canReload).toBe(false);
    expect(
      convertDbMessage({ ...baseMsg, role: "assistant", _canReload: true }).metadata
        ?.custom?.canReload
    ).toBe(true);
  });

  it("preserves the final report reference for each assistant reply", () => {
    const result = convertDbMessage({
      ...baseMsg,
      role: "assistant",
      metadata: { final_report_ref: "report-for-this-message" },
    });
    expect(result.metadata?.custom?.finalReportRef).toBe("report-for-this-message");
  });

  it("keeps a streamed message's local custom evidence reference", () => {
    const result = convertDbMessage({
      ...baseMsg,
      role: "assistant",
      metadata: { custom: { finalReportRef: "stream-report-ref" } },
    });
    expect(result.metadata?.custom?.finalReportRef).toBe("stream-report-ref");
  });

  it("preserves response-scoped evidence metadata for the same assistant message", () => {
    const result = convertDbMessage({
      ...baseMsg,
      role: "assistant",
      metadata: {
        final_report_ref: "report:turn-1",
        custom: {
          finalReportRef: "report:turn-1",
          traceItems: [{ citation_id: "1", claim_id: 701 }],
          citationCoverage: { total_claims: 1, cited_claims: 1 },
          unresolvedRelations: [{ relation_key: "r-1" }],
          unresolvedClaims: [{ claim_text: "needs evidence" }],
        },
      },
    });

    expect(result.metadata?.custom).toMatchObject({
      finalReportRef: "report:turn-1",
      traceItems: [{ citation_id: "1", claim_id: 701 }],
      citationCoverage: { total_claims: 1, cited_claims: 1 },
      unresolvedRelations: [{ relation_key: "r-1" }],
      unresolvedClaims: [{ claim_text: "needs evidence" }],
    });
  });
});
