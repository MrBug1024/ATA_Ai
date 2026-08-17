"use client";

import { CheckCircle, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDemoCaseValidate } from "@/lib/hooks/use-demo-case-validate";

interface DemoValidationGateProps {
  caseId: number;
  reportRef: string | null;
}

export function DemoValidationGate({ caseId, reportRef }: DemoValidationGateProps) {
  const { data, isMutating, validate } = useDemoCaseValidate();

  if (!reportRef) return null;

  return (
    <div className="flex items-start gap-2">
      {!data && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 text-xs"
          disabled={isMutating}
          onClick={() => validate({ case_id: caseId, report_ref: reportRef })}
        >
          {isMutating && <Loader2 className="h-3 w-3 animate-spin" />}
          验收
        </Button>
      )}

      {data?.ready && (
        <div className="flex items-center gap-1.5">
          <span className="flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-500">
            <CheckCircle className="h-3 w-3" />
            证据链校验通过
          </span>
        </div>
      )}

      {data && !data.ready && (
        <div className="space-y-1">
          <span className="flex items-center gap-1 rounded-md bg-destructive/10 px-2 py-0.5 text-xs text-destructive">
            <XCircle className="h-3 w-3" />
            {data.failed_citations} 条角标失败
          </span>
          <div className="max-h-32 overflow-y-auto space-y-0.5">
            {data.checks.filter((c) => !c.ok).map((c) => (
              <div key={c.citation_id} className="rounded bg-muted/50 px-2 py-1 text-xs">
                <span className="text-muted-foreground">[{c.citation_id}]</span>{" "}
                {c.claim_text}
                {c.issues.map((issue, i) => (
                  <div key={i} className="text-destructive/80">{issue}</div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
