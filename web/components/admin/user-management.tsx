"use client";

import { useMemo, useState } from "react";
import { AlertCircle, KeyRound, Pencil, Plus, RefreshCw, Search, Users } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
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
import type { AdminUserRecord, UserStatus } from "@/lib/backend/admin";
import { useAdminCompanies, useAdminUsers } from "@/lib/hooks/use-admin";
import { UserAccessDialog } from "./user-access-dialog";
import { UserFormDialog } from "./user-form-dialog";

const STATUS_LABEL: Record<UserStatus, string> = {
  active: "正常",
  disabled: "停用",
  locked: "锁定",
};

function StatusBadge({ status }: { status: UserStatus }) {
  return (
    <Badge variant={status === "active" ? "secondary" : "destructive"}>
      {STATUS_LABEL[status]}
    </Badge>
  );
}

function dateTime(value: string | null): string {
  if (!value) return "从未登录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export function UserManagement() {
  const [status, setStatus] = useState<UserStatus | "">("");
  const [companyId, setCompanyId] = useState("");
  const [query, setQuery] = useState("");
  const [formUser, setFormUser] = useState<AdminUserRecord | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [accessUser, setAccessUser] = useState<AdminUserRecord | null>(null);
  const companiesQuery = useAdminCompanies(true);
  const usersQuery = useAdminUsers({ companyId, status, limit: 1000 });

  const filteredUsers = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return usersQuery.users;
    return usersQuery.users.filter((user) =>
      [
        user.user_id,
        user.username,
        user.company_display_name,
        user.company,
        user.region,
      ].some((value) => value?.toLocaleLowerCase().includes(needle))
    );
  }, [query, usersQuery.users]);

  function openCreate() {
    setFormUser(null);
    setFormOpen(true);
  }

  function openEdit(user: AdminUserRecord) {
    setFormUser(user);
    setFormOpen(true);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">用户管理</h2>
          <p className="text-sm text-muted-foreground">
            管理用户主档、状态、认证来源，以及独立的角色和人员标签。
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus data-icon="inline-start" />
          新建用户
        </Button>
      </div>

      <Card>
        <CardHeader className="gap-3 pb-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <CardTitle className="text-base">用户列表</CardTitle>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="relative min-w-56">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input
                  value={query}
                  className="pl-8"
                  placeholder="筛选当前结果"
                  aria-label="筛选当前用户结果"
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
              <Select
                value={companyId || "__all__"}
                onValueChange={(value) => setCompanyId(value === "__all__" ? "" : value)}
              >
                <SelectTrigger className="w-full sm:w-44" aria-label="按公司筛选">
                  <SelectValue placeholder="全部公司" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部公司</SelectItem>
                  {companiesQuery.companies.map((company) => (
                    <SelectItem key={company.company_id} value={company.company_id}>
                      {company.company_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={status || "__all__"}
                onValueChange={(value) => setStatus(value === "__all__" ? "" : value as UserStatus)}
              >
                <SelectTrigger className="w-full sm:w-32" aria-label="按状态筛选">
                  <SelectValue placeholder="全部状态" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部状态</SelectItem>
                  <SelectItem value="active">正常</SelectItem>
                  <SelectItem value="disabled">停用</SelectItem>
                  <SelectItem value="locked">锁定</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {usersQuery.error ? (
            <Alert variant="destructive">
              <AlertCircle aria-hidden="true" />
              <AlertDescription className="flex flex-1 items-center justify-between gap-3">
                <span>{usersQuery.error}</span>
                <Button size="sm" variant="outline" onClick={() => usersQuery.refresh()}>
                  <RefreshCw data-icon="inline-start" />
                  重试
                </Button>
              </AlertDescription>
            </Alert>
          ) : usersQuery.isLoading ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : filteredUsers.length === 0 ? (
            <Empty className="min-h-56 border">
              <EmptyHeader>
                <EmptyMedia variant="icon"><Users /></EmptyMedia>
                <EmptyTitle>没有匹配的用户</EmptyTitle>
                <EmptyDescription>
                  {query || status || companyId ? "调整筛选条件后重试。" : "创建第一个平台用户。"}
                </EmptyDescription>
              </EmptyHeader>
              {!query && !status && !companyId && (
                <Button size="sm" onClick={openCreate}><Plus data-icon="inline-start" />新建用户</Button>
              )}
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>用户</TableHead>
                  <TableHead>公司 / 区域</TableHead>
                  <TableHead>认证</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>最近登录</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredUsers.map((user) => (
                  <TableRow key={user.user_id}>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2 font-medium">
                          {user.username}
                          {user.is_super_admin && <Badge>超级管理员</Badge>}
                        </div>
                        <span className="text-xs text-muted-foreground">{user.user_id}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <span>{user.company_display_name || user.company || "未指定"}</span>
                        <span className="text-xs text-muted-foreground">
                          {[user.company_id, user.region].filter(Boolean).join(" · ") || "—"}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell><Badge variant="outline">{user.auth_source}</Badge></TableCell>
                    <TableCell><StatusBadge status={user.status} /></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{dateTime(user.last_login_at)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setAccessUser(user)}>
                          <KeyRound data-icon="inline-start" />
                          权限
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => openEdit(user)}>
                          <Pencil data-icon="inline-start" />
                          编辑
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <UserFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        user={formUser}
        companies={companiesQuery.companies}
      />
      <UserAccessDialog
        open={Boolean(accessUser)}
        onOpenChange={(open) => { if (!open) setAccessUser(null); }}
        user={accessUser}
      />
    </div>
  );
}
