import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  attachmentJobKey,
  getArtifactDownloadTicket,
  getArtifactPreviewTicket,
  getAttachmentJob,
  isAttachmentJobRef,
  listAttachmentJobs,
  retryAttachmentJob,
} from "@/lib/backend/generated-artifacts";

const fetchMock = vi.fn();

const JOB_REF = {
  job_id: "job/a",
  case_id: 42,
  assistant_turn_id: "turn-1-assistant",
  report_id: 88,
  report_version: 3,
  template_version_id: "template-v1",
  template_version_label: "v1",
  delivery_level: "review_draft",
} as const;

describe("generated artifact backend contract", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://annual-api.test");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("requires a complete immutable assistant-message job reference", () => {
    expect(isAttachmentJobRef(JOB_REF)).toBe(true);
    expect(isAttachmentJobRef({ job_id: "job/a", case_id: 42 })).toBe(false);
    expect(isAttachmentJobRef({ ...JOB_REF, case_id: 0 })).toBe(false);
  });

  it("addresses a job only through its bound case and stable id", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ ...JOB_REF, status: "queued" }));
    expect(attachmentJobKey(42, "job/a")).toBe(
      "http://annual-api.test/api/annual-audit/42/attachment-jobs/job%2Fa"
    );
    await getAttachmentJob(42, "job/a");
    expect(fetchMock.mock.calls[0][0]).toBe(attachmentJobKey(42, "job/a"));
  });

  it("normalizes the persisted job shape used by detail and history", async () => {
    const rawJob = {
      id: "job/a",
      engagement_id: 42,
      assistant_turn_id: "turn-1-assistant",
      report_id: 88,
      report_version: 3,
      template_version_id: "template-v1",
      template_version_label: "v1",
      delivery_level: "review_draft",
      status: "running",
      stage: "rendering",
      progress: 55,
      expected_item_count: 2,
      succeeded_item_count: 1,
      items: [{ id: "item-1", document_code: "audit_report", display_name: "审计报告", status: "succeeded", stage: "published", attempt_count: 1 }],
      artifacts: [{ id: "artifact-1", document_code: "audit_report", display_name: "审计报告", file_name: "审计报告.docx", extension: "docx", content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", file_size: 1024, sha256: "a".repeat(64), preview_sha256: "b".repeat(64), status: "published", delivery_approved: true }],
    };
    fetchMock
      .mockResolvedValueOnce(Response.json(rawJob))
      .mockResolvedValueOnce(Response.json({ case_id: 42, jobs: [rawJob] }));

    await expect(getAttachmentJob(42, "job/a")).resolves.toMatchObject({
      job_id: "job/a",
      case_id: 42,
      progress: { percent: 55, completed: 1, total: 2, failed: 0 },
      artifacts: [{ preview_available: true }],
    });
    await expect(listAttachmentJobs(42, { limit: 10 })).resolves.toMatchObject({
      total: 1,
      limit: 10,
      items: [{ job_id: "job/a" }],
    });
    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://annual-api.test/api/annual-audit/42/attachment-jobs?limit=10"
    );
  });

  it("retries the same frozen job without a request body", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ ...JOB_REF, status: "queued" }));
    await retryAttachmentJob(42, "job/a");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${attachmentJobKey(42, "job/a")}/retry`);
    expect(init).toEqual({ method: "POST" });
  });

  it("obtains purpose-specific short-lived tickets instead of artifact URLs", async () => {
    const ticket = {
      url: "https://objects.test/ticket",
      expires_at: "2026-08-31T12:00:00Z",
      content_type: "application/pdf",
      file_name: "审计报告.pdf",
    };
    fetchMock.mockResolvedValueOnce(Response.json(ticket)).mockResolvedValueOnce(Response.json(ticket));
    await expect(getArtifactPreviewTicket(42, "artifact/a")).resolves.toEqual(ticket);
    await expect(getArtifactDownloadTicket(42, "artifact/a")).resolves.toEqual(ticket);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://annual-api.test/api/annual-audit/42/artifacts/artifact%2Fa/preview-ticket"
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://annual-api.test/api/annual-audit/42/artifacts/artifact%2Fa/download-ticket"
    );
  });

  it("resolves relative capability tickets against the backend origin", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({
      url: "/api/artifact-access/signed-token",
      expires_at: "2026-08-31T12:00:00Z",
      content_type: "application/pdf",
      file_name: "预览.pdf",
    }));
    await expect(getArtifactPreviewTicket(42, "artifact/a")).resolves.toMatchObject({
      url: "http://annual-api.test/api/artifact-access/signed-token",
    });
  });
});
