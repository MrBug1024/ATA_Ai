"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sparkles } from "lucide-react";
import { useCaseReview } from "@/lib/hooks/use-case-review";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  caseId: number;
  disabled?: boolean;
}

export function ReviewDialog({ caseId, disabled = false }: Props) {
  const [open, setOpen] = useState(false);
  const { data, isMutating, error, review, reset } = useCaseReview(caseId);

  const runReview = async () => {
    try {
      await review({});
    } catch {
      // 错误已在 hook 内暂存,UI 展示
    }
  };

  const onOpen = () => {
    setOpen(true);
    if (!data && !isMutating) void runReview();
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-7 gap-1.5 text-xs"
        onClick={onOpen}
        disabled={disabled}
      >
        <Sparkles className="h-3.5 w-3.5" />
        AI 复盘
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) reset();
        }}
      >
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>AI 回款复盘对账</DialogTitle>
          </DialogHeader>
          {isMutating ? (
            <div className="py-10 text-center text-sm text-muted-foreground">复盘生成中…</div>
          ) : error ? (
            <div className="flex flex-col items-center gap-2 py-10 text-sm text-muted-foreground">
              <span>复盘失败:{error}</span>
              <Button size="sm" variant="outline" onClick={() => void runReview()}>
                重试
              </Button>
            </div>
          ) : data ? (
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.final_report}</ReactMarkdown>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
