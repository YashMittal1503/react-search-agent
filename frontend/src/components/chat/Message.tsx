"use client";

import { motion } from "motion/react";
import { AlertTriangle, Check, Copy, CornerDownRight, RefreshCw, Share2, Sparkles, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import type { ChatMessage } from "@/lib/types";
import { useChat } from "@/store/chat";
import { Markdown } from "./Markdown";
import { SourceStrip } from "./Sources";
import { Timeline } from "./Timeline";
import { Widgets } from "./Widgets";

export function UserMessage({ m }: { m: ChatMessage }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md px-4 py-2.5 text-[0.95rem] leading-relaxed shadow-sm"
        style={{ background: "var(--user-bubble)", color: "var(--user-fg)" }}>
        {m.content}
      </div>
    </motion.div>
  );
}

function toMarkdown(m: ChatMessage) {
  const refs = (m.meta.sources || []).map((s) => `[${s.n}]: ${s.url} "${s.title.replace(/"/g, "'")}"`).join("\n");
  return m.content + (refs ? `\n\n---\nSources\n${refs}\n` : "");
}

export function AssistantMessage({ m, last }: { m: ChatMessage; last: boolean }) {
  const { send, regenerate, streaming } = useChat();
  const [copied, setCopied] = useState(false);
  const cited = m.meta.sources || [];
  const all = m.meta.all_sources || [];
  const steps = m.meta.steps || [];
  const travel = m.meta.route?.intent === "travel";
  const writing = m.streaming && m.content.length > 0;
  const thinking = m.streaming && !m.content;

  const copy = async () => {
    await navigator.clipboard.writeText(toMarkdown(m));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const share = async () => {
    const blob = new Blob([toMarkdown(m)], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "answer.md";
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Answer downloaded as Markdown with sources");
  };

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-3" data-testid="assistant-message">
      {m.meta.route?.mode && (
        <div className="glass flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium text-muted">
          {m.meta.route.mode === "deep" ? <Sparkles className="h-3.5 w-3.5 text-accent" /> : <Zap className="h-3.5 w-3.5 text-accent" />}
          {m.meta.route.mode === "deep" ? "Deep research" : "Quick answer"}
          {m.meta.route.intent && m.meta.route.intent !== "general" && <span className="rounded-full bg-accent-soft px-2 py-0.5 capitalize text-accent">{m.meta.route.intent}</span>}
        </div>
      )}
      <Timeline steps={steps} plan={m.meta.plan} streaming={!!m.streaming && !writing} />
      {(m.meta.widgets?.length ?? 0) > 0 && <Widgets widgets={m.meta.widgets!} />}
      {(cited.length > 0 || (writing && all.length > 0)) && <SourceStrip cited={cited} all={all} />}

      {(m.content || thinking) && (
        <div className="glass rounded-2xl px-5 py-4">
          {thinking ? (
            <div className="space-y-2.5 py-1">
              <div className="skeleton h-3 w-11/12 rounded" />
              <div className="skeleton h-3 w-9/12 rounded" />
              <div className="skeleton h-3 w-10/12 rounded" />
            </div>
          ) : (
            <div className={m.streaming ? "caret-host" : ""}>
              <Markdown text={m.content} sources={cited} className={travel ? "itinerary" : ""} />
              {m.streaming && <span className="caret" />}
            </div>
          )}
          {!m.streaming && m.content && (
            <div className="mt-3 flex items-center gap-1 border-t border-border pt-2 text-muted">
              <button onClick={copy} className="rounded-lg p-1.5 hover:bg-surface-hover hover:text-fg" aria-label="Copy answer with sources">
                {copied ? <Check className="h-4 w-4 text-ok" /> : <Copy className="h-4 w-4" />}
              </button>
              <button onClick={share} className="rounded-lg p-1.5 hover:bg-surface-hover hover:text-fg" aria-label="Download as Markdown"><Share2 className="h-4 w-4" /></button>
              {last && <button onClick={() => regenerate()} disabled={streaming} className="rounded-lg p-1.5 hover:bg-surface-hover hover:text-fg disabled:opacity-40" aria-label="Regenerate"><RefreshCw className="h-4 w-4" /></button>}
              {m.meta.usage && (
                <span className="ml-auto text-[11px] text-subtle">
                  {m.meta.usage.searches} searches · {m.meta.usage.fetches} pages · {m.meta.usage.seconds}s
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {(m.meta.error || (m.meta.notices?.length ?? 0) > 0) && !m.streaming && (
        <div className="glass flex items-start gap-2 rounded-xl px-3 py-2 text-xs text-warn">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{m.meta.error || m.meta.notices?.[m.meta.notices.length - 1]}</span>
        </div>
      )}

      {last && !m.streaming && (m.meta.follow_ups?.length ?? 0) > 0 && (
        <div className="flex flex-col gap-1.5" data-testid="followups">
          {m.meta.follow_ups!.map((q) => (
            <button key={q} onClick={() => send(q)} className="glass flex w-fit items-center gap-2 rounded-xl px-3 py-1.5 text-left text-sm text-fg transition hover:bg-surface-hover">
              <CornerDownRight className="h-3.5 w-3.5 text-accent" /> {q}
            </button>
          ))}
        </div>
      )}
    </motion.div>
  );
}
