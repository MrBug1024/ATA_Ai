"use client";

import { useParams } from "next/navigation";
import { TemplateVersionFiles } from "@/components/admin/template-version-files";

export default function TemplateVersionFilesPage() {
  const params = useParams<{ templateCode: string; versionNo: string }>();
  return <TemplateVersionFiles templateCode={decodeURIComponent(params.templateCode)} versionNo={Number(params.versionNo)} />;
}
