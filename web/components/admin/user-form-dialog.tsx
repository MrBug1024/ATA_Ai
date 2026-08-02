"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Loader2, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
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
import { Textarea } from "@/components/ui/textarea";
import type {
  AdminUserRecord,
  AuthSource,
  CompanyRecord,
  UserStatus,
} from "@/lib/backend/admin";
import {
  useCreateAdminUser,
  useUpdateAdminUser,
} from "@/lib/hooks/use-admin";

interface UserFormState {
  userId: string;
  username: string;
  companyId: string;
  authSource: AuthSource;
  status: UserStatus;
  password: string;
  region: string;
  note: string;
}

const EMPTY_FORM: UserFormState = {
  userId: "",
  username: "",
  companyId: "",
  authSource: "local",
  status: "active",
  password: "",
  region: "",
  note: "",
};

function stateForUser(user: AdminUserRecord | null): UserFormState {
  if (!user) return EMPTY_FORM;
  return {
    userId: user.user_id,
    username: user.username,
    companyId: user.company_id,
    authSource: user.auth_source,
    status: user.status,
    password: "",
    region: user.region,
    note: user.note,
  };
}

export function passwordError(
  value: string,
  userId: string,
  username: string,
  required: boolean
): string | null {
  if (!value) return required ? "本地认证用户必须设置初始密码" : null;
  if (value.length < 10) return "密码至少需要 10 个字符";
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
    return "密码必须同时包含字母和数字";
  }
  const normalized = value.toLocaleLowerCase();
  if (
    normalized === userId.trim().toLocaleLowerCase() ||
    normalized === username.trim().toLocaleLowerCase()
  ) {
    return "密码不能与用户 ID 或显示名称相同";
  }
  return null;
}

export interface UserFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: AdminUserRecord | null;
  companies: CompanyRecord[];
}

