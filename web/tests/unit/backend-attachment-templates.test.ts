import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ATTACHMENT_TEMPLATE_MISSING_POLICIES,
  ATTACHMENT_TEMPLATE_STYLE_POLICIES,
  ATTACHMENT_TEMPLATE_VALUE_TYPES,
  SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS,
  attachmentTemplateVersionsKey,
  compileAttachmentTemplateFile,
  createDefaultAttachmentTemplateSlot,
  createAttachmentTemplateVersion,
  deleteAttachmentTemplateFile,
  deleteAttachmentTemplateVersion,
  getAttachmentTemplateFilePreview,
  isAttachmentTemplateDocumentCode,
  isAttachmentTemplateSlotId,
  isAttachmentTemplateSourcePath,
  listAttachmentTemplateBusinessTypes,
  listAttachmentTemplateVersions,
  uploadAttachmentTemplateFile,
  validateAttachmentTemplateVersion,
} from "@/lib/backend/attachment-templates";

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

describe("attachment template backend contract", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://annual-api.test");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("only advertises the four production template formats", () => {
    expect([...SUPPORTED_ATTACHMENT_TEMPLATE_FORMATS]).toEqual([".docx", ".xlsx", ".md", ".pdf"]);
  });

  it("matches the canonical runtime slot contract", () => {
    expect([...ATTACHMENT_TEMPLATE_VALUE_TYPES]).toEqual([
      "scalar",
      "narrative_blocks",
      "table_rows",
    ]);
    expect([...ATTACHMENT_TEMPLATE_STYLE_POLICIES]).toEqual([
      "inherit_template",
      "clone_prototype_row",
      "explicit",
    ]);
    expect([...ATTACHMENT_TEMPLATE_MISSING_POLICIES]).toEqual([
      "block",
      "omit_slot",
      "omit_sentence",
      "empty",
    ]);
    expect(isAttachmentTemplateSourcePath("document.company_profile.overview")).toBe(true);
    expect(isAttachmentTemplateSourcePath("document.risks.items[].amount")).toBe(true);
    expect(isAttachmentTemplateSourcePath("document.Company.name")).toBe(false);
    expect(isAttachmentTemplateSourcePath("entity_facts.company_name")).toBe(false);
    expect(isAttachmentTemplateSourcePath("document")).toBe(false);
    expect(isAttachmentTemplateDocumentCode("audit_report")).toBe(true);
    expect(isAttachmentTemplateDocumentCode("Audit_Report")).toBe(false);
    expect(isAttachmentTemplateDocumentCode("a")).toBe(false);
    expect(isAttachmentTemplateSlotId("company.name-1")).toBe(true);
    expect(isAttachmentTemplateSlotId("CompanyName")).toBe(false);
    expect(isAttachmentTemplateSlotId("a")).toBe(false);
    expect(createDefaultAttachmentTemplateSlot()).toMatchObject({
      value_type: "scalar",
      style_policy: "inherit_template",
      overflow_policy: "error",
      missing_policy: "block",
    });
  });

  it("builds UUID list/detail pagination without a client version number", async () => {
    expect(attachmentTemplateVersionsKey({ businessType: "annual_audit", page: 2, pageSize: 25 })).toBe(
      "http://annual-api.test/api/admin/template-versions?business_type=annual_audit&page=2&page_size=25"
    );
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ items: [{ code: "annual_audit", label: "年度审计", generator_enabled: true, supported_formats: ["docx"] }] }))
      .mockResolvedValueOnce(jsonResponse({ items: [], total: 0, page: 2, page_size: 25 }))
      .mockResolvedValueOnce(jsonResponse({ id: "version-1", version_label: "v1" }));

    await expect(listAttachmentTemplateBusinessTypes()).resolves.toEqual([
      expect.objectContaining({ supported_formats: [".docx"] }),
    ]);
    await expect(listAttachmentTemplateVersions({ page: 2, pageSize: 25 })).resolves.toMatchObject({ page: 2, page_size: 25 });
    await createAttachmentTemplateVersion({
      business_type: "annual_audit",
      name: "2026 年度模板",
      description: "一般企业",
    });

    const createInit = fetchMock.mock.calls[2][1] as RequestInit;
    expect(createInit.method).toBe("POST");
    expect(JSON.parse(String(createInit.body))).toEqual({
      business_type: "annual_audit",
      name: "2026 年度模板",
      description: "一般企业",
    });
    expect(String(createInit.body)).not.toContain("version_no");
    expect(String(createInit.body)).not.toContain("version_label");
  });

  it("uploads one file with explicit business metadata", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "file-1" }));
    const file = new File(["template"], "财务报表.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await uploadAttachmentTemplateFile("version/a", {
      file,
      document_code: "financial_statements",
      display_name: "财务报表",
      sort_order: 2,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://annual-api.test/api/admin/template-versions/version%2Fa/files");
    expect(init.method).toBe("POST");
    const form = init.body as FormData;
    expect(form.get("file")).toBe(file);
    expect(form.get("document_code")).toBe("financial_statements");
    expect(form.get("display_name")).toBe("财务报表");
    expect(form.get("sort_order")).toBe("2");
  });

  it("carries revision through destructive and compilation gates", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({})));
    await deleteAttachmentTemplateVersion("version/a", 7);
    await deleteAttachmentTemplateFile("file/a", 8);
    await compileAttachmentTemplateFile("file/a", {
      revision: 8,
      binding_manifest: {
        contract_version: "1.0",
        document_code: "audit_report",
        source_template_sha256: "a".repeat(64),
        slots: [],
      },
    });
    await validateAttachmentTemplateVersion("version/a", 9);

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://annual-api.test/api/admin/template-versions/version%2Fa?revision=7"
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://annual-api.test/api/admin/template-files/file%2Fa?revision=8"
    );
    expect(JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body))).toMatchObject({
      revision: 8,
      binding_manifest: { document_code: "audit_report" },
    });
    expect(JSON.parse(String((fetchMock.mock.calls[3][1] as RequestInit).body))).toEqual({ revision: 9 });
  });

  it("loads the authenticated admin preview as PDF bytes", async () => {
    fetchMock.mockResolvedValueOnce(new Response("pdf-bytes", {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    }));
    const blob = await getAttachmentTemplateFilePreview("file/a");
    expect(blob.type).toBe("application/pdf");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://annual-api.test/api/admin/template-files/file%2Fa/preview"
    );
  });
});
