import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AuthGuard } from "@/components/auth/auth-guard";

export const metadata: Metadata = {
  title: "AI 会计师",
  description: "年度财务报表审计智能工作平台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning className="h-full">
      <body className="font-sans antialiased h-full overflow-hidden">
        <Providers>
          <AuthGuard>{children}</AuthGuard>
        </Providers>
      </body>
    </html>
  );
}