export function UserFormDialog({
  open,
  onOpenChange,
  user,
  companies,
}: UserFormDialogProps) {
  const [form, setForm] = useState<UserFormState>(() => stateForUser(user));
  const [validationError, setValidationError] = useState<string | null>(null);
  const createMutation = useCreateAdminUser();
  const updateMutation = useUpdateAdminUser(user?.user_id ?? "__new__");
  const editing = Boolean(user);
  const isSaving = createMutation.isMutating || updateMutation.isMutating;
  const requestError = createMutation.error || updateMutation.error;

  useEffect(() => {
    if (!open) return;
    setForm(stateForUser(user));
    setValidationError(null);
    createMutation.reset();
    updateMutation.reset();
  }, [open, user, createMutation.reset, updateMutation.reset]);

  const selectedCompany = useMemo(
    () => companies.find((company) => company.company_id === form.companyId),
    [companies, form.companyId]
  );

  function update<K extends keyof UserFormState>(key: K, value: UserFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);
    const userId = form.userId.trim();
    const username = form.username.trim();
    if (!userId || !username) {
      setValidationError("用户 ID 和显示名称不能为空");
      return;
    }
    if (!form.companyId && (!editing || !user?.is_super_admin)) {
      setValidationError("普通用户必须归属一家公司");
      return;
    }
    const invalidPassword =
      !editing && form.authSource === "local"
        ? passwordError(form.password, userId, username, true)
        : null;
    if (invalidPassword) {
      setValidationError(invalidPassword);
      return;
    }

    const profilePayload = {
      username,
      company_id: form.companyId,
      company:
        selectedCompany?.company_name ??
        (form.companyId === user?.company_id ? user.company : ""),
      status: form.status,
      region: form.region.trim(),
      note: form.note.trim(),
    };

    try {
      if (editing) {
        await updateMutation.updateAdminUser(profilePayload);
        toast.success("用户资料已更新");
      } else {
        await createMutation.createAdminUser({
          user_id: userId,
          ...profilePayload,
          auth_source: form.authSource,
          ...(form.authSource === "local" ? { password: form.password } : {}),
        });
        toast.success("用户已创建");
      }
      onOpenChange(false);
    } catch {
      // The mutation hook exposes the backend detail below.
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑用户" : "新建用户"}</DialogTitle>
          <DialogDescription>
            用户主档与角色、标签分开保存，避免多接口部分成功时误报完成。
          </DialogDescription>
        </DialogHeader>

        <form id="admin-user-form" onSubmit={submit}>
          <FieldGroup className="grid gap-4 md:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="admin-user-id">用户 ID</FieldLabel>
              <Input
                id="admin-user-id"
                value={form.userId}
                disabled={editing || isSaving}
                required
                autoComplete="off"
                onChange={(event) => update("userId", event.target.value)}
              />
              <FieldDescription>
                新建本地密码账号时，该值同时作为登录用户名；创建后不可修改。
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="admin-username">显示名称</FieldLabel>
              <Input
                id="admin-username"
                value={form.username}
                disabled={isSaving}
                required
                autoComplete="off"
                onChange={(event) => update("username", event.target.value)}
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="admin-company">归属公司</FieldLabel>
              <Select
                value={form.companyId || "__none__"}
                disabled={isSaving}
                onValueChange={(value) =>
                  update("companyId", value === "__none__" ? "" : value)
                }
              >
                <SelectTrigger id="admin-company" className="w-full">
                  <SelectValue placeholder="选择公司" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="__none__">不指定</SelectItem>
                    {companies.map((company) => (
                      <SelectItem key={company.company_id} value={company.company_id}>
                        {company.company_name}
                        {company.status === "disabled" ? "（已停用）" : ""}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="admin-auth-source">认证来源</FieldLabel>
              <Select
                value={form.authSource}
                disabled={editing || isSaving}
                onValueChange={(value) =>
                  setForm((current) => ({
                    ...current,
                    authSource: value as AuthSource,
                    password: value === "local" ? current.password : "",
                  }))
                }
              >
                <SelectTrigger id="admin-auth-source" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="local">本地密码</SelectItem>
                    <SelectItem value="platform">平台账号</SelectItem>
                    <SelectItem value="sso">SSO</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              {editing && (
                <FieldDescription>
                  现有账号的认证来源需由后端完成凭据迁移后才能修改。
                </FieldDescription>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="admin-user-status">账号状态</FieldLabel>
              <Select
                value={form.status}
                disabled={isSaving}
                onValueChange={(value) => update("status", value as UserStatus)}
              >
                <SelectTrigger id="admin-user-status" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="active">正常</SelectItem>
                    <SelectItem value="disabled">停用</SelectItem>
                    <SelectItem value="locked">锁定</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                停用或锁定会阻止后续登录；已有会话需等待后端令牌撤销支持。
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="admin-region">区域</FieldLabel>
              <Input
                id="admin-region"
                value={form.region}
                disabled={isSaving}
                onChange={(event) => update("region", event.target.value)}
              />
            </Field>

            {!editing && form.authSource === "local" && (
              <Field className="md:col-span-2">
                <FieldLabel htmlFor="admin-password">初始密码</FieldLabel>
                <Input
                  id="admin-password"
                  type="password"
                  value={form.password}
                  disabled={isSaving}
                  autoComplete="new-password"
                  onChange={(event) => update("password", event.target.value)}
                />
                <FieldDescription>
                  至少 10 位并同时包含字母和数字，且不能与用户 ID 或显示名称相同。
                </FieldDescription>
              </Field>
            )}

            <Field className="md:col-span-2">
              <FieldLabel htmlFor="admin-user-note">备注</FieldLabel>
              <Textarea
                id="admin-user-note"
                value={form.note}
                disabled={isSaving}
                onChange={(event) => update("note", event.target.value)}
              />
            </Field>
          </FieldGroup>
        </form>

        {(validationError || requestError) && (
          <Alert variant="destructive">
            <ShieldAlert aria-hidden="true" />
            <AlertDescription>
              <FieldError>{validationError || requestError}</FieldError>
            </AlertDescription>
          </Alert>
        )}

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
            取消
          </Button>
          <Button type="submit" form="admin-user-form" disabled={isSaving}>
            {isSaving && <Loader2 data-icon="inline-start" className="animate-spin" />}
            {editing ? "保存资料" : "创建用户"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
