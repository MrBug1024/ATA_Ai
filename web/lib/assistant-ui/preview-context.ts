"use client";

import { createContext, useContext } from "react";

export interface PreviewableFile {
  name: string;
  contentType?: string;
  previewUrl?: string;
  downloadUrl?: string;
  previewUrlIsDownload?: boolean;
  requestHeaders?: Record<string, string>;
  file?: File;
}

interface PreviewContextValue {
  previewFile: PreviewableFile | null;
  openPreview: (file: PreviewableFile) => void;
  closePreview: () => void;
}

export const PreviewContext = createContext<PreviewContextValue>({
  previewFile: null,
  openPreview: () => {},
  closePreview: () => {},
});

export function usePreview() {
  return useContext(PreviewContext);
}
