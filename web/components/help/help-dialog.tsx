"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { HELP_SECTIONS } from "./help-content";

interface HelpDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function HelpDialog({ open, onOpenChange }: HelpDialogProps) {
  const [activeId, setActiveId] = useState(HELP_SECTIONS[0].id);
  const active = HELP_SECTIONS.find((s) => s.id === activeId) ?? HELP_SECTIONS[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[80vh] max-h-[680px] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="border-b px-5 py-3">
          <DialogTitle className="text-base">使用帮助</DialogTitle>
        </DialogHeader>

        <div className="flex min-h-0 flex-1">
          {/* Section nav */}
          <nav className="w-44 shrink-0 overflow-y-auto border-r p-2">
            {HELP_SECTIONS.map((s) => {
              const Icon = s.icon;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setActiveId(s.id)}
                  className={cn(
                    "mb-0.5 flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors",
                    s.id === activeId
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  <span className="truncate">{s.title}</span>
                </button>
              );
            })}
          </nav>

          {/* Section content */}
          <div className="min-w-0 flex-1 overflow-y-auto px-6 py-5">
            <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
              <active.icon className="size-5 text-primary" />
              {active.title}
            </h2>
            {active.content}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
