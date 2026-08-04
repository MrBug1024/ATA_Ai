import { ClipboardCheck, Loader2, SlashIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Case } from "@/lib/hooks/use-cases";
import type { SlashCommandDef } from "@/lib/utils/slash-commands";

function PickerShell({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 max-h-72 overflow-y-auto rounded-2xl border border-border/70 bg-popover py-1.5 shadow-xl shadow-black/20">
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground/50">
        {title}
      </div>
      {children}
    </div>
  );
}

export function CommandPalette({
  matches,
  highlightIdx,
  onHover,
  onPick,
}: {
  matches: SlashCommandDef[];
  highlightIdx: number;
  onHover: (idx: number) => void;
  onPick: (c: SlashCommandDef) => void;
}) {
  return (
    <PickerShell title="指令 · ↑↓ Tab / Enter 选择 · Esc 取消">
      {matches.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground/60">
          无匹配指令
        </div>
      ) : (
        matches.map((cmd, idx) => (
          <button
            key={cmd.key}
            type="button"
            onMouseEnter={() => onHover(idx)}
            onMouseDown={(e) => {
              e.preventDefault();
              onPick(cmd);
            }}
            className={cn(
              "flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs transition-colors",
              idx === highlightIdx
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            )}
          >
            <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border/30 bg-muted/50">
              <SlashIcon className="size-3.5 text-muted-foreground/60" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[12px] font-medium text-foreground/90">{cmd.label}</div>
              <p className="truncate text-[11px] text-muted-foreground/55">{cmd.description}</p>
            </div>
          </button>
        ))
      )}
    </PickerShell>
  );
}

export function CasePickerDropdown({
  cases,
  isLoading,
  highlightIdx,
  onHover,
  onPick,
}: {
  cases: Case[];
  isLoading: boolean;
  highlightIdx: number;
  onHover: (idx: number) => void;
  onPick: (c: Case) => void;
}) {
  return (
    <PickerShell title="选择年审项目 · ↑↓ Enter 确认 · Esc 取消">
      {isLoading && cases.length === 0 ? (
        <div className="flex items-center justify-center gap-2 px-3 py-6 text-xs text-muted-foreground/60">
          <Loader2 className="size-3 animate-spin" /> 加载中…
        </div>
      ) : cases.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground/60">
          无匹配年审项目
        </div>
      ) : (
        cases.map((c, idx) => (
          <button
            key={c.case_id}
            type="button"
            onMouseEnter={() => onHover(idx)}
            onMouseDown={(e) => {
              e.preventDefault();
              onPick(c);
            }}
            className={cn(
              "flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs transition-colors",
              idx === highlightIdx
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            )}
          >
            <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border/30 bg-muted/50">
              <ClipboardCheck className="size-3.5 text-muted-foreground/60" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium text-foreground/90">{c.case_name}</span>
                <span className="shrink-0 font-mono text-[10px] text-muted-foreground/50">#{c.case_id}</span>
              </div>
              <p className="truncate text-[11px] text-muted-foreground/55">
                {c.entity_name || "—"} · {c.case_type}
              </p>
            </div>
          </button>
        ))
      )}
    </PickerShell>
  );
}
