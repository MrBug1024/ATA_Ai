"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useDebugMode } from "@/lib/hooks/use-debug-mode";
import { useTheme } from "next-themes";
import { useAuth } from "@/lib/hooks/use-auth";
import { ChevronDown, KeyRound, Loader2, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const THEMES = [
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
  { value: "system", label: "跟随系统", icon: Monitor },
] as const;

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const [debugMode, setDebugMode] = useDebugMode();
  const { theme, setTheme } = useTheme();
  const { user, logout, changePassword } = useAuth();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const resetPasswordForm = () => {
    setOldPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setPasswordOpen(false);
  };

  const handlePasswordChange = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!oldPassword || !newPassword || !confirmPassword) {
      toast.error("请填写全部密码字段");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("两次输入的新密码不一致");
      return;
    }

    setIsChangingPassword(true);
    try {
      await changePassword(oldPassword, newPassword);
      toast.success("密码已修改");
      resetPasswordForm();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "修改密码失败");
    } finally {
      setIsChangingPassword(false);
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) resetPasswordForm();
    onOpenChange(nextOpen);
  };

  const passwordsMismatch = Boolean(confirmPassword && newPassword !== confirmPassword);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle className="text-base">设置</DialogTitle>
          <DialogDescription className="text-xs">外观、调试与账户安全</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* Theme */}
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">外观</span>
            <div className="grid grid-cols-3 gap-2">
              {THEMES.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTheme(value)}
                  className={cn(
                    "flex flex-col items-center gap-1.5 rounded-md border px-3 py-2.5 text-xs transition-colors",
                    theme === value
                      ? "border-ring bg-accent text-foreground"
                      : "border-border/40 text-muted-foreground hover:bg-accent/40 hover:text-foreground"
                  )}
                >
                  <Icon className="size-4" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Debug */}
          <label className="flex items-start gap-3 rounded-md border border-border/40 bg-background px-3 py-2.5 cursor-pointer hover:bg-accent/30">
            <input
              type="checkbox"
              checked={debugMode}
              onChange={(e) => setDebugMode(e.target.checked)}
              className="mt-0.5 size-4 accent-foreground"
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">显示节点跟踪</span>
              <span className="text-xs text-muted-foreground/70">
                开启后，AI 回复时会展示后端图节点的执行步骤与 payload（调试用）。
              </span>
            </div>
          </label>

          {user?.authenticated && (
            <>
              <Separator />
              <div className="flex flex-col gap-3">
                <span className="text-xs font-medium text-muted-foreground">账户安全</span>
                <Collapsible open={passwordOpen} onOpenChange={setPasswordOpen}>
                  <CollapsibleTrigger asChild>
                    <Button type="button" variant="outline" className="w-full justify-between">
                      <span className="flex items-center gap-2">
                        <KeyRound data-icon="inline-start" />
                        修改密码
                      </span>
                      <ChevronDown
                        data-icon="inline-end"
                        className={cn("transition-transform", passwordOpen && "rotate-180")}
                      />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="pt-3">
                    <form onSubmit={handlePasswordChange}>
                      <FieldGroup className="gap-3">
                        <Field>
                          <FieldLabel htmlFor="old-password" className="text-xs">
                            当前密码
                          </FieldLabel>
                          <Input
                            id="old-password"
                            type="password"
                            autoComplete="current-password"
                            value={oldPassword}
                            onChange={(event) => setOldPassword(event.target.value)}
                            required
                          />
                        </Field>
                        <Field>
                          <FieldLabel htmlFor="new-password" className="text-xs">
                            新密码
                          </FieldLabel>
                          <Input
                            id="new-password"
                            type="password"
                            autoComplete="new-password"
                            value={newPassword}
                            onChange={(event) => setNewPassword(event.target.value)}
                            required
                          />
                        </Field>
                        <Field data-invalid={passwordsMismatch || undefined}>
                          <FieldLabel htmlFor="confirm-password" className="text-xs">
                            确认新密码
                          </FieldLabel>
                          <Input
                            id="confirm-password"
                            type="password"
                            autoComplete="new-password"
                            value={confirmPassword}
                            onChange={(event) => setConfirmPassword(event.target.value)}
                            aria-invalid={passwordsMismatch || undefined}
                            required
                          />
                          {passwordsMismatch && <FieldError>两次输入的新密码不一致</FieldError>}
                        </Field>
                        <Button type="submit" disabled={isChangingPassword}>
                          {isChangingPassword && (
                            <Loader2 className="animate-spin" data-icon="inline-start" />
                          )}
                          保存新密码
                        </Button>
                      </FieldGroup>
                    </form>
                  </CollapsibleContent>
                </Collapsible>

                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => {
                    onOpenChange(false);
                    void logout();
                  }}
                  className="w-full"
                >
                  <LogOut data-icon="inline-start" />
                  退出登录
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
