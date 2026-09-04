"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  BookOpenCheck,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  FileWarning,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import type { MeResponse } from "@/lib/backend/auth";
import {
  type AnnualAuditDocumentCategory,
  type AnnualAuditPolicyBinding,
  type AnnualAuditProgramItem,
  type AnnualAuditProgramItemUpdate,
  type AnnualAuditProgramStatus,
  type AnnualAuditPolicyCatalog,
  type AnnualAuditProfile,
  type AnnualAuditReleaseGate,
  type AnnualAuditReview,
  type AnnualAuditReviewDecision,
  type AnnualAuditReviewLevel,
  type AnnualEngagementProfileUpdate,
  getAnnualAuditPolicyCatalog,
} from "@/lib/backend/annual-audit";
import {
  type AlternativeProceduresDraft,
  type AlternativeProcedureRowDraft,
  type EvidenceAnchorDraft,
  type ReviewScopeType,
  type SamplingPlanDraft,
  alternativeDraftToProcedures,
  alternativeProceduresToDraft,
  createAlternativeProcedureRow,
  createEvidenceAnchorDraft,
  evidenceAnchorValidationError,
  evidenceDraftsToRefs,
  evidenceRefsToDrafts,
  reviewDraftToScope,
  reviewScopeOptions,
  reviewScopeToDraft,
  samplingDraftToPlan,
  samplingPlanToDraft,
  samplingPlanValidationError,
} from "@/lib/annual-audit-execution-form";
import { canAccessModule, isSystemAdminPreview } from "@/lib/auth/authorization";
import { useAuth } from "@/lib/hooks/use-auth";
import { useAnnualAuditExecution } from "@/lib/hooks/use-annual-audit-execution";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

const PHASE_ORDER = ["承接与独立性", "计划", "循环执行", "完成"];

const PROGRAM_STATUS_LABELS: Record<AnnualAuditProgramStatus, string> = {
  not_started: "未开始",
  blocked: "受阻",
  in_progress: "执行中",
  evidence_ready: "待形成结论",
  completed: "已完成",
  not_applicable: "不适用",
  returned: "已退回",
};

const REVIEW_LEVEL_LABELS: Record<AnnualAuditReviewLevel, string> = {
  project_manager: "项目经理复核",
  department_manager: "部门经理复核",
  engagement_partner: "项目合伙人复核",
};

const REVIEW_DECISION_LABELS: Record<AnnualAuditReviewDecision, string> = {
  pending: "待复核",
  approved: "已批准",
  returned: "已退回",
};

const ACCEPTANCE_OPTIONS = [
  ["pending", "待评估"],
  ["accepted", "已承接/续约"],
  ["rejected", "不承接"],
  ["withdrawn", "已撤回"],
] as const;

const INDEPENDENCE_OPTIONS = [
  ["pending", "待清除"],
  ["cleared", "已清除"],
  ["blocked", "存在障碍"],
  ["not_applicable", "不适用"],
] as const;

const EVIDENCE_LOCATOR_OPTIONS = [
  ["worksheet", "工作表/单元格"],
  ["page", "文件页码"],
  ["row", "数据行"],
  ["chunk", "解析段落"],
] as const;

const SAMPLING_METHOD_OPTIONS = [
  ["random", "随机抽样"],
  ["systematic", "系统抽样"],
  ["monetary_unit", "货币单元抽样"],
  ["judgmental", "判断抽样"],
  ["full_population", "全量检查"],
  ["other", "其他"],
] as const;

const REVIEW_SCOPE_OPTIONS: ReadonlyArray<readonly [ReviewScopeType, string]> = [
  ["engagement", "整个项目"],
  ["phase", "指定阶段"],
  ["cycle", "指定循环"],
  ["procedure", "指定程序"],
];

function formatDate(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function compactText(value: string, maxLength = 88): string {
  const normalized = value.trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized || "-";
}

function statusBadgeVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (["completed", "approved", "cleared", "accepted", "ready_for_signature"].includes(status)) {
    return "default";
  }
  if (["blocked", "returned", "rejected", "withdrawn"].includes(status)) return "destructive";
  if (["not_applicable", "pending", "not_started"].includes(status)) return "outline";
  return "secondary";
}

function ProgramStatusBadge({ status }: { status: AnnualAuditProgramStatus }) {
  return <Badge variant={statusBadgeVariant(status)}>{PROGRAM_STATUS_LABELS[status] ?? status}</Badge>;
}

function ReviewStatusBadge({ decision }: { decision: AnnualAuditReviewDecision }) {
  return <Badge variant={statusBadgeVariant(decision)}>{REVIEW_DECISION_LABELS[decision]}</Badge>;
}

