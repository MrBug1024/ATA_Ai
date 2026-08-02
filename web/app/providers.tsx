"use client";

import { ThemeProvider } from "next-themes";
import { SWRConfig } from "swr";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GlobalUploadFloat } from "@/components/global-upload-float";
import { AuthProvider } from "@/lib/hooks/use-auth";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <AuthProvider>
        <SWRConfig value={{ revalidateOnFocus: false, dedupingInterval: 30000 }}>
          <TooltipProvider delayDuration={0}>
            {children}
            <Toaster
              position="top-right"
              toastOptions={{
                classNames: {
                  toast:
                    "bg-popover text-popover-foreground border border-border shadow-lg",
                  description: "text-muted-foreground",
                },
              }}
            />
            <GlobalUploadFloat />
          </TooltipProvider>
        </SWRConfig>
      </AuthProvider>
    </ThemeProvider>
  );
}
