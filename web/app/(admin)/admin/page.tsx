"use client";

import Link from "next/link";
import {
  Building2,
  Files,
  RefreshCw,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAdminCompanies,
  useAdminRoles,
  useAdminUsers,
} from "@/lib/hooks/use-admin";

interface MetricCardProps {
  title: string;
  value: number;
  detail: string;
  icon: LucideIcon;
  isLoading: boolean;
}

function MetricCard({
  title,
  value,
  detail,
  icon: Icon,
  isLoading,
}: MetricCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
          <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-20" />
        ) : (
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

export default function AdminOverviewPage() {
  const companies = useAdminCompanies(true);
  const users = useAdminUsers({ limit: 200 });
  const roles = useAdminRoles();

  const errors = [companies.error, users.error, roles.error].filter(
    (error): error is string => Boolean(error)
  );
  const activeCompanies = companies.companies.filter(
    (company) => company.status === "active"
  ).length;
  const activeUsers = users.users.filter((user) => user.status === "active").length;
  const roleCount = Object.keys(roles.roles).length;

  const refreshAll = () => {
    void Promise.all([
      companies.refresh(),
      users.refresh(),
      roles.refresh(),
    ]).catch(() => undefined);
  };

  return (
    <section className="flex flex-col gap-6" aria-labelledby="admin-overview-title">
      <div className="flex flex-col gap-1">
        <h2 id="admin-overview-title" className="text-xl font-semibold">
          管理概览
        </h2>
        <p className="text-sm text-muted-foreground">
          查看当前组织、用户与角色权限配置的汇总情况。
        </p>
      </div>

      {errors.length > 0 && (
        <Alert variant="destructive">
          <RefreshCw aria-hidden="true" />
          <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <AlertTitle>部分管理数据加载失败</AlertTitle>
              <AlertDescription>{errors.join("；")}</AlertDescription>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={refreshAll}>
              <RefreshCw data-icon="inline-start" />
              重试
            </Button>
          </div>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="公司"
          value={companies.companies.length}
          detail={`${activeCompanies} 家启用中`}
          icon={Building2}
          isLoading={companies.isLoading && companies.companies.length === 0}
        />
        <MetricCard
          title="用户"
          value={users.users.length}
          detail={`${activeUsers} 位状态正常，最多加载 200 位`}
          icon={Users}
          isLoading={users.isLoading && users.users.length === 0}
        />
        <MetricCard
          title="角色"
          value={roleCount}
          detail={`${roles.allModules.length} 个可配置模块`}
          icon={ShieldCheck}
          isLoading={roles.isLoading && roleCount === 0}
        />
        <MetricCard
          title="报告分区"
          value={roles.reportSections.length}
          detail="用于控制报告内容可见范围"
          icon={ShieldCheck}
          isLoading={roles.isLoading && roles.reportSections.length === 0}
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle className="text-base">常用管理入口</CardTitle>
            <p className="text-sm text-muted-foreground">
              进入对应页面维护公司、用户及角色权限。
            </p>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link href="/admin/companies">
              <Building2 data-icon="inline-start" />
              公司管理
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/admin/users">
              <Users data-icon="inline-start" />
              用户管理
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/admin/roles">
              <ShieldCheck data-icon="inline-start" />
              角色权限
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/admin/templates">
              <Files data-icon="inline-start" />
              模板管理
            </Link>
          </Button>
        </CardContent>
      </Card>
    </section>
  );
}