function GateStatusBadge({ gate }: { gate: AnnualAuditReleaseGate }) {
  const ready = gate.gate_status === "ready_for_signature";
  return (
    <Badge variant={ready ? "default" : "destructive"}>
      {ready ? "待人工签字" : "存在阻断项"}
    </Badge>
  );
}

function hasRole(user: MeResponse | null, roles: string[]): boolean {
  return Boolean(user?.roles?.some((role) => roles.includes(role)));
}

function isProjectController(user: MeResponse | null): boolean {
  if (!user || !canAccessModule(user, "report")) return false;
  return Boolean(
    user.is_super_admin ||
      user.is_company_admin ||
      isSystemAdminPreview(user) ||
      hasRole(user, ["engagement_manager", "engagement_partner", "reviewer"])
  );
}

function canEditProgram(user: MeResponse | null): boolean {
  return Boolean(user && canAccessModule(user, "tasks"));
}

function canRecordReview(user: MeResponse | null, level: AnnualAuditReviewLevel): boolean {
  if (!user || !canAccessModule(user, "report")) return false;
  if (user.is_super_admin || user.is_company_admin || isSystemAdminPreview(user)) return true;
  if (level === "project_manager") {
    return hasRole(user, ["engagement_manager", "reviewer", "engagement_partner"]);
  }
  if (level === "department_manager") return hasRole(user, ["reviewer", "engagement_partner"]);
  return hasRole(user, ["engagement_partner"]);
}

function categoryLabel(category: AnnualAuditDocumentCategory | undefined, code: string): string {
  return category?.name || code;
}

type ProfileDraft = Record<
  | "entity_type"
  | "audit_purpose"
  | "accounting_framework"
  | "firm_name"
  | "engagement_partner"
  | "signing_cpa_primary"
  | "signing_cpa_secondary"
  | "data_classification"
  | "data_residency"
  | "model_data_policy"
  | "acceptance_status"
  | "independence_status",
  string
>;

function profileToDraft(profile: AnnualAuditProfile): ProfileDraft {
  return {
    entity_type: profile.entity_type ?? "",
    audit_purpose: profile.audit_purpose ?? "",
    accounting_framework: profile.accounting_framework ?? "",
    firm_name: profile.firm_name ?? "",
    engagement_partner: profile.engagement_partner ?? "",
    signing_cpa_primary: profile.signing_cpa_primary ?? "",
    signing_cpa_secondary: profile.signing_cpa_secondary ?? "",
    data_classification: profile.data_classification ?? "",
    data_residency: profile.data_residency ?? "",
    model_data_policy: profile.model_data_policy ?? "",
    acceptance_status: profile.acceptance_status || "pending",
    independence_status: profile.independence_status || "pending",
  };
}

