import { AttachmentTemplateFiles } from "@/components/admin/attachment-template-files";

export default async function AdminAttachmentTemplateDetailPage({
  params,
}: {
  params: Promise<{ versionId: string }>;
}) {
  const { versionId } = await params;
  return <AttachmentTemplateFiles versionId={versionId} />;
}
