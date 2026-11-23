"use client";

import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Source } from "@/lib/types";
import { CitationChip } from "./Citation";

/** Turns "[3]" markers into links react-markdown can hand to our chip renderer. Code spans are left alone. */
function linkCitations(text: string): string {
  const parts = text.split(/(```[\s\S]*?```|`[^`]*`)/g);
  return parts
    .map((p, i) => (i % 2 === 1 ? p : p.replace(/\[(\d{1,3})\](?!\()/g, (_, n) => `[${n}](#cite-${n})`)))
    .join("");
}

function MarkdownImpl({ text, sources, className }: { text: string; sources: Source[]; className?: string }) {
  const byN = useMemo(() => new Map(sources.map((s) => [s.n ?? -1, s])), [sources]);
  const content = useMemo(() => linkCitations(text), [text]);
  return (
    <div className={`answer ${className || ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) {
            if (href?.startsWith("#cite-")) {
              const n = Number(href.slice(6));
              return <CitationChip n={n} source={byN.get(n)} />;
            }
            return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
