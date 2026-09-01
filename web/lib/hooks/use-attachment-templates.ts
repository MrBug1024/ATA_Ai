"use client";

import useSWR, { useSWRConfig } from "swr";
import {
  attachmentTemplateBusinessTypesKey,
  attachmentTemplateVersionKey,
  attachmentTemplateVersionsKey,
  cloneAttachmentTemplateVersion,
  compileAttachmentTemplateFile,
  createAttachmentTemplateVersion,
  deleteAttachmentTemplateFile,
  deleteAttachmentTemplateVersion,
  getAttachmentTemplateVersion,
  inspectAttachmentTemplateFile,
  isAttachmentTemplateVersionsKey,
  listAttachmentTemplateBusinessTypes,
  listAttachmentTemplateVersions,
  setAttachmentTemplateVersionActivation,
  updateAttachmentTemplateFile,
  updateAttachmentTemplateVersion,
  uploadAttachmentTemplateFile,
  validateAttachmentTemplateVersion,
  type AttachmentTemplateBindingManifest,
  type AttachmentTemplateVersionListParams,
  type CreateAttachmentTemplateVersionRequest,
  type UpdateAttachmentTemplateFileRequest,
  type UpdateAttachmentTemplateVersionRequest,
} from "@/lib/backend/attachment-templates";
import { useBackendMutation } from "./use-backend-mutation";

function errorMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof TypeError && /failed to fetch/i.test(error.message)) {
    return "无法连接模板服务，请稍后重试。";
  }
  return error instanceof Error && error.message.trim()
    ? error.message
    : "模板服务暂时不可用。";
}

function ignoreRevalidationFailure(work: Promise<unknown> | unknown): void {
  void Promise.resolve(work).catch(() => undefined);
}

export function useAttachmentTemplateBusinessTypes() {
  const { data, error, isLoading, mutate } = useSWR(
    attachmentTemplateBusinessTypesKey(),
    listAttachmentTemplateBusinessTypes
  );
  return {
    businessTypes: data ?? [],
    error: errorMessage(error),
    isLoading,
    refresh: mutate,
  };
}

export function useAttachmentTemplateVersions(
  params: AttachmentTemplateVersionListParams = {}
) {
  const key = attachmentTemplateVersionsKey(params);
  const { data, error, isLoading, mutate } = useSWR(key, () =>
    listAttachmentTemplateVersions(params)
  );
  return {
    versions: data?.items ?? [],
    total: data?.total ?? 0,
    page: data?.page ?? params.page ?? 1,
    pageSize: data?.page_size ?? params.pageSize ?? 50,
    error: errorMessage(error),
    isLoading,
    refresh: mutate,
  };
}

export function useAttachmentTemplateVersion(versionId: string | null) {
  const key = versionId ? attachmentTemplateVersionKey(versionId) : null;
  const { data, error, isLoading, mutate } = useSWR(
    key,
    () => getAttachmentTemplateVersion(versionId as string)
  );
  return {
    version: data ?? null,
    error: errorMessage(error),
    isLoading,
    refresh: mutate,
  };
}

function useTemplateInvalidation(versionId?: string) {
  const { mutate } = useSWRConfig();
  return () => {
    ignoreRevalidationFailure(mutate(isAttachmentTemplateVersionsKey));
    if (versionId) {
      ignoreRevalidationFailure(mutate(attachmentTemplateVersionKey(versionId)));
    }
  };
}

export function useCreateAttachmentTemplateVersion() {
  const invalidate = useTemplateInvalidation();
  const mutation = useBackendMutation(async (request: CreateAttachmentTemplateVersionRequest) => {
    const result = await createAttachmentTemplateVersion(request);
    invalidate();
    return result;
  });
  return { ...mutation, createVersion: mutation.trigger };
}

export function useUpdateAttachmentTemplateVersion(versionId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (request: UpdateAttachmentTemplateVersionRequest) => {
    const result = await updateAttachmentTemplateVersion(versionId, request);
    invalidate();
    return result;
  });
  return { ...mutation, updateVersion: mutation.trigger };
}

export function useCloneAttachmentTemplateVersion(versionId: string) {
  const invalidate = useTemplateInvalidation();
  const mutation = useBackendMutation(async (request: { name?: string; description?: string }) => {
    const result = await cloneAttachmentTemplateVersion(versionId, request);
    invalidate();
    return result;
  });
  return { ...mutation, cloneVersion: mutation.trigger };
}

export function useDeleteAttachmentTemplateVersion(versionId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (revision: number) => {
    await deleteAttachmentTemplateVersion(versionId, revision);
    invalidate();
  });
  return { ...mutation, deleteVersion: mutation.trigger };
}

export function useUploadAttachmentTemplateFile(versionId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (request: {
    file: File;
    document_code: string;
    display_name: string;
    sort_order?: number;
  }) => {
    const result = await uploadAttachmentTemplateFile(versionId, request);
    invalidate();
    return result;
  });
  return { ...mutation, uploadFile: mutation.trigger };
}

export function useUpdateAttachmentTemplateFile(versionId: string, fileId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (request: UpdateAttachmentTemplateFileRequest) => {
    const result = await updateAttachmentTemplateFile(fileId, request);
    invalidate();
    return result;
  });
  return { ...mutation, updateFile: mutation.trigger };
}

export function useDeleteAttachmentTemplateFile(versionId: string, fileId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (revision: number) => {
    await deleteAttachmentTemplateFile(fileId, revision);
    invalidate();
  });
  return { ...mutation, deleteFile: mutation.trigger };
}

export function useInspectAttachmentTemplateFile(versionId: string, fileId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (_request: void) => {
    const result = await inspectAttachmentTemplateFile(fileId);
    invalidate();
    return result;
  });
  return { ...mutation, inspectFile: mutation.trigger };
}

export function useCompileAttachmentTemplateFile(versionId: string, fileId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (request: {
    binding_manifest: AttachmentTemplateBindingManifest;
    revision: number;
  }) => {
    const result = await compileAttachmentTemplateFile(fileId, request);
    invalidate();
    return result;
  });
  return { ...mutation, compileFile: mutation.trigger };
}

export function useValidateAttachmentTemplateVersion(versionId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (revision: number) => {
    const result = await validateAttachmentTemplateVersion(versionId, revision);
    invalidate();
    return result;
  });
  return { ...mutation, validateVersion: mutation.trigger };
}

export function useSetAttachmentTemplateVersionActivation(versionId: string) {
  const invalidate = useTemplateInvalidation(versionId);
  const mutation = useBackendMutation(async (request: {
    active: boolean;
    revision: number;
    preview_confirmations?: Array<{ file_id: string; preview_sha256: string }>;
  }) => {
    const result = await setAttachmentTemplateVersionActivation(versionId, request);
    invalidate();
    return result;
  });
  return { ...mutation, setActivation: mutation.trigger };
}