function ProfileEditorDialog({
  open,
  onOpenChange,
  profile,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profile: AnnualAuditProfile;
  saving: boolean;
  onSave: (payload: AnnualEngagementProfileUpdate) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState<ProfileDraft>(() => profileToDraft(profile));

  useEffect(() => {
    if (open) setDraft(profileToDraft(profile));
  }, [open, profile]);

  const setValue = (field: keyof ProfileDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await onSave({
        entity_type: draft.entity_type.trim(),
        audit_purpose: draft.audit_purpose.trim(),
        accounting_framework: draft.accounting_framework.trim(),
        firm_name: draft.firm_name.trim(),
        engagement_partner: draft.engagement_partner.trim(),
        signing_cpa_primary: draft.signing_cpa_primary.trim(),
        signing_cpa_secondary: draft.signing_cpa_secondary.trim(),
        data_classification: draft.data_classification.trim(),
        data_residency: draft.data_residency.trim(),
        model_data_policy: draft.model_data_policy.trim(),
        acceptance_status: draft.acceptance_status as AnnualEngagementProfileUpdate["acceptance_status"],
        independence_status: draft.independence_status as AnnualEngagementProfileUpdate["independence_status"],
      });
      toast.success("项目画像已留痕更新");
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存项目画像失败");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>项目画像与承接控制</DialogTitle>
          <DialogDescription>变更将写入项目控制轨迹。</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="annual-entity-type">被审计单位类型</Label>
              <Input
                id="annual-entity-type"
                value={draft.entity_type}
                onChange={(event) => setValue("entity_type", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-audit-purpose">审计目的</Label>
              <Input
                id="annual-audit-purpose"
                value={draft.audit_purpose}
                onChange={(event) => setValue("audit_purpose", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-accounting-framework">会计准则框架</Label>
              <Input
                id="annual-accounting-framework"
                value={draft.accounting_framework}
                onChange={(event) => setValue("accounting_framework", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-firm-name">会计师事务所</Label>
              <Input
                id="annual-firm-name"
                value={draft.firm_name}
                onChange={(event) => setValue("firm_name", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-engagement-partner">项目合伙人</Label>
              <Input
                id="annual-engagement-partner"
                value={draft.engagement_partner}
                onChange={(event) => setValue("engagement_partner", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-signing-cpa-primary">主签注册会计师</Label>
              <Input
                id="annual-signing-cpa-primary"
                value={draft.signing_cpa_primary}
                onChange={(event) => setValue("signing_cpa_primary", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-signing-cpa-secondary">副签注册会计师</Label>
              <Input
                id="annual-signing-cpa-secondary"
                value={draft.signing_cpa_secondary}
                onChange={(event) => setValue("signing_cpa_secondary", event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-data-classification">数据分级</Label>
              <Input
                id="annual-data-classification"
                value={draft.data_classification}
                onChange={(event) => setValue("data_classification", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-data-residency">数据存储地域</Label>
              <Input
                id="annual-data-residency"
                value={draft.data_residency}
                onChange={(event) => setValue("data_residency", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="annual-model-data-policy">模型数据策略</Label>
              <Input
                id="annual-model-data-policy"
                value={draft.model_data_policy}
                onChange={(event) => setValue("model_data_policy", event.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label>承接/续约</Label>
              <Select
                value={draft.acceptance_status}
                onValueChange={(value) => setValue("acceptance_status", value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACCEPTANCE_OPTIONS.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>独立性</Label>
              <Select
                value={draft.independence_status}
                onValueChange={(value) => setValue("independence_status", value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INDEPENDENCE_OPTIONS.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={saving}>
              {saving ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <ShieldCheck data-icon="inline-start" />}
              保存画像
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type ProgramDraft = {
  status: AnnualAuditProgramStatus;
  conclusion_text: string;
  not_applicable_reason: string;
  exception_count: string;
  evidence_refs: string;
  sample_plan: string;
  alternative_procedures: string;
};

function programToDraft(item: AnnualAuditProgramItem): ProgramDraft {
  return {
    status: item.status,
    conclusion_text: item.conclusion_text,
    not_applicable_reason: item.not_applicable_reason,
    exception_count: String(item.exception_count ?? 0),
    evidence_refs: stringifyStructured(item.evidence_refs, []),
    sample_plan: stringifyStructured(item.sample_plan, {}),
    alternative_procedures: stringifyStructured(item.alternative_procedures, {}),
  };
}

function ProgramEditorDialog({
  item,
  onOpenChange,
  saving,
  onSave,
}: {
  item: AnnualAuditProgramItem | null;
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onSave: (procedureCode: string, payload: AnnualAuditProgramItemUpdate) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState<ProgramDraft | null>(item ? programToDraft(item) : null);

  useEffect(() => {
    setDraft(item ? programToDraft(item) : null);
  }, [item]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!item || !draft) return;
    const exceptionCount = Number(draft.exception_count || "0");
    if (!Number.isInteger(exceptionCount) || exceptionCount < 0) {
      toast.error("例外数量必须是非负整数");
      return;
    }
    try {
      await onSave(item.procedure_code, {
        status: draft.status,
        conclusion_text: draft.conclusion_text.trim(),
        not_applicable_reason: draft.not_applicable_reason.trim(),
        exception_count: exceptionCount,
        evidence_refs: parseEvidence(draft.evidence_refs),
        sample_plan: parseStructured(draft.sample_plan, "抽样方案"),
        alternative_procedures: parseStructured(draft.alternative_procedures, "替代程序"),
      });
      toast.success(`${item.procedure_code} 已留痕更新`);
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存审计程序失败");
    }
  };

  return (
    <Dialog open={Boolean(item)} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        {item && draft && (
          <>
            <DialogHeader>
              <DialogTitle>{item.procedure_code} {item.procedure_name}</DialogTitle>
              <DialogDescription>{item.cycle} · {item.risk_area || "未标注风险领域"}</DialogDescription>
            </DialogHeader>
            <form onSubmit={submit} className="grid gap-4">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
                <div className="grid gap-1.5">
                  <Label>执行状态</Label>
                  <Select
                    value={draft.status}
                    onValueChange={(value) =>
                      setDraft((current) => current ? { ...current, status: value as AnnualAuditProgramStatus } : current)
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(PROGRAM_STATUS_LABELS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="annual-exception-count">例外数量</Label>
                  <Input
                    id="annual-exception-count"
                    type="number"
                    min="0"
                    step="1"
                    value={draft.exception_count}
                    onChange={(event) => setDraft((current) => current ? { ...current, exception_count: event.target.value } : current)}
                  />
                </div>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="annual-program-conclusion">审计结论</Label>
                <Textarea
                  id="annual-program-conclusion"
                  value={draft.conclusion_text}
                  onChange={(event) => setDraft((current) => current ? { ...current, conclusion_text: event.target.value } : current)}
                  rows={3}
                  required={draft.status === "completed"}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="annual-program-not-applicable">不适用原因</Label>
                <Textarea
                  id="annual-program-not-applicable"
                  value={draft.not_applicable_reason}
                  onChange={(event) => setDraft((current) => current ? { ...current, not_applicable_reason: event.target.value } : current)}
                  rows={2}
                  required={draft.status === "not_applicable"}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="annual-program-evidence">证据锚点 JSON</Label>
                <Textarea
                  id="annual-program-evidence"
                  className="font-mono text-xs"
                  value={draft.evidence_refs}
                  onChange={(event) => setDraft((current) => current ? { ...current, evidence_refs: event.target.value } : current)}
                  rows={7}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="annual-program-sample">抽样方案 JSON</Label>
                  <Textarea
                    id="annual-program-sample"
                    className="font-mono text-xs"
                    value={draft.sample_plan}
                    onChange={(event) => setDraft((current) => current ? { ...current, sample_plan: event.target.value } : current)}
                    rows={5}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="annual-program-alternative">替代程序 JSON</Label>
                  <Textarea
                    id="annual-program-alternative"
                    className="font-mono text-xs"
                    value={draft.alternative_procedures}
                    onChange={(event) => setDraft((current) => current ? { ...current, alternative_procedures: event.target.value } : current)}
                    rows={5}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button type="submit" disabled={saving}>
                  {saving ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <ClipboardCheck data-icon="inline-start" />}
                  保存程序记录
                </Button>
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ReviewEditorDialog({
  review,
  onOpenChange,
  saving,
  onSave,
}: {
  review: AnnualAuditReview | null;
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onSave: (payload: {
    review_level: AnnualAuditReviewLevel;
    decision: "approved" | "returned";
    decision_note?: string;
    scope?: Record<string, unknown> | unknown[];
  }) => Promise<unknown>;
}) {
  const [decision, setDecision] = useState<"approved" | "returned">("approved");
  const [note, setNote] = useState("");
  const [scope, setScope] = useState('{\n  "scope": "engagement"\n}');

  useEffect(() => {
    setDecision("approved");
    setNote("");
    setScope('{\n  "scope": "engagement"\n}');
  }, [review]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!review) return;
    if (decision === "returned" && !note.trim()) {
      toast.error("退回复核必须填写处理意见");
      return;
    }
    try {
      await onSave({
        review_level: review.review_level,
        decision,
        decision_note: note.trim() || undefined,
        scope: parseStructured(scope, "复核范围"),
      });
      toast.success("复核决定已留痕记录");
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "记录复核决定失败");
    }
  };

  return (
    <Dialog open={Boolean(review)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        {review && (
          <>
            <DialogHeader>
              <DialogTitle>{REVIEW_LEVEL_LABELS[review.review_level]}</DialogTitle>
              <DialogDescription>该决定不可覆盖既有记录，将形成新的复核轨迹。</DialogDescription>
            </DialogHeader>
            <form onSubmit={submit} className="grid gap-4">
              <div className="grid gap-1.5">
                <Label>复核决定</Label>
                <Select value={decision} onValueChange={(value) => setDecision(value as "approved" | "returned")}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="approved">批准</SelectItem>
                    <SelectItem value="returned">退回</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="annual-review-note">复核意见</Label>
                <Textarea
                  id="annual-review-note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={3}
                  required={decision === "returned"}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="annual-review-scope">复核范围 JSON</Label>
                <Textarea
                  id="annual-review-scope"
                  value={scope}
                  onChange={(event) => setScope(event.target.value)}
                  rows={4}
                  className="font-mono text-xs"
                />
              </div>
              <DialogFooter>
                <Button type="submit" disabled={saving}>
                  {saving ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <BadgeCheck data-icon="inline-start" />}
                  记录决定
                </Button>
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ProfileSummary({
  profile,
  blockers,
  editable,
  onEdit,
}: {
  profile: AnnualAuditProfile;
  blockers: string[];
  editable: boolean;
  onEdit: () => void;
}) {
  const fields = [
    ["被审计单位", profile.entity_type],
    ["审计目的", profile.audit_purpose],
    ["会计准则", profile.accounting_framework],
    ["事务所", profile.firm_name],
    ["项目合伙人", profile.engagement_partner],
    ["主签 CPA", profile.signing_cpa_primary],
  ];
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 p-4 pb-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">项目画像与承接</CardTitle>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant={statusBadgeVariant(profile.acceptance_status)}>{ACCEPTANCE_OPTIONS.find(([value]) => value === profile.acceptance_status)?.[1] ?? profile.acceptance_status}</Badge>
            <Badge variant={statusBadgeVariant(profile.independence_status)}>{INDEPENDENCE_OPTIONS.find(([value]) => value === profile.independence_status)?.[1] ?? profile.independence_status}</Badge>
          </div>
        </div>
        {editable && (
          <Button type="button" variant="outline" size="xs" onClick={onEdit}>
            <Pencil data-icon="inline-start" />
            编辑
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-4 pt-0">
        <dl className="grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
          {fields.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[5rem_minmax(0,1fr)] gap-2">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="truncate">{value || "未填写"}</dd>
            </div>
          ))}
        </dl>
        {blockers.length > 0 && (
          <div className="mt-3 border-t pt-3">
            <p className="text-xs font-medium text-destructive">待处理 {blockers.length} 项</p>
            <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
              {blockers.slice(0, 3).map((message) => <li key={message}>{message}</li>)}
              {blockers.length > 3 && <li>另有 {blockers.length - 3} 项</li>}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GateSummary({
  gate,
  evaluating,
  canEvaluate,
  onEvaluate,
}: {
  gate: AnnualAuditReleaseGate;
  evaluating: boolean;
  canEvaluate: boolean;
  onEvaluate: () => Promise<unknown>;
}) {
  const runEvaluation = async () => {
    try {
      await onEvaluate();
      toast.success("签发门禁已重新评估");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "评估签发门禁失败");
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 p-4 pb-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">签发门禁</CardTitle>
          <div className="mt-2 flex items-center gap-2">
            <GateStatusBadge gate={gate} />
            <span className="text-xs text-muted-foreground">{gate.blockers.length} 项阻断</span>
          </div>
        </div>
        {canEvaluate && (
          <Button type="button" variant="outline" size="xs" onClick={runEvaluation} disabled={evaluating}>
            {evaluating ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <RefreshCw data-icon="inline-start" />}
            重新评估
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-4 pt-0">
        <div className="grid grid-cols-4 divide-x border-y text-center text-xs">
          <div className="py-2"><p className="font-semibold">{gate.program_summary.completed}</p><p className="text-muted-foreground">已完成</p></div>
          <div className="py-2"><p className="font-semibold">{gate.program_summary.not_applicable}</p><p className="text-muted-foreground">不适用</p></div>
          <div className="py-2"><p className="font-semibold text-destructive">{gate.program_summary.open}</p><p className="text-muted-foreground">未闭环</p></div>
          <div className="py-2"><p className="font-semibold text-destructive">{gate.open_findings.count}</p><p className="text-muted-foreground">开放发现</p></div>
        </div>
        {gate.blockers.length > 0 && (
          <ul className="mt-3 space-y-1.5 text-xs">
            {gate.blockers.slice(0, 4).map((blocker) => (
              <li key={blocker.code} className="flex gap-1.5 text-muted-foreground">
                <AlertTriangle className="mt-0.5 size-3 shrink-0 text-destructive" />
                <span>{blocker.message}</span>
              </li>
            ))}
            {gate.blockers.length > 4 && <li className="text-muted-foreground">另有 {gate.blockers.length - 4} 项阻断</li>}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function PolicyBindingDialog({
  open,
  onOpenChange,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onSave: (payload: {
    knowledge_release_id: number;
    ruleset_id: number;
    reporting_period_date?: string;
  }) => Promise<unknown>;
}) {
  const [catalog, setCatalog] = useState<AnnualAuditPolicyCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [knowledgeReleaseId, setKnowledgeReleaseId] = useState("");
  const [rulesetId, setRulesetId] = useState("");
  const [reportingPeriodDate, setReportingPeriodDate] = useState("");

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoadingCatalog(true);
    setCatalogError(null);
    void getAnnualAuditPolicyCatalog()
      .then((result) => {
        if (!active) return;
        const releases = result.knowledge_releases.filter((item) => item.status === "published");
        const rulesets = result.rulesets.filter((item) => item.status === "published");
        setCatalog({ knowledge_releases: releases, rulesets });
        setKnowledgeReleaseId(String(releases[0]?.id ?? ""));
        setRulesetId(String(rulesets[0]?.id ?? ""));
      })
      .catch((error) => {
        if (active) setCatalogError(error instanceof Error ? error.message : "获取版本目录失败");
      })
      .finally(() => {
        if (active) setLoadingCatalog(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const releaseId = Number(knowledgeReleaseId);
    const selectedRulesetId = Number(rulesetId);
    if (
      !Number.isInteger(releaseId) ||
      releaseId <= 0 ||
      !Number.isInteger(selectedRulesetId) ||
      selectedRulesetId <= 0
    ) {
      toast.error("请选择已发布的知识版本和规则集");
      return;
    }
    try {
      await onSave({
        knowledge_release_id: releaseId,
        ruleset_id: selectedRulesetId,
        reporting_period_date: reportingPeriodDate || undefined,
      });
      toast.success("规则与知识版本已冻结并留痕");
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "冻结规则与知识版本失败");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>冻结规则与知识版本</DialogTitle>
          <DialogDescription>仅可选择已发布版本；服务端会再次校验有效期和项目适用范围。</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          {catalogError && (
            <Alert variant="destructive">
              <AlertDescription>{catalogError}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-1.5">
            <Label>知识发布版本</Label>
            <Select
              value={knowledgeReleaseId}
              onValueChange={setKnowledgeReleaseId}
              disabled={loadingCatalog || !catalog}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="选择已发布知识版本" />
              </SelectTrigger>
              <SelectContent>
                {catalog?.knowledge_releases.map((release) => (
                  <SelectItem key={release.id} value={String(release.id)}>
                    {release.release_code} {release.release_version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>审计规则集</Label>
            <Select value={rulesetId} onValueChange={setRulesetId} disabled={loadingCatalog || !catalog}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="选择已发布规则集" />
              </SelectTrigger>
              <SelectContent>
                {catalog?.rulesets.map((ruleset) => (
                  <SelectItem key={ruleset.id} value={String(ruleset.id)}>
                    {ruleset.ruleset_code} {ruleset.version} · {ruleset.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="annual-policy-reporting-period">报告期截止日</Label>
            <Input
              id="annual-policy-reporting-period"
              type="date"
              value={reportingPeriodDate}
              onChange={(event) => setReportingPeriodDate(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="submit"
              disabled={saving || loadingCatalog || !knowledgeReleaseId || !rulesetId}
            >
              {saving ? (
                <LoaderCircle data-icon="inline-start" className="animate-spin" />
              ) : (
                <BookOpenCheck data-icon="inline-start" />
              )}
              冻结版本
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PolicyBindingSummary({
  binding,
  editable,
  onFreeze,
}: {
  binding: AnnualAuditPolicyBinding | null;
  editable: boolean;
  onFreeze: () => void;
}) {
  if (!binding) {
    return (
      <section className="border-t pt-4" aria-labelledby="annual-policy-title">
        <div className="flex flex-wrap items-center gap-2">
          <BookOpenCheck className="size-4 text-muted-foreground" />
          <h2 id="annual-policy-title" className="text-sm font-medium">冻结的规则与知识版本</h2>
          <Badge variant="destructive">未冻结</Badge>
          {editable && (
            <Button type="button" variant="outline" size="xs" onClick={onFreeze}>
              <BookOpenCheck data-icon="inline-start" />
              选择版本
            </Button>
          )}
        </div>
      </section>
    );
  }
  return (
    <section className="border-t pt-4" aria-labelledby="annual-policy-title">
      <div className="flex flex-wrap items-center gap-2">
        <BookOpenCheck className="size-4 text-muted-foreground" />
        <h2 id="annual-policy-title" className="text-sm font-medium">冻结的规则与知识版本</h2>
        <Badge variant={statusBadgeVariant(binding.binding_status)}>{binding.binding_status}</Badge>
      </div>
      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="text-muted-foreground">知识发布</dt><dd className="mt-1 font-medium">{binding.knowledge_release.release_code} {binding.knowledge_release.release_version}</dd><dd className="mt-1 text-muted-foreground">{binding.knowledge_release.status}</dd></div>
        <div><dt className="text-muted-foreground">规则集</dt><dd className="mt-1 font-medium">{binding.ruleset.ruleset_code} {binding.ruleset.version}</dd><dd className="mt-1 text-muted-foreground">{binding.ruleset.status}</dd></div>
        <div><dt className="text-muted-foreground">报告期</dt><dd className="mt-1 font-medium">{binding.reporting_period_date || "-"}</dd></div>
        <div><dt className="text-muted-foreground">冻结记录</dt><dd className="mt-1 font-medium">{binding.bound_by || "-"}</dd><dd className="mt-1 text-muted-foreground">{formatDate(binding.bound_at)}</dd></div>
      </dl>
    </section>
  );
}

function ReviewSummary({
  reviews,
  user,
  saving,
  onRecord,
}: {
  reviews: AnnualAuditReview[];
  user: MeResponse | null;
  saving: boolean;
  onRecord: (review: AnnualAuditReview) => void;
}) {
  return (
    <section className="border-t pt-4" aria-labelledby="annual-review-title">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="size-4 text-muted-foreground" />
        <h2 id="annual-review-title" className="text-sm font-medium">三级复核</h2>
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-3">
        {reviews.map((review) => {
          const available = canRecordReview(user, review.review_level);
          return (
            <div key={review.review_level} className="border p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs font-medium">{REVIEW_LEVEL_LABELS[review.review_level]}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{review.reviewer_user_id || "未记录复核人"}</p>
                </div>
                <ReviewStatusBadge decision={review.decision} />
              </div>
              <p className="mt-2 min-h-8 text-xs text-muted-foreground">{compactText(review.decision_note, 72)}</p>
              <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{formatDate(review.created_at)}</span>
                {available && (
                  <Button type="button" variant="outline" size="xs" disabled={saving} onClick={() => onRecord(review)}>
                    <Pencil data-icon="inline-start" />
                    记录
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function DocumentMatrix({ categories }: { categories: AnnualAuditDocumentCategory[] }) {
  const ordered = [...categories].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  return (
    <section className="border-t pt-4" aria-labelledby="annual-documents-title">
      <div className="flex items-center gap-2">
        <FileCheck2 className="size-4 text-muted-foreground" />
        <h2 id="annual-documents-title" className="text-sm font-medium">资料类别矩阵</h2>
        <span className="text-xs text-muted-foreground">{ordered.filter((item) => item.uploaded || item.covered_by_case_workpaper).length}/{ordered.length} 已覆盖</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {ordered.map((category) => (
          <Badge key={category.code} variant={category.uploaded || category.covered_by_case_workpaper ? "outline" : "destructive"} title={category.code}>
            {category.uploaded || category.covered_by_case_workpaper ? <CheckCircle2 data-icon="inline-start" /> : <FileWarning data-icon="inline-start" />}
            {category.name} {category.uploaded ? `(${category.file_count})` : category.covered_by_case_workpaper ? "（主底稿）" : ""}
          </Badge>
        ))}
      </div>
    </section>
  );
}

function ProgramMatrix({
  program,
  categories,
  editable,
  saving,
  onEdit,
}: {
  program: AnnualAuditProgramItem[];
  categories: AnnualAuditDocumentCategory[];
  editable: boolean;
  saving: boolean;
  onEdit: (item: AnnualAuditProgramItem) => void;
}) {
  const categoriesByCode = useMemo(
    () => new Map(categories.map((category) => [category.code, category])),
    [categories]
  );
  const phases = useMemo(() => {
    const phaseNames = Array.from(new Set(program.map((item) => item.phase))).sort((a, b) => {
      const aIndex = PHASE_ORDER.indexOf(a);
      const bIndex = PHASE_ORDER.indexOf(b);
      return (aIndex < 0 ? Number.MAX_SAFE_INTEGER : aIndex) - (bIndex < 0 ? Number.MAX_SAFE_INTEGER : bIndex);
    });
    return phaseNames.map((phase) => ({ phase, items: program.filter((item) => item.phase === phase) }));
  }, [program]);

  return (
    <section aria-labelledby="annual-program-title" className="border-t pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <ClipboardCheck className="size-4 text-muted-foreground" />
        <h2 id="annual-program-title" className="text-sm font-medium">审计程序矩阵</h2>
        <span className="text-xs text-muted-foreground">按项目冻结的程序版本执行</span>
      </div>
      <div className="mt-3 space-y-2">
        {phases.map(({ phase, items }) => {
          const completed = items.filter((item) => ["completed", "not_applicable"].includes(item.status)).length;
          return (
            <Collapsible key={phase} defaultOpen={phase !== "循环执行"} className="border">
              <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted/50">
                <span className="text-sm font-medium">{phase}</span>
                <span className="text-xs text-muted-foreground">{completed}/{items.length} 已闭环</span>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="overflow-x-auto border-t">
                  <table className="w-full min-w-[920px] text-left text-xs">
                    <thead className="bg-muted/50 text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">程序</th>
                        <th className="px-3 py-2 font-medium">认定/风险</th>
                        <th className="px-3 py-2 font-medium">必需资料</th>
                        <th className="px-3 py-2 font-medium">证据</th>
                        <th className="px-3 py-2 font-medium">结论</th>
                        <th className="px-3 py-2 font-medium">状态</th>
                        <th className="px-3 py-2 font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {items.map((item) => (
                        <tr key={item.procedure_code} className="align-top">
                          <td className="px-3 py-3">
                            <p className="font-medium">{item.procedure_code} {item.procedure_name}</p>
                            <p className="mt-1 text-muted-foreground">{item.cycle}</p>
                          </td>
                          <td className="max-w-48 px-3 py-3">
                            <p>{item.assertions.join("、") || "-"}</p>
                            <p className="mt-1 text-muted-foreground">{item.risk_area || "-"}</p>
                          </td>
                          <td className="max-w-52 px-3 py-3">
                            <div className="flex flex-wrap gap-1">
                              {item.required_material_categories.map((code) => {
                                const missing = item.missing_material_categories.includes(code);
                                return <Badge key={code} variant={missing ? "destructive" : "outline"}>{categoryLabel(categoriesByCode.get(code), code)}</Badge>;
                              })}
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <p>{item.requires_evidence ? `${item.evidence_refs.length} 条锚点` : "不要求"}</p>
                            {item.exception_count > 0 && <p className="mt-1 text-destructive">{item.exception_count} 项例外</p>}
                          </td>
                          <td className="max-w-60 px-3 py-3 text-muted-foreground">{compactText(item.status === "not_applicable" ? item.not_applicable_reason : item.conclusion_text, 76)}</td>
                          <td className="px-3 py-3"><ProgramStatusBadge status={item.status} /></td>
                          <td className="px-3 py-3">
                            {editable ? (
                              <Button type="button" variant="outline" size="xs" disabled={saving} onClick={() => onEdit(item)}>
                                <Pencil data-icon="inline-start" />
                                更新
                              </Button>
                            ) : <span className="text-muted-foreground">-</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CollapsibleContent>
            </Collapsible>
          );
        })}
      </div>
    </section>
  );
}

export function AnnualAuditExecutionPanel({ caseId }: { caseId: number }) {
  const { user } = useAuth();
  const {
    execution,
    isLoading,
    error,
    refresh,
    mutationName,
    mutationError,
    saveProfile,
    saveProgramItem,
    saveReview,
    freezePolicyBinding,
    evaluateReleaseGate,
  } = useAnnualAuditExecution(Number.isFinite(caseId) && caseId > 0 ? caseId : null);
  const [profileEditorOpen, setProfileEditorOpen] = useState(false);
  const [programEditorItem, setProgramEditorItem] = useState<AnnualAuditProgramItem | null>(null);
  const [reviewEditor, setReviewEditor] = useState<AnnualAuditReview | null>(null);
  const [policyBindingOpen, setPolicyBindingOpen] = useState(false);

  const canControl = isProjectController(user);
  const canUpdateProgram = canEditProgram(user);

  if (isLoading) {
    return (
      <div className="grid gap-4 xl:grid-cols-2" aria-label="正在加载年审执行工作台">
        <Skeleton className="h-52" />
        <Skeleton className="h-52" />
        <Skeleton className="h-80 xl:col-span-2" />
      </div>
    );
  }

  if (error || !execution) {
    return (
      <Alert variant="destructive" className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <AlertTitle>年审执行工作台加载失败</AlertTitle>
          <AlertDescription>{error || "未获取到项目执行数据"}</AlertDescription>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => void refresh()}>
          <RefreshCw data-icon="inline-start" />
          重试
        </Button>
      </Alert>
    );
  }

  const profileBlockers = execution.release_gate.blockers
    .filter((blocker) => blocker.code.startsWith("profile."))
    .map((blocker) => blocker.message);

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4">
      {mutationError && (
        <Alert variant="destructive">
          <ShieldAlert className="size-4" />
          <AlertTitle>操作未完成</AlertTitle>
          <AlertDescription>{mutationError}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <ProfileSummary
          profile={execution.profile}
          blockers={profileBlockers}
          editable={canControl}
          onEdit={() => setProfileEditorOpen(true)}
        />
        <GateSummary
          gate={execution.release_gate}
          evaluating={mutationName === "release_gate"}
          canEvaluate={canControl}
          onEvaluate={evaluateReleaseGate}
        />
      </div>

      <DocumentMatrix categories={execution.document_categories} />
      <ProgramMatrix
        program={execution.program}
        categories={execution.document_categories}
        editable={canUpdateProgram}
        saving={mutationName === "program"}
        onEdit={setProgramEditorItem}
      />
      <ReviewSummary
        reviews={execution.reviews}
        user={user}
        saving={mutationName === "review"}
        onRecord={setReviewEditor}
      />
      <PolicyBindingSummary
        binding={execution.policy_binding}
        editable={canControl}
        onFreeze={() => setPolicyBindingOpen(true)}
      />

      <ProfileEditorDialog
        open={profileEditorOpen}
        onOpenChange={setProfileEditorOpen}
        profile={execution.profile}
        saving={mutationName === "profile"}
        onSave={saveProfile}
      />
      <ProgramEditorDialog
        item={programEditorItem}
        onOpenChange={(open) => { if (!open) setProgramEditorItem(null); }}
        saving={mutationName === "program"}
        onSave={saveProgramItem}
      />
      <ReviewEditorDialog
        review={reviewEditor}
        onOpenChange={(open) => { if (!open) setReviewEditor(null); }}
        saving={mutationName === "review"}
        onSave={saveReview}
      />
      <PolicyBindingDialog
        open={policyBindingOpen}
        onOpenChange={setPolicyBindingOpen}
        saving={mutationName === "policy"}
        onSave={freezePolicyBinding}
      />
    </div>
  );
}
