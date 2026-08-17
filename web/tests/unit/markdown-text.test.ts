import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import { describe, expect, it } from "vitest";
import { rehypeCitations } from "@/components/assistant-ui/markdown-text";

function renderMarkdown(text: string): string {
  return renderToStaticMarkup(
    createElement(
      ReactMarkdown,
      {
        rehypePlugins: [rehypeCitations],
        components: {
          citation({ n }: { n?: string }) {
            return createElement("button", { "data-citation": n }, `[${n}]`);
          },
        } as never,
      },
      text
    )
  );
}

describe("rehypeCitations", () => {
  it("renders an explicit cite marker as a citation button", () => {
    const html = renderMarkdown("该结论由 [[cite:1]] 支持。");

    expect(html).toContain('<button data-citation="1">[1]</button>');
  });

  it("leaves years and ordinary bracketed numbers as plain text", () => {
    const html = renderMarkdown("2026 年度年审按 [2026] 号规则执行，清单项为 [1]，[[cite:0]] 也不是合法角标。");

    expect(html).not.toContain("data-citation");
    expect(html).toContain("[2026]");
    expect(html).toContain("[1]");
    expect(html).toContain("[[cite:0]]");
  });

  it("does not turn citation-looking text in inline code into a marker", () => {
    const html = renderMarkdown("协议示例：`[[cite:8]]`；实际结论：[[cite:9]]。");

    expect(html).toContain('<code>[[cite:8]]</code>');
    expect(html).toContain('<button data-citation="9">[9]</button>');
  });
});
