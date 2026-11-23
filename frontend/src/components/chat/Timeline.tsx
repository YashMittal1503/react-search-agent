"use client";

import { AnimatePresence, motion } from "motion/react";
import { Brain, Check, ChevronDown, CloudSun, FileText, Globe, ListTodo, Loader2, Newspaper, PenLine, X } from "lucide-react";
import { useState } from "react";
import type { Step, Todo } from "@/lib/types";
import { Favicon } from "./Citation";

const ICON = { think: Brain, search: Globe, news: Newspaper, fetch: FileText, weather: CloudSun, write: PenLine } as const;

function stepText(s: Step) {
  switch (s.kind) {
    case "search": return <>Searching <span className="text-fg">“{s.label}”</span></>;
    case "news": return <>Scanning news for <span className="text-fg">“{s.label}”</span></>;
    case "fetch": return <>Reading <span className="text-fg">{s.title || s.label}</span></>;
    case "weather": return <>Checking live weather for <span className="text-fg">{s.title || s.label}</span></>;
    case "write": return <>Writing the answer</>;
    default: return <>{s.label}</>;
  }
}

/** Live research timeline: the agent's plan (deep mode) plus every search/read it performs. */
export function Timeline({ steps, plan, streaming }: { steps: Step[]; plan?: Todo[]; streaming: boolean }) {
  const [open, setOpen] = useState(true);
  const visible = steps.filter((s) => s.kind);
  if (!visible.length && !plan?.length) return null;
  const searches = visible.filter((s) => s.kind === "search" || s.kind === "news").length;
  const reads = visible.filter((s) => s.kind === "fetch" && s.status === "done").length;
  const expanded = open || streaming;

  return (
    <div className="glass rounded-2xl text-sm" data-testid="timeline">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-muted">
        {streaming ? <Loader2 className="h-4 w-4 animate-spin text-accent" /> : <Check className="h-4 w-4 text-ok" />}
        <span className="font-medium text-fg">{streaming ? "Researching…" : "Research complete"}</span>
        <span className="text-xs">· {searches} {searches === 1 ? "search" : "searches"} · {reads} {reads === 1 ? "page" : "pages"} read</span>
        <ChevronDown className={`ml-auto h-4 w-4 transition ${expanded ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="space-y-3 px-4 pb-3">
              {!!plan?.length && (
                <div className="rounded-xl bg-accent-soft p-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-accent"><ListTodo className="h-3.5 w-3.5" /> Plan</div>
                  <ol className="space-y-1">
                    {plan.map((t, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className={`mt-[3px] flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border ${t.status === "completed" ? "border-ok bg-ok text-white" : t.status === "in_progress" ? "border-accent" : "border-subtle/50"}`}>
                          {t.status === "completed" && <Check className="h-2.5 w-2.5" />}
                          {t.status === "in_progress" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />}
                        </span>
                        <span className={t.status === "completed" ? "text-muted line-through decoration-subtle/40" : "text-fg"}>{t.content}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              <ol className="relative space-y-2 border-l border-border pl-4">
                {visible.map((s) => {
                  const Icon = ICON[s.kind as keyof typeof ICON] ?? Globe;
                  return (
                    <motion.li key={s.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="relative text-muted">
                      <span className="absolute -left-[23px] top-0.5 flex h-[14px] w-[14px] items-center justify-center rounded-full bg-surface-strong ring-1 ring-border">
                        {s.status === "running" ? <Loader2 className="h-2.5 w-2.5 animate-spin text-accent" /> : s.status === "failed" ? <X className="h-2.5 w-2.5 text-bad" /> : <Icon className="h-2.5 w-2.5 text-accent" />}
                      </span>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 leading-snug">
                        <span>{stepText(s)}</span>
                        {s.kind === "fetch" && s.url && <Favicon domain={new URL(s.url).hostname} size={14} />}
                        {s.status === "failed" && <span className="text-xs text-bad">{s.detail?.startsWith("stopped") ? s.detail : `${s.detail || "failed"} — trying other sources`}</span>}
                        {s.status === "done" && s.tier && s.kind === "fetch" && <span className="rounded bg-surface-hover px-1.5 text-[10px] uppercase tracking-wide text-subtle">{s.tier.replace(" (cached)", " · cached")}</span>}
                      </div>
                      {s.domains && s.domains.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {[...new Set(s.domains)].map((d) => (
                            <span key={d} className="inline-flex items-center gap-1 rounded-full bg-surface-hover px-2 py-0.5 text-[11px]"><Favicon domain={d} size={12} />{d}</span>
                          ))}
                        </div>
                      )}
                    </motion.li>
                  );
                })}
              </ol>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
