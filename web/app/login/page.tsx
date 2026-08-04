"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/hooks/use-auth";
import { toast } from "sonner";
import { Loader2, Eye, EyeOff } from "lucide-react";

export default function LoginPage() {
  const { login } = useAuth();
  const [loginIdentifier, setLoginIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!loginIdentifier.trim() || !password.trim()) {
      toast.error("请输入用户名和密码");
      return;
    }
    setIsLoading(true);
    try {
      await login(loginIdentifier.trim(), password);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "登录失败");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4">
      <div className="relative w-full max-w-[340px]">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex size-9 items-center justify-center rounded-md border border-border/50 bg-card text-sm font-bold text-foreground">
            A
          </div>
          <h1 className="text-base font-semibold tracking-tight text-foreground">
            AI 会计师
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">年度财务报表审计智能工作平台</p>
        </div>

        <Card className="border-border/50 bg-card/60 shadow-xl shadow-black/20 backdrop-blur-sm">
          <CardHeader className="p-6 pb-5">
            <CardTitle className="text-sm">登录账户</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit}>
              <FieldGroup className="gap-4">
                <Field>
                  <FieldLabel htmlFor="login-identifier" className="text-xs text-muted-foreground">
                    用户名
                  </FieldLabel>
                  <Input
                    id="login-identifier"
                    type="text"
                    autoComplete="username"
                    placeholder="请输入用户名"
                    value={loginIdentifier}
                    onChange={(event) => setLoginIdentifier(event.target.value)}
                    required
                    className="h-9 bg-background/50"
                  />
                </Field>

                <Field>
                  <FieldLabel htmlFor="login-password" className="text-xs text-muted-foreground">
                    密码
                  </FieldLabel>
                  <div className="relative">
                    <Input
                      id="login-password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      placeholder="请输入密码"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      required
                      className="h-9 bg-background/50 pr-9"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setShowPassword((current) => !current)}
                      className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground"
                      aria-label={showPassword ? "隐藏密码" : "显示密码"}
                    >
                      {showPassword ? <EyeOff /> : <Eye />}
                    </Button>
                  </div>
                </Field>

                <Button type="submit" size="lg" disabled={isLoading} className="w-full">
                  {isLoading ? (
                    <>
                      <Loader2 className="animate-spin" data-icon="inline-start" />
                      登录中...
                    </>
                  ) : (
                    "登录"
                  )}
                </Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
