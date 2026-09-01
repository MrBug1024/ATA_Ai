// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AttachmentTemplateBusinessType,
  AttachmentTemplateVersionSummary,
} from "@/lib/backend/attachment-templates";
import { AttachmentTemplateVersionList } from "@/components/admin/attachment-template-version-list";

const mocks = vi.hoisted(() => ({
  businessTypesQuery: vi.fn(),
  versionsQuery: vi.fn(),
  refreshBusinessTypes: vi.fn(),
  refreshVersions: vi.fn(),
  setActivation: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.routerPush }),
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => <a {...props}>{children}</a>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/hooks/use-attachment-templates", () => ({
  useAttachmentTemplateBusinessTypes: () => mocks.businessTypesQuery(),
  useAttachmentTemplateVersions: (params: unknown) => mocks.versionsQuery(params),
  useCloneAttachmentTemplateVersion: () => ({
    cloneVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn(),
  }),
  useDeleteAttachmentTemplateVersion: () => ({
    deleteVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn(),
  }),
  useSetAttachmentTemplateVersionActivation: () => ({
    setActivation: mocks.setActivation, isMutating: false, error: null, reset: vi.fn(),
  }),
  useCreateAttachmentTemplateVersion: () => ({
    createVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn(),
  }),
  useUpdateAttachmentTemplateVersion: () => ({
    updateVersion: vi.fn(), isMutating: false, error: null, reset: vi.fn(),
  }),
}));

const BUSINESS_TYPE: AttachmentTemplateBusinessType = {
  code: "annual_audit",
  label: "年度审计",
  generator_enabled: true,
  supported_formats: [".docx"],
  required_profile: [],
};

function version(
  overrides: Partial<AttachmentTemplateVersionSummary> = {}
): AttachmentTemplateVersionSummary {
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
    content_sha256: "a".repeat(64),
    file_count: 1,
    ready_file_count: 1,
    revision: 7,
    active: false,
    ...overrides,
  };
}

function businessQuery(overrides: Record<string, unknown> = {}) {
  return {
    businessTypes: [BUSINESS_TYPE],
    isLoading: false,
    error: null,
    refresh: mocks.refreshBusinessTypes,
    ...overrides,
  };
}

function versionsQuery(overrides: Record<string, unknown> = {}) {
  return {
    versions: [],
    total: 0,
    page: 1,
    pageSize: 25,
    isLoading: false,
    error: null,
    refresh: mocks.refreshVersions,
    ...overrides,
  };
}

describe("AttachmentTemplateVersionList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.businessTypesQuery.mockReturnValue(businessQuery());
    mocks.versionsQuery.mockReturnValue(versionsQuery());
    mocks.setActivation.mockResolvedValue({});
    mocks.refreshBusinessTypes.mockResolvedValue(undefined);
    mocks.refreshVersions.mockResolvedValue(undefined);
  });

  it("disables creation and retries both queries when business types fail", async () => {
    mocks.businessTypesQuery.mockReturnValue(businessQuery({
      businessTypes: [],
      error: "业务类型目录不可用",
    }));

    render(<AttachmentTemplateVersionList />);
    expect((screen.getByRole("button", { name: "创建版本" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => {
      expect(mocks.refreshBusinessTypes).toHaveBeenCalledOnce();
      expect(mocks.refreshVersions).toHaveBeenCalledOnce();
    });
  });

  it("requires opening version details before a retired version can be reactivated", () => {
    mocks.versionsQuery.mockReturnValue(versionsQuery({
      versions: [version({
        status: "retired",
        validation_report: {
          passed: true,
          content_sha256: "a".repeat(64),
          validated_at: "2026-08-31T10:00:00Z",
        },
      })],
      total: 1,
    }));

    render(<AttachmentTemplateVersionList />);
    expect(screen.queryByRole("button", { name: /重新激活/ })).toBeNull();
    expect(screen.getByRole("link", { name: /查看 年度审计模板/ })).toBeTruthy();
    expect(mocks.setActivation).not.toHaveBeenCalled();
  });

  it("clamps the current page when the filtered total shrinks", async () => {
    let total = 26;
    mocks.versionsQuery.mockImplementation((params: { page: number }) => versionsQuery({
      versions: [version()],
      total,
      page: params.page,
    }));

    const view = render(<AttachmentTemplateVersionList />);
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(mocks.versionsQuery).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 })
    ));

    total = 25;
    view.rerender(<AttachmentTemplateVersionList />);
    await waitFor(() => expect(mocks.versionsQuery).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1 })
    ));
  });
});
