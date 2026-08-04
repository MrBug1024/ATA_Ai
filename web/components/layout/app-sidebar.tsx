"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  MessageSquare,
  ClipboardCheck,
  User,
  Loader2,
  Trash2,
  Search,
  Settings,
  ShieldCheck,
  HelpCircle,
  RefreshCw,
} from "lucide-react";
import { SettingsDialog } from "@/components/settings/settings-dialog";
import { HelpDialog } from "@/components/help/help-dialog";
import { useState, useEffect } from "react";
import { useConversations, type LangGraphThread } from "@/lib/hooks/use-conversations";
import { useAuth } from "@/lib/hooks/use-auth";
import { canAccessAdmin } from "@/lib/auth/authorization";
import { deleteThread } from "@/lib/backend/langgraph";
import { toast } from "sonner";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function AppSidebar() {
  const pathname = usePathname();
  const { conversations, total, isLoading, error, refresh } = useConversations({ limit: 200 });
  const { user } = useAuth();
  const [isSearching, setIsSearching] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // Refresh thread list when navigating to a chat page so a new thread shows up.
  useEffect(() => {
    if (pathname.startsWith("/chat/")) {
      refresh();
    }
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Sidebar variant="inset" collapsible="offcanvas">
      {/* ── Header ─────────────────────────────── */}
      <SidebarHeader className="px-3 py-3">
        <div className="flex items-center gap-1.5">
          <Link href="/chat" className="flex flex-1 items-center gap-2.5">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-sidebar-foreground/10 text-[11px] font-bold text-sidebar-foreground">
              A
            </div>
            <span className="text-sm font-semibold tracking-tight text-sidebar-foreground">
              AI 会计师
            </span>
          </Link>
          <button
            type="button"
            onClick={() => {
              setIsSearching((v) => !v);
              if (isSearching) setSearchQuery("");
            }}
            className={cn(
              "flex size-6 items-center justify-center rounded-md text-sidebar-foreground/50 hover:bg-sidebar-accent hover:text-sidebar-foreground transition-colors",
              isSearching && "bg-sidebar-accent text-sidebar-foreground"
            )}
            aria-label="搜索对话"
          >
            <Search className="size-3.5" />
          </button>
        </div>
        {isSearching && (
          <div className="px-1 pt-2">
            <input
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setIsSearching(false);
                  setSearchQuery("");
                }
              }}
              placeholder="搜索对话..."
              className="w-full rounded-md border border-sidebar-border bg-sidebar-accent/50 px-2.5 py-1 text-xs text-sidebar-foreground placeholder:text-sidebar-foreground/40 outline-none focus:border-sidebar-foreground/30"
            />
          </div>
        )}
      </SidebarHeader>

      {/* ── Content ────────────────────────────── */}
      <SidebarContent>
        {/* Navigation */}
        <SidebarGroup className="py-1">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname === "/chat"}>
                  <Link href="/chat">
                    <MessageSquare className="size-4" />
                    <span>新建对话</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname === "/cases"}>
                  <Link href="/cases">
                    <ClipboardCheck className="size-4" />
                    <span>年审项目</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {canAccessAdmin(user) && (
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith("/admin")}
                  >
                    <Link href="/admin">
                      <ShieldCheck />
                      <span>管理后台</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarSeparator />

        {/* Conversation list */}
        <SidebarGroup className="flex-1 overflow-hidden py-1">
          <SidebarGroupLabel>
            最近对话{total > 0 ? ` (${conversations.length}/${total})` : ""}
          </SidebarGroupLabel>
          <SidebarGroupContent className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin] [scrollbar-color:transparent_transparent] hover:[scrollbar-color:oklch(0.60_0.04_255_/_0.2)_transparent] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-transparent [&:hover::-webkit-scrollbar-thumb]:bg-sidebar-foreground/20">
            <ConversationList
              conversations={conversations}
              isLoading={isLoading}
              error={error}
              refresh={refresh}
              pathname={pathname}
              searchQuery={searchQuery}
            />
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      {/* ── Footer ─────────────────────────────── */}
      <SidebarFooter className="px-2 py-2">
        <SidebarMenu>
          {user && (
            <SidebarMenuItem>
              <SidebarMenuButton className="cursor-default select-none opacity-70 hover:bg-transparent hover:text-sidebar-foreground">
                <User className="size-3.5" />
                <span className="truncate text-xs">
                  {user.username || user.user_id || "当前用户"}
                </span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => setHelpOpen(true)}
              className="text-sidebar-foreground/70"
            >
              <HelpCircle className="size-3.5" />
              <span>使用帮助</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => setSettingsOpen(true)}
              className="text-sidebar-foreground/70"
            >
              <Settings className="size-3.5" />
              <span>设置</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <HelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </Sidebar>
  );
}

function ConversationList({
  conversations,
  isLoading,
  error,
  refresh,
  pathname,
  searchQuery,
}: {
  conversations: LangGraphThread[];
  isLoading: boolean;
  error: string | null;
  refresh: () => void | Promise<unknown>;
  pathname: string;
  searchQuery: string;
}) {
  const router = useRouter();
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const visibleItems = conversations.filter(
    (c) =>
      !deletedIds.has(c.thread_id) &&
      (!searchQuery ||
        (c.title || "新对话").toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (deletingId) return;
    setDeletingId(id);
    try {
      await deleteThread(id);
      setDeletedIds((prev) => new Set(prev).add(id));
      toast.success("对话已删除");
      if (pathname === `/chat/${id}`) router.push("/chat");
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  // Only show spinner on initial load (no data yet)
  if (isLoading && conversations.length === 0) {
    return (
      <div className="flex justify-center py-6">
        <Loader2 className="size-3.5 animate-spin text-sidebar-foreground/30" />
      </div>
    );
  }

  if (error && conversations.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-2 py-4 text-center">
        <p className="text-xs text-sidebar-foreground/50">对话加载失败</p>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={() => void Promise.resolve(refresh()).catch(() => undefined)}
        >
          <RefreshCw data-icon="inline-start" />
          重试
        </Button>
      </div>
    );
  }

  if (visibleItems.length === 0) {
    return (
      <p className="px-2 py-2 text-xs text-sidebar-foreground/40">暂无对话</p>
    );
  }

  return (
    <SidebarMenu>
      {visibleItems.map((conversation) => {
        const id = conversation.thread_id;
        return (
          <SidebarMenuItem key={id}>
            <SidebarMenuButton
              asChild
              isActive={pathname === `/chat/${id}`}
              className="pr-10"
            >
              <Link
                href={conversation.case_id ? `/chat/${id}?caseId=${conversation.case_id}` : `/chat/${id}`}
                className="flex items-center gap-1.5"
              >
                <span className="truncate text-xs">
                  {conversation.title || "新对话"}
                </span>
                <span className={cn(
                  "shrink-0 rounded px-1 py-0 text-[9px] font-medium",
                  conversation.case_id
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-muted text-muted-foreground/70"
                )}>
                  {conversation.case_id ? "年审" : "通用"}
                </span>
              </Link>
            </SidebarMenuButton>

            <SidebarMenuAction
              showOnHover
              onClick={(e) => handleDelete(id, e)}
              disabled={!!deletingId}
              className="text-sidebar-foreground/40 hover:text-sidebar-foreground"
            >
              {deletingId === id ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Trash2 className="size-3" />
              )}
            </SidebarMenuAction>
          </SidebarMenuItem>
        );
      })}
    </SidebarMenu>
  );
}
