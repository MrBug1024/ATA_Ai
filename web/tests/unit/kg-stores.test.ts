import { describe, it, expect, beforeEach } from "vitest";

describe("evidenceDrawerStore", () => {
  beforeEach(async () => {
    // reset store state between tests
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    useEvidenceDrawerStore.setState({
      open: false, caseId: 0, reportRef: "", citationId: "",
      selectedEvidenceIndex: 0, currentPage: null,
    });
  });

  it("opens drawer with correct params", async () => {
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    useEvidenceDrawerStore.getState().openDrawer({
      caseId: 116, reportRef: "final_report:demo-116", citationId: "1",
    });
    const s = useEvidenceDrawerStore.getState();
    expect(s.open).toBe(true);
    expect(s.caseId).toBe(116);
    expect(s.citationId).toBe("1");
  });

  it("closes drawer and resets", async () => {
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    useEvidenceDrawerStore.getState().openDrawer({ caseId: 1, reportRef: "r", citationId: "2" });
    useEvidenceDrawerStore.getState().closeDrawer();
    expect(useEvidenceDrawerStore.getState().open).toBe(false);
  });
});

describe("graphModalStore", () => {
  beforeEach(async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.setState({ open: false, caseId: 0, centerEntityId: undefined, reportRef: null });
  });

  it("opens modal with caseId", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116 });
    expect(useGraphModalStore.getState().open).toBe(true);
    expect(useGraphModalStore.getState().caseId).toBe(116);
  });

  it("opens modal with optional centerEntityId", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116, centerEntityId: 12 });
    expect(useGraphModalStore.getState().centerEntityId).toBe(12);
  });

  it("closes modal", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 1 });
    useGraphModalStore.getState().closeModal();
    expect(useGraphModalStore.getState().open).toBe(false);
  });

  it("sets reportRef when passed to openModal", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116, reportRef: "final_report:demo-116" });
    expect(useGraphModalStore.getState().reportRef).toBe("final_report:demo-116");
  });

  it("resets reportRef to null on closeModal", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116, reportRef: "final_report:demo-116" });
    useGraphModalStore.getState().closeModal();
    expect(useGraphModalStore.getState().reportRef).toBeNull();
  });

  it("defaults reportRef to null when not passed", async () => {
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 116 });
    expect(useGraphModalStore.getState().reportRef).toBeNull();
  });

  it("openModal 关闭已打开的证据抽屉(角标抽屉不带入图谱)", async () => {
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useEvidenceDrawerStore.getState().openDrawer({ caseId: 1, reportRef: "r", citationId: "1" });
    useGraphModalStore.getState().openModal({ caseId: 1 });
    expect(useEvidenceDrawerStore.getState().open).toBe(false);
    expect(useGraphModalStore.getState().open).toBe(true);
  });

  it("closeModal 同时关闭证据抽屉(图谱内打开的证据不残留到聊天)", async () => {
    const { useEvidenceDrawerStore } = await import("@/lib/stores/evidence-drawer");
    const { useGraphModalStore } = await import("@/lib/stores/graph-modal");
    useGraphModalStore.getState().openModal({ caseId: 1 });
    useEvidenceDrawerStore.getState().openDrawer({ caseId: 1, reportRef: "r", citationId: "2" });
    useGraphModalStore.getState().closeModal();
    expect(useEvidenceDrawerStore.getState().open).toBe(false);
  });
});
