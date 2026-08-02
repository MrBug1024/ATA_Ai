"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/hooks/use-auth";
import { Loader2 } from "lucide-react";

const PUBLIC_PATHS = ["/login"];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isLoading, isAuthenticated } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const isPublicPath = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated && isPublicPath) {
      router.replace("/chat");
      return;
    }
    if (!isAuthenticated && !isPublicPath) {
      const from = pathname + window.location.search;
      router.replace(`/login?from=${encodeURIComponent(from)}`);
    }
  }, [isLoading, isAuthenticated, isPublicPath, pathname, router]);

  const isRedirecting =
    !isLoading &&
    ((isAuthenticated && isPublicPath) || (!isAuthenticated && !isPublicPath));

  if (isLoading || isRedirecting) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="size-8 animate-spin text-muted-foreground/30" />
      </div>
    );
  }

  return <>{children}</>;
}
