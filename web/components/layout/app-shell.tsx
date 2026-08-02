import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { AppSidebar } from "./app-sidebar";
import { GraphModal } from "@/components/knowledge-graph/graph-modal";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <SidebarProvider className="h-svh min-h-0 overflow-hidden bg-sidebar">
      <AppSidebar />
      <SidebarInset className="flex min-h-0 flex-col overflow-hidden">
        {children}
      </SidebarInset>
      <GraphModal />
    </SidebarProvider>
  );
}
