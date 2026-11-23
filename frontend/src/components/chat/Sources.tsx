"use client";

import { Layers } from "lucide-react";
import type { Source } from "@/lib/types";
import { Favicon, formatDate } from "./Citation";

/** Horizontal source cards above the answer (cited sources first, numbered like the chips). */
export function SourceStrip({ cited, all }: { cited: Source[]; all: Source[] }) {
  const list = cited.length ? cited : all.slice(0, 8);
  if (!list.length) return null;
  const extra = Math.max(0, all.length - cited.length);
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 thin-scroll" data-testid="sources">
      {list.map((s, i) => (
        <a key={s.id} href={s.url} target="_blank" rel="noopener noreferrer"
          className="glass group flex w-48 shrink-0 flex-col justify-between rounded-xl p-2.5 text-xs transition hover:-translate-y-0.5 hover:bg-surface-hover">
          <div className="line-clamp-2 font-medium leading-snug text-fg">{s.title}</div>
          <div className="mt-2 flex items-center gap-1.5 text-muted">
            <Favicon src={s.favicon} domain={s.domain} size={14} />
            <span className="truncate">{s.domain}</span>
            <span className="ml-auto shrink-0 rounded bg-cite-bg px-1 font-semibold text-cite">{s.n ?? i + 1}</span>
          </div>
          {s.published && <div className="mt-0.5 text-[10px] text-subtle">{formatDate(s.published)}</div>}
        </a>
      ))}
      {extra > 0 && (
        <div className="glass flex w-28 shrink-0 flex-col items-center justify-center rounded-xl p-2 text-center text-xs text-muted">
          <Layers className="mb-1 h-4 w-4" />+{extra} more looked at
        </div>
      )}
    </div>
  );
}
