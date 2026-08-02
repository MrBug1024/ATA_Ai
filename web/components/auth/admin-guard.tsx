"use client";

import { useEffect } from "react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { canAccessAdmin } from "@/lib/auth/authorization";
import { useAuth } from "@/lib/hooks/use-auth";

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, isLoading } = useAuth();
  const hasAccess = canAccessAdmin(user);

  useEffect(() => {
    if (!isLoading && !hasAccess) router.replace("/chat");
  }, [hasAccess, isLoading, router]);

  if (isLoading || !hasAccess) {
    return (
      <div
        className="flex min-h-svh items-center justify-center gap-2 text-sm text-muted-foreground"
        role="status"
      >
        <Loader2 className="size-5 animate-spin" aria-hidden="true" />
        <span>
          {isLoading ? "正在验证管理员权限…" : "无管理员权限，正在返回工作台…"}
        </span>
      </div>
    );
  }

  return <>{children}</>;
}
