"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Info,
  LayoutDashboard,
  ShieldCheck,
  Users,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  canManageCompanies,
  isSystemAdminPreview,
} from "@/lib/auth/authorization";
import { useAuth } from "@/lib/hooks/use-auth";

const ADMIN_NAVIGATION = [
  { href: "/admin", label: "概览", icon: LayoutDashboard },
  { href: "/admin/users", label: "用户", icon: Users },
  { href: "/admin/roles", label: "角色权限", icon: ShieldCheck },
] as const;

function isNavigationActive(
  pathname: string,
  item: (typeof ADMIN_NAVIGATION)[number]
): boolean {
  return item.href === "/admin"
    ? pathname === item.href
    : pathname.startsWith(item.href);
}

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/admin/users")) return "用户管理";
  if (pathname.startsWith("/admin/companies")) return "公司管理";
  if (pathname.startsWith("/admin/roles")) return "角色权限";
  return "管理概览";
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const showCompanies = canManageCompanies(user);
  const isPreview = isSystemAdminPreview(user);

  return (
    <SidebarProvider className="h-svh min-h-0 overflow-hidden bg-sidebar">
      <Sidebar variant="inset" collapsible="offcanvas">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild>
                <Link href="/admin">
                  <ShieldCheck />
                  <div className="flex min-w-0 flex-col leading-tight">
                    <span className="truncate font-semibold">AI 会计师</span>
                    <span className="truncate text-xs text-muted-foreground">
                      管理后台
                    </span>
                  </div>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>系统管理</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {ADMIN_NAVIGATION.slice(0, 2).map((item) => {
                  const Icon = item.icon;
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        asChild
                        isActive={isNavigationActive(pathname, item)}
                      >
                        <Link href={item.href}>
                          <Icon />
                          <span>{item.label}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}

                {showCompanies && (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      asChild
                      isActive={pathname.startsWith("/admin/companies")}
                    >
                      <Link href="/admin/companies">
                        <Building2 />
                        <span>公司</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )}

                {ADMIN_NAVIGATION.slice(2).map((item) => {
                  const Icon = item.icon;
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        asChild
                        isActive={isNavigationActive(pathname, item)}
                      >
                        <Link href={item.href}>
                          <Icon />
                          <span>{item.label}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton asChild>
                <Link href="/chat">
                  <ArrowLeft />
                  <span>返回工作台</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="flex min-h-0 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
          <SidebarTrigger />
          <h1 className="text-sm font-medium">{pageTitle(pathname)}</h1>
        </header>
        <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 md:p-6">
          {isPreview && (
            <Alert>
              <Info aria-hidden="true" />
              <div>
                <AlertTitle>开放模式本地预览</AlertTitle>
                <AlertDescription>
                  此入口仅用于本地界面预览，所有管理员操作仍必须以后端权限校验为准。
                </AlertDescription>
              </div>
            </Alert>
          )}
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
