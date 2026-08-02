"use client";

import { useMemo, useState, type FormEvent } from "react";
import { AlertCircle, Pencil, RefreshCw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  type ModuleCode,
  type PermissionTier,
  type RolePermission,
  type RolePermissionRequest,
} from "@/lib/backend/admin";
import { useAdminRoles, useSaveRolePermission } from "@/lib/hooks/use-admin";

const TIER_LABELS: Record<PermissionTier, string> = {
  field: "执行层",
  expert: "专业层",
  management: "管理层",
};

const MODULE_LABELS: Record<ModuleCode, string> = {
  admin: "后台管理",
  corrections: "纠错治理",
  deadline: "期限管理",
  drilldown: "报告下钻",
  graph: "知识图谱",
  progress: "进度跟踪",
  report: "审计报告",
  review: "案件复核",
};

const DEFAULT_TIERS: PermissionTier[] = ["field", "expert", "management"];

function isPermissionTier(value: string): value is PermissionTier {
  return value === "field" || value === "expert" || value === "management";
}

function isModuleCode(value: ModuleCode | "*"): value is ModuleCode {
  return value !== "*";
}

function mutationErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "保存角色权限失败";
}

function RoleListSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-label="正在加载角色权限">
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="flex items-center gap-4 py-2">
          <div className="flex min-w-44 flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-36" />
          </div>
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-7 w-14" />
        </div>
      ))}
    </div>
  );
}

