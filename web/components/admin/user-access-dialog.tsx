"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, Tags, UserCog } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  AdminUserRecord,
  TagCatalogItem,
  TagDimension,
} from "@/lib/backend/admin";
import {
  useAdminRoles,
  useAdminUserRoles,
  useAdminUserTags,
  useSaveUserRoles,
  useSaveUserTags,
  useTagCatalog,
} from "@/lib/hooks/use-admin";

const TAG_DIMENSIONS: Array<{ code: TagDimension; label: string }> = [
  { code: "project_role", label: "项目角色" },
  { code: "title", label: "职级" },
  { code: "expertise", label: "专业领域" },
];

type TagSelection = Record<TagDimension, string[]>;

const EMPTY_TAGS: TagSelection = {
  project_role: [],
  title: [],
  expertise: [],
};

function emptyTagSelection(): TagSelection {
  return {
    project_role: [],
    title: [],
    expertise: [],
  };
}

function toggleValue(values: string[], value: string, checked: boolean): string[] {
  if (checked) return values.includes(value) ? values : [...values, value];
  return values.filter((item) => item !== value);
}

function groupCatalog(items: TagCatalogItem[]): Map<string, TagCatalogItem[]> {
  const groups = new Map<string, TagCatalogItem[]>();
  for (const item of items) {
    const group = item.tag_group || "其他";
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return groups;
}

export interface UserAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: AdminUserRecord | null;
}

