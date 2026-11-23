"use client";

import * as HoverCard from "@radix-ui/react-hover-card";
import { ExternalLink } from "lucide-react";
import type { Source } from "@/lib/types";

export function Favicon({ src, domain, size = 16 }: { src?: string; domain: string; size?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src || `https://www.google.com/s2/favicons?domain=${domain}&sz=64`} alt="" width={size} height={size}
      className="shrink-0 rounded-[4px] bg-white/60" loading="lazy"
      onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
  );
}

export function formatDate(d?: string | null) {
  if (!d) return null;
  const t = new Date(d);
  if (isNaN(t.getTime())) return d.slice(0, 10);
  return t.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** Inline [n] chip with a hover card showing the exact URL it maps to. */
export function CitationChip({ n, source }: { n: number; source?: Source }) {
  if (!source) {
    return <sup className="mx-0.5 text-[0.7em] text-subtle">[{n}]</sup>;
  }
  return (
    <HoverCard.Root openDelay={120} closeDelay={80}>
      <HoverCard.Trigger asChild>
        <a href={source.url} target="_blank" rel="noopener noreferrer" data-testid="citation"
          className="mx-[1px] inline-flex h-[1.25rem] min-w-[1.25rem] -translate-y-[1px] items-center justify-center rounded-md bg-cite-bg px-1 align-middle text-[0.7rem] font-semibold text-cite no-underline transition hover:brightness-110"
          aria-label={`Source ${n}: ${source.title}`}>
          {n}
        </a>
      </HoverCard.Trigger>
      <HoverCard.Portal>
        <HoverCard.Content side="top" sideOffset={6} className="glass-strong z-50 w-80 rounded-xl p-3 text-sm text-fg">
          <div className="flex items-center gap-2 text-xs text-muted">
            <Favicon src={source.favicon} domain={source.domain} />
            <span className="truncate">{source.domain}</span>
            {source.published && <span className="ml-auto shrink-0">{formatDate(source.published)}</span>}
          </div>
          <div className="mt-1.5 line-clamp-2 font-medium leading-snug">{source.title}</div>
          {source.snippet && <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted">{source.snippet}</p>}
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="mt-2 flex items-center gap-1 break-all text-[11px] text-accent">
            <ExternalLink className="h-3 w-3 shrink-0" /> {source.url}
          </a>
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
}