export function RoleManagement() {
  const {
    roles,
    reportSections,
    allModules,
    tiers,
    isLoading,
    error,
    refresh,
  } = useAdminRoles();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRoleCode, setEditingRoleCode] = useState("");
  const [roleName, setRoleName] = useState("");
  const [tier, setTier] = useState<PermissionTier>("field");
  const [description, setDescription] = useState("");
  const [allModulesSelected, setAllModulesSelected] = useState(false);
  const [selectedModules, setSelectedModules] = useState<ModuleCode[]>([]);
  const [allSectionsSelected, setAllSectionsSelected] = useState(false);
  const [selectedSections, setSelectedSections] = useState<string[]>([]);
  const [roleNameError, setRoleNameError] = useState<string | null>(null);
  const {
    saveRolePermission,
    isMutating,
    reset: resetMutation,
  } = useSaveRolePermission(editingRoleCode);

  const roleEntries = useMemo(
    () =>
      Object.entries(roles).sort(([leftCode, left], [rightCode, right]) =>
        (left.role_name || leftCode).localeCompare(
          right.role_name || rightCode,
          "zh-CN"
        )
      ),
    [roles]
  );
  const availableTiers = tiers.length > 0 ? tiers : DEFAULT_TIERS;
  const reportSectionCodes = useMemo(
    () => reportSections.map((section) => section.section_code),
    [reportSections]
  );

  function openRoleEditor(roleCode: string, permission: RolePermission) {
    const grantsAllModules = permission.modules.includes("*");
    const grantsAllSections = permission.visible_report_sections.includes("*");

    setEditingRoleCode(roleCode);
    setRoleName(permission.role_name || roleCode);
    setTier(permission.tier);
    setDescription(permission.description ?? "");
    setAllModulesSelected(grantsAllModules);
    setSelectedModules(
      grantsAllModules
        ? [...allModules]
        : permission.modules.filter(isModuleCode)
    );
    setAllSectionsSelected(grantsAllSections);
    setSelectedSections(
      grantsAllSections
        ? [...reportSectionCodes]
        : permission.visible_report_sections.filter((code) => code !== "*")
    );
    setRoleNameError(null);
    resetMutation();
    setDialogOpen(true);
  }

  function toggleModule(module: ModuleCode, checked: boolean) {
    setSelectedModules((current) => {
      if (checked) {
        return allModules.filter(
          (candidate) => candidate === module || current.includes(candidate)
        );
      }
      return current.filter((candidate) => candidate !== module);
    });
  }

  function toggleSection(sectionCode: string, checked: boolean) {
    setSelectedSections((current) => {
      if (checked) {
        return reportSectionCodes.filter(
          (candidate) =>
            candidate === sectionCode || current.includes(candidate)
        );
      }
      return current.filter((candidate) => candidate !== sectionCode);
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedRoleName = roleName.trim();
    if (!normalizedRoleName) {
      setRoleNameError("请输入角色名称");
      return;
    }

    setRoleNameError(null);
    const request: RolePermissionRequest = {
      role_name: normalizedRoleName,
      tier,
      description: description.trim(),
      modules: allModulesSelected
        ? ["*"]
        : allModules.filter((module) => selectedModules.includes(module)),
      visible_report_sections: allSectionsSelected
        ? ["*"]
        : reportSectionCodes.filter((code) => selectedSections.includes(code)),
    };

    try {
      await saveRolePermission(request);
      toast.success("角色权限已保存");
      setDialogOpen(false);
    } catch (saveError) {
      toast.error(mutationErrorMessage(saveError));
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>角色权限配置</CardTitle>
          <p className="text-sm text-muted-foreground">
            统一维护角色的报告可见层级、功能模块和报告章节授权。
          </p>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <RoleListSkeleton />
          ) : error ? (
            <Alert variant="destructive">
              <AlertCircle aria-hidden="true" />
              <div className="flex flex-1 items-center justify-between gap-4">
                <div>
                  <AlertTitle>角色权限加载失败</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void refresh()}
                >
                  <RefreshCw data-icon="inline-start" />
                  重试
                </Button>
              </div>
            </Alert>
          ) : roleEntries.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ShieldCheck aria-hidden="true" />
                </EmptyMedia>
                <EmptyTitle>暂无角色</EmptyTitle>
                <EmptyDescription>
                  后端尚未返回可配置的角色权限记录。
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>角色</TableHead>
                  <TableHead>最高可见层级</TableHead>
                  <TableHead>模块权限</TableHead>
                  <TableHead>报告章节</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {roleEntries.map(([roleCode, permission]) => (
                  <TableRow key={roleCode}>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <span className="font-medium">
                          {permission.role_name || roleCode}
                        </span>
                        <code className="text-xs text-muted-foreground">
                          {roleCode}
                        </code>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {TIER_LABELS[permission.tier]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex max-w-md flex-wrap gap-1">
                        {permission.modules.includes("*") ? (
                          <Badge>全部模块</Badge>
                        ) : permission.modules.length === 0 ? (
                          <Badge variant="outline">无模块</Badge>
                        ) : (
                          permission.modules.filter(isModuleCode).map((module) => (
                            <Badge key={module} variant="outline">
                              {MODULE_LABELS[module]}
                            </Badge>
                          ))
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      {permission.visible_report_sections.includes("*") ? (
                        <Badge>全部章节</Badge>
                      ) : permission.visible_report_sections.length === 0 ? (
                        <Badge variant="outline">未授权</Badge>
                      ) : (
                        <Badge variant="secondary">
                          {permission.visible_report_sections.length} 个章节
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => openRoleEditor(roleCode, permission)}
                      >
                        <Pencil data-icon="inline-start" />
                        编辑
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!isMutating) setDialogOpen(open);
        }}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>编辑角色权限</DialogTitle>
            <DialogDescription>
              角色代码 {editingRoleCode || "-"} 为稳定标识，不可在此修改。
            </DialogDescription>
          </DialogHeader>

          <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
            <FieldGroup>
              <Field data-invalid={roleNameError ? true : undefined}>
                <FieldLabel htmlFor="role-name">角色名称</FieldLabel>
                <Input
                  id="role-name"
                  value={roleName}
                  onChange={(event) => {
                    setRoleName(event.target.value);
                    if (roleNameError) setRoleNameError(null);
                  }}
                  aria-invalid={roleNameError ? true : undefined}
                  disabled={isMutating}
                />
                <FieldError>{roleNameError}</FieldError>
              </Field>

              <Field>
                <FieldLabel htmlFor="role-tier">最高可见层级</FieldLabel>
                <Select
                  value={tier}
                  onValueChange={(value) => {
                    if (isPermissionTier(value)) setTier(value);
                  }}
                  disabled={isMutating}
                >
                  <SelectTrigger id="role-tier" className="w-full">
                    <SelectValue placeholder="选择层级" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {availableTiers.map((item) => (
                        <SelectItem key={item} value={item}>
                          {TIER_LABELS[item]}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>

              <Field>
                <FieldLabel htmlFor="role-description">角色说明</FieldLabel>
                <Textarea
                  id="role-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  rows={3}
                  disabled={isMutating}
                />
              </Field>
            </FieldGroup>

            <FieldSet>
              <FieldLegend>模块权限</FieldLegend>
              <FieldDescription>
                选择“全部模块”将以通配符 * 保存；取消后可逐项精确授权。
              </FieldDescription>
              <FieldGroup className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field orientation="horizontal" className="sm:col-span-2">
                  <Checkbox
                    id="all-role-modules"
                    checked={allModulesSelected}
                    onCheckedChange={(checked) =>
                      setAllModulesSelected(checked === true)
                    }
                    disabled={isMutating}
                  />
                  <FieldContent>
                    <FieldLabel htmlFor="all-role-modules">
                      全部模块（*）
                    </FieldLabel>
                    <FieldDescription>
                      自动包含后续新增的功能模块。
                    </FieldDescription>
                  </FieldContent>
                </Field>

                {allModules.map((module) => (
                  <Field
                    key={module}
                    orientation="horizontal"
                    data-disabled={allModulesSelected ? true : undefined}
                  >
                    <Checkbox
                      id={`role-module-${module}`}
                      checked={
                        allModulesSelected || selectedModules.includes(module)
                      }
                      onCheckedChange={(checked) =>
                        toggleModule(module, checked === true)
                      }
                      disabled={allModulesSelected || isMutating}
                    />
                    <FieldContent>
                      <FieldLabel htmlFor={`role-module-${module}`}>
                        {MODULE_LABELS[module]}
                      </FieldLabel>
                      <FieldDescription>{module}</FieldDescription>
                    </FieldContent>
                  </Field>
                ))}
              </FieldGroup>
            </FieldSet>

            <FieldSet>
              <FieldLegend>可见报告章节</FieldLegend>
              <FieldDescription>
                可使用 * 授权全部章节；取消全部并清空所有选项会提交 []。
              </FieldDescription>
              <FieldGroup className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field orientation="horizontal" className="sm:col-span-2">
                  <Checkbox
                    id="all-report-sections"
                    checked={allSectionsSelected}
                    onCheckedChange={(checked) =>
                      setAllSectionsSelected(checked === true)
                    }
                    disabled={isMutating}
                  />
                  <FieldContent>
                    <FieldLabel htmlFor="all-report-sections">
                      全部报告章节（*）
                    </FieldLabel>
                    <FieldDescription>
                      自动包含后续启用的报告章节。
                    </FieldDescription>
                  </FieldContent>
                </Field>

                {reportSections.map((section) => (
                  <Field
                    key={section.section_code}
                    orientation="horizontal"
                    data-disabled={allSectionsSelected ? true : undefined}
                  >
                    <Checkbox
                      id={`report-section-${section.section_code}`}
                      checked={
                        allSectionsSelected ||
                        selectedSections.includes(section.section_code)
                      }
                      onCheckedChange={(checked) =>
                        toggleSection(section.section_code, checked === true)
                      }
                      disabled={allSectionsSelected || isMutating}
                    />
                    <FieldContent>
                      <FieldLabel
                        htmlFor={`report-section-${section.section_code}`}
                      >
                        {section.title}
                      </FieldLabel>
                      <FieldDescription>
                        {section.section_code} · {TIER_LABELS[section.audience]}
                      </FieldDescription>
                    </FieldContent>
                  </Field>
                ))}
              </FieldGroup>
            </FieldSet>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={isMutating}
              >
                取消
              </Button>
              <Button type="submit" disabled={isMutating || !editingRoleCode}>
                {isMutating ? "保存中…" : "保存更改"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