export function UserAccessDialog({ open, onOpenChange, user }: UserAccessDialogProps) {
  const userId = user?.user_id ?? null;
  const userCompanyId = user?.company_id ?? "";
  const roleCatalog = useAdminRoles();
  const tagCatalog = useTagCatalog();
  const userRoles = useAdminUserRoles(userId, userCompanyId);
  const userTags = useAdminUserTags(userId);
  const roleMutation = useSaveUserRoles(
    user ?? { user_id: "__none__", company_id: "" }
  );
  const tagMutation = useSaveUserTags(userId ?? "__none__");
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<TagSelection>(EMPTY_TAGS);

  useEffect(() => {
    if (!open) return;
    setSelectedRoles([]);
    setSelectedTags(emptyTagSelection());
    roleMutation.reset();
    tagMutation.reset();
  }, [open, userId, roleMutation.reset, tagMutation.reset]);

  useEffect(() => {
    if (
      !open ||
      userRoles.error ||
      userRoles.data?.user_id !== userId ||
      userRoles.data.company_id !== userCompanyId
    ) return;
    setSelectedRoles(userRoles.data.roles);
  }, [open, userCompanyId, userId, userRoles.data, userRoles.error]);

  useEffect(() => {
    if (
      !open ||
      userTags.error ||
      userTags.data?.user_id !== userId
    ) return;
    setSelectedTags({
      project_role: userTags.data.tags.project_role ?? [],
      title: userTags.data.tags.title ?? [],
      expertise: userTags.data.tags.expertise ?? [],
    });
  }, [open, userId, userTags.data, userTags.error]);

  const rolesReady = Boolean(
    open &&
    userId &&
    !roleCatalog.isLoading &&
    !roleCatalog.error &&
    !userRoles.isLoading &&
    !userRoles.error &&
    userRoles.data?.user_id === userId &&
    userRoles.data.company_id === userCompanyId
  );
  const tagsReady = Boolean(
    open &&
    userId &&
    !tagCatalog.isLoading &&
    !tagCatalog.error &&
    !userTags.isLoading &&
    !userTags.error &&
    userTags.data?.user_id === userId
  );

  const requestError =
    roleCatalog.error ||
    tagCatalog.error ||
    userRoles.error ||
    userTags.error ||
    roleMutation.error ||
    tagMutation.error;

  async function saveRoles() {
    if (!user || !rolesReady) return;
    try {
      await roleMutation.saveUserRoles({
        company_id: user.company_id,
        roles: selectedRoles,
      });
      toast.success("用户角色已更新");
    } catch {
      // Hook error is displayed in the dialog.
    }
  }

  async function saveTags(dimension: TagDimension) {
    if (!tagsReady) return;
    try {
      await tagMutation.saveUserTags({
        dimension,
        values: selectedTags[dimension],
      });
      toast.success(`${TAG_DIMENSIONS.find((item) => item.code === dimension)?.label}已更新`);
    } catch {
      // Hook error is displayed in the dialog.
    }
  }

  if (!user) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>角色与标签 · {user.username}</DialogTitle>
          <DialogDescription>
            每个区域单独保存。角色和标签接口采用整组替换，取消全部选项会明确提交空数组。
          </DialogDescription>
        </DialogHeader>

        {requestError && (
          <Alert variant="destructive">
            <AlertCircle aria-hidden="true" />
            <AlertDescription>{requestError}</AlertDescription>
          </Alert>
        )}

        <Tabs defaultValue="roles">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="roles">
              <UserCog data-icon="inline-start" />
              用户角色
            </TabsTrigger>
            <TabsTrigger value="tags">
              <Tags data-icon="inline-start" />
              人员标签
            </TabsTrigger>
          </TabsList>

          <TabsContent value="roles" className="flex flex-col gap-4 pt-3">
            {roleCatalog.isLoading || userRoles.isLoading ? (
              <div className="grid gap-3 md:grid-cols-2">
                {Array.from({ length: 4 }, (_, index) => (
                  <Skeleton key={index} className="h-20" />
                ))}
              </div>
            ) : Object.keys(roleCatalog.roles).length === 0 ? (
              <Empty className="border">
                <EmptyHeader>
                  <EmptyMedia variant="icon"><UserCog /></EmptyMedia>
                  <EmptyTitle>暂无可分配角色</EmptyTitle>
                  <EmptyDescription>请先在角色权限页面配置角色。</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {Object.entries(roleCatalog.roles).map(([code, role]) => (
                  <label
                    key={code}
                    className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 hover:bg-muted/50"
                  >
                    <Checkbox
                      checked={selectedRoles.includes(code)}
                      disabled={!rolesReady || roleMutation.isMutating}
                      onCheckedChange={(checked) =>
                        setSelectedRoles((current) =>
                          toggleValue(current, code, checked === true)
                        )
                      }
                    />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex flex-wrap items-center gap-2 font-medium">
                        {role.role_name}
                        <Badge variant="outline">{role.tier}</Badge>
                      </span>
                      <span className="break-all text-xs text-muted-foreground">{code}</span>
                      {role.description && (
                        <span className="text-xs text-muted-foreground">{role.description}</span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            )}
            <div className="flex justify-end">
              <Button onClick={saveRoles} disabled={!rolesReady || roleMutation.isMutating}>
                {roleMutation.isMutating && <Loader2 data-icon="inline-start" className="animate-spin" />}
                保存角色
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="tags" className="flex flex-col gap-5 pt-3">
            {tagCatalog.isLoading || userTags.isLoading ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} className="h-28" />
                ))}
              </div>
            ) : (
              TAG_DIMENSIONS.map((dimension) => {
                const items = tagCatalog.catalog.filter(
                  (item) => item.dimension === dimension.code
                );
                const groups = groupCatalog(items);
                return (
                  <section key={dimension.code} className="flex flex-col gap-3 rounded-lg border p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <h3 className="font-medium">{dimension.label}</h3>
                        <p className="text-xs text-muted-foreground">
                          已选择 {selectedTags[dimension.code].length} 项
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!tagsReady || tagMutation.isMutating}
                        onClick={() => saveTags(dimension.code)}
                      >
                        {tagMutation.isMutating && <Loader2 data-icon="inline-start" className="animate-spin" />}
                        保存{dimension.label}
                      </Button>
                    </div>
                    {items.length === 0 ? (
                      <p className="text-sm text-muted-foreground">目录中暂无选项，可提交空数组清空现有值。</p>
                    ) : (
                      <div className="flex flex-col gap-3">
                        {[...groups.entries()].map(([group, groupItems]) => (
                          <div key={group} className="flex flex-col gap-2">
                            <p className="text-xs font-medium text-muted-foreground">{group}</p>
                            <div className="flex flex-wrap gap-3">
                              {groupItems.map((item) => (
                                <label key={item.tag_value} className="flex cursor-pointer items-center gap-2 text-sm">
                                  <Checkbox
                                    checked={selectedTags[dimension.code].includes(item.tag_value)}
                                    disabled={!tagsReady || tagMutation.isMutating}
                                    onCheckedChange={(checked) =>
                                      setSelectedTags((current) => ({
                                        ...current,
                                        [dimension.code]: toggleValue(
                                          current[dimension.code],
                                          item.tag_value,
                                          checked === true
                                        ),
                                      }))
                                    }
                                  />
                                  {item.tag_value}
                                </label>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                );
              })
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
