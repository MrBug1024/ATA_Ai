"use client";

import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import { cn } from "@/lib/utils";
import { MermaidDiagram } from "@/components/assistant-ui/mermaid-diagram";
import { CitationButton } from "@/components/knowledge-graph/citation-button";

/**
 * Convert only the explicit citation wire format emitted by the backend.
 *
 * `[[cite:n]]` is deliberately an internal transport marker.  The renderer
 * turns it into the user-facing `[n]` evidence marker, while plain bracketed
 * numbers remain ordinary Markdown text.  Audit reports routinely contain
 * years, legal provisions, spreadsheet row labels, and list items such as
 * `[2026]` / `[1]`; accepting those as citations would let a reader open
 * unrelated evidence.
 */
export function rehypeCitations() {
  return (tree: unknown) => {
    visit(tree as Parameters<typeof visit>[0], "text", (node: any, index: number | undefined, parent: any) => {
      if (index === undefined || !parent || parent.type === "element" && parent.tagName === "code") return;
      const text: string = node.value ?? "";
      const regex = /\[\[cite:([1-9]\d*)\]\]/g;
      if (!regex.test(text)) return;
      regex.lastIndex = 0;

      const parts: any[] = [];
      let last = 0;
      let match: RegExpExecArray | null;
      while ((match = regex.exec(text)) !== null) {
        if (match.index > last) {
          parts.push({ type: "text", value: text.slice(last, match.index) });
        }
        parts.push({
          type: "element",
          tagName: "citation",
          properties: { n: match[1] },
          children: [],
        });
        last = match.index + match[0].length;
      }
      if (last < text.length) {
        parts.push({ type: "text", value: text.slice(last) });
      }
      parent.children.splice(index, 1, ...parts);
      return index + parts.length;
    });
  };
}

const CLAIM_TYPE_LABELS: Record<string, string> = {
  entity_fact: "实体",
  relation_fact: "关系",
  risk_signal: "风险",
  event_fact: "事件",
  claim: "断言",
};

// 美化「知识图谱证据追溯」段：
//   [entity_fact|1.00]            → <claimtag> 小徽标
//   证据锚点: file_id=X page=Y chunk=<hash> | 引文 → <evanchor> 紧凑卡片（隐藏 chunk hash）
function rehypeEvidenceTrace() {
  return (tree: unknown) => {
    visit(tree as Parameters<typeof visit>[0], "text", (node: any, index: number | undefined, parent: any) => {
      if (index === undefined || !parent) return;
      if (parent.type === "element" && parent.tagName === "code") return;
      const text: string = node.value ?? "";

      // 1. 证据锚点行（整段替换，去掉 chunk hash）
      const anchor =
        /^\s*证据锚点[:：]\s*file_id=(\d+)\s+page=(\d+)\s+chunk=[0-9a-fA-F]+\s*\|\s*([\s\S]+)$/.exec(text);
      if (anchor) {
        parent.children.splice(index, 1, {
          type: "element",
          tagName: "evanchor",
          properties: { file: anchor[1], page: anchor[2] },
          children: [{ type: "text", value: anchor[3].trim() }],
        });
        return index + 1;
      }

      // 2. [type|conf] 标签（行内可能多个）
      const tagRe = /\[([a-z_]+)\|([\d.]+)\]/g;
      if (!tagRe.test(text)) return;
      tagRe.lastIndex = 0;
      const parts: any[] = [];
      let last = 0;
      let m: RegExpExecArray | null;
      while ((m = tagRe.exec(text)) !== null) {
        if (m.index > last) parts.push({ type: "text", value: text.slice(last, m.index) });
        parts.push({
          type: "element",
          tagName: "claimtag",
          properties: { ctype: m[1], conf: m[2] },
          children: [],
        });
        last = m.index + m[0].length;
      }
      if (last < text.length) parts.push({ type: "text", value: text.slice(last) });
      parent.children.splice(index, 1, ...parts);
      return index + parts.length;
    });
  };
}

export function MarkdownText() {
  return (
    <MarkdownTextPrimitive
      smooth
      className="aui-md aui-markdown-text prose prose-sm max-w-none dark:prose-invert"
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeCitations, rehypeEvidenceTrace]}
      components={{
        // Map our custom <citation n="..."> to CitationButton
        // @ts-expect-error custom element not in default HAST mapping
        citation({ n }: { n?: string }) {
          return <CitationButton citationId={String(n ?? "")} />;
        },
        claimtag({ ctype, conf }: { ctype?: string; conf?: string }) {
          const label = CLAIM_TYPE_LABELS[ctype ?? ""] ?? ctype ?? "";
          const pct = Math.round(Number(conf ?? 0) * 100);
          return (
            <span className="mx-0.5 inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 align-middle text-[10px] font-medium text-primary">
              {label}
              {Number.isFinite(pct) && <span className="opacity-60">{pct}%</span>}
            </span>
          );
        },
        evanchor({ file, page, children }: { file?: string; page?: string; children?: React.ReactNode }) {
          return (
            <span className="my-1 flex items-start gap-2 rounded-md bg-muted/40 px-2 py-1.5 text-xs">
              <span className="mt-px shrink-0 rounded bg-background px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                文件{file} · P.{page}
              </span>
              <span className="leading-relaxed text-muted-foreground">{children}</span>
            </span>
          );
        },
        a({ children, href }) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline hover:text-primary/80"
            >
              {children}
            </a>
          );
        },
        code({ className, children }) {
          const isInline = !className;
          if (isInline) {
            return (
              <code className="rounded bg-muted px-1 py-0.5 text-sm font-mono text-foreground">
                {children}
              </code>
            );
          }
          const lang = /language-(\w+)/.exec(className ?? "")?.[1];
          if (lang === "mermaid") {
            return <MermaidDiagram code={String(children)} />;
          }
          return (
            <pre className="my-2 overflow-x-auto rounded-lg bg-muted p-3 text-sm">
              <code className={cn("font-mono text-foreground", className)}>
                {children}
              </code>
            </pre>
          );
        },
        pre({ children }) {
          return <>{children}</>;
        },
        ul({ children }) {
          return (
            <ul className="my-2 list-disc pl-5 text-foreground">{children}</ul>
          );
        },
        ol({ children }) {
          return (
            <ol className="my-2 list-decimal pl-5 text-foreground">
              {children}
            </ol>
          );
        },
        li({ children }) {
          return <li className="my-0.5">{children}</li>;
        },
        p({ children }) {
          return <p className="my-1.5 leading-relaxed">{children}</p>;
        },
        h1({ children }) {
          return (
            <h1 className="my-3 text-xl font-semibold text-foreground">
              {children}
            </h1>
          );
        },
        h2({ children }) {
          return (
            <h2 className="my-2.5 text-lg font-semibold text-foreground">
              {children}
            </h2>
          );
        },
        h3({ children }) {
          return (
            <h3 className="my-2 text-base font-semibold text-foreground">
              {children}
            </h3>
          );
        },
        blockquote({ children }) {
          return (
            <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground">
              {children}
            </blockquote>
          );
        },
        hr() {
          return <hr className="my-3 border-border" />;
        },
        script() {
          return null;
        },
        table({ children }) {
          return (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                {children}
              </table>
            </div>
          );
        },
        thead({ children }) {
          return <thead className="bg-muted">{children}</thead>;
        },
        th({ children }) {
          return (
            <th className="border border-border px-3 py-1.5 text-left text-foreground">
              {children}
            </th>
          );
        },
        td({ children }) {
          return (
            <td className="border border-border px-3 py-1.5 text-foreground">
              {children}
            </td>
          );
        },
      }}
    />
  );
}
