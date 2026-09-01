// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AttachmentTemplateBusinessType,
  AttachmentTemplateFile,
  AttachmentTemplateVersionDetail,
} from "@/lib/backend/attachment-templates";

const mocks = vi.hoisted(() => ({
  compileFile: vi.fn(),
  reset: vi.fn(),
  versionQuery: vi.fn(),
  businessTypesQuery: vi.fn(),
  validateVersion: vi.fn(),
  setActivation: vi.fn(),
  uploadFile: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => <a {...props}>{children}</a>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/shared/file-preview-panel", () => ({ PdfViewer: () => null }));
vi.mock("@/lib/hooks/use-attachment-templates", () => ({
  useAttachmentTemplateBusinessTypes: () => mocks.businessTypesQuery(),
  useAttachmentTemplateVersion: () => mocks.versionQuery(),
  useCreateAttachmentTemplateVersion: () => ({ createVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn() }),
  useUpdateAttachmentTemplateVersion: () => ({ updateVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn() }),
  useCloneAttachmentTemplateVersion: () => ({ cloneVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn() }),
  useCompileAttachmentTemplateFile: () => ({ compileFile: mocks.compileFile, isMutating: false, error: null, reset: mocks.reset }),
  useDeleteAttachmentTemplateFile: () => ({ deleteFile: vi.fn(), isMutating: false, error: null, reset: vi.fn() }),
  useInspectAttachmentTemplateFile: () => ({ inspectFile: vi.fn(), isMutating: false, error: null, reset: vi.fn() }),
  useSetAttachmentTemplateVersionActivation: () => ({ setActivation: mocks.setActivation, isMutating: false, error: null, reset: vi.fn() }),
  useUpdateAttachmentTemplateFile: () => ({ updateFile: vi.fn(), isMutating: false, error: null, reset: vi.fn() }),
  useUploadAttachmentTemplateFile: () => ({ uploadFile: mocks.uploadFile, isMutating: false, error: null, reset: vi.fn() }),
  useValidateAttachmentTemplateVersion: () => ({ validateVersion: mocks.validateVersion, isMutating: false, error: null, reset: vi.fn() }),
}));

function templateFile(
  extension: AttachmentTemplateFile["extension"],
  candidate: Record<string, unknown>
): AttachmentTemplateFile {
  return {
    id: `file-${extension}`,
    template_version_id: "version-1",
    document_code: "financial_statements",
    display_name: "财务报表",
    source_file_name: `template${extension}`,
    extension,
    content_type: "application/octet-stream",
    size_bytes: 1024,
    source_sha256: "a".repeat(64),
    inspection_report: {
      ok: true,
      suggested_mapping: { slots: [candidate] },
    },
    status: "mapping",
    sort_order: 0,
    revision: 3,
  };
}

const BUSINESS_TYPE: AttachmentTemplateBusinessType = {
  code: "annual_audit",
  label: "年度审计",
  generator_enabled: true,
  supported_formats: [".docx"],
  required_profile: [],
};

function templateVersion(
  overrides: Partial<AttachmentTemplateVersionDetail> = {}
): AttachmentTemplateVersionDetail {
  return {
    id: "version-1",
    family_id: "family-1",
    business_type: "annual_audit",
    scope_type: "global",
    scope_key: "global",
    version_no: 1,
    version_label: "v1",
    name: "年度审计模板",
    description: "",
    status: "draft",
    content_sha256: "c".repeat(64),
    file_count: 0,
    ready_file_count: 0,
    revision: 9,
    active: false,
    files: [],
    ...overrides,
  };
}

describe("Attachment template binding options", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.compileFile.mockResolvedValue({});
    mocks.validateVersion.mockResolvedValue({});
    mocks.setActivation.mockResolvedValue({});
    mocks.businessTypesQuery.mockReturnValue({
      businessTypes: [],
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
    mocks.versionQuery.mockReturnValue({
      version: null,
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
  });

  it("preserves compiler candidate options while editing an XLSX table contract", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".xlsx", {
      suggested_slot_id: "statement_rows",
      target: "xlsx:table:StatementRows",
      source: "document.financial_statements.balance_sheet",
      value_type: "table_rows",
      options: {
        column_map: { Name: "name", Amount: "amount", Formula: "formula" },
        prototype_row: 4,
        formula_columns: ["Formula"],
        compiler_hint: { preserve: true },
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);

    expect((screen.getByLabelText("槽位 1 ID") as HTMLInputElement).value).toBe("statement_rows");
    expect((screen.getByLabelText("槽位 1 模板列 2") as HTMLInputElement).value).toBe("Amount");
    expect((screen.getByLabelText("槽位 1 数据字段 2") as HTMLInputElement).value).toBe("amount");
    expect((screen.getByLabelText("槽位 1 原型行") as HTMLInputElement).value).toBe("4");
    expect((screen.getByLabelText("槽位 1 公式列 1") as HTMLInputElement).value).toBe("Formula");

    fireEvent.change(screen.getByLabelText("槽位 1 数据字段 2"), { target: { value: "amount_value" } });
    fireEvent.change(screen.getByLabelText("槽位 1 原型行"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    await waitFor(() => expect(mocks.compileFile).toHaveBeenCalledTimes(1));
    const request = mocks.compileFile.mock.calls[0][0];
    expect(request.revision).toBe(3);
    expect(request.binding_manifest.slots[0].options).toEqual({
      column_map: { Name: "name", Amount: "amount_value", Formula: "formula" },
      prototype_row: 5,
      formula_columns: ["Formula"],
      compiler_hint: { preserve: true },
    });
  });

  it("serializes PDF overlay geometry, font, overflow, and coordinate options", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".pdf", {
      suggested_slot_id: "company_name",
      target: "pdf:overlay:company_name",
      source: "document.company_profile.name",
      value_type: "scalar",
      overflow_policy: "shrink_font",
      options: {
        page: 2,
        x: 20,
        y: 30,
        width: 180,
        height: 36,
        font_name: "Helvetica",
        font_size: 11,
        minimum_font_size: 7,
        max_lines: 2,
        leading_factor: 1.1,
        alignment: "right",
        y_from_top: true,
        compiler_hint: "keep-me",
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);

    expect((screen.getByLabelText("槽位 1 页码") as HTMLInputElement).value).toBe("2");
    expect((screen.getByLabelText("槽位 1 宽度") as HTMLInputElement).value).toBe("180");
    expect((screen.getByLabelText("槽位 1 字体") as HTMLInputElement).value).toBe("Helvetica");
    expect((screen.getByLabelText("槽位 1 最小字号") as HTMLInputElement).value).toBe("7");
    expect((screen.getByLabelText("槽位 1 最大行数") as HTMLInputElement).value).toBe("2");
    expect(screen.getByLabelText("槽位 1 Y 坐标从页顶计算").getAttribute("data-state")).toBe("checked");

    fireEvent.change(screen.getByLabelText("槽位 1 宽度"), { target: { value: "200" } });
    fireEvent.click(screen.getByLabelText("槽位 1 Y 坐标从页顶计算"));
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    await waitFor(() => expect(mocks.compileFile).toHaveBeenCalledTimes(1));
    expect(mocks.compileFile.mock.calls[0][0].binding_manifest.slots[0]).toEqual(
      expect.objectContaining({
        target: "pdf:overlay:company_name",
        overflow_policy: "shrink_font",
        options: {
          page: 2,
          x: 20,
          y: 30,
          width: 200,
          height: 36,
          font_name: "Helvetica",
          font_size: 11,
          minimum_font_size: 7,
          max_lines: 2,
          leading_factor: 1.1,
          alignment: "right",
          y_from_top: false,
          compiler_hint: "keep-me",
        },
      })
    );
  });

  it("supports list-based table column contracts for templated documents", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".md", {
      suggested_slot_id: "risk_rows",
      target: "md:jinja:risk_rows",
      source: "document.risks.items[]",
      value_type: "table_rows",
      options: {
        columns: ["description", "amount"],
        candidate_note: "preserve",
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);

    expect((screen.getByLabelText("槽位 1 数据字段 1") as HTMLInputElement).value).toBe("description");
    expect((screen.getByLabelText("槽位 1 数据字段 2") as HTMLInputElement).value).toBe("amount");
    fireEvent.change(screen.getByLabelText("槽位 1 数据字段 2"), { target: { value: "risk_amount" } });
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    await waitFor(() => expect(mocks.compileFile).toHaveBeenCalledTimes(1));
    expect(mocks.compileFile.mock.calls[0][0].binding_manifest.slots[0].options).toEqual({
      columns: ["description", "risk_amount"],
      candidate_note: "preserve",
    });
  });

  it("exposes AcroForm typography and serializes renderer defaults", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".pdf", {
      suggested_slot_id: "company_name",
      target: "pdf:acroform:company_name",
      source: "document.company_profile.name",
      value_type: "scalar",
      overflow_policy: "truncate",
      options: {
        font_name: "Helvetica",
        font_size: 9,
        max_lines: 1,
        candidate_note: "preserve",
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);

    expect((screen.getByLabelText("槽位 1 字体") as HTMLInputElement).value).toBe("Helvetica");
    expect((screen.getByLabelText("槽位 1 字号") as HTMLInputElement).value).toBe("9");
    expect((screen.getByLabelText("槽位 1 最小字号") as HTMLInputElement).value).toBe("6");
    expect(screen.queryByLabelText("槽位 1 页码")).toBeNull();
    fireEvent.change(screen.getByLabelText("槽位 1 最小字号"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    await waitFor(() => expect(mocks.compileFile).toHaveBeenCalledTimes(1));
    expect(mocks.compileFile.mock.calls[0][0].binding_manifest.slots[0]).toEqual(
      expect.objectContaining({
        overflow_policy: "truncate",
        options: {
          font_name: "Helvetica",
          font_size: 9,
          minimum_font_size: 5,
          leading_factor: 1.2,
          max_lines: 1,
          alignment: "left",
          candidate_note: "preserve",
        },
      })
    );
  });

  it("configures an opt-in semantic narrative contract without a deterministic source", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".docx", {
      suggested_slot_id: "audit_summary",
      target: "docx:content_control:audit_summary",
      source: "",
      value_type: "narrative_blocks",
      overflow_policy: "continue_paragraphs",
      options: {
        compiler_hint: "preserve",
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);

    expect(screen.getByLabelText("槽位 1 确定性编制").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByLabelText("槽位 1 语义编制"));
    expect(screen.getByLabelText("槽位 1 语义编制").getAttribute("aria-pressed")).toBe("true");
    expect((screen.getByLabelText("槽位 1 数据来源") as HTMLInputElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("槽位 1 语义指令"), {
      target: { value: "  仅依据批准事实编写审计概况。  " },
    });
    fireEvent.change(screen.getByLabelText("槽位 1 允许事实引用 1"), {
      target: { value: "entity.registered_address" },
    });
    fireEvent.change(screen.getByLabelText("槽位 1 外发标签 1"), {
      target: { value: "注册地址" },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    fireEvent.change(screen.getByLabelText("槽位 1 允许事实引用 2"), {
      target: { value: "entity.uscc" },
    });
    fireEvent.change(screen.getByLabelText("槽位 1 外发标签 2"), {
      target: { value: "统一社会信用代码" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    await waitFor(() => expect(mocks.compileFile).toHaveBeenCalledTimes(1));
    expect(mocks.compileFile.mock.calls[0][0].binding_manifest.slots[0]).toEqual(
      expect.objectContaining({
        source: "",
        value_type: "narrative_blocks",
        options: {
          composition_mode: "semantic",
          semantic_instruction: "仅依据批准事实编写审计概况。",
          allowed_fact_refs: ["entity.registered_address", "entity.uscc"],
          fact_ref_labels: {
            "entity.registered_address": "注册地址",
            "entity.uscc": "统一社会信用代码",
          },
          require_fact_refs: true,
          compiler_hint: "preserve",
        },
      })
    );
  });

  it("removes every semantic-only option when switching back to deterministic", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".docx", {
      suggested_slot_id: "audit_summary",
      target: "docx:content_control:audit_summary",
      source: "document.report.summary",
      value_type: "narrative_blocks",
      options: {
        composition_mode: "semantic",
        semantic_instruction: "编写概况",
        allowed_fact_refs: ["entity.legal_name"],
        fact_ref_labels: { "entity.legal_name": "被审计单位名称" },
        require_fact_refs: true,
        compiler_hint: { preserve: true },
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("槽位 1 确定性编制"));

    expect(screen.queryByLabelText("槽位 1 语义指令")).toBeNull();
    expect((screen.getByLabelText("槽位 1 数据来源") as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    await waitFor(() => expect(mocks.compileFile).toHaveBeenCalledTimes(1));
    expect(mocks.compileFile.mock.calls[0][0].binding_manifest.slots[0].options).toEqual({
      compiler_hint: { preserve: true },
    });
  });

  it("allows semantic composition only for narrative block slots", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".docx", {
      suggested_slot_id: "company_name",
      target: "docx:content_control:company_name",
      source: "",
      value_type: "scalar",
      options: {
        composition_mode: "semantic",
        semantic_instruction: "编写名称",
        allowed_fact_refs: ["entity.legal_name"],
        fact_ref_labels: { "entity.legal_name": "被审计单位名称" },
        require_fact_refs: true,
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);
    expect((screen.getByLabelText("槽位 1 语义编制") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    expect(await screen.findByText("槽位 company_name 仅叙述段落支持语义编制")).toBeTruthy();
    expect(mocks.compileFile).not.toHaveBeenCalled();
  });

  it("requires fact ref labels to match allowed fact refs exactly", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".docx", {
      suggested_slot_id: "audit_summary",
      target: "docx:content_control:audit_summary",
      source: "",
      value_type: "narrative_blocks",
      options: {
        composition_mode: "semantic",
        semantic_instruction: "编写概况",
        allowed_fact_refs: ["entity.legal_name", "entity.uscc"],
        fact_ref_labels: { "entity.legal_name": "被审计单位名称" },
        require_fact_refs: true,
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    expect(await screen.findByText("槽位 audit_summary 的外发标签必须与允许事实引用逐项对应")).toBeTruthy();
    expect(mocks.compileFile).not.toHaveBeenCalled();
  });

  it("blocks internal fact keys in semantic external labels", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".docx", {
      suggested_slot_id: "audit_summary",
      target: "docx:content_control:audit_summary",
      source: "",
      value_type: "narrative_blocks",
      options: {
        composition_mode: "semantic",
        semantic_instruction: "编写概况",
        allowed_fact_refs: ["entity.legal_name"],
        fact_ref_labels: { "entity.legal_name": "entity.legal_name" },
        require_fact_refs: true,
      },
    });

    render(<SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));

    expect(await screen.findByText("槽位 audit_summary 的语义指令和外发标签不能包含内部标识符")).toBeTruthy();
    expect(mocks.compileFile).not.toHaveBeenCalled();
  });

  it("blocks invalid source paths and duplicate targets before compilation", async () => {
    const { SlotContractDialog } = await import("@/components/admin/attachment-template-files");
    const file = templateFile(".docx", {
      suggested_slot_id: "company_name",
      target: "docx:content_control:company_name",
      source: "document.Company.name",
      value_type: "scalar",
    });
    file.binding_manifest = {
      slots: [
        {
          slot_id: "company_name",
          target: "docx:content_control:company_name",
          source: "document.company.name",
          value_type: "scalar",
          required: true,
          style_policy: "inherit_template",
          overflow_policy: "error",
        },
        {
          slot_id: "company_code",
          target: "docx:content_control:company_name",
          source: "document.company.code",
          value_type: "scalar",
          required: true,
          style_policy: "inherit_template",
          overflow_policy: "error",
        },
      ],
    };

    const first = render(
      <SlotContractDialog versionId="version-1" file={file} open onOpenChange={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));
    expect(await screen.findByText("模板目标不能重复")).toBeTruthy();
    expect(mocks.compileFile).not.toHaveBeenCalled();

    first.unmount();
    const invalidSourceFile = templateFile(".docx", {
      suggested_slot_id: "company_name",
      target: "docx:content_control:company_name",
      source: "document.Company.name",
      value_type: "scalar",
    });
    render(
      <SlotContractDialog
        versionId="version-1"
        file={invalidSourceFile}
        open
        onOpenChange={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "确认并编译" }));
    expect(await screen.findByText(/数据来源必须是小写 document/)).toBeTruthy();
    expect(mocks.compileFile).not.toHaveBeenCalled();
  });

  it("renders backend blockers on failed validation and never shows success copy", async () => {
    const { AttachmentTemplateFiles } = await import("@/components/admin/attachment-template-files");
    mocks.versionQuery.mockReturnValue({
      version: templateVersion({
        validation_report: {
          passed: false,
          validated_at: "2026-08-31T10:00:00Z",
          blockers: [{ code: "missing_slot", message: "缺少公司名称槽位" }],
          warnings: [{ code: "font_fallback", message: "字体将回退" }],
        },
      }),
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
    mocks.businessTypesQuery.mockReturnValue({
      businessTypes: [BUSINESS_TYPE],
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });

    render(<AttachmentTemplateFiles versionId="version-1" />);
    expect(screen.getByText("激活门禁未通过")).toBeTruthy();
    expect(screen.getByText("缺少公司名称槽位")).toBeTruthy();
    expect(screen.getByText("警告：字体将回退")).toBeTruthy();
    expect(screen.getByText(/校验时间：/)).toBeTruthy();
    expect(screen.queryByText("全部文件、槽位与预览检查已完成。")).toBeNull();
  });

  it("allows a retired version to be revalidated and reactivated after a current passing validation", async () => {
    const { AttachmentTemplateFiles } = await import("@/components/admin/attachment-template-files");
    const file = {
      ...templateFile(".docx", {}),
      status: "ready" as const,
      preview_available: true,
      preview_sha256: "b".repeat(64),
    };
    mocks.versionQuery.mockReturnValue({
      version: templateVersion({
        status: "retired",
        file_count: 1,
        ready_file_count: 1,
        files: [file],
        validation_report: {
          passed: true,
          validated_at: "2026-08-31T10:00:00Z",
          content_sha256: "c".repeat(64),
          blockers: [],
          warnings: [],
        },
      }),
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
    mocks.businessTypesQuery.mockReturnValue({
      businessTypes: [BUSINESS_TYPE],
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });

    render(<AttachmentTemplateFiles versionId="version-1" />);
    fireEvent.click(screen.getByRole("button", { name: "重新校验" }));
    fireEvent.click(screen.getByRole("button", { name: "重新激活" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "确认并激活" }));
    await waitFor(() => expect(mocks.validateVersion).toHaveBeenCalledWith(9));
    expect(mocks.setActivation).toHaveBeenCalledWith({
      active: true,
      revision: 9,
      preview_confirmations: [
        { file_id: file.id, preview_sha256: "b".repeat(64) },
      ],
    });
  });

  it("limits upload selection to formats declared by the business type", async () => {
    const { AttachmentTemplateFiles } = await import("@/components/admin/attachment-template-files");
    mocks.versionQuery.mockReturnValue({
      version: templateVersion(),
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
    mocks.businessTypesQuery.mockReturnValue({
      businessTypes: [BUSINESS_TYPE],
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });

    render(<AttachmentTemplateFiles versionId="version-1" />);
    const input = screen.getByLabelText("模板文件") as HTMLInputElement;
    expect(input.accept).toBe(".docx");
    fireEvent.change(input, {
      target: { files: [new File(["sheet"], "statements.xlsx")] },
    });
    expect(screen.getByText("所选文件格式不在当前业务类型的允许列表中")).toBeTruthy();
    expect((screen.getByRole("button", { name: "上传" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
