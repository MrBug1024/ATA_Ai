import { AdminShell } from "@/components/admin/admin-shell";
import { AdminGuard } from "@/components/auth/admin-guard";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminGuard>
      <AdminShell>{children}</AdminShell>
    </AdminGuard>
  );
}
